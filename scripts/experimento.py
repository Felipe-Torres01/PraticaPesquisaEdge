import json, subprocess, sys, csv, os
 
DATASET = "cenarios/dataset_registries.json"
AQUI = os.path.dirname(os.path.abspath(__file__))
 
 
def ids_dos_servidores(dataset):
    d = json.load(open(dataset))
    return [s["attributes"]["id"] for s in d["EdgeServer"]]
 
 
def rodar(server_id):
    out = subprocess.run(
        [sys.executable, os.path.join(AQUI, "run_cenario.py"), DATASET, str(server_id)],
        capture_output=True, text=True, timeout=600,
    )
    for linha in out.stdout.splitlines():
        if linha.startswith("RESULT"):
            _, sid, ticks, prov = linha.split()
            return int(ticks), int(prov)
    return None, None
 
 
def main():
    resultados = []
    for sid in ids_dos_servidores(DATASET):
        ticks, prov = rodar(sid)
        resultados.append((sid, ticks, prov))
        print(f"Registry no servidor {sid:>2}: {ticks} ticks ({prov} servicos provisionados)")
 
    with open(os.path.join(AQUI, "resultados.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["servidor_registry", "tempo_provisionamento_ticks", "servicos_provisionados"])
        w.writerows(resultados)
 
    validos = [(s, t) for s, t, p in resultados if t is not None]
    if validos:
        melhor = min(validos, key=lambda x: x[1])
        pior = max(validos, key=lambda x: x[1])
        print("\n--- RESUMO ---")
        print(f"Melhor posicao: servidor {melhor[0]} ({melhor[1]} ticks)")
        print(f"Pior posicao:   servidor {pior[0]} ({pior[1]} ticks)")
        if melhor[1] > 0:
            print(f"Diferenca: {pior[1]/melhor[1]:.1f}x mais lento na pior posicao")
 
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        servs = [str(s) for s, t, p in resultados]
        temps = [t for s, t, p in resultados]
        plt.figure(figsize=(10, 5))
        plt.bar(servs, temps, color="#4C72B0")
        plt.xlabel("Servidor que hospeda o Container Registry")
        plt.ylabel("Tempo de provisionamento (ticks)")
        plt.title("Impacto da posicao do Container Registry no tempo de provisionamento")
        plt.tight_layout()
        plt.savefig(os.path.join(AQUI, "grafico_provisionamento.png"), dpi=130)
        print("\nGrafico salvo em grafico_provisionamento.png")
    except Exception as e:
        print("grafico nao gerado:", e)
 
 
if __name__ == "__main__":
    main()
 
