import argparse
import json
import subprocess
import time
import urllib.parse

HUB = "https://hub.docker.com/v2"
BUSCA = "https://hub.docker.com/api/search/v3/catalog/search"


def get(url):
    r = subprocess.run(["curl", "-s", "-f", "-L", "--max-time", "30", url],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"curl falhou (codigo {r.returncode}) em {url}")
    return json.loads(r.stdout)


def repositorio(item):
    for plano in item.get("rate_plans", []):
        for repo in plano.get("repositories", []):
            return repo.get("namespace") or "library", repo.get("name"), repo
    nome = item.get("slug") or item.get("name") or item.get("id")
    ns, _, rep = nome.rpartition("/")
    return ns or "library", rep, {}


def ranking(quantos):
    vistos, lista, inicio = set(), [], 0
    while len(lista) < quantos:
        d = get(f"{BUSCA}?query=&from={inicio}&size=25&sort=pull_count&order=desc")
        itens = d.get("results", [])
        if not itens:
            break
        for item in itens:
            if item.get("type", "image") != "image":
                continue
            ns, rep, info = repositorio(item)
            if not rep or (ns, rep) in vistos:
                continue
            vistos.add((ns, rep))
            lista.append({"namespace": ns, "repo": rep,
                          "pull_count": info.get("pull_count"),
                          "oficial": bool(info.get("is_official")) or ns == "library"})
        inicio += 25
        time.sleep(0.3)
    return lista


def variante_amd64(lista):
    for i in lista:
        if i.get("os") == "linux" and i.get("architecture") == "amd64":
            return i
    return None


def escolher_tag(ns, rep):
    try:
        t = get(f"{HUB}/repositories/{ns}/{rep}/tags/latest")
        if variante_amd64(t.get("images", [])):
            return "latest", t
    except Exception:
        pass
    d = get(f"{HUB}/repositories/{ns}/{rep}/tags?page_size=25&ordering=last_updated")
    for t in d.get("results", []):
        if variante_amd64(t.get("images", [])):
            return t["name"], t
    return None, None


def camadas_da_tag(ns, rep, tag):
    lista = get(f"{HUB}/repositories/{ns}/{rep}/tags/{urllib.parse.quote(tag)}/images")
    alvo = variante_amd64(lista if isinstance(lista, list) else lista.get("results", []))
    camadas = []
    for c in (alvo or {}).get("layers", []):
        if c.get("digest") and c.get("size"):
            camadas.append({"digest": c["digest"], "tamanho_MB": round(c["size"] / 1e6, 3)})
    return camadas


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--top", type=int, default=50)
    p.add_argument("--saida", default="cenarios/dockerhub_top50.json")
    a = p.parse_args()

    candidatos = ranking(a.top + 30)
    print(f"{len(candidatos)} repositorios no ranking por downloads")

    resultado = []
    for posicao, c in enumerate(candidatos, start=1):
        if len(resultado) >= a.top:
            break
        nome = f"{c['namespace']}/{c['repo']}"
        try:
            tag, info = escolher_tag(c["namespace"], c["repo"])
            if not tag:
                print(f"   pulando {nome}: sem versao linux/amd64")
                continue
            tamanho = round((variante_amd64(info["images"]).get("size") or 0) / 1e6, 3)
            try:
                camadas = camadas_da_tag(c["namespace"], c["repo"], tag)
            except Exception as e:
                camadas = []
                print(f"   sem camadas para {nome}:{tag} ({e})")
        except Exception as e:
            print(f"   pulando {nome}: {e}")
            continue
        resultado.append({"posicao_ranking": posicao, "nome": nome, "tag": tag,
                          "oficial": c["oficial"], "pull_count": c["pull_count"],
                          "tamanho_MB": tamanho, "camadas": camadas})
        print(f"{len(resultado):2d}. {nome}:{tag}  {tamanho:8.1f} MB  {len(camadas):2d} camadas  "
              f"{c['pull_count']} pulls{'  (oficial)' if c['oficial'] else ''}")
        time.sleep(0.3)

    json.dump({"fonte": "Docker Hub, busca ordenada por pull_count (mesma da pagina hub.docker.com/search)",
               "coletado_em": time.strftime("%Y-%m-%d"), "imagens": resultado},
              open(a.saida, "w"), indent=2)
    com_camadas = sum(1 for i in resultado if i["camadas"])
    total = sum(i["tamanho_MB"] for i in resultado)
    print(f"\n{len(resultado)} imagens salvas em {a.saida} "
          f"({com_camadas} com lista de camadas, {total/1000:.1f} GB no total)")


if __name__ == "__main__":
    main()
