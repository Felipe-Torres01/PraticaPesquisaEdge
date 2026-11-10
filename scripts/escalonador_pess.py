"""Adaptacao simplificada do escalonador PESS para posicionar containers.

O PESS (Doriguzzi-Corin et al., "Dynamic and Application-Aware Provisioning of Chained Virtual Security
Network Functions", IEEE TNSM 2020; codigo em github.com/doriguzzi/pess-security) calcula o caminho de
menor custo entre o ponto de entrada do usuario (ep1) e o ponto de saida (EP2), com custo de enlace
inversamente proporcional a banda residual, e posiciona a funcao "no no de maior capacidade residual do
caminho". A tese do Knob (PUCRS, 2022, sec. 4.5.3) usa o PESS para escolher o no de cada container e
observa que ele "tende a escalonar as aplicacoes no centro da rede, com a maior banda possivel" (67% dos
containers em 6 nos).

Adaptacao usada aqui:
    - ep1 = switch da estacao-base por onde a requisicao entra;
    - EP2 = gateway da rede: o switch de maior banda agregada (soma da banda dos seus enlaces), ou seja, o
      centro de maior banda (sem contar os switches dos hospedeiros de registry);
    - caminho = Dijkstra de ep1 ate EP2 com custo de enlace 1 / (banda_residual / banda_max + delta)
      (Eq. 3 do PESS, normalizada); a banda residual e a do enlace menos a ja alocada aos fluxos ativos;
    - no escolhido = servidor do caminho com maior CPU residual que ainda comporte o container.
      Empates sao sorteados de modo uniforme. Sem limite de capacidade (modo fiel ao simulador do Knob,
      que nao considera o impacto da aplicacao no no) todos os nos do caminho empatam, e os nos do centro,
      que aparecem em quase todos os caminhos, recebem a maior parte dos containers;
    - se nenhum no do caminho comportar o container (com limite de capacidade), usa a fase de expansao do
      PESS de forma simplificada: o servidor de menor custo caminho(ep1 -> i) + caminho(i -> EP2) entre os
      que comportam.

Simplificacoes: um container por requisicao (nao uma cadeia de funcoes), sem restricoes de latencia,
seguranca ou regiao.
"""
import networkx as nx

DELTA = 0.01

_gateway = {}   # id(topologia) -> switch gateway (a topologia nao muda durante a simulacao)


def _banda_residual(link):
    usada = sum((f.bandwidth.get(link["id"]) or 0) for f in link["active_flows"])
    return max(0.0, link["bandwidth"] - usada)


def banda_agregada(topologia, sw):
    return sum(topologia[sw][v]["bandwidth"] for v in topologia.neighbors(sw))


def gateway(topologia, excluir=()):
    """Switch de maior banda agregada (EP2 do PESS). `excluir`: switches dos hospedeiros de registry."""
    chave = id(topologia)
    if chave not in _gateway:
        excl = set(excluir)
        nos = [sw for sw in topologia.nodes if sw not in excl]
        _gateway[chave] = max(nos, key=lambda sw: (banda_agregada(topologia, sw), -sw.id))
    return _gateway[chave]


def escolher(topologia, origem, candidatos, demanda_cpu, rng, excluir=(), sem_limite=False, delta=DELTA):
    """Servidor escolhido pelo PESS para uma requisicao que entra pelo switch `origem`.

    candidatos: servidores de borda elegiveis (ja filtrados por capacidade, se houver limite).
    demanda_cpu: CPU do container. rng: gerador para os desempates (random.Random).
    excluir: switches dos hospedeiros de registry. sem_limite: CPU nao conta (todos os nos empatam).
    """
    if not candidatos:
        return None
    banda_max = max(l["bandwidth"] for _, _, l in topologia.edges(data=True)) or 1.0

    def peso(u, v, link):
        return 1.0 / (_banda_residual(link) / banda_max + delta)

    gw = gateway(topologia, excluir)
    por_switch = {}
    for srv in candidatos:
        por_switch.setdefault(srv.base_station.network_switch, []).append(srv)

    caminho = nx.dijkstra_path(topologia, origem, gw, weight=peso)
    no_caminho = [s for sw in caminho for s in por_switch.get(sw, [])]
    if not sem_limite:
        no_caminho = [s for s in no_caminho if s.cpu - s.cpu_demand >= demanda_cpu]
    if no_caminho:
        if sem_limite:
            return rng.choice(no_caminho)
        maior = max(s.cpu - s.cpu_demand for s in no_caminho)
        return rng.choice([s for s in no_caminho if s.cpu - s.cpu_demand == maior])

    # expansao simplificada: menor desvio em relacao ao caminho, entre os que comportam o container
    ida = nx.single_source_dijkstra_path_length(topologia, origem, weight=peso)
    volta = nx.single_source_dijkstra_path_length(topologia, gw, weight=peso)
    viaveis = [s for s in candidatos if s.cpu - s.cpu_demand >= demanda_cpu
               and s.base_station.network_switch in ida and s.base_station.network_switch in volta]
    if not viaveis:
        return None
    return min(viaveis, key=lambda s: (ida[s.base_station.network_switch] + volta[s.base_station.network_switch],
                                       s.id))
