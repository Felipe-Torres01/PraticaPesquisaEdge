"""Varredura completa: K x metodo de posicionamento x seeds. Compara FluidC com baselines.

Exemplos (a partir da raiz do repositorio):
    # Teste rapido do pipeline SEM o arquivo GARR (grafo aleatorio 70 nos / 112 links)
    python scripts/experimento.py --topologia aleatoria --nos 70 --links 112 --seeds 1,2 --ks 1,4

    # Experimento do artigo na GARR (K = 1, 2, 4, 8; FluidC x aleatorio; 10 seeds)
    python scripts/experimento.py --topologia garr --garr-arquivo cenarios/garr/garr.gml \
        --ks 1,2,4,8 --metodos fluidc,aleatorio --seeds 1,2,3,4,5,6,7,8,9,10 --jobs 4

Saidas em resultados/<nome>/:
    resumo_experimento.csv      1 linha por execucao (K, metodo, seed, tempos, saturacao, ...)
    comparacao_por_k.csv        medias por (metodo, K) e razao aleatorio / fluidc
    cdf_provisionamento.png     CDF do tempo de provisionamento por K (como a Fig. 3 do artigo)
    tempo_e_saturacao.png       tempo medio por K e link-ticks saturados por tipo de link
    <execucao>/                 saidas completas do run_cenario.py (ticks.csv, links_por_tick.csv, ...)
"""
import argparse
import csv
import json
import os
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

AQUI = os.path.dirname(os.path.abspath(__file__))


def executar(cmd, timeout):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def uma_execucao(a, k, metodo, seed, raiz):
    nome = f"{a.topologia}_{metodo}_k{k}_s{seed}"
    cenario = os.path.join("cenarios", "gerados", nome + ".json")
    pasta = os.path.join(raiz, nome)
    if os.path.exists(os.path.join(pasta, "resumo.json")) and not a.refazer:
        return nome, json.load(open(os.path.join(pasta, "resumo.json"))), None

    gerar = [sys.executable, os.path.join(AQUI, "gerar_cenario.py"),
             "--topologia", a.topologia, "--registries", str(k), "--metodo", metodo,
             "--centralidade", a.centralidade, "--seed", str(seed), "--servicos", str(a.servicos),
             "--saida", cenario]
    if a.topologia == "garr":
        gerar += ["--garr-arquivo", a.garr_arquivo]
        if a.ignorar_contagem:
            gerar += ["--ignorar-contagem"]
    else:
        gerar += ["--nos", str(a.nos), "--links", str(a.links)]
    if a.banda_link:
        gerar += ["--banda-link", str(a.banda_link)]
    code, out, err = executar(gerar, 600)
    if code != 0:
        return nome, None, "gerar_cenario: " + (err or out)[-400:]

    rodar = [sys.executable, os.path.join(AQUI, "run_cenario.py"), cenario, "--saida", pasta,
             "--scheduler", a.scheduler, "--seed", str(seed), "--taxa", str(a.taxa),
             "--max-ticks", str(a.max_ticks)]
    code, out, err = executar(rodar, a.timeout)
    if code != 0 or not os.path.exists(os.path.join(pasta, "resumo.json")):
        return nome, None, "run_cenario: " + (err or out)[-400:]
    return nome, json.load(open(os.path.join(pasta, "resumo.json"))), None


def linha_resumo(a, k, metodo, seed, r):
    t = r["tempo_provisionamento"]
    s = r["saturacao"]
    down = r["downloads_total"] or 1
    por_reg = list(r["downloads_por_registry"].values()) or [0]
    return {
        "topologia": a.topologia, "metodo": metodo, "k": k, "seed": seed,
        "ticks_totais": r["ticks_totais"], "nao_iniciados": r["nao_iniciados"],
        "tempo_medio": t["media"], "tempo_p50": t["p50"], "tempo_p90": t["p90"],
        "tempo_p99": t["p99"], "tempo_max": t["max"],
        "link_ticks_sat_intra": s["link_ticks_saturados_intra"],
        "link_ticks_sat_inter": s["link_ticks_saturados_inter"],
        "link_ticks_sat_acesso": s["link_ticks_saturados_acesso"],
        "links_saturados_pico": s["links_saturados_pico"],
        "downloads": r["downloads_total"],
        "pct_downloads_cruzam_comunidade": round(100 * r["downloads_que_cruzam_comunidade"] / down, 2),
        "pct_registry_na_comunidade": round(100 * r["downloads_com_registry_na_comunidade"] / down, 2),
        "maior_parcela_de_um_registry_pct": round(100 * max(por_reg) / down, 2),
    }


def media(v):
    v = [x for x in v if x is not None]
    return round(statistics.mean(v), 3) if v else None


def comparar(linhas):
    grupos = {}
    for l in linhas:
        grupos.setdefault((l["metodo"], l["k"]), []).append(l)
    campos = ["tempo_medio", "tempo_p90", "tempo_max", "ticks_totais", "nao_iniciados",
              "link_ticks_sat_intra", "link_ticks_sat_inter", "link_ticks_sat_acesso",
              "pct_downloads_cruzam_comunidade", "pct_registry_na_comunidade"]
    saida = []
    for (metodo, k), ls in sorted(grupos.items(), key=lambda x: (x[0][1], x[0][0])):
        row = {"metodo": metodo, "k": k, "execucoes": len(ls)}
        for c in campos:
            row[c] = media([l[c] for l in ls])
            row[c + "_dp"] = (round(statistics.stdev([l[c] for l in ls]), 3) if len(ls) > 1 else 0.0)
        saida.append(row)
    # razao baseline / fluidc (>1 = FluidC melhor)
    ref = {(r["metodo"], r["k"]): r for r in saida}
    for r in saida:
        f = ref.get(("fluidc", r["k"]))
        r["razao_tempo_medio_vs_fluidc"] = (round(r["tempo_medio"] / f["tempo_medio"], 3)
                                            if f and f["tempo_medio"] else None)
    return saida


def escrever_csv(caminho, linhas):
    if not linhas:
        return
    campos = list(linhas[0].keys())
    for l in linhas:
        for c in l:
            if c not in campos:
                campos.append(c)
    with open(caminho, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(linhas)


def graficos(raiz, linhas, ks, metodos):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print("graficos nao gerados:", e)
        return
    cores = {"fluidc": "#1f77b4", "aleatorio": "#d62728", "topk_global": "#2ca02c"}

    fig, eixos = plt.subplots(1, len(ks), figsize=(4.2 * len(ks), 3.8), squeeze=False, sharey=True)
    for ax, k in zip(eixos[0], ks):
        for m in metodos:
            tempos = []
            for l in linhas:
                if l["metodo"] == m and l["k"] == k:
                    cam = os.path.join(raiz, f"{l['topologia']}_{m}_k{k}_s{l['seed']}", "servicos.csv")
                    if os.path.exists(cam):
                        tempos += [int(r["tempo_provisionamento"]) for r in csv.DictReader(open(cam))
                                   if r["tempo_provisionamento"] not in ("", None)]
            if tempos:
                v = sorted(tempos)
                ax.step(v, [(i + 1) / len(v) for i in range(len(v))], where="post",
                        label=m, color=cores.get(m))
        ax.set_title(f"K = {k}")
        ax.set_xlabel("tempo de provisionamento (ticks)")
        ax.grid(alpha=.3)
    eixos[0][0].set_ylabel("CDF")
    eixos[0][0].legend()
    fig.tight_layout()
    fig.savefig(os.path.join(raiz, "cdf_provisionamento.png"), dpi=130)
    plt.close(fig)

    comp = comparar(linhas)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))
    larg = 0.8 / max(1, len(metodos))
    for j, m in enumerate(metodos):
        xs = [i + j * larg for i, k in enumerate(ks)]
        med = [next((r["tempo_medio"] for r in comp if r["metodo"] == m and r["k"] == k), 0) or 0 for k in ks]
        dp = [next((r["tempo_medio_dp"] for r in comp if r["metodo"] == m and r["k"] == k), 0) or 0 for k in ks]
        ax1.bar(xs, med, larg, yerr=dp, label=m, color=cores.get(m), capsize=3)
    ax1.set_xticks([i + 0.4 - larg / 2 for i in range(len(ks))])
    ax1.set_xticklabels([str(k) for k in ks])
    ax1.set_xlabel("K (registries)")
    ax1.set_ylabel("tempo medio de provisionamento (ticks)")
    ax1.legend()
    ax1.grid(axis="y", alpha=.3)

    tipos = [("link_ticks_sat_intra", "intra"), ("link_ticks_sat_inter", "inter"), ("link_ticks_sat_acesso", "acesso")]
    rotulos, fundo = [], None
    colunas = [(m, k) for k in ks for m in metodos]
    base = [0] * len(colunas)
    for campo, nome in tipos:
        vals = [next((r[campo] for r in comp if r["metodo"] == m and r["k"] == k), 0) or 0 for m, k in colunas]
        ax2.bar(range(len(colunas)), vals, bottom=base, label=nome)
        base = [b + v for b, v in zip(base, vals)]
    ax2.set_xticks(range(len(colunas)))
    ax2.set_xticklabels([f"{m[:4]}\nK={k}" for m, k in colunas], fontsize=8)
    ax2.set_ylabel("link-ticks saturados (media por execucao)")
    ax2.legend(title="tipo de link")
    ax2.grid(axis="y", alpha=.3)
    fig.tight_layout()
    fig.savefig(os.path.join(raiz, "tempo_e_saturacao.png"), dpi=130)
    plt.close(fig)


def lista(txt, tipo=str):
    return [tipo(x) for x in txt.split(",") if x.strip()]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--topologia", choices=["garr", "aleatoria"], default="garr")
    p.add_argument("--garr-arquivo")
    p.add_argument("--nos", type=int, default=70)
    p.add_argument("--links", type=int, default=112)
    p.add_argument("--banda-link", type=float, default=None, help="MB/s dos links sem banda propria (padrao 125)")
    p.add_argument("--ignorar-contagem", action="store_true")
    p.add_argument("--ks", default="1,2,4,8")
    p.add_argument("--metodos", default="fluidc,aleatorio",
                   help="fluidc, aleatorio e/ou topk_global (separados por virgula)")
    p.add_argument("--seeds", default="1,2,3,4,5")
    p.add_argument("--centralidade", default="eigenvector", choices=["eigenvector", "betweenness", "degree"])
    p.add_argument("--scheduler", default="random", choices=["random", "worstfit"])
    p.add_argument("--servicos", type=int, default=60)
    p.add_argument("--taxa", type=int, default=0, help="servicos por tick (0 = todos de uma vez)")
    p.add_argument("--max-ticks", type=int, default=3600)
    p.add_argument("--timeout", type=int, default=1800, help="segundos por execucao")
    p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--refazer", action="store_true")
    p.add_argument("--nome", help="pasta em resultados/ (padrao: <topologia>)")
    a = p.parse_args()

    if a.topologia == "garr" and not a.garr_arquivo:
        raise SystemExit("--topologia garr exige --garr-arquivo")
    ks, metodos, seeds = lista(a.ks, int), lista(a.metodos), lista(a.seeds, int)
    raiz = os.path.join("resultados", a.nome or a.topologia)
    os.makedirs(raiz, exist_ok=True)
    os.makedirs(os.path.join("cenarios", "gerados"), exist_ok=True)

    tarefas = [(k, m, s) for k in ks for m in metodos for s in seeds]
    print(f"{len(tarefas)} execucoes ({len(ks)} K x {len(metodos)} metodos x {len(seeds)} seeds)")
    linhas, falhas = [], []
    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        futuros = {ex.submit(uma_execucao, a, k, m, s, raiz): (k, m, s) for k, m, s in tarefas}
        for fut in futuros:
            k, m, s = futuros[fut]
            nome, r, erro = fut.result()
            if erro:
                falhas.append((nome, erro))
                print(f"  FALHOU {nome}: {erro}")
                continue
            linhas.append(linha_resumo(a, k, m, s, r))
            print(f"  {nome}: tempo medio {r['tempo_provisionamento']['media']} ticks, "
                  f"{r['nao_iniciados']} nao iniciados")

    linhas.sort(key=lambda l: (l["k"], l["metodo"], l["seed"]))
    escrever_csv(os.path.join(raiz, "resumo_experimento.csv"), linhas)
    comp = comparar(linhas)
    escrever_csv(os.path.join(raiz, "comparacao_por_k.csv"), comp)
    graficos(raiz, linhas, ks, metodos)

    print("\n--- COMPARACAO (media das seeds; razao > 1 = FluidC mais rapido) ---")
    print(f"{'K':>2} {'metodo':<12} {'tempo medio':>11} {'p90':>7} {'sat.intra':>9} {'sat.inter':>9} "
          f"{'sat.acesso':>10} {'razao':>6}")
    for r in comp:
        print(f"{r['k']:>2} {r['metodo']:<12} {r['tempo_medio']:>11} {r['tempo_p90']:>7} "
              f"{r['link_ticks_sat_intra']:>9} {r['link_ticks_sat_inter']:>9} "
              f"{r['link_ticks_sat_acesso']:>10} {str(r['razao_tempo_medio_vs_fluidc']):>6}")
    print(f"\nArquivos em {raiz}/")
    if falhas:
        print(f"{len(falhas)} execucoes falharam (veja as mensagens acima).")


if __name__ == "__main__":
    main()
