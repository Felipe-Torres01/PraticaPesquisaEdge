"""Carga de trabalho no estilo do artigo: requisicoes chegando ao longo do tempo, com deadline, e cache LRU.

Usado pelo run_cenario.py quando --chegadas > 0. Sem isso o run_cenario mantem o comportamento antigo
(todos os servicos provisionados de uma vez no inicio).

Modelo (o artigo cita ~5 requisicoes/s durante 1 hora, deadline minimo de 25 s e cache de 600 MB com LRU;
o que ele NAO detalha esta marcado como SUPOSICAO e virou parametro):
    - Chegadas: processo de Poisson com taxa --chegadas (req/s) durante --duracao segundos.
    - Cada requisicao pede UM container de uma imagem do catalogo (uniforme ou zipf pelo ranking).
    - Deadline: sorteado em [--deadline-min, --deadline-max] segundos a partir da chegada. A requisicao
      conta como "nao iniciada" se o container nao estiver rodando ate o deadline. Se ainda estiver na fila
      (sem servidor com capacidade) quando o deadline vence, ela e descartada.
    - SUPOSICAO: o container roda --tempo-vida segundos depois de iniciar e entao libera CPU/memoria.
      Sem isso os servidores lotam em poucos minutos (cada servidor do template aceita 4 containers).
    - Escalonador: aleatorio entre os servidores com capacidade (o mesmo "random" do run_cenario).
    - Cache: com --cache-mb > 0 cada servidor guarda no maximo esse volume de camadas; quando passa, remove
      as camadas usadas ha mais tempo (LRU), nunca as que um container rodando ou em provisionamento usa.
      SUPOSICAO: o limite e por servidor e pode ser excedido temporariamente se tudo estiver em uso.

Os objetos Service do dataset sao reaproveitados como "slots": quando uma requisicao e atendida, um Service
ocioso recebe a imagem dela e e provisionado; quando o container termina, o Service volta ao pool. Por isso
o dataset precisa de --servicos >= capacidade total (servidores x 4 no template); o gerar_cenario cria isso.

Desempenho: fluxos concluidos e camadas removidas do cache saem das listas de agentes do EdgeSimPy (que sao
percorridas a cada tick); antes de sair, cada fluxo vira uma linha de resumo (callback registrar_fluxo).
"""
import math
import random

import edge_sim_py as es


class CargaTrabalho:
    def __init__(self, taxa, duracao, deadline_min, deadline_max, tempo_vida, cache_mb,
                 popularidade, zipf_s, semente, segundos_por_tick, registrar_fluxo=None):
        self.taxa = taxa
        self.duracao = duracao
        self.deadline = (deadline_min, max(deadline_min, deadline_max))
        self.tempo_vida = tempo_vida
        self.cache_mb = cache_mb
        self.popularidade = popularidade
        self.zipf_s = zipf_s
        self.spt = segundos_por_tick
        self.rng = random.Random(f"carga-{semente}")
        self.registrar_fluxo = registrar_fluxo
        self.requisicoes = []      # todas, na ordem de chegada
        self.fila = []             # requisicoes esperando servidor
        self.ativas = {}           # Service -> requisicao (provisionando ou rodando)
        self.livres = []           # Services ociosos
        self.ultimo_uso = {}       # (servidor, digest) -> tick do ultimo uso da camada
        self.cache = {"hits_MB": 0.0, "misses_MB": 0.0, "despejos": 0, "despejados_MB": 0.0}
        self.hospedeiros = set()
        self.proxima = 0

    # ------------------------------------------------------------------ preparo
    def preparar(self):
        """Chamado depois do sim.initialize: gera as chegadas e monta o pool de Services."""
        self.hospedeiros = {r.server for r in es.ContainerRegistry.all() if r.server}
        digests = list(dict.fromkeys(img.digest for img in es.ContainerImage.all()))
        # imagem -> camadas e camada -> tamanho, para nao usar find_by (busca linear numa lista que cresce)
        self.camadas_da_imagem = {img.digest: list(img.layers_digests) for img in es.ContainerImage.all()}
        self.tamanho_camada = {l.digest: l.size for l in es.ContainerLayer.all()}
        pesos = None if self.popularidade == "uniforme" else [1 / (i + 1) ** self.zipf_s for i in range(len(digests))]
        t = 0.0
        while True:
            t += self.rng.expovariate(self.taxa)
            if t > self.duracao:
                break
            dl = self.rng.uniform(*self.deadline)
            img = self.rng.randrange(len(digests)) if pesos is None else self.rng.choices(range(len(digests)), pesos)[0]
            chegada = max(1, math.ceil(t / self.spt))
            self.requisicoes.append({
                "requisicao": len(self.requisicoes) + 1, "chegada_s": round(t, 3), "chegada_tick": chegada,
                "deadline_s": round(dl, 3), "limite_tick": chegada + math.floor(dl / self.spt),
                "imagem": digests[img], "servidor": None, "inicio_tick": None, "fim_tick": None,
                "status": "pendente"})
        self.livres = list(es.Service.all())
        capacidade = sum(int(s.cpu // max(1, self.livres[0].cpu_demand)) for s in es.EdgeServer.all()
                         if s not in self.hospedeiros) if self.livres else 0
        if len(self.livres) < capacidade:
            print(f"AVISO: pool de {len(self.livres)} Services < capacidade {capacidade}; "
                  f"gere o dataset com --servicos >= {capacidade}")

    # ------------------------------------------------------------------ escalonamento (1x por tick)
    def __call__(self, parameters):
        modelo = es.Service.all()[0].model if es.Service.count() else None
        agora = modelo.schedule.steps + 1          # tick em que os provisionamentos de agora comecam
        self._concluidos(agora)
        while self.proxima < len(self.requisicoes) and self.requisicoes[self.proxima]["chegada_tick"] <= agora:
            self.fila.append(self.requisicoes[self.proxima])
            self.proxima += 1
        # todo container tem a mesma demanda de CPU/memoria: a lista de servidores com espaco e a mesma
        # para qualquer requisicao, entao e calculada uma vez por tick (com fila longa isso domina o custo)
        modelo_servico = es.Service.all()[0]
        candidatos = [s for s in es.EdgeServer.all()
                      if s not in self.hospedeiros and s.has_capacity_to_host(service=modelo_servico)]
        pendentes = []
        for req in self.fila:
            if agora > req["limite_tick"]:
                req["status"] = "descartada"       # deadline venceu sem servidor livre
                continue
            if not (candidatos and self.livres):
                pendentes.append(req)
                continue
            alvo = self._colocar(req, agora, candidatos)
            if not alvo.has_capacity_to_host(service=modelo_servico):
                candidatos.remove(alvo)
        self.fila = pendentes
        if self.cache_mb:
            self._despejar()
        self._limpar_fluxos()

    def _colocar(self, req, agora, candidatos):
        servico = self.livres.pop()
        servico.image_digest = req["imagem"]
        alvo = self.rng.choice(candidatos)
        presentes = {l.digest for l in alvo.container_layers}
        for dig in self.camadas_da_imagem[req["imagem"]]:
            self.ultimo_uso[(alvo, dig)] = agora
            self.cache["hits_MB" if dig in presentes else "misses_MB"] += self.tamanho_camada[dig]
        servico.provision(target_server=alvo)
        req.update(servidor=alvo.id, inicio_tick=agora, status="provisionando")
        self.ativas[servico] = req
        return alvo

    def _concluidos(self, agora):
        """Marca os containers que ficaram prontos e libera os que terminaram o tempo de vida."""
        for servico, req in list(self.ativas.items()):
            if req["status"] == "provisionando" and servico._available:
                req["fim_tick"] = servico._Service__migrations[-1]["end"]
                req["status"] = "rodando"
                req["no_prazo"] = req["fim_tick"] <= req["limite_tick"]
                req["sai_tick"] = req["fim_tick"] + math.ceil(self.tempo_vida / self.spt)
            if req["status"] == "rodando" and agora >= req["sai_tick"]:
                self._desalocar(servico)
                req["status"] = "concluida"
                del self.ativas[servico]
                self.livres.append(servico)

    @staticmethod
    def _desalocar(servico):
        """Inverso do provisionamento: tira o container do servidor e devolve CPU/memoria."""
        srv = servico.server
        if srv is not None:
            if servico in srv.services:
                srv.services.remove(servico)
            srv.cpu_demand -= servico.cpu_demand
            srv.memory_demand -= servico.memory_demand
        servico.server = None
        servico._available = False
        servico.being_provisioned = False

    # ------------------------------------------------------------------ cache LRU
    def _despejar(self):
        cheios = [srv for srv in es.EdgeServer.all() if srv not in self.hospedeiros
                  and sum(l.size for l in srv.container_layers) > self.cache_mb]
        if not cheios:
            return
        em_uso = {}
        for servico, req in self.ativas.items():
            alvo = servico._Service__migrations[-1]["target"]
            em_uso.setdefault(alvo, set()).update(self.camadas_da_imagem[req["imagem"]])
        removidas = []
        for srv in cheios:
            total = sum(l.size for l in srv.container_layers)
            usadas = em_uso.get(srv, set())
            candidatas = sorted((l for l in srv.container_layers if l.digest not in usadas),
                                key=lambda l: self.ultimo_uso.get((srv, l.digest), 0))
            for camada in candidatas:
                if total <= self.cache_mb:
                    break
                srv.container_layers.remove(camada)
                srv.disk_demand -= camada.size
                camada.server = None
                total -= camada.size
                removidas.append(camada)
                self.cache["despejos"] += 1
                self.cache["despejados_MB"] += camada.size
        if removidas:
            ids = set(map(id, removidas))
            es.ContainerLayer._instances[:] = [l for l in es.ContainerLayer._instances if id(l) not in ids]

    def _limpar_fluxos(self):
        terminados = [f for f in es.NetworkFlow.all() if f.status == "finished"]
        if not terminados:
            return
        if self.registrar_fluxo:
            for f in terminados:
                self.registrar_fluxo(f)
        es.NetworkFlow._instances[:] = [f for f in es.NetworkFlow._instances if f.status != "finished"]

    # ------------------------------------------------------------------ fim e metricas
    def terminou(self, modelo):
        t = modelo.schedule.steps
        acabou_chegada = self.proxima >= len(self.requisicoes)
        provisionando = any(r["status"] == "provisionando" for r in self.ativas.values())
        return acabou_chegada and not self.fila and not provisionando and t * self.spt >= self.duracao

    def linhas(self):
        saida = []
        for r in self.requisicoes:
            tempo = ((r["fim_tick"] - r["chegada_tick"]) * self.spt) if r["fim_tick"] is not None else None
            saida.append({
                "requisicao": r["requisicao"], "chegada_s": r["chegada_s"], "deadline_s": r["deadline_s"],
                "imagem": r["imagem"], "servidor": r["servidor"],
                "espera_fila_s": (round((r["inicio_tick"] - r["chegada_tick"]) * self.spt, 3)
                                  if r["inicio_tick"] is not None else None),
                "tempo_ate_rodar_s": round(tempo, 3) if tempo is not None else None,
                "status": r["status"], "iniciou_no_prazo": bool(r.get("no_prazo")),
            })
        return saida

    def resumo(self):
        linhas = self.linhas()
        total = len(linhas)
        no_prazo = sum(1 for l in linhas if l["iniciou_no_prazo"])
        tempos = sorted(l["tempo_ate_rodar_s"] for l in linhas if l["tempo_ate_rodar_s"] is not None)

        def pct(p):
            return tempos[min(len(tempos) - 1, round(p / 100 * (len(tempos) - 1)))] if tempos else None

        trafego = self.cache["hits_MB"] + self.cache["misses_MB"]
        return {
            "taxa_req_s": self.taxa, "duracao_s": self.duracao, "deadline_s": list(self.deadline),
            "tempo_vida_s": self.tempo_vida, "cache_MB": self.cache_mb, "popularidade": self.popularidade,
            "requisicoes": total, "iniciadas_no_prazo": no_prazo,
            "nao_iniciadas": total - no_prazo,
            "pct_nao_iniciadas": round(100 * (total - no_prazo) / total, 3) if total else None,
            "descartadas_na_fila": sum(1 for l in linhas if l["status"] == "descartada"),
            "iniciadas_atrasadas": sum(1 for l in linhas if l["tempo_ate_rodar_s"] is not None
                                       and not l["iniciou_no_prazo"]),
            "tempo_ate_rodar_s": {"media": round(sum(tempos) / len(tempos), 3) if tempos else None,
                                  "p50": pct(50), "p90": pct(90), "p99": pct(99),
                                  "max": tempos[-1] if tempos else None},
            "cache": {k: round(v, 3) for k, v in self.cache.items()} | {
                "taxa_acerto_MB": round(self.cache["hits_MB"] / trafego, 4) if trafego else None},
        }
