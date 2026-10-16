"""Posicionamento de registries: Algoritmo 1 (FluidC-Placement) do artigo.

Fase 1: roda o FluidC varias vezes (hill-climbing) e guarda a particao com o MENOR
        desvio-padrao da banda interna das comunidades (eq. 1-3 do artigo).
Fase 2: em cada comunidade, escolhe o no de maior eigenvector centrality (artigo, linha 22).

Ids devolvidos sao 1-based (id do EdgeServer no dataset = no do grafo + 1).

Uso rapido:
    python scripts/fluidc_placement.py --garr cenarios/garr/garr.gml --k 4 --seed 1
    python scripts/fluidc_placement.py --aleatoria --nos 70 --links 112 --k 4
"""
import argparse
import random
import statistics

import networkx as nx
from networkx.algorithms.community import asyn_fluidc

import topologia


def banda_interna(g, comunidade):
    """alpha_k: soma da banda das arestas com os dois extremos dentro da comunidade (eq. 2)."""
    return sum(d["bandwidth"] for u, v, d in g.subgraph(comunidade).edges(data=True))


def desvio_banda(g, comunidades):
    """Desvio-padrao amostral (divisor K-1) dos alpha_k (eq. 1). K=1 -> 0."""
    alfas = [banda_interna(g, c) for c in comunidades]
    return statistics.stdev(alfas) if len(alfas) > 1 else 0.0


def particao_valida(g, comunidades):
    """Restricao (5): toda comunidade precisa ter banda interna > 0 (ao menos uma aresta)."""
    return all(banda_interna(g, c) > 0 for c in comunidades)


def fase1_comunidades(g, k, semente, max_sem_melhora=100):
    """Hill-climbing sobre execucoes do FluidC (Algoritmo 1, linhas 5-17).

    OBS: o pseudocodigo do artigo nao atualiza `sd` ao aceitar uma particao melhor;
    aqui `sd` e atualizado (e o que o texto descreve: 'ate nao haver comunidades melhores').
    """
    if k == 1:
        return [set(g.nodes)], 0.0, 0
    rng = random.Random(semente)
    melhor, sd, sem_melhora, execucoes = None, float("inf"), 0, 0
    while sem_melhora < max_sem_melhora:
        execucoes += 1
        try:
            comunidades = [set(c) for c in asyn_fluidc(g, k, seed=rng.randrange(2 ** 31))]
        except Exception:  # FluidC pode falhar/ficar com menos de k comunidades
            sem_melhora += 1
            continue
        if len(comunidades) != k or not particao_valida(g, comunidades):
            sem_melhora += 1
            continue
        atual = desvio_banda(g, comunidades)
        if atual < sd:
            melhor, sd, sem_melhora = comunidades, atual, 0
        else:
            sem_melhora += 1
    if melhor is None:
        raise SystemExit(f"FluidC nao produziu {k} comunidades validas em {execucoes} execucoes.")
    return melhor, sd, execucoes


def no_central(g, comunidade, metrica="eigenvector"):
    """No mais central da comunidade (empate -> menor id, para ser deterministico)."""
    sub = g.subgraph(comunidade)
    if len(comunidade) == 1:
        return next(iter(comunidade))
    if len(comunidade) == 2 and metrica == "eigenvector":
        metrica = "degree"
    if metrica == "eigenvector":
        try:
            c = nx.eigenvector_centrality(sub, max_iter=2000)
        except nx.PowerIterationFailedConvergence:
            c = nx.eigenvector_centrality_numpy(sub)
    elif metrica == "betweenness":
        c = nx.betweenness_centrality(sub)
    elif metrica == "degree":
        c = nx.degree_centrality(sub)
    else:
        raise SystemExit(f"centralidade desconhecida: {metrica}")
    return max(comunidade, key=lambda n: (round(c[n], 9), -n))


def fluidc_placement(g, k, semente=1, centralidade="eigenvector", max_sem_melhora=100):
    comunidades, sd, execucoes = fase1_comunidades(g, k, semente, max_sem_melhora)
    registries = [no_central(g, c, centralidade) for c in comunidades]
    ordem = sorted(range(k), key=lambda i: registries[i])
    return {
        "metodo": "fluidc",
        "posicoes": [registries[i] + 1 for i in ordem],
        "comunidades": {registries[i] + 1: sorted(n + 1 for n in comunidades[i]) for i in ordem},
        "desvio_banda": sd,
        "execucoes_fluidc": execucoes,
    }


def aleatorio(g, k, semente=1):
    """Baseline do artigo: k nos sorteados."""
    rng = random.Random(semente)
    pos = sorted(n + 1 for n in rng.sample(sorted(g.nodes), k))
    return {"metodo": "aleatorio", "posicoes": pos, "comunidades": None}


def topk_global(g, k, centralidade="eigenvector"):
    """Baseline extra: os k nos de maior centralidade no grafo INTEIRO (tende a agrupar registries)."""
    c = nx.eigenvector_centrality_numpy(g) if centralidade == "eigenvector" else nx.betweenness_centrality(g)
    top = sorted(g.nodes, key=lambda n: (-round(c[n], 9), n))[:k]
    return {"metodo": "topk_global", "posicoes": sorted(n + 1 for n in top), "comunidades": None}


def posicionar(g, metodo, k, semente=1, centralidade="eigenvector"):
    if not 1 <= k <= g.number_of_nodes():
        raise SystemExit(f"k deve estar entre 1 e {g.number_of_nodes()}")
    if metodo == "fluidc":
        return fluidc_placement(g, k, semente, centralidade)
    if metodo == "aleatorio":
        return aleatorio(g, k, semente)
    if metodo == "topk_global":
        return topk_global(g, k, centralidade)
    raise SystemExit(f"metodo desconhecido: {metodo}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    origem = p.add_mutually_exclusive_group(required=True)
    origem.add_argument("--garr", help="arquivo do grafo GARR (.gml/.graphml/.csv/.json)")
    origem.add_argument("--aleatoria", action="store_true", help="grafo Erdos-Renyi (teste de pipeline)")
    p.add_argument("--nos", type=int, default=70)
    p.add_argument("--links", type=int, default=112)
    p.add_argument("--k", type=int, required=True)
    p.add_argument("--metodo", default="fluidc", choices=["fluidc", "aleatorio", "topk_global"])
    p.add_argument("--centralidade", default="eigenvector", choices=["eigenvector", "betweenness", "degree"])
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--ignorar-contagem", action="store_true")
    a = p.parse_args()

    g = (topologia.carregar_garr(a.garr, ignorar_contagem=a.ignorar_contagem) if a.garr
         else topologia.grafo_aleatorio(a.nos, a.links, a.seed))
    print("Grafo:", topologia.resumo(g))
    r = posicionar(g, a.metodo, a.k, a.seed, a.centralidade)
    print(f"{r['metodo']}: registries nos nos {r['posicoes']}")
    if r.get("comunidades"):
        print(f"  desvio-padrao da banda interna: {r['desvio_banda']:.1f} "
              f"({r['execucoes_fluidc']} execucoes do FluidC)")
        for reg, nos in r["comunidades"].items():
            print(f"  registry {reg:>3} <- comunidade de {len(nos)} nos")


if __name__ == "__main__":
    main()
