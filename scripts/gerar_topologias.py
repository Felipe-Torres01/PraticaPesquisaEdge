"""Gera as topologias do artigo (GARR real e Erdos-Renyi G(n, p)) e, opcionalmente, os datasets EdgeSimPy.

GARR: usa o mapa real do Internet Topology Zoo (Garr201201.gml = rede GARR de nov/2011, ultima versao
publicada no Zoo). O arquivo bruto e baixado do topology-zoo.org (ou do Wayback Machine, se o site
estiver fora do ar) e salvo em cenarios/garr/Garr201201_zoo.gml para rastreabilidade. A versao limpa
(grafo simples, nos 0..N-1) vai para cenarios/garr/garr.gml, que e o formato lido por
topologia.carregar_garr / gerar_cenario.py --garr-arquivo.

    Grafo real: 61 nos (48 PoPs da GARR + 13 pontos de peering externos: GEANT, MIX, NAMEX, Google...)
    e 89 arestas, 75 apos colapsar links paralelos. O artigo cita 70 nos / 112 links, numero que nao
    bate com nenhuma versao publica do Zoo (a maior tem 61/75); por isso gerar_cenario.py precisa de
    --ignorar-contagem com este arquivo. Se o download falhar e nao houver arquivo local, usa
    topologia.aproximacao_garr (parametrizavel com --aprox-nos/--aprox-links) e registra no .info.json.

Erdos-Renyi: G(n, p) conexo (re-sorteia se sair desconexo). O .gml e so para inspecao; o experimento
regenera o mesmo grafo via gerar_cenario.py --topologia erdos_renyi --nos N --prob P --seed S.

Exemplos (a partir da raiz do repositorio):
    python scripts/gerar_topologias.py --garr
    python scripts/gerar_topologias.py --garr --banda-real            # banda real de cada link da GARR
    python scripts/gerar_topologias.py --er --nos 100 --prob 0.049 --seed 1
    python scripts/gerar_topologias.py --hex --hex-x 10 --hex-y 10     # malha hexagonal (rede celular)
    python scripts/gerar_topologias.py --garr --er --datasets --ks 1,2,4,8 --metodos fluidc,aleatorio

Unidades: banda em MB/s (125 = 1 Gbps). O garr.gml so grava banda nas arestas com --banda-real;
sem ela, gerar_cenario.py aplica --banda-link a todos os links.
"""
import argparse
import json
import os
import sys
import urllib.request
from types import SimpleNamespace

import networkx as nx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gerar_cenario
import topologia

GARR_VERSAO = "Garr201201"
GARR_URLS = [
    f"http://www.topology-zoo.org/files/{GARR_VERSAO}.gml",
    f"https://web.archive.org/web/2021id_/http://www.topology-zoo.org/files/{GARR_VERSAO}.gml",
]
PASTA_GARR = os.path.join("cenarios", "garr")
PASTA_ER = os.path.join("cenarios", "erdos_renyi")
PASTA_HEX = os.path.join("cenarios", "hexagonal")


# ----------------------------------------------------------------------------- GARR
def baixar_garr(destino, timeout=60):
    """Baixa o .gml bruto do Zoo para `destino`. Devolve a URL usada, ou None se todas falharem."""
    for url in GARR_URLS:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                dados = r.read()
        except Exception as e:
            print(f"  falhou {url}: {e}")
            continue
        if b"node [" in dados:
            with open(destino, "wb") as f:
                f.write(dados)
            return url
    return None


def limpar_garr(bruto, banda_padrao, banda_real, so_internos):
    """Multigrafo do Zoo -> grafo simples com 'bandwidth' (MB/s), nome e coordenadas de cada no.
    Links paralelos viram um so; com banda_real a banda dele e a soma das bandas dos paralelos."""
    if so_internos:
        bruto = bruto.subgraph([n for n, d in bruto.nodes(data=True) if d.get("Internal") == 1]).copy()
    g = nx.Graph()
    for n, d in bruto.nodes(data=True):
        g.add_node(n, nome=str(d.get("label", n)), interno=int(d.get("Internal", 0)),
                   lat=float(d.get("Latitude", 0.0)), lon=float(d.get("Longitude", 0.0)))
    for u, v, d in bruto.edges(data=True):
        if u == v:
            continue
        bw = (topologia.velocidade_zoo_MBps(d) if banda_real else None) or float(banda_padrao)
        if g.has_edge(u, v):
            g[u][v]["paralelos"] += 1
            if banda_real:
                g[u][v]["bandwidth"] += bw
        else:
            g.add_edge(u, v, bandwidth=bw, paralelos=1)
    g.remove_nodes_from([n for n in list(g.nodes) if g.degree(n) == 0])
    return nx.convert_node_labels_to_integers(g, ordering="sorted")


def gerar_garr(a):
    os.makedirs(PASTA_GARR, exist_ok=True)
    caminho_bruto = a.garr_bruto or os.path.join(PASTA_GARR, f"{GARR_VERSAO}_zoo.gml")
    origem = caminho_bruto if os.path.exists(caminho_bruto) else None
    if origem is None and not a.garr_bruto:
        print(f"Baixando {GARR_VERSAO} do Internet Topology Zoo...")
        origem = baixar_garr(caminho_bruto)

    if origem:
        bruto = topologia.ler_gml_topology_zoo(caminho_bruto)
        g = limpar_garr(bruto, a.banda_link, a.banda_real, a.so_internos)
        info = {"fonte": "Internet Topology Zoo", "versao": GARR_VERSAO, "origem": origem,
                "arquivo_bruto": caminho_bruto, "nos_bruto": bruto.number_of_nodes(),
                "arestas_bruto": bruto.number_of_edges(), "aproximacao": False}
    else:
        print("AVISO: GARR real indisponivel; usando aproximacao sintetica (topologia.aproximacao_garr).")
        g = topologia.aproximacao_garr(a.aprox_nos, a.aprox_links, a.seed, a.banda_link)
        info = {"fonte": "aproximacao sintetica (arvore BA m=1 + atalhos preferenciais)",
                "aproximacao": True, "aprox_nos": a.aprox_nos, "aprox_links": a.aprox_links, "seed": a.seed}

    topologia.verificar(g)
    saida = a.garr_saida or os.path.join(PASTA_GARR, "garr.gml")
    bw = [d["bandwidth"] for _, _, d in g.edges(data=True)]
    arquivo = g.copy()
    if not a.banda_real:
        # sem banda no arquivo: quem carrega aplica --banda-link (senao o parametro seria ignorado)
        for _, _, d in arquivo.edges(data=True):
            del d["bandwidth"]
    nx.write_gml(arquivo, saida)
    info.update({"arquivo": saida, "nos": g.number_of_nodes(), "links": g.number_of_edges(),
                 "so_internos": a.so_internos, "banda_real": a.banda_real,
                 "banda_min_MBps": min(bw), "banda_max_MBps": max(bw),
                 "grau_medio": round(2 * g.number_of_edges() / g.number_of_nodes(), 3),
                 "diametro": nx.diameter(g)})
    with open(os.path.splitext(saida)[0] + ".info.json", "w") as f:
        json.dump(info, f, indent=1)
    print(f"GARR -> {saida}: {topologia.resumo(g)}, diametro {info['diametro']}")
    return saida


# ----------------------------------------------------------------------------- Erdos-Renyi
def gerar_er(a):
    os.makedirs(PASTA_ER, exist_ok=True)
    g = topologia.grafo_erdos_renyi(a.nos, a.prob, a.seed, banda=a.banda_link)
    saida = os.path.join(PASTA_ER, f"er_n{a.nos}_p{a.prob}_s{a.seed}.gml")
    nx.write_gml(nx.Graph(g.edges()), saida)
    print(f"Erdos-Renyi G({a.nos}, {a.prob}) -> {saida}: {topologia.resumo(g)}, "
          f"diametro {nx.diameter(g)} (semente do grafo {g.graph['semente_grafo']})")


# ----------------------------------------------------------------------------- hexagonal
def gerar_hex(a):
    os.makedirs(PASTA_HEX, exist_ok=True)
    g = topologia.grade_hexagonal(a.hex_x, a.hex_y, banda=a.banda_link)
    saida = os.path.join(PASTA_HEX, f"hexagonal_{a.hex_x}x{a.hex_y}.gml")
    h = nx.Graph()
    for n, d in g.nodes(data=True):
        h.add_node(n, x=d["coordenadas"][0], y=d["coordenadas"][1])
    h.add_edges_from(g.edges())
    nx.write_gml(h, saida)
    print(f"Hexagonal {a.hex_x}x{a.hex_y} -> {saida}: {topologia.resumo(g)}, diametro {nx.diameter(g)}")


# ----------------------------------------------------------------------------- datasets EdgeSimPy
def args_cenario(a, topo, k, metodo, garr_arquivo):
    """Namespace equivalente a linha de comando do gerar_cenario.py."""
    return SimpleNamespace(
        topologia=topo, garr_arquivo=garr_arquivo, ignorar_contagem=True,
        nos=a.nos, links=242, prob=a.prob, hex_x=a.hex_x, hex_y=a.hex_y, banda_link=a.banda_link,
        banda_registry=gerar_cenario.BANDA_REGISTRY, segundos_por_tick=a.segundos_por_tick,
        registries=k, metodo=metodo, centralidade="eigenvector", posicoes=None,
        servicos=a.servicos, imagens=gerar_cenario.N_IMAGENS,
        tamanho_imagem=a.tamanho_imagem, tamanho_faixa=a.tamanho_faixa, seed=a.seed,
        imagens_dockerhub=a.imagens_dockerhub, top_imagens=0, popularidade=a.popularidade, zipf_s=1.0,
        template=os.path.join("cenarios", "dataset_registries.json"))


def gerar_datasets(a, topologias):
    os.makedirs(a.pasta_datasets, exist_ok=True)
    for topo, garr_arquivo in topologias:
        for k in [int(x) for x in a.ks.split(",")]:
            for metodo in a.metodos.split(","):
                D, info = gerar_cenario.gerar(args_cenario(a, topo, k, metodo, garr_arquivo))
                gerar_cenario.validar(D)
                saida = os.path.join(a.pasta_datasets, f"{topo}_{metodo}_k{k}_s{a.seed}.json")
                with open(saida, "w") as f:
                    json.dump(D, f)
                with open(saida.replace(".json", ".info.json"), "w") as f:
                    json.dump(info, f, indent=1)
                print(f"  dataset {saida}: registries nos nos {info['posicoes']}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--garr", action="store_true", help="gera cenarios/garr/garr.gml a partir do Topology Zoo")
    p.add_argument("--garr-bruto", help="usa este .gml do Zoo em vez de baixar")
    p.add_argument("--garr-saida", help="padrao: cenarios/garr/garr.gml")
    p.add_argument("--banda-real", action="store_true",
                   help="usa a banda real de cada link da GARR (LinkSpeedRaw); padrao: --banda-link em todos")
    p.add_argument("--so-internos", action="store_true", help="descarta os 13 nos de peering externo")
    p.add_argument("--aprox-nos", type=int, default=61, help="aproximacao da GARR: numero de nos")
    p.add_argument("--aprox-links", type=int, default=75, help="aproximacao da GARR: numero de links")
    p.add_argument("--er", action="store_true", help="gera um grafo Erdos-Renyi G(n, p)")
    p.add_argument("--nos", type=int, default=100)
    p.add_argument("--prob", type=float, default=0.049)
    p.add_argument("--hex", action="store_true", help="gera a malha hexagonal (rede celular)")
    p.add_argument("--hex-x", type=int, default=10)
    p.add_argument("--hex-y", type=int, default=10)
    p.add_argument("--banda-link", type=float, default=topologia.BANDA_PADRAO, help="MB/s (125 = 1 Gbps)")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--datasets", action="store_true", help="tambem gera os datasets EdgeSimPy (.json)")
    p.add_argument("--ks", default="1,2,4,8")
    p.add_argument("--metodos", default="fluidc,aleatorio")
    p.add_argument("--servicos", type=int, default=60)
    p.add_argument("--tamanho-imagem", type=float, default=gerar_cenario.TAMANHO_IMAGEM)
    p.add_argument("--tamanho-faixa", help="MIN,MAX em MB por imagem")
    p.add_argument("--imagens-dockerhub", help="JSON do coletar_dockerhub.py (imagens reais)")
    p.add_argument("--popularidade", choices=["uniforme", "zipf"], default="uniforme")
    p.add_argument("--segundos-por-tick", type=float, default=1.0)
    p.add_argument("--pasta-datasets", default=os.path.join("cenarios", "gerados"))
    a = p.parse_args()
    if not (a.garr or a.er or a.hex):
        p.error("escolha --garr, --er e/ou --hex")

    topologias = []
    if a.garr:
        topologias.append(("garr", gerar_garr(a)))
    if a.er:
        gerar_er(a)
        topologias.append(("erdos_renyi", None))
    if a.hex:
        gerar_hex(a)
        topologias.append(("hexagonal", None))
    if a.datasets:
        gerar_datasets(a, topologias)


if __name__ == "__main__":
    main()
