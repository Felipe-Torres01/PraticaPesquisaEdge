import argparse
import copy
import hashlib
import json
import math
import random
 
import networkx as nx
 
N_NOS = 100
N_LINKS = 242
N_IMAGENS = 13
TAMANHO_IMAGEM = 200
BANDA_NO = 125
BANDA_REGISTRY = 1250
 
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
 
 
def grafo_aleatorio(semente):
    s = semente
    while True:
        g = nx.gnm_random_graph(N_NOS, N_LINKS, seed=s)
        if nx.is_connected(g):
            return g, s
        s += 1000
 
 
def carregar_modelos(caminho):
    d = json.load(open(caminho))
    return {k: v[0] for k, v in d.items() if v}
 
 
def gerar(args):
    m = carregar_modelos(args.template)
    rng = random.Random(args.seed)
    g, semente_grafo = grafo_aleatorio(args.seed)
 
    k = args.registries
    if not 1 <= k <= N_NOS:
        raise SystemExit(f"--registries deve estar entre 1 e {N_NOS}")
    if args.posicoes:
        posicoes = [int(x) for x in args.posicoes.split(",")]
        if len(posicoes) != k or len(set(posicoes)) != k:
            raise SystemExit("--posicoes precisa ter K ids distintos")
        if any(not 1 <= p <= N_NOS for p in posicoes):
            raise SystemExit(f"--posicoes: ids entre 1 e {N_NOS}")
    else:
        posicoes = sorted(rng.sample(range(1, N_NOS + 1), k))
 
    total = N_NOS + k
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
        if n > N_NOS:
            srv["attributes"]["cpu"] = 1
            srv["attributes"]["memory"] = 1
        srv["relationships"]["base_station"] = ref("BaseStation", n)
        srv["relationships"]["network_switch"] = ref("NetworkSwitch", n)
        srv["relationships"]["services"] = []
        srv["relationships"]["container_layers"] = []
        srv["relationships"]["container_images"] = []
        srv["relationships"]["container_registries"] = []
        D["EdgeServer"].append(srv)
 
    arestas = [(a + 1, b + 1, BANDA_NO) for a, b in g.edges()]
    for j, pos in enumerate(posicoes):
        arestas.append((N_NOS + j + 1, pos, BANDA_REGISTRY))
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
        host = N_NOS + j + 1
        reg = copy.deepcopy(m["ContainerRegistry"])
        reg["attributes"]["id"] = j + 1
        reg["relationships"]["server"] = ref("EdgeServer", host)
        D["ContainerRegistry"].append(reg)
        rel = D["EdgeServer"][host - 1]["relationships"]
        rel["container_registries"].append(ref("ContainerRegistry", j + 1))
        for i in range(N_IMAGENS):
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
 
    for i in range(1, args.servicos + 1):
        img = rng.randrange(N_IMAGENS)
        estacao = rng.randint(1, N_NOS)
 
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
 
    info = {"posicoes": posicoes, "hospedeiros": [N_NOS + j + 1 for j in range(k)],
            "semente_grafo": semente_grafo, "links": len(arestas)}
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
 
 
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--registries", type=int, default=1, help="K, numero de registries")
    p.add_argument("--posicoes", help="ids dos nos (1-100) onde ligar os registries, ex: 10,57")
    p.add_argument("--servicos", type=int, default=200,
                   help="numero de servicos (valor nosso, nao vem do artigo)")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--template", default="cenarios/dataset_registries.json")
    p.add_argument("--saida", help="padrao: cenarios/aleatoria_k<K>.json")
    args = p.parse_args()
 
    D, info = gerar(args)
    validar(D)
    saida = args.saida or f"cenarios/aleatoria_k{args.registries}.json"
    with open(saida, "w") as f:
        json.dump(D, f)
    print(f"Gerado: {saida}")
    print(f"  {N_NOS} trabalhadores + {args.registries} hospedeiro(s) de registry, {info['links']} links")
    print(f"  registries ligados aos nos {info['posicoes']} (servidores {info['hospedeiros']})")
    print(f"  {N_IMAGENS} imagens de {TAMANHO_IMAGEM} MB, {args.servicos} servicos, semente do grafo {info['semente_grafo']}")
 
 
if __name__ == "__main__":
    main()
 
