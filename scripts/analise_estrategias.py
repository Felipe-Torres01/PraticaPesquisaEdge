"""Consolida os experimentos de estrategias (FluidC x aleatorio) e gera graficos com media e desvio-padrao.

Le o resumo_experimento.csv de cada pasta gerada pelo experimento.py e compara os metodos POR SEED
(mesma seed = mesmo grafo, mesmos servicos e mesmas imagens; so muda a posicao dos registries).

Exemplo (a partir da raiz do repositorio):
    python scripts/analise_estrategias.py resultados/garr resultados/erdos_renyi --saida resultados/estrategias

Saidas em --saida:
    estatisticas.csv         por (topologia, K, metodo): n, media, desvio-padrao, IC95%, mediana, min, max
    ganho_pareado.csv        por (topologia, K): ganho do FluidC sobre o aleatorio (media e desvio das seeds),
                             seeds em que o FluidC venceu e p-valor do teste de permutacao pareado
    ganho_por_seed.csv       ganho de cada seed
    tempo_medio_por_k.png    tempo medio de provisionamento (s) x K, media +- desvio-padrao das seeds
    ganho_por_seed.png       ganho percentual do FluidC em cada seed, por K

Metrica: tempo medio de provisionamento dos servicos (s) = coluna tempo_medio_s (ou tempo_medio em
ticks, se o experimento for anterior a coluna em segundos).
"""
import argparse
import csv
import itertools
import math
import os
import random
import statistics

# t de Student bicaudal 95% por graus de liberdade (evita depender do scipy)
T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262,
       10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110,
       18: 2.101, 19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
       26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042}

# paleta categorica de referencia (slots 1 e 2), validada para daltonismo
CORES = {"fluidc": "#2a78d6", "aleatorio": "#eb6834"}
NOMES = {"fluidc": "Comunidades (FluidC)", "aleatorio": "Aleatória"}
TITULOS = {"garr": "GARR (Topology Zoo, 61 nós)", "erdos_renyi": "Erdős-Rényi G(100, 0.049)",
           "aleatoria": "Aleatória G(n, m)"}
TINTA, TINTA_2, GRADE, FUNDO = "#0b0b0b", "#52514e", "#e4e3dd", "#fcfcfb"


def ler(pasta):
    linhas = list(csv.DictReader(open(os.path.join(pasta, "resumo_experimento.csv"))))
    for l in linhas:
        l["k"] = int(l["k"])
        l["seed"] = int(l["seed"])
        v = l.get("tempo_medio_s") or l["tempo_medio"]
        l["tempo"] = float(v) if v not in ("", None) else None
    return linhas


def ic95(v):
    if len(v) < 2:
        return 0.0
    return T95.get(len(v) - 1, 1.96) * statistics.stdev(v) / math.sqrt(len(v))


def permutacao_pareada(dif, amostras=200000, semente=1):
    """p-valor bicaudal do teste de permutacao com troca de sinais (H0: diferenca media = 0).
    Exato (todas as 2^n trocas) ate n = 22; acima disso, Monte Carlo."""
    n = len(dif)
    if n == 0:
        return None
    obs = abs(sum(dif))
    try:
        import numpy as np
        d = np.asarray(dif, dtype=float)
        if n <= 22:
            sinais = ((np.arange(2 ** n)[:, None] >> np.arange(n)) & 1) * 2 - 1
        else:
            sinais = np.random.default_rng(semente).choice([-1, 1], size=(amostras, n))
        return float(np.mean(np.abs(sinais @ d) >= obs - 1e-9))
    except ImportError:
        rng = random.Random(semente)
        conta = sum(1 for _ in range(amostras)
                    if abs(sum(x if rng.random() < .5 else -x for x in dif)) >= obs - 1e-9)
        return conta / amostras


def estatisticas(linhas):
    grupos = {}
    for l in linhas:
        if l["tempo"] is not None:
            grupos.setdefault((l["topologia"], l["k"], l["metodo"]), []).append(l["tempo"])
    saida = []
    for (topo, k, metodo), v in sorted(grupos.items()):
        saida.append({
            "topologia": topo, "k": k, "metodo": metodo, "n": len(v),
            "media_s": round(statistics.mean(v), 3),
            "dp_s": round(statistics.stdev(v), 3) if len(v) > 1 else 0.0,
            "ic95_s": round(ic95(v), 3), "mediana_s": round(statistics.median(v), 3),
            "min_s": round(min(v), 3), "max_s": round(max(v), 3)})
    return saida


def ganhos(linhas):
    """Ganho por seed = 1 - tempo_fluidc / tempo_aleatorio (positivo = FluidC mais rapido)."""
    idx = {(l["topologia"], l["k"], l["metodo"], l["seed"]): l["tempo"] for l in linhas}
    resumo, por_seed = [], []
    for topo, k in sorted({(l["topologia"], l["k"]) for l in linhas}):
        seeds = sorted({l["seed"] for l in linhas if l["topologia"] == topo and l["k"] == k})
        pares = [(s, idx.get((topo, k, "fluidc", s)), idx.get((topo, k, "aleatorio", s))) for s in seeds]
        pares = [(s, f, a) for s, f, a in pares if f is not None and a]
        if not pares:
            continue
        g = [100 * (1 - f / a) for _, f, a in pares]
        por_seed += [{"topologia": topo, "k": k, "seed": s, "ganho_pct": round(x, 2)}
                     for (s, _, _), x in zip(pares, g)]
        resumo.append({
            "topologia": topo, "k": k, "pares": len(pares),
            "ganho_medio_pct": round(statistics.mean(g), 2),
            "ganho_dp_pct": round(statistics.stdev(g), 2) if len(g) > 1 else 0.0,
            "ganho_mediano_pct": round(statistics.median(g), 2),
            "razao_das_medias": round(statistics.mean(a for _, _, a in pares) /
                                      statistics.mean(f for _, f, _ in pares), 3),
            "seeds_fluidc_venceu": sum(1 for _, f, a in pares if f < a),
            "p_valor_permutacao": round(permutacao_pareada([a - f for _, f, a in pares]), 6),
        })
    return resumo, por_seed


def escrever_csv(caminho, linhas):
    if not linhas:
        return
    with open(caminho, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        w.writeheader()
        w.writerows(linhas)


def estilo(ax):
    ax.spines[["top", "right"]].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color("#b5b4ad")
    ax.tick_params(colors=TINTA_2, labelsize=9)
    ax.grid(axis="y", color=GRADE, linewidth=0.8)
    ax.set_axisbelow(True)


def graficos(saida, est, por_seed, topologias):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 10, "axes.titlesize": 11, "axes.labelcolor": TINTA_2,
                         "axes.titlecolor": TINTA, "figure.facecolor": FUNDO,
                         "axes.facecolor": FUNDO, "savefig.facecolor": FUNDO})

    # 1) tempo medio x K, media +- desvio-padrao (uma faceta por topologia, cada uma com seu eixo y)
    fig, eixos = plt.subplots(1, len(topologias), figsize=(5.4 * len(topologias), 4.0), squeeze=False)
    for ax, topo in zip(eixos[0], topologias):
        ks = sorted({r["k"] for r in est if r["topologia"] == topo})
        pos = {k: i for i, k in enumerate(ks)}
        for j, metodo in enumerate(("fluidc", "aleatorio")):
            rs = [r for r in est if r["topologia"] == topo and r["metodo"] == metodo]
            if not rs:
                continue
            x = [pos[r["k"]] + (j - 0.5) * 0.12 for r in rs]
            y = [r["media_s"] for r in rs]
            ax.errorbar(x, y, yerr=[r["dp_s"] for r in rs], color=CORES[metodo], linewidth=2,
                        marker="o", markersize=7, markeredgecolor=FUNDO, markeredgewidth=1.5,
                        capsize=4, elinewidth=1.2, label=NOMES[metodo])
            for xi, yi in zip(x, y):
                # FluidC abaixo-a-esquerda e aleatorio a direita: as linhas descem da esquerda
                ax.annotate(f"{yi:.1f}", (xi, yi), textcoords="offset points",
                            xytext=(-7, -10) if j == 0 else (9, 0), ha="right" if j == 0 else "left",
                            va="center", fontsize=8, color=TINTA_2)
        ax.set_xticks(range(len(ks)))
        ax.set_xticklabels([str(k) for k in ks])
        ax.set_xlim(-0.5, len(ks) - 0.5)
        ax.set_ylim(bottom=0)
        ax.set_xlabel("K (número de registries)")
        ax.set_title(TITULOS.get(topo, topo), loc="left")
        estilo(ax)
    eixos[0][0].set_ylabel("tempo médio de provisionamento (s)")
    eixos[0][0].legend(frameon=False, fontsize=9)
    n = max((r["n"] for r in est), default=0)
    fig.text(0.01, 0.01, f"Pontos: média de {n} seeds (valor ao lado); barras: ±1 desvio-padrão.",
             fontsize=8, color=TINTA_2)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(os.path.join(saida, "tempo_medio_por_k.png"), dpi=150)
    plt.close(fig)

    # 2) ganho de cada seed (pontos) e media +- dp, por K
    fig, eixos = plt.subplots(1, len(topologias), figsize=(5.4 * len(topologias), 3.8),
                              squeeze=False, sharey=True)
    for ax, topo in zip(eixos[0], topologias):
        ks = sorted({r["k"] for r in por_seed if r["topologia"] == topo})
        for i, k in enumerate(ks):
            g = [r["ganho_pct"] for r in por_seed if r["topologia"] == topo and r["k"] == k]
            jit = random.Random(k)
            ax.scatter([i + jit.uniform(-0.15, 0.15) for _ in g], g, s=24, color=CORES["fluidc"],
                       alpha=0.6, edgecolors=FUNDO, linewidths=0.8, zorder=3)
            m = statistics.mean(g)
            dp = statistics.stdev(g) if len(g) > 1 else 0
            ax.errorbar([i + 0.3], [m], yerr=[dp], color=TINTA, marker="D", markersize=6,
                        capsize=4, linewidth=1.2, zorder=4)
            ax.annotate(f"{m:.0f}%", (i + 0.3, m), textcoords="offset points", xytext=(7, 0),
                        va="center", fontsize=8.5, color=TINTA_2)
        ax.axhline(0, color="#8a8983", linewidth=1)
        ax.set_xticks(range(len(ks)))
        ax.set_xticklabels([str(k) for k in ks])
        ax.set_xlim(-0.5, len(ks) - 0.2)
        ax.set_xlabel("K (número de registries)")
        ax.set_title(TITULOS.get(topo, topo), loc="left")
        estilo(ax)
    eixos[0][0].set_ylabel("ganho do FluidC sobre o aleatório (%)")
    fig.text(0.01, 0.01, "Cada ponto é uma seed (mesmo grafo e serviços nos dois métodos).\n"
             "Losango = média ± 1 desvio-padrão. Acima de 0 = FluidC mais rápido.",
             fontsize=8, color=TINTA_2)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(os.path.join(saida, "ganho_por_seed.png"), dpi=150)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pastas", nargs="+", help="pastas de resultados do experimento.py")
    p.add_argument("--saida", default=os.path.join("resultados", "estrategias"))
    a = p.parse_args()

    linhas = list(itertools.chain.from_iterable(ler(x) for x in a.pastas))
    topologias = list(dict.fromkeys(l["topologia"] for l in linhas))
    os.makedirs(a.saida, exist_ok=True)
    est = estatisticas(linhas)
    resumo, por_seed = ganhos(linhas)
    escrever_csv(os.path.join(a.saida, "estatisticas.csv"), est)
    escrever_csv(os.path.join(a.saida, "ganho_pareado.csv"), resumo)
    escrever_csv(os.path.join(a.saida, "ganho_por_seed.csv"), por_seed)
    graficos(a.saida, est, por_seed, topologias)

    print(f"{'topologia':<12} {'K':>2} {'FluidC (s)':>15} {'Aleatorio (s)':>15} {'ganho %':>13} "
          f"{'venceu':>7} {'p':>8}")
    for g in resumo:
        chave = (g["topologia"], g["k"])
        f = next(r for r in est if (r["topologia"], r["k"], r["metodo"]) == chave + ("fluidc",))
        r = next(r for r in est if (r["topologia"], r["k"], r["metodo"]) == chave + ("aleatorio",))
        print(f"{g['topologia']:<12} {g['k']:>2} {f['media_s']:>7.2f} ± {f['dp_s']:<5.2f} "
              f"{r['media_s']:>7.2f} ± {r['dp_s']:<5.2f} {g['ganho_medio_pct']:>6.1f} ± {g['ganho_dp_pct']:<5.1f}"
              f"{g['seeds_fluidc_venceu']:>3}/{g['pares']:<3} {g['p_valor_permutacao']:>8.4f}")
    print(f"\nArquivos em {a.saida}/")


if __name__ == "__main__":
    main()
