"""Compara o experimento fiel com a Tabela 4.3 da tese do Knob (PUCRS, 2022, p. 79).

O experimento fiel reproduz o cenario da tese (sec. 4.5): 13 imagens de 200 MB, cache LRU de 600 MB,
~5 requisicoes/s, deadline de 25 s, nos sem limite de capacidade, container vivo ate o deadline, topologia
aleatoria com 100 nos e 242 enlaces de 1 Gbps e GARR limitada a 10% da banda. Rodar antes:
    experimento.py ... --nome fiel_aleatoria_random / fiel_garr10_random / fiel_garr10_pess

Saidas em --saida (padrao resultados/comparacao_knob):
    comparacao_knob.csv     por cenario, K e metodo: nosso valor (media +- dp das seeds) e o da tese
    pareado_knob.csv        diferenca aleatorio - FluidC seed a seed (V/E/D e p da permutacao pareada)
    comparacao_knob.png     % nao iniciadas e tempo medio x K, nossos (linhas) e da tese (marcadores)
    (o mesmo grafico em artigo/figuras/comparacao_knob.pdf)
"""
import argparse
import csv
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analise_estrategias import permutacao_pareada

# Tabela 4.3 da tese: (cenario, metodo, K) -> (% nao iniciados, tempo medio de deployment em s).
# Na GARR, com 1 registry a tese reporta o mesmo valor para os dois metodos.
KNOB = {
    ("aleatoria_random", "aleatorio", 1): (19.37, 21.43), ("aleatoria_random", "aleatorio", 2): (1.11, 5.14),
    ("aleatoria_random", "aleatorio", 4): (0.00, 2.09), ("aleatoria_random", "aleatorio", 8): (0.00, 1.53),
    ("aleatoria_random", "fluidc", 1): (13.26, 13.46), ("aleatoria_random", "fluidc", 2): (0.12, 3.31),
    ("aleatoria_random", "fluidc", 4): (0.00, 1.81), ("aleatoria_random", "fluidc", 8): (0.00, 1.34),
    ("garr10_random", "aleatorio", 1): (47.86, 273.62), ("garr10_random", "aleatorio", 2): (44.64, 207.80),
    ("garr10_random", "aleatorio", 4): (38.09, 106.72), ("garr10_random", "aleatorio", 8): (33.42, 75.65),
    ("garr10_random", "fluidc", 1): (47.86, 273.62), ("garr10_random", "fluidc", 2): (44.35, 132.72),
    ("garr10_random", "fluidc", 4): (31.34, 45.42), ("garr10_random", "fluidc", 8): (7.93, 15.89),
    ("garr10_pess", "aleatorio", 1): (40.52, 75.15), ("garr10_pess", "aleatorio", 2): (35.23, 64.93),
    ("garr10_pess", "aleatorio", 4): (24.29, 46.06), ("garr10_pess", "aleatorio", 8): (17.61, 38.25),
    ("garr10_pess", "fluidc", 1): (40.52, 75.15), ("garr10_pess", "fluidc", 2): (24.95, 49.91),
    ("garr10_pess", "fluidc", 4): (3.18, 16.34), ("garr10_pess", "fluidc", 8): (0.87, 7.76),
}
CENARIOS = [("aleatoria_random", "Aleatória, escalonador aleatório"),
            ("garr10_random", "GARR, escalonador aleatório"),
            ("garr10_pess", "GARR, escalonador PESS")]
CORES = {"fluidc": "#2a78d6", "aleatorio": "#eb6834"}
NOMES = {"fluidc": "FluidC", "aleatorio": "Aleatório"}


def ler(raiz, cenario):
    caminho = os.path.join(raiz, f"fiel_{cenario}", "resumo_experimento.csv")
    if not os.path.exists(caminho):
        return []
    return [{"metodo": l["metodo"], "k": int(l["k"]), "seed": int(l["seed"]),
             "nao": float(l["pct_nao_iniciadas"]), "tempo": float(l["tempo_medio_s"])}
            for l in csv.DictReader(open(caminho))]


def resumir(dados):
    linhas, pares = [], []
    for cen, _ in CENARIOS:
        ls = dados.get(cen, [])
        for k in (1, 2, 4, 8):
            for m in ("fluidc", "aleatorio"):
                v = [l for l in ls if l["k"] == k and l["metodo"] == m]
                if not v:
                    continue
                kn = KNOB[(cen, m, k)]

                def md(c):
                    xs = [l[c] for l in v]
                    return statistics.mean(xs), (statistics.stdev(xs) if len(xs) > 1 else 0.0)
                (nao, nao_dp), (t, t_dp) = md("nao"), md("tempo")
                linhas.append({"cenario": cen, "k": k, "metodo": m, "seeds": len(v),
                               "nao_iniciadas_pct": round(nao, 2), "nao_iniciadas_dp": round(nao_dp, 2),
                               "knob_nao_iniciadas_pct": kn[0],
                               "tempo_medio_s": round(t, 2), "tempo_medio_dp": round(t_dp, 2),
                               "knob_tempo_medio_s": kn[1]})
            idx = {(l["metodo"], l["seed"]): l for l in ls if l["k"] == k}
            seeds = sorted({s for (_, s) in idx})
            dif = [idx[("aleatorio", s)]["nao"] - idx[("fluidc", s)]["nao"] for s in seeds
                   if ("aleatorio", s) in idx and ("fluidc", s) in idx]
            dift = [idx[("aleatorio", s)]["tempo"] - idx[("fluidc", s)]["tempo"] for s in seeds
                    if ("aleatorio", s) in idx and ("fluidc", s) in idx]
            if dif:
                pares.append({"cenario": cen, "k": k, "pares": len(dif),
                              "dif_nao_iniciadas_pp": round(statistics.mean(dif), 2),
                              "fluidc_venceu": sum(1 for d in dif if d > 1e-9),
                              "empate": sum(1 for d in dif if abs(d) <= 1e-9),
                              "fluidc_perdeu": sum(1 for d in dif if d < -1e-9),
                              "p_nao_iniciadas": round(permutacao_pareada(dif), 6),
                              "dif_tempo_s": round(statistics.mean(dift), 2),
                              "p_tempo": round(permutacao_pareada(dift), 6)})
    return linhas, pares


def grafico(linhas, caminhos):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "serif", "font.serif": ["Times New Roman", "DejaVu Serif"],
                         "font.size": 8, "axes.titlesize": 8.5, "legend.fontsize": 7.5, "pdf.fonttype": 42,
                         "axes.labelcolor": "#52514e"})
    fig, eixos = plt.subplots(2, 3, figsize=(5.9, 3.9), sharex=True)
    ks = [1, 2, 4, 8]
    for col, (cen, titulo) in enumerate(CENARIOS):
        for lin, (campo, campo_dp, campo_kn, rotulo) in enumerate([
                ("nao_iniciadas_pct", "nao_iniciadas_dp", "knob_nao_iniciadas_pct", "não iniciadas (%)"),
                ("tempo_medio_s", "tempo_medio_dp", "knob_tempo_medio_s", "tempo médio (s)")]):
            ax = eixos[lin][col]
            for j, m in enumerate(("fluidc", "aleatorio")):
                rs = sorted((r for r in linhas if r["cenario"] == cen and r["metodo"] == m), key=lambda r: r["k"])
                if not rs:
                    continue
                x = [ks.index(r["k"]) + (j - 0.5) * 0.12 for r in rs]
                ax.errorbar(x, [r[campo] for r in rs], yerr=[r[campo_dp] for r in rs], color=CORES[m],
                            marker="o", markersize=3.5, linewidth=1.3, capsize=2, elinewidth=0.8,
                            label=f"{NOMES[m]} (nosso)")
                ax.plot(x, [r[campo_kn] for r in rs], linestyle="none", marker="x", markersize=5,
                        markeredgewidth=1.3, color=CORES[m], label=f"{NOMES[m]} (Knob)")
            ax.set_xticks(range(len(ks)))
            ax.set_xticklabels([str(k) for k in ks])
            ax.set_ylim(bottom=0)
            ax.spines[["top", "right"]].set_visible(False)
            ax.grid(axis="y", color="#e4e3dd", linewidth=0.6)
            ax.set_axisbelow(True)
            if lin == 0:
                ax.set_title(titulo, loc="left")
            else:
                ax.set_xlabel("K (registries)")
            if col == 0:
                ax.set_ylabel(rotulo)
    h, l = eixos[0][0].get_legend_handles_labels()
    fig.legend(h, l, frameon=False, loc="upper center", ncol=4)
    fig.tight_layout(rect=(0, 0, 1, 0.92), h_pad=0.8)
    for c in caminhos:
        fig.savefig(c, dpi=150)
    plt.close(fig)


def escrever(caminho, linhas):
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        w.writeheader()
        w.writerows(linhas)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--resultados", default="resultados")
    p.add_argument("--saida", default=os.path.join("resultados", "comparacao_knob"))
    a = p.parse_args()
    dados = {cen: ler(a.resultados, cen) for cen, _ in CENARIOS}
    linhas, pares = resumir(dados)
    os.makedirs(a.saida, exist_ok=True)
    escrever(os.path.join(a.saida, "comparacao_knob.csv"), linhas)
    if pares:
        escrever(os.path.join(a.saida, "pareado_knob.csv"), pares)
    os.makedirs(os.path.join("artigo", "figuras"), exist_ok=True)
    grafico(linhas, [os.path.join(a.saida, "comparacao_knob.png"),
                     os.path.join("artigo", "figuras", "comparacao_knob.pdf")])
    print(f"{'cenario':<17} {'K':>2} {'metodo':<10} {'nao inic. % (nosso | Knob)':>28} {'tempo s (nosso | Knob)':>28}")
    for r in linhas:
        print(f"{r['cenario']:<17} {r['k']:>2} {r['metodo']:<10} "
              f"{r['nao_iniciadas_pct']:>7.2f} ± {r['nao_iniciadas_dp']:<6.2f} | {r['knob_nao_iniciadas_pct']:>6.2f}   "
              f"{r['tempo_medio_s']:>8.2f} ± {r['tempo_medio_dp']:<7.2f} | {r['knob_tempo_medio_s']:>6.2f}")
    print("\npareado (aleatorio - FluidC): cenario K | dif. nao iniciadas pp (V/E/D, p) | dif. tempo s (p)")
    for r in pares:
        print(f"  {r['cenario']:<17} {r['k']} | {r['dif_nao_iniciadas_pp']:7.2f} pp "
              f"({r['fluidc_venceu']}/{r['empate']}/{r['fluidc_perdeu']}, p={r['p_nao_iniciadas']:.4f}) | "
              f"{r['dif_tempo_s']:8.2f} s (p={r['p_tempo']:.4f})")
    print(f"\nArquivos em {a.saida}/ e artigo/figuras/comparacao_knob.pdf")


if __name__ == "__main__":
    main()
