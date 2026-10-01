"""
Reproducao (EdgeSimPy) — mede o tempo de provisionamento dos servicos
com o Container Registry posicionado em um servidor especifico.

Uso:  python3 run_cenario.py <caminho_dataset> <id_do_servidor_do_registry>
Saida (stdout, ultima linha):  RESULT <server_id> <ticks> <servicos_providos>
"""
import sys, json, tempfile, os
import edge_sim_py as es


def mover_registry(dataset_path, target_server_id):
    """Le o dataset e reescreve movendo o registry (e suas imagens/camadas)
    para o servidor alvo. Retorna o caminho de um arquivo temporario."""
    d = json.load(open(dataset_path))

    # servidor onde o registry esta hoje
    reg = d["ContainerRegistry"][0]
    origem_id = reg["relationships"]["server"]["id"]
    if origem_id == target_server_id:
        return dataset_path  # nada a mover

    # move o registry
    reg["relationships"]["server"]["id"] = target_server_id

    # move as imagens e camadas que estao no servidor de origem
    for img in d.get("ContainerImage", []):
        s = img["relationships"].get("server")
        if s and s["id"] == origem_id:
            s["id"] = target_server_id
    for lay in d.get("ContainerLayer", []):
        s = lay["relationships"].get("server")
        if s and s["id"] == origem_id:
            s["id"] = target_server_id

    # atualiza as listas dos EdgeServers (origem perde, alvo ganha)
    for srv in d["EdgeServer"]:
        sid = srv["attributes"]["id"]
        rel = srv["relationships"]
        if sid == origem_id:
            rel["container_registries"] = []
            rel["container_images"] = []
            rel["container_layers"] = []
        if sid == target_server_id:
            rel["container_registries"] = [{"class": "ContainerRegistry", "id": reg["attributes"]["id"]}]
            rel["container_images"] = [{"class": "ContainerImage", "id": i["attributes"]["id"]}
                                       for i in d.get("ContainerImage", [])]
            rel["container_layers"] = [{"class": "ContainerLayer", "id": l["attributes"]["id"]}
                                       for l in d.get("ContainerLayer", [])]

    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(d, tmp)
    tmp.close()
    return tmp.name


def placement_worst_fit(parameters):
    """Coloca cada servico no servidor com mais recursos livres que couber."""
    for service in es.Service.all():
        if service.server is None and not service.being_provisioned:
            candidatos = [s for s in es.EdgeServer.all() if s.has_capacity_to_host(service=service)]
            if candidatos:
                alvo = max(candidatos, key=lambda s: (s.memory - s.memory_demand))
                service.provision(target_server=alvo)


def todos_disponiveis(model):
    return all(s._available for s in es.Service.all()) and es.Service.count() > 0


def main():
    dataset = sys.argv[1]
    target = int(sys.argv[2])
    caminho = mover_registry(dataset, target)

    sim = es.Simulator(
        tick_duration=1,
        tick_unit="seconds",
        stopping_criterion=todos_disponiveis,
        resource_management_algorithm=placement_worst_fit,
        network_flow_scheduling_algorithm=es.max_min_fairness,
        dump_interval=float("inf"),
    )
    sim.initialize(input_file=caminho)

    # Forca o cenario de provisionamento do zero: nenhum servico comeca
    # disponivel, para que o download das camadas a partir do registry
    # realmente ocorra durante a simulacao.
    for service in es.Service.all():
        service._available = False
        service.being_provisioned = False
        service.server = None

    sim.run_model()

    providos = sum(1 for s in es.Service.all() if s._available)
    print(f"RESULT {target} {sim.schedule.steps} {providos}")


if __name__ == "__main__":
    main()
