"""Carrega ou gera o grafo da rede (GARR ou aleatorio) para o experimento.

Todas as funcoes devolvem um nx.Graph simples, nao direcionado e conexo, com os nos
numerados de 0 a N-1 e, em cada aresta, o atributo "bandwidth" em MB/s
(125 MB/s = 1 Gbps, que e a unidade usada pelo EdgeSimPy neste projeto).
"""
import csv
import json
import os

import networkx as nx

BANDA_PADRAO = 125  # MB/s = 1 Gbps (Tabela II do artigo: worker node bandwidth)

GARR_NOS = 70      # artigo, secao V-B
GARR_LINKS = 112   # artigo, secao V-B


def _normalizar(g, banda_padrao):
    """Grafo simples, sem lacos, nos 0..N-1 e banda em todas as arestas."""
    g = nx.Graph(g)  # colapsa arestas paralelas (multigrafo -> grafo simples)
    g.remove_edges_from(list(nx.selfloop_edges(g)))
    g.remove_nodes_from([n for n in list(g.nodes) if g.degree(n) == 0])
    rotulos = {n: str(g.nodes[n].get("label", n)) for n in g.nodes}
    g = nx.convert_node_labels_to_integers(g, ordering="sorted", label_attribute="rotulo_original")
    for _, _, d in g.edges(data=True):
        bw = d.get("bandwidth")
        d["bandwidth"] = float(bw) if bw not in (None, "") else float(banda_padrao)
    g.graph["rotulos"] = rotulos
    return g


def _ler_csv(caminho):
    g = nx.Graph()
    with open(caminho, newline="") as f:
        for linha in csv.reader(f):
            if not linha or linha[0].strip().startswith("#"):
                continue
            if linha[0].strip().lower() in ("u", "origem", "source", "no1"):
                continue  # cabecalho
            u, v = linha[0].strip(), linha[1].strip()
            bw = linha[2].strip() if len(linha) > 2 else None
            g.add_edge(u, v, bandwidth=bw)
    return g


def _ler_json(caminho):
    d = json.load(open(caminho))
    g = nx.Graph()
    for n in d.get("nodes", []):
        g.add_node(n)
    for e in d["edges"]:
        g.add_edge(e[0], e[1], bandwidth=(e[2] if len(e) > 2 else None))
    return g


def carregar_arquivo(caminho, banda_padrao=BANDA_PADRAO):
    """Le .gml, .graphml, .csv/.txt (u,v[,banda_MBps]) ou .json ({"edges": [[u,v,bw?],...]})."""
    ext = os.path.splitext(caminho)[1].lower()
    if ext == ".gml":
        bruto = nx.read_gml(caminho, label="id")
    elif ext == ".graphml":
        bruto = nx.read_graphml(caminho)
    elif ext in (".csv", ".txt"):
        bruto = _ler_csv(caminho)
    elif ext == ".json":
        bruto = _ler_json(caminho)
    else:
        raise SystemExit(f"Formato nao suportado: {ext} (use .gml, .graphml, .csv ou .json)")
    return _normalizar(bruto, banda_padrao)


def carregar_garr(caminho, banda_padrao=BANDA_PADRAO, esperado_nos=GARR_NOS,
                  esperado_links=GARR_LINKS, ignorar_contagem=False):
    g = carregar_arquivo(caminho, banda_padrao)
    verificar(g, esperado_nos, esperado_links, ignorar_contagem)
    return g


def grafo_aleatorio(n_nos, n_links, semente, banda=BANDA_PADRAO):
    """Erdos-Renyi G(n, m) conexo (mesmo modelo do artigo para a Random Topology)."""
    s = semente
    while True:
        g = nx.gnm_random_graph(n_nos, n_links, seed=s)
        if nx.is_connected(g):
            for _, _, d in g.edges(data=True):
                d["bandwidth"] = float(banda)
            g.graph["semente_grafo"] = s
            return g
        s += 1000


def verificar(g, esperado_nos=None, esperado_links=None, ignorar_contagem=False):
    problemas = []
    if esperado_nos is not None and g.number_of_nodes() != esperado_nos:
        problemas.append(f"{g.number_of_nodes()} nos (esperado {esperado_nos})")
    if esperado_links is not None and g.number_of_edges() != esperado_links:
        problemas.append(f"{g.number_of_edges()} links (esperado {esperado_links})")
    if not nx.is_connected(g):
        comps = sorted((len(c) for c in nx.connected_components(g)), reverse=True)
        raise SystemExit(f"Grafo nao conexo (componentes: {comps}). O FluidC exige grafo conexo.")
    if problemas and not ignorar_contagem:
        raise SystemExit("Grafo difere do artigo: " + "; ".join(problemas) +
                         ". Confira o arquivo ou use --ignorar-contagem.")
    if problemas:
        print("AVISO: " + "; ".join(problemas))
    return g


def resumo(g):
    bw = [d["bandwidth"] for _, _, d in g.edges(data=True)]
    return (f"{g.number_of_nodes()} nos, {g.number_of_edges()} links, "
            f"grau medio {2 * g.number_of_edges() / g.number_of_nodes():.2f}, "
            f"banda media {sum(bw) / len(bw):.0f} MB/s")
