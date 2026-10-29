"""Roda UM cenario no EdgeSimPy e salva metricas por tick (congestionamento dos links).

Saidas em --saida:
    resumo.json          tempos de provisionamento (media/p50/p90/p99/max), nao iniciados,
                         saturacao e carga por registry
    ticks.csv            1 linha por tick: fluxos ativos, links saturados e utilizacao
                         (geral, intra-comunidade, inter-comunidades, acesso ao registry)
    links_por_tick.csv   1 linha por (tick, link) COM trafego: capacidade, demanda, utilizacao
    fluxos.csv           1 linha por download de camada: registry usado, saltos, inicio/fim
    servicos.csv         1 linha por servico: servidor, inicio, fim, tempo de provisionamento

Definicao de comunidade (a MESMA particao para FluidC e aleatorio, para a comparacao ser justa):
    usa "comunidades_referencia" do arquivo <cenario>.info.json (particao do FluidC para o mesmo
    grafo, K e seed, gravada pelo gerar_cenario.py). Sem esse campo, cai no dominio do registry
    mais proximo - nesse caso o trafego "inter" e ~0 por construcao (os caminhos mais curtos ficam
    dentro do proprio dominio), entao nao serve para medir congestionamento inter-comunidades.
    Link "intra"  = os dois extremos na mesma comunidade.
    Link "inter"  = extremos em comunidades diferentes.
    Link "acesso" = liga um registry (10 Gbps) ao seu no da rede.

Carga de trabalho do artigo (--chegadas > 0): em vez de provisionar todos os servicos no inicio, requisicoes
chegam por um processo de Poisson durante --duracao segundos, com deadline, tempo de vida e cache LRU
(detalhes e suposicoes em carga_trabalho.py). Saida extra: requisicoes.csv (1 linha por requisicao) e o
bloco "carga" no resumo.json; nesse modo "servicos_*", "nao_iniciados" e "tempo_provisionamento*" passam
a se referir as requisicoes (tempo da chegada ate o container rodar).

Unidades: capacidade em MB/tick; utilizacao = demanda / capacidade (0 a 1); tempo em ticks.
    A duracao do tick e o "segundos_por_tick" do <cenario>.info.json (padrao 1 s, quando capacidade
    em MB/tick = MB/s); o resumo traz tambem "tempo_provisionamento_s", ja convertido para segundos.
"""
import argparse
import csv
import json
import os
import random
import statistics

import networkx as nx
import edge_sim_py as es

from carga_trabalho import CargaTrabalho


# ----------------------------------------------------------------------------- escalonador
def criar_escalonador(nome, semente, taxa):
    """Define ONDE cada servico sobe. 'random' = Random Scheduler do artigo; 'worstfit' = o do experimento anterior.
    taxa > 0 limita quantos servicos sao provisionados por tick (0 = todos no tick 1)."""
    rng = random.Random(semente)

    def algoritmo(parameters):
        hospedeiros = {r.server.id for r in es.ContainerRegistry.all() if r.server}
        iniciados = 0
        for service in es.Service.all():
            if taxa and iniciados >= taxa:
                break
            if service.server is not None or service.being_provisioned:
                continue
            candidatos = [s for s in es.EdgeServer.all()
                          if s.id not in hospedeiros and s.has_capacity_to_host(service=service)]
            if not candidatos:
                continue
            if nome == "random":
                alvo = rng.choice(candidatos)
            else:
                alvo = max(candidatos, key=lambda s: (s.memory - s.memory_demand))
            service.provision(target_server=alvo)
            iniciados += 1

    return algoritmo


# ----------------------------------------------------------------------------- comunidades
def mapear_dominios(topology, info):
    """switch.id -> id da comunidade. Devolve (mapa, ids dos switches hospedeiros de registry, origem da particao)."""
    registries = list(es.ContainerRegistry.all())
    hosts = {r.server.base_station.network_switch: r.id for r in registries}

    ref = info.get("comunidades_referencia")
    if ref:
        dominio = {n: i for i, nos in enumerate(ref) for n in nos}
        for r in registries:  # o hospedeiro herda a comunidade do no onde esta ligado
            sw = r.server.base_station.network_switch
            vizinho = next(v for v in topology.neighbors(sw))
            dominio[sw.id] = dominio.get(vizinho.id)
        return dominio, {sw.id for sw in hosts}, "referencia_fluidc"

    dominio = {}
    for sw in topology.nodes:
        if sw in hosts:
            dominio[sw.id] = hosts[sw]
            continue
        melhor = None
        for r in registries:
            origem = r.server.base_station.network_switch
            try:
                saltos = nx.shortest_path_length(topology, origem, sw)
            except nx.NetworkXNoPath:
                continue
            if melhor is None or saltos < melhor[0]:
                melhor = (saltos, r.id)
        dominio[sw.id] = melhor[1] if melhor else None
    return dominio, {sw.id for sw in hosts}, "registry_mais_proximo"


def classificar_links(dominio, ids_hosts):
    tipo = {}
    for link in es.NetworkLink.all():
        a, b = link["nodes"]
        if a.id in ids_hosts or b.id in ids_hosts:
            tipo[link["id"]] = "acesso"
        elif dominio.get(a.id) == dominio.get(b.id):
            tipo[link["id"]] = "intra"
        else:
            tipo[link["id"]] = "inter"
    return tipo


# ----------------------------------------------------------------------------- coleta por tick
class Coletor:
    def __init__(self, tipo_link, limiar, max_ticks, detalhe_links=True):
        self.tipo = tipo_link
        self.limiar = limiar
        self.max_ticks = max_ticks
        self.detalhe_links = detalhe_links
        self.fim = None            # criterio de parada alternativo (modo carga de trabalho)
        self.ticks = []
        self.links = []

    def __call__(self, model):
        """Usado como stopping_criterion: o EdgeSimPy chama depois de cada tick."""
        t = model.schedule.steps
        grupos = {"todos": [], "intra": [], "inter": [], "acesso": []}
        saturados = {"todos": 0, "intra": 0, "inter": 0, "acesso": 0}
        for link in es.NetworkLink.all():
            fluxos = link["active_flows"]
            if not fluxos:
                continue
            capacidade = link["bandwidth"]
            demanda = sum((f.bandwidth.get(link["id"]) or 0) for f in fluxos)
            util = demanda / capacidade if capacidade else 0.0
            tp = self.tipo[link["id"]]
            for g in ("todos", tp):
                grupos[g].append(util)
                if util >= self.limiar:
                    saturados[g] += 1
            if not self.detalhe_links:
                continue
            a, b = link["nodes"]
            self.links.append({"tick": t, "link": link["id"], "no_a": a.id, "no_b": b.id, "tipo": tp,
                               "capacidade_MBps": capacidade, "demanda_MBps": round(demanda, 3),
                               "utilizacao": round(util, 4), "fluxos": len(fluxos)})

        def media(v): return round(sum(v) / len(v), 4) if v else 0.0
        def maximo(v): return round(max(v), 4) if v else 0.0

        self.ticks.append({
            "tick": t,
            "fluxos_ativos": sum(1 for f in es.NetworkFlow.all() if f.status == "active"),
            "servicos_disponiveis": sum(1 for s in es.Service.all() if s._available),
            "links_ativos": len(grupos["todos"]),
            "links_saturados": saturados["todos"],
            "util_media": media(grupos["todos"]), "util_max": maximo(grupos["todos"]),
            "intra_ativos": len(grupos["intra"]), "intra_saturados": saturados["intra"],
            "intra_util_media": media(grupos["intra"]), "intra_util_max": maximo(grupos["intra"]),
            "inter_ativos": len(grupos["inter"]), "inter_saturados": saturados["inter"],
            "inter_util_media": media(grupos["inter"]), "inter_util_max": maximo(grupos["inter"]),
            "acesso_ativos": len(grupos["acesso"]), "acesso_saturados": saturados["acesso"],
            "acesso_util_max": maximo(grupos["acesso"]),
        })
        if self.fim:
            return self.fim(model) or t >= self.max_ticks
        todos = es.Service.count() > 0 and all(s._available for s in es.Service.all())
        return todos or t >= self.max_ticks


# ----------------------------------------------------------------------------- saidas
def escrever_csv(caminho, linhas):
    if not linhas:
        open(caminho, "w").close()
        return
    with open(caminho, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        w.writeheader()
        w.writerows(linhas)


def percentil(valores, p):
    if not valores:
        return None
    v = sorted(valores)
    i = min(len(v) - 1, max(0, round(p / 100 * (len(v) - 1))))
    return v[i]


def linha_fluxo(model, f, tipo_link, dominio):
    """Resumo de um download de camada (None para fluxos de outro tipo)."""
    if f.metadata.get("type") != "layer":
        return None
    caminho = f.path
    ids = [model.topology[caminho[i]][caminho[i + 1]]["id"] for i in range(len(caminho) - 1)]
    tipos = [tipo_link[i] for i in ids]
    com_destino = dominio.get(f.target.base_station.network_switch.id)
    com_registry = dominio.get(f.source.base_station.network_switch.id)
    return {
        "fluxo": f.id, "registry": f.metadata["container_registry"].id,
        "origem_servidor": f.source.id, "destino_servidor": f.target.id,
        "inicio": f.start, "fim": f.end, "duracao": (f.end - f.start) if f.end is not None else None,
        "saltos": len(ids), "links_intra": tipos.count("intra"),
        "links_inter": tipos.count("inter"), "cruza_comunidade": tipos.count("inter") > 0,
        "comunidade_destino": com_destino, "comunidade_registry": com_registry,
        "registry_na_comunidade_do_destino": com_destino == com_registry,
        "MB": f.metadata["object"].size,
    }


def tabela_fluxos(model, tipo_link, dominio, ja_registrados=()):
    """Fluxos ainda na lista do EdgeSimPy + os ja removidos pela carga de trabalho (ja_registrados)."""
    linhas = list(ja_registrados)
    for f in es.NetworkFlow.all():
        linha = linha_fluxo(model, f, tipo_link, dominio)
        if linha:
            linhas.append(linha)
    return linhas


def tabela_servicos():
    linhas = []
    for s in es.Service.all():
        migs = s._Service__migrations
        m = migs[-1] if migs else None
        fim = m["end"] if m else None
        linhas.append({
            "servico": s.id, "servidor": (m["target"].id if m else None),
            "inicio": (m["start"] if m else None), "fim": fim,
            "tempo_provisionamento": (fim - m["start"]) if (m and fim is not None) else None,
            "espera": (m["waiting_time"] if m else None),
            "download": (m["pulling_layers_time"] if m else None),
            "nao_iniciado": not s._available,
        })
    return linhas


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dataset")
    p.add_argument("--saida", help="pasta de saida (padrao: resultados/<nome do dataset>)")
    p.add_argument("--scheduler", choices=["random", "worstfit"], default="random")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--taxa", type=int, default=0, help="servicos provisionados por tick (0 = todos de uma vez)")
    p.add_argument("--limiar-saturacao", type=float, default=0.99)
    p.add_argument("--max-ticks", type=int, default=3600)
    p.add_argument("--sem-detalhe-links", action="store_true",
                   help="nao grava links_por_tick.csv (simulacoes longas: o arquivo fica com milhoes de linhas)")
    g = p.add_argument_group("carga de trabalho do artigo (ativada com --chegadas > 0; ver carga_trabalho.py)")
    g.add_argument("--chegadas", type=float, default=0, help="requisicoes por segundo (artigo: ~5); 0 = desligado")
    g.add_argument("--duracao", type=float, default=3600, help="segundos de chegadas (artigo: 1 hora)")
    g.add_argument("--deadline-min", type=float, default=25, help="deadline minimo em s (artigo: 25)")
    g.add_argument("--deadline-max", type=float, default=25, help="deadline maximo em s (sorteio uniforme)")
    g.add_argument("--tempo-vida", type=float, default=30, help="SUPOSICAO: segundos que o container roda")
    g.add_argument("--cache-mb", type=float, default=0, help="cache de camadas por servidor, LRU (artigo: 600); 0 = sem limite")
    g.add_argument("--popularidade", choices=["uniforme", "zipf"], default="uniforme")
    g.add_argument("--zipf-s", type=float, default=1.0)
    a = p.parse_args()

    base = os.path.splitext(os.path.basename(a.dataset))[0]
    saida = a.saida or os.path.join("resultados", base)
    os.makedirs(saida, exist_ok=True)

    # o coletor precisa dos tipos de link, que so existem depois do initialize -> criamos antes e preenchemos depois
    coletor = Coletor({}, a.limiar_saturacao, a.max_ticks, detalhe_links=not a.sem_detalhe_links)
    info_path = a.dataset.replace(".json", ".info.json")
    info = json.load(open(info_path)) if os.path.exists(info_path) else {}
    fluxos_removidos = []
    carga = None
    if a.chegadas > 0:
        carga = CargaTrabalho(a.chegadas, a.duracao, a.deadline_min, a.deadline_max, a.tempo_vida, a.cache_mb,
                              a.popularidade, a.zipf_s, a.seed, float(info.get("segundos_por_tick", 1)),
                              registrar_fluxo=lambda f: fluxos_removidos.append(
                                  linha_fluxo(sim, f, coletor.tipo, dominio)))
        coletor.fim = carga.terminou

    sim = es.Simulator(
        tick_duration=1,
        tick_unit="seconds",
        stopping_criterion=coletor,
        resource_management_algorithm=carga or criar_escalonador(a.scheduler, a.seed, a.taxa),
        network_flow_scheduling_algorithm=es.max_min_fairness,
        dump_interval=float("inf"),
    )
    sim.initialize(input_file=a.dataset)
    sim.monitor = lambda: None

    for service in es.Service.all():
        service._available = False
        service.being_provisioned = False
        service.server = None

    dominio, ids_hosts, origem_particao = mapear_dominios(sim.topology, info)
    coletor.tipo = classificar_links(dominio, ids_hosts)
    if carga:
        carga.preparar()
    sim.run_model()

    fluxos = tabela_fluxos(sim, coletor.tipo, dominio, [f for f in fluxos_removidos if f])
    if carga:
        # no modo carga, "servicos" sao as requisicoes e o tempo vai da chegada ate o container rodar
        reqs = carga.linhas()
        servicos = [{"servico": r["requisicao"], "nao_iniciado": not r["iniciou_no_prazo"],
                     "tempo_provisionamento": (round(r["tempo_ate_rodar_s"] / carga.spt)
                                               if r["tempo_ate_rodar_s"] is not None else None)} for r in reqs]
    else:
        servicos = tabela_servicos()
    tempos = [s["tempo_provisionamento"] for s in servicos if s["tempo_provisionamento"] is not None]
    por_registry = {}
    for f in fluxos:
        por_registry[f["registry"]] = por_registry.get(f["registry"], 0) + 1
    tt = coletor.ticks

    spt = float(info.get("segundos_por_tick", 1))

    def em_segundos(v): return round(v * spt, 3) if v is not None else None
    def pico(chave): return max((r[chave] for r in tt), default=0)
    def soma(chave): return sum(r[chave] for r in tt)

    resumo = {
        "dataset": a.dataset, "scheduler": a.scheduler, "seed": a.seed, "info_cenario": info,
        "particao_usada": origem_particao,
        "downloads_com_registry_na_comunidade": sum(1 for f in fluxos if f["registry_na_comunidade_do_destino"]),
        "ticks_totais": sim.schedule.steps,
        "servicos_total": len(servicos), "servicos_providos": sum(1 for s in servicos if not s["nao_iniciado"]),
        "nao_iniciados": sum(1 for s in servicos if s["nao_iniciado"]),
        "tempo_provisionamento": {
            "media": round(statistics.mean(tempos), 3) if tempos else None,
            "p50": percentil(tempos, 50), "p90": percentil(tempos, 90),
            "p99": percentil(tempos, 99), "max": max(tempos) if tempos else None},
        "segundos_por_tick": spt,
        "tempo_provisionamento_s": {
            "media": round(statistics.mean(tempos) * spt, 3) if tempos else None,
            "p50": em_segundos(percentil(tempos, 50)), "p90": em_segundos(percentil(tempos, 90)),
            "p99": em_segundos(percentil(tempos, 99)), "max": em_segundos(max(tempos) if tempos else None),
            "makespan": em_segundos(sim.schedule.steps)},
        "downloads_por_registry": por_registry,
        "downloads_que_cruzam_comunidade": sum(1 for f in fluxos if f["cruza_comunidade"]),
        "downloads_total": len(fluxos),
        "saturacao": {
            "limiar": a.limiar_saturacao,
            "links_saturados_pico": pico("links_saturados"),
            "intra_saturados_pico": pico("intra_saturados"),
            "inter_saturados_pico": pico("inter_saturados"),
            "acesso_saturados_pico": pico("acesso_saturados"),
            "link_ticks_saturados_intra": soma("intra_saturados"),
            "link_ticks_saturados_inter": soma("inter_saturados"),
            "link_ticks_saturados_acesso": soma("acesso_saturados"),
            "util_max_intra": pico("intra_util_max"), "util_max_inter": pico("inter_util_max"),
        },
    }
    if carga:
        resumo["carga"] = carga.resumo()
        escrever_csv(os.path.join(saida, "requisicoes.csv"), reqs)
    escrever_csv(os.path.join(saida, "ticks.csv"), coletor.ticks)
    if coletor.detalhe_links:
        escrever_csv(os.path.join(saida, "links_por_tick.csv"), coletor.links)
    escrever_csv(os.path.join(saida, "fluxos.csv"), fluxos)
    escrever_csv(os.path.join(saida, "servicos.csv"), servicos)
    with open(os.path.join(saida, "resumo.json"), "w") as f:
        json.dump(resumo, f, indent=1)

    print(f"RESULT {sim.schedule.steps} {resumo['servicos_providos']} {resumo['servicos_total']}")


if __name__ == "__main__":
    main()
