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


def _ponta(x, nomes):
    if isinstance(x, dict):
        x = x.get("name", x.get("id"))
    if isinstance(x, int) and nomes and x < len(nomes) and x not in nomes:
        return nomes[x]
    return x


def _banda_MBps(bw):
    if bw in (None, ""):
        return None
    if isinstance(bw, (int, float)):
        return float(bw)
    t = str(bw).strip().lower().replace("bps", "").replace("b", "")
    mult = {"k": 1e-3, "m": 1.0, "g": 1e3, "t": 1e6}
    if t and t[-1] in mult:
        return float(t[:-1]) * mult[t[-1]] / 8
    return float(t)


def _ler_json(caminho):
    d = json.load(open(caminho))
    g = nx.Graph()
    nomes = []
    for n in d.get("nodes", []):
        if isinstance(n, dict):
            nome = n.get("name", n.get("id"))
            g.add_node(nome, label=nome, pos=n.get("pos"))
        else:
            nome = n
            g.add_node(nome)
        nomes.append(nome)
    for e in d["edges"]:
        if isinstance(e, dict):
            u = e.get("source", e.get("u", e.get("from")))
            v = e.get("target", e.get("v", e.get("to")))
            bw = _banda_MBps(e.get("bandwidth"))
        else:
            u, v = e[0], e[1]
            bw = e[2] if len(e) > 2 else None
        g.add_edge(_ponta(u, nomes), _ponta(v, nomes), bandwidth=bw)
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


def grafo_erdos_renyi(n_nos, prob, semente, banda=BANDA_PADRAO, max_tentativas=10000):
    """Erdos-Renyi G(n, p) conexo: cada par de nos ganha uma aresta com probabilidade p.
    Se o grafo sorteado sair desconexo, sorteia de novo com outra semente (nao corta nos)."""
    s = semente
    for _ in range(max_tentativas):
        g = nx.gnp_random_graph(n_nos, prob, seed=s)
        if nx.is_connected(g):
            for _, _, d in g.edges(data=True):
                d["bandwidth"] = float(banda)
            g.graph["semente_grafo"] = s
            return g
        s += 1000
    raise SystemExit(f"G({n_nos}, {prob}) nao gerou grafo conexo em {max_tentativas} tentativas; aumente p.")


def grade_hexagonal(x_size, y_size, banda=BANDA_PADRAO):
    """Malha hexagonal no estilo de rede celular: cada no e uma celula (estacao-base + servidor de borda)
    ligada as ate 6 celulas vizinhas. Mesma convencao do gerador do EdgeSimPy
    (dataset_generator.map.hexagonal_grid + network_topologies.partially_connected_hexagonal_mesh,
    adaptados de Aral et al. / Zilic et al.): coordenadas (x, y) com x de 0 a 2*x_size-1 e x % 2 == y % 2;
    vizinhos em (x+-2, y) e (x+-1, y+-1). x_size = y_size = 10 da 100 nos e 261 links."""
    coords = [(x, y) for y in range(y_size) for x in range(2 * x_size) if x % 2 == y % 2]
    indice = {c: i for i, c in enumerate(coords)}
    g = nx.Graph()
    for i, c in enumerate(coords):
        g.add_node(i, coordenadas=c)
    for (x, y), i in indice.items():
        for viz in ((x + 2, y), (x + 1, y + 1), (x - 1, y + 1)):  # metade dos 6 vizinhos basta (grafo nao dirigido)
            if viz in indice:
                g.add_edge(i, indice[viz], bandwidth=float(banda))
    g.graph["coordenadas"] = coords
    return g


def ler_gml_topology_zoo(caminho):
    """Le um .gml do Internet Topology Zoo. Esses arquivos tem arestas paralelas sem declarar
    'multigraph 1', o que faz o nx.read_gml falhar; o cabecalho e inserido antes do parse."""
    texto = open(caminho, encoding="utf-8").read()
    if "multigraph" not in texto.split("node [", 1)[0]:
        texto = texto.replace("graph [", "graph [\n  multigraph 1", 1)
    return nx.parse_gml(texto, label="id")


def velocidade_zoo_MBps(d):
    """Banda de uma aresta do Topology Zoo (LinkSpeedRaw, em bit/s) em MB/s. None se ausente."""
    bruto = d.get("LinkSpeedRaw")
    return float(bruto) / 8e6 if bruto not in (None, "") else None


def aproximacao_garr(n_nos=61, n_links=75, semente=1, banda=BANDA_PADRAO):
    """Aproximacao parametrizavel da GARR, para quando o arquivo real nao estiver disponivel.

    Redes academicas nacionais como a GARR sao quase arvores (grau medio ~2.5) com poucos hubs de
    grau alto. Isso e reproduzido com uma arvore de anexacao preferencial (Barabasi-Albert, m=1)
    completada ate n_links com atalhos que ligam preferencialmente nos de grau alto."""
    import random
    if n_links < n_nos - 1:
        raise SystemExit("aproximacao_garr: n_links precisa ser >= n_nos - 1 (grafo conexo)")
    rng = random.Random(semente)
    g = nx.barabasi_albert_graph(n_nos, 1, seed=semente)
    while g.number_of_edges() < n_links:
        pesos = [g.degree(n) for n in g.nodes]
        u, v = rng.choices(list(g.nodes), weights=pesos, k=2)
        if u != v and not g.has_edge(u, v):
            g.add_edge(u, v)
    for _, _, d in g.edges(data=True):
        d["bandwidth"] = float(banda)
    g.graph["aproximacao"] = True
    return g


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
