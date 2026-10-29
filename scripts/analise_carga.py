"""Analisa a varredura de taxa de chegada (modo carga de trabalho): FluidC x aleatorio por taxa e por K.

Le as pastas do experimento.py rodado com --chegadas (uma pasta por taxa) e gera:
    carga_resumo.csv        por (taxa, K, metodo): media e desvio-padrao das seeds de
                            % nao iniciadas no prazo, tempo medio ate rodar, taxa de acerto do cache
    carga_por_taxa.png      linha de cima: % nao iniciadas x taxa; linha de baixo: tempo medio x taxa
                            (uma coluna por K, media +- desvio-padrao das seeds)

Exemplo:
    python scripts/analise_carga.py resultados/carga_garr70_l5 resultados/carga_garr70_l10 \\
        resultados/carga_garr70_l20 --saida resultados/carga_garr70
"""
import argparse
import csv
import os
import statistics

CORES = {"fluidc": "#2a78d6", "aleatorio": "#eb6834"}
NOMES = {"fluidc": "Comunidades (FluidC)", "aleatorio": "Aleatória"}
TINTA, TINTA_2, GRADE, FUNDO = "#0b0b0b", "#52514e", "#e4e3dd", "#fcfcfb"
CAMPOS = [("pct_nao_iniciadas", "não iniciadas no prazo (%)"),
          ("tempo_medio_s", "tempo médio até rodar (s)"),
          ("taxa_acerto_cache", None)]


def ler(pastas):
    linhas = []
    for pasta in pastas:
        for l in csv.DictReader(open(os.path.join(pasta, "resumo_experimento.csv"))):
            linhas.append({"taxa": float(l["taxa_req_s"]), "k": int(l["k"]), "metodo": l["metodo"],
                           "seed": int(l["seed"]), **{c: float(l[c]) for c, _ in CAMPOS if l.get(c) not in ("", None)}})
    return linhas


def resumir(linhas):
    grupos = {}
    for l in linhas:
        grupos.setdefault((l["taxa"], l["k"], l["metodo"]), []).append(l)
    saida = []
    for (taxa, k, metodo), ls in sorted(grupos.items()):
        row = {"taxa_req_s": taxa, "k": k, "metodo": metodo, "seeds": len(ls)}
        for c, _ in CAMPOS:
            v = [l[c] for l in ls if c in l]
            row[c] = round(statistics.mean(v), 4) if v else None
            row[c + "_dp"] = round(statistics.stdev(v), 4) if len(v) > 1 else 0.0
        saida.append(row)
    return saida


def pareado(linhas):
    """Por (taxa, K): diferenca aleatorio - FluidC em pontos percentuais de nao iniciadas, seed a seed.
    Nao usa razao (o aleatorio zera em varias seeds). p = permutacao pareada exata (analise_estrategias)."""
    from analise_estrategias import permutacao_pareada
    idx = {(l["taxa"], l["k"], l["metodo"], l["seed"]): l.get("pct_nao_iniciadas") for l in linhas}
    saida = []
    for taxa, k in sorted({(l["taxa"], l["k"]) for l in linhas}):
        seeds = sorted({l["seed"] for l in linhas if l["taxa"] == taxa and l["k"] == k})
        dif = [idx[(taxa, k, "aleatorio", s)] - idx[(taxa, k, "fluidc", s)] for s in seeds
               if idx.get((taxa, k, "aleatorio", s)) is not None and idx.get((taxa, k, "fluidc", s)) is not None]
        saida.append({"taxa_req_s": taxa, "k": k, "pares": len(dif),
                      "diferenca_media_pp": round(statistics.mean(dif), 3),
                      "diferenca_dp_pp": round(statistics.stdev(dif), 3) if len(dif) > 1 else 0.0,
                      "fluidc_venceu": sum(1 for d in dif if d > 1e-9),
                      "empate": sum(1 for d in dif if abs(d) <= 1e-9),
                      "fluidc_perdeu": sum(1 for d in dif if d < -1e-9),
                      "p_valor_permutacao": round(permutacao_pareada(dif), 6)})
    return saida


def grafico(resumo, caminho):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 9.5, "axes.labelcolor": TINTA_2, "axes.titlecolor": TINTA,
                         "figure.facecolor": FUNDO, "axes.facecolor": FUNDO, "savefig.facecolor": FUNDO})
    ks = sorted({r["k"] for r in resumo})
    taxas = sorted({r["taxa_req_s"] for r in resumo})
    fig, eixos = plt.subplots(2, len(ks), figsize=(3.6 * len(ks), 6.2), squeeze=False, sharey="row")
    for col, k in enumerate(ks):
        for lin, (campo, rotulo) in enumerate(CAMPOS[:2]):
            ax = eixos[lin][col]
            for metodo in ("fluidc", "aleatorio"):
                rs = [r for r in resumo if r["k"] == k and r["metodo"] == metodo]
                ax.errorbar([r["taxa_req_s"] for r in rs], [r[campo] for r in rs],
                            yerr=[r[campo + "_dp"] for r in rs], color=CORES[metodo], marker="o",
                            markersize=6, markeredgecolor=FUNDO, linewidth=2, capsize=3, label=NOMES[metodo])
            ax.set_xticks(taxas)
            ax.set_ylim(bottom=0)
            ax.grid(axis="y", color=GRADE)
            ax.set_axisbelow(True)
            ax.spines[["top", "right"]].set_visible(False)
            if lin == 0:
                ax.set_title(f"K = {k}", loc="left")
            else:
                ax.set_xlabel("chegadas (requisições/s)")
            if col == 0:
                ax.set_ylabel(rotulo)
    eixos[0][0].legend(frameon=False, fontsize=8.5)
    fig.text(0.01, 0.01, "Média ± 1 desvio-padrão das seeds. GARR do artigo (70 nós), top 50 imagens do Docker Hub, "
             "deadline 25 s, cache LRU de 600 MB por servidor.", fontsize=8, color=TINTA_2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(caminho, dpi=150)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pastas", nargs="+")
    p.add_argument("--saida", default=os.path.join("resultados", "carga"))
    a = p.parse_args()
    os.makedirs(a.saida, exist_ok=True)
    linhas = ler(a.pastas)
    resumo = resumir(linhas)
    pares = pareado(linhas)
    for nome, dados in (("carga_resumo.csv", resumo), ("carga_pareado.csv", pares)):
        with open(os.path.join(a.saida, nome), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(dados[0].keys()))
            w.writeheader()
            w.writerows(dados)
    grafico(resumo, os.path.join(a.saida, "carga_por_taxa.png"))
    print(f"{'taxa':>5} {'K':>2} {'metodo':<10} {'nao inic. %':>14} {'tempo (s)':>14} {'acerto cache':>12}")
    for r in resumo:
        print(f"{r['taxa_req_s']:>5.0f} {r['k']:>2} {r['metodo']:<10} {r['pct_nao_iniciadas']:>7.2f} ± {r['pct_nao_iniciadas_dp']:<5.2f}"
              f"{r['tempo_medio_s']:>7.2f} ± {r['tempo_medio_s_dp']:<5.2f} {r['taxa_acerto_cache']:>10.3f}")
    print("\nPareado (aleatorio - FluidC, em pontos percentuais de nao iniciadas; V/E/D = FluidC venceu/empatou/perdeu)")
    for r in pares:
        print(f"{r['taxa_req_s']:>5.0f} {r['k']:>2}  {r['diferenca_media_pp']:>7.2f} ± {r['diferenca_dp_pp']:<6.2f} "
              f"{r['fluidc_venceu']}/{r['empate']}/{r['fluidc_perdeu']:<3}  p = {r['p_valor_permutacao']:.4f}")
    print(f"\nArquivos em {a.saida}/")


if __name__ == "__main__":
    main()
