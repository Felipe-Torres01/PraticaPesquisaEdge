"""Gera as figuras do artigo (artigo/figuras/*.pdf) a partir dos CSVs consolidados em resultados/.

Tamanho pensado para a largura de texto do template SBC (15 cm); fonte serifada para combinar com o
Times do texto. Rodar depois de analise_estrategias.py e analise_carga.py:
    python scripts/figuras_artigo.py
"""
import csv
import os
import random
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SAIDA = os.path.join("artigo", "figuras")
LARGURA = 5.9   # polegadas (15 cm)
CORES = {"fluidc": "#2a78d6", "aleatorio": "#eb6834"}
NOMES = {"fluidc": "Comunidades (FluidC)", "aleatorio": "Aleatório"}
TINTA_2, GRADE = "#52514e", "#e4e3dd"
ORDEM = ["GARR artigo (70 nós)", "GARR Zoo (61 nós)", "Erdős-Rényi (100 nós)", "Hexagonal (100 nós)"]

plt.rcParams.update({"font.family": "serif", "font.serif": ["Times New Roman", "DejaVu Serif"],
                     "font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8, "legend.fontsize": 7.5,
                     "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "axes.labelcolor": TINTA_2,
                     "pdf.fonttype": 42})


def ler(caminho):
    return list(csv.DictReader(open(caminho, encoding="utf-8")))


def estilo(ax):
    ax.spines[["top", "right"]].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color("#b5b4ad")
    ax.tick_params(colors=TINTA_2)
    ax.grid(axis="y", color=GRADE, linewidth=0.6)
    ax.set_axisbelow(True)


def fig_tempo_k():
    est = ler(os.path.join("resultados", "estrategias_ficticias", "estatisticas.csv"))
    fig, eixos = plt.subplots(2, 2, figsize=(LARGURA, 3.9))
    for ax, topo in zip(eixos.flat, ORDEM):
        ks = sorted({int(r["k"]) for r in est if r["topologia"] == topo})
        for j, metodo in enumerate(("fluidc", "aleatorio")):
            rs = sorted((r for r in est if r["topologia"] == topo and r["metodo"] == metodo), key=lambda r: int(r["k"]))
            x = [ks.index(int(r["k"])) + (j - 0.5) * 0.1 for r in rs]
            ax.errorbar(x, [float(r["media_s"]) for r in rs], yerr=[float(r["dp_s"]) for r in rs],
                        color=CORES[metodo], marker="o", markersize=4, linewidth=1.4, capsize=2.5,
                        elinewidth=0.9, markeredgecolor="white", markeredgewidth=0.8, label=NOMES[metodo])
        ax.set_xticks(range(len(ks)))
        ax.set_xticklabels([str(k) for k in ks])
        ax.set_ylim(bottom=0)
        ax.set_title(topo, loc="left")
        estilo(ax)
    for ax in eixos[1]:
        ax.set_xlabel("K (número de registries)")
    for ax in eixos[:, 0]:
        ax.set_ylabel("tempo médio (s)")
    eixos[0][0].legend(frameon=False)
    fig.tight_layout(h_pad=1.0)
    fig.savefig(os.path.join(SAIDA, "tempo_por_k.pdf"))
    plt.close(fig)


def fig_ganho_seed():
    pts = ler(os.path.join("resultados", "estrategias_ficticias", "ganho_por_seed.csv"))
    fig, eixos = plt.subplots(1, 4, figsize=(LARGURA, 1.9), sharey=True)
    for ax, topo in zip(eixos, ORDEM):
        ks = sorted({int(r["k"]) for r in pts if r["topologia"] == topo})
        for i, k in enumerate(ks):
            g = [float(r["ganho_pct"]) for r in pts if r["topologia"] == topo and int(r["k"]) == k]
            rng = random.Random(k)
            ax.scatter([i + rng.uniform(-0.18, 0.18) for _ in g], g, s=7, color=CORES["fluidc"],
                       alpha=0.6, linewidths=0, zorder=3)
            ax.plot([i - 0.25, i + 0.25], [statistics.median(g)] * 2, color="#0b0b0b", linewidth=1.2, zorder=4)
        ax.axhline(0, color="#8a8983", linewidth=0.7)
        ax.set_xticks(range(len(ks)))
        ax.set_xticklabels([str(k) for k in ks])
        ax.set_xlabel("K")
        ax.set_title(topo.replace(" (", "\n("), loc="left", fontsize=7.5)
        estilo(ax)
    eixos[0].set_ylabel("ganho do FluidC (%)")
    eixos[0].set_yticks(range(-40, 101, 20))
    fig.tight_layout(w_pad=0.6)
    fig.savefig(os.path.join(SAIDA, "ganho_por_seed.pdf"))
    plt.close(fig)


def fig_carga():
    res = ler(os.path.join("resultados", "carga_garr70", "carga_resumo.csv"))
    ks = sorted({int(r["k"]) for r in res})
    taxas = sorted({float(r["taxa_req_s"]) for r in res})
    fig, eixos = plt.subplots(1, len(ks), figsize=(LARGURA, 2.1), sharey=True)
    for ax, k in zip(eixos, ks):
        for metodo in ("fluidc", "aleatorio"):
            rs = sorted((r for r in res if int(r["k"]) == k and r["metodo"] == metodo),
                        key=lambda r: float(r["taxa_req_s"]))
            ax.errorbar([float(r["taxa_req_s"]) for r in rs], [float(r["pct_nao_iniciadas"]) for r in rs],
                        yerr=[float(r["pct_nao_iniciadas_dp"]) for r in rs], color=CORES[metodo], marker="o",
                        markersize=3.5, linewidth=1.3, capsize=2, elinewidth=0.8, label=NOMES[metodo])
        ax.set_xticks(taxas)
        ax.set_xticklabels([f"{t:.0f}" for t in taxas])
        ax.set_ylim(0, 100)
        ax.set_title(f"K = {k}", loc="left")
        ax.set_xlabel("requisições/s")
        estilo(ax)
    eixos[0].set_ylabel("não iniciadas (%)")
    alcas, rotulos = eixos[0].get_legend_handles_labels()
    fig.legend(alcas, rotulos, frameon=False, loc="upper center", ncol=2)
    fig.tight_layout(w_pad=0.6, rect=(0, 0, 1, 0.88))
    fig.savefig(os.path.join(SAIDA, "carga.pdf"))
    plt.close(fig)


def main():
    os.makedirs(SAIDA, exist_ok=True)
    fig_tempo_k()
    fig_ganho_seed()
    fig_carga()
    print("figuras em", SAIDA, ":", sorted(os.listdir(SAIDA)))


if __name__ == "__main__":
    main()
