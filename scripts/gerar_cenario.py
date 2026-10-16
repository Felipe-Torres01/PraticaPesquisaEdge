"""Gera o dataset JSON do EdgeSimPy para a topologia GARR (ou aleatoria) com K registries.

Exemplos (rodar a partir da raiz do repositorio):
    # GARR + FluidC (artigo) com 4 registries
    python scripts/gerar_cenario.py --topologia garr --garr-arquivo cenarios/garr/garr.gml --metodo fluidc --registries 4

    # GARR + posicao aleatoria (baseline do artigo)
    python scripts/gerar_cenario.py --topologia garr --garr-arquivo cenarios/garr/garr.gml --metodo aleatorio --registries 4 --seed 2

    # Teste do pipeline sem o arquivo GARR (grafo aleatorio com 70 nos e 112 links)
    python scripts/gerar_cenario.py --topologia aleatoria --nos 70 --links 112 --registries 4

    # Topologia aleatoria do artigo (100 nos, 242 links)
    python scripts/gerar_cenario.py --topologia aleatoria --registries 4

Unidades: banda em MB/s (125 = 1 Gbps, 1250 = 10 Gbps); tamanho das camadas em MB.
"""
import argparse
import copy
import hashlib
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fluidc_placement
import topologia

N_IMAGENS = 13          # Tabela II do artigo
TAMANHO_IMAGEM = 200    # MB, Tabela II
BANDA_REGISTRY = 1250   # MB/s = 10 Gbps, Tabela II

SECOES = [
    "NetworkSwitch", "NetworkLink", "BaseStation", "User", "ContainerLayer",
    "ContainerImage", "Service", "ContainerRegistry", "Application",
    "EdgeServer", "RandomDurationAndIntervalAccessPattern",
    "CircularDurationAndIntervalAccessPattern",
]


def ref(classe, i):
    return {"class": classe, "id": i}


def digest(texto):
    return "sha256:" + hashlib.sha256(texto.encode()).hexdigest()


def carregar_modelos(caminho):
    d = json.load(open(caminho))
    return {k: v[0] for k, v in d.items() if v}


def numero(x):
    return int(x) if float(x).is_integer() else float(x)


def montar_grafo(args):
    if args.topologia == "garr":
        if not args.garr_arquivo:
            raise SystemExit("--topologia garr exige --garr-arquivo (ex: cenarios/garr/garr.gml)")
        return topologia.carregar_garr(args.garr_arquivo, banda_padrao=args.banda_link,
                                       ignorar_contagem=args.ignorar_contagem)
    g = topologia.grafo_aleatorio(args.nos, args.links, args.seed, banda=args.banda_link)
    return topologia.verificar(g)


def gerar(args):
    m = carregar_modelos(args.template)
    rng = random.Random(args.seed)          # usado so para servicos/usuarios (igual entre metodos)
    g = montar_grafo(args)
    n_nos = g.number_of_nodes()
    k = args.registries

    if args.posicoes:
        posicoes = [int(x) for x in args.posicoes.split(",")]
        if len(posicoes) != k or len(set(posicoes)) != k:
            raise SystemExit("--posicoes precisa ter K ids distintos")
        if any(not 1 <= p <= n_nos for p in posicoes):
            raise SystemExit(f"--posicoes: ids entre 1 e {n_nos}")
        colocacao = {"metodo": "manual", "posicoes": sorted(posicoes), "comunidades": None}
    else:
        colocacao = fluidc_placement.posicionar(g, args.metodo, k, args.seed, args.centralidade)
        posicoes = colocacao["posicoes"]

    # Particao de REFERENCIA para medir trafego intra/inter-comunidades: comunidades do FluidC para o mesmo
    # grafo, K e seed. E a mesma para qualquer --metodo, entao FluidC e aleatorio sao medidos igualmente.
    if colocacao.get("comunidades"):
        referencia = [sorted(v) for v in colocacao["comunidades"].values()]
    else:
        comunidades, _, _ = fluidc_placement.fase1_comunidades(g, k, args.seed)
        referencia = [sorted(n + 1 for n in c) for c in comunidades]

    total = n_nos + k
    lado = math.ceil(math.sqrt(total))

    def coord(n):
        return [(n - 1) % lado, (n - 1) // lado]

    D = {s: [] for s in SECOES}

    for n in range(1, total + 1):
        sw = copy.deepcopy(m["NetworkSwitch"])
        sw["attributes"]["id"] = n
        sw["attributes"]["coordinates"] = coord(n)
        sw["relationships"]["edge_servers"] = [ref("EdgeServer", n)]
        sw["relationships"]["links"] = []
        sw["relationships"]["base_station"] = ref("BaseStation", n)
        D["NetworkSwitch"].append(sw)

        bs = copy.deepcopy(m["BaseStation"])
        bs["attributes"]["id"] = n
        bs["attributes"]["coordinates"] = coord(n)
        bs["relationships"]["users"] = []
        bs["relationships"]["edge_servers"] = [ref("EdgeServer", n)]
        bs["relationships"]["network_switch"] = ref("NetworkSwitch", n)
        D["BaseStation"].append(bs)

        srv = copy.deepcopy(m["EdgeServer"])
        srv["attributes"]["id"] = n
        srv["attributes"]["coordinates"] = coord(n)
        if n > n_nos:                       # hospedeiro do registry: sem folga para servicos
            srv["attributes"]["cpu"] = 1
            srv["attributes"]["memory"] = 1
        srv["relationships"]["base_station"] = ref("BaseStation", n)
        srv["relationships"]["network_switch"] = ref("NetworkSwitch", n)
        srv["relationships"]["services"] = []
        srv["relationships"]["container_layers"] = []
        srv["relationships"]["container_images"] = []
        srv["relationships"]["container_registries"] = []
        D["EdgeServer"].append(srv)

    # Links: arestas do grafo (banda por aresta) + 1 link de acesso por registry (10 Gbps)
    arestas = [(a + 1, b + 1, numero(d["bandwidth"])) for a, b, d in g.edges(data=True)]
    n_links_rede = len(arestas)
    for j, pos in enumerate(posicoes):
        arestas.append((n_nos + j + 1, pos, numero(args.banda_registry)))
    for lid, (a, b, banda) in enumerate(arestas, start=1):
        link = copy.deepcopy(m["NetworkLink"])
        link["attributes"]["id"] = lid
        link["attributes"]["bandwidth"] = banda
        link["relationships"]["active_flows"] = []
        link["relationships"]["applications"] = []
        link["relationships"]["nodes"] = [ref("NetworkSwitch", a), ref("NetworkSwitch", b)]
        D["NetworkLink"].append(link)
        for n in (a, b):
            D["NetworkSwitch"][n - 1]["relationships"]["links"].append(ref("NetworkLink", lid))

    layer_id = image_id = 0
    for j in range(k):
        host = n_nos + j + 1
        reg = copy.deepcopy(m["ContainerRegistry"])
        reg["attributes"]["id"] = j + 1
        reg["relationships"]["server"] = ref("EdgeServer", host)
        D["ContainerRegistry"].append(reg)
        rel = D["EdgeServer"][host - 1]["relationships"]
        rel["container_registries"].append(ref("ContainerRegistry", j + 1))
        for i in range(args.imagens):
            layer_id += 1
            image_id += 1
            camada = copy.deepcopy(m["ContainerLayer"])
            camada["attributes"].update(
                id=layer_id, digest=digest(f"camada-{i}"),
                size=TAMANHO_IMAGEM, instruction=f"ADD imagem-{i}")
            camada["relationships"]["server"] = ref("EdgeServer", host)
            D["ContainerLayer"].append(camada)
            imagem = copy.deepcopy(m["ContainerImage"])
            imagem["attributes"].update(
                id=image_id, name=f"imagem-{i}", tag="latest",
                digest=digest(f"imagem-{i}"),
                layers_digests=[digest(f"camada-{i}")], architecture="")
            imagem["relationships"]["server"] = ref("EdgeServer", host)
            D["ContainerImage"].append(imagem)
            rel["container_layers"].append(ref("ContainerLayer", layer_id))
            rel["container_images"].append(ref("ContainerImage", image_id))

    # Servicos: imagem sorteada entre as 13 e estacao-base (zona operacional) sorteada entre as N zonas
    for i in range(1, args.servicos + 1):
        img = rng.randrange(args.imagens)
        estacao = rng.randint(1, n_nos)

        svc = copy.deepcopy(m["Service"])
        svc["attributes"].update(id=i, label=f"Servico {i}",
                                 image_digest=digest(f"imagem-{img}"))
        svc["relationships"]["application"] = ref("Application", i)
        svc["relationships"]["server"] = None
        D["Service"].append(svc)

        app = copy.deepcopy(m["Application"])
        app["attributes"].update(id=i, label="", provisioned=False)
        app["relationships"]["services"] = [ref("Service", i)]
        app["relationships"]["users"] = [ref("User", i)]
        D["Application"].append(app)

        usr = copy.deepcopy(m["User"])
        xy = coord(estacao)
        usr["attributes"]["id"] = i
        usr["attributes"]["coordinates"] = xy
        usr["attributes"]["coordinates_trace"] = [list(xy)] * 3
        usr["attributes"]["delays"] = {str(i): None}
        usr["attributes"]["delay_slas"] = {str(i): 3}
        usr["attributes"]["communication_paths"] = {str(i): None}
        usr["attributes"]["making_requests"] = {str(i): {"1": True}}
        usr["relationships"]["access_patterns"] = {
            str(i): ref("CircularDurationAndIntervalAccessPattern", i)}
        usr["relationships"]["applications"] = [ref("Application", i)]
        usr["relationships"]["base_station"] = ref("BaseStation", estacao)
        D["User"].append(usr)
        D["BaseStation"][estacao - 1]["relationships"]["users"].append(ref("User", i))

        pad = copy.deepcopy(m["CircularDurationAndIntervalAccessPattern"])
        pad["attributes"]["id"] = i
        pad["relationships"]["user"] = ref("User", i)
        pad["relationships"]["app"] = ref("Application", i)
        D["CircularDurationAndIntervalAccessPattern"].append(pad)

    info = {
        "topologia": args.topologia, "n_nos": n_nos, "links_rede": n_links_rede,
        "links_total": len(arestas), "k": k, "metodo": colocacao["metodo"],
        "centralidade": args.centralidade, "seed": args.seed,
        "posicoes": posicoes, "hospedeiros": [n_nos + j + 1 for j in range(k)],
        "comunidades": ({str(r): v for r, v in colocacao["comunidades"].items()}
                        if colocacao.get("comunidades") else None),
        "desvio_banda": colocacao.get("desvio_banda"),
        "comunidades_referencia": referencia,
        "servicos": args.servicos, "imagens": args.imagens, "tamanho_imagem_mb": TAMANHO_IMAGEM,
    }
    return D, info


def refs(x):
    if isinstance(x, dict):
        if "class" in x and "id" in x:
            yield x
        for v in x.values():
            yield from refs(v)
    elif isinstance(x, list):
        for v in x:
            yield from refs(v)


def validar(D):
    ids = {s: {o["attributes"]["id"] for o in v} for s, v in D.items()}
    erros = []
    for secao, objs in D.items():
        for o in objs:
            for r in refs(o["relationships"]):
                if r["class"] in ids and r["id"] not in ids[r["class"]]:
                    erros.append(f"{secao} {o['attributes']['id']} -> {r['class']} {r['id']}")
    if erros:
        raise SystemExit("Referencias quebradas:\n  " + "\n  ".join(erros[:20]))


def nome_padrao(args):
    return (f"cenarios/{args.topologia}_{args.metodo if not args.posicoes else 'manual'}"
            f"_k{args.registries}_s{args.seed}.json")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--topologia", choices=["garr", "aleatoria"], default="garr")
    p.add_argument("--garr-arquivo", help="grafo GARR (.gml/.graphml/.csv/.json), 70 nos e 112 links")
    p.add_argument("--nos", type=int, default=100, help="so topologia aleatoria (artigo: 100)")
    p.add_argument("--links", type=int, default=242, help="so topologia aleatoria (artigo: 242)")
    p.add_argument("--banda-link", type=float, default=topologia.BANDA_PADRAO,
                   help="MB/s dos links sem banda propria no arquivo (125 = 1 Gbps)")
    p.add_argument("--banda-registry", type=float, default=BANDA_REGISTRY,
                   help="MB/s do link de acesso do registry (1250 = 10 Gbps)")
    p.add_argument("--registries", type=int, default=1, help="K, numero de registries")
    p.add_argument("--metodo", choices=["fluidc", "aleatorio", "topk_global"], default="fluidc")
    p.add_argument("--centralidade", choices=["eigenvector", "betweenness", "degree"],
                   default="eigenvector", help="artigo usa eigenvector")
    p.add_argument("--posicoes", help="ids dos nos (1..N) dos registries, ex: 10,57 (ignora --metodo)")
    p.add_argument("--servicos", type=int, default=60)
    p.add_argument("--imagens", type=int, default=N_IMAGENS)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--ignorar-contagem", action="store_true",
                   help="aceita GARR com contagem de nos/links diferente de 70/112")
    p.add_argument("--template", default="cenarios/dataset_registries.json")
    p.add_argument("--saida", help="padrao: cenarios/<topologia>_<metodo>_k<K>_s<seed>.json")
    args = p.parse_args()

    D, info = gerar(args)
    validar(D)
    saida = args.saida or nome_padrao(args)
    os.makedirs(os.path.dirname(saida) or ".", exist_ok=True)
    with open(saida, "w") as f:
        json.dump(D, f)
    with open(saida.replace(".json", ".info.json"), "w") as f:
        json.dump(info, f, indent=1)
    print(f"Gerado: {saida}")
    print(f"  {info['n_nos']} nos + {info['k']} hospedeiro(s) de registry, "
          f"{info['links_rede']} links de rede + {info['k']} de acesso")
    print(f"  metodo {info['metodo']}: registries nos nos {info['posicoes']}")
    print(f"  {info['imagens']} imagens de {TAMANHO_IMAGEM} MB, {info['servicos']} servicos")


if __name__ == "__main__":
    main()