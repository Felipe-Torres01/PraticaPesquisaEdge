# Labbook – Grupo 7

**Prática em Pesquisa (PUCRS), 2º semestre de 2026**
**Integrantes:** Felipe Torres, Gerson Gomes e Pedro Augusto Wagner
**Trabalho:** reprodução e extensão de Knob et al. (2021), *Community-based Placement of Registries to
Speed up Application Deployment on Edge Computing* (IEEE IC2E), no simulador EdgeSimPy.
**Repositório:** https://github.com/Felipe-Torres01/PraticaPesquisaEdge

Cada entrada registra a data, quem fez, o objetivo, o que foi feito, os resultados, os problemas e
decisões, e os próximos passos. Os comandos exatos de cada experimento estão no `README.md`, e os
relatórios detalhados de cada etapa estão em `docs/atualizacao_*.txt`.

---

## Pergunta de pesquisa e plano

- **Pergunta:** os resultados de Knob et al. (2021) se reproduzem num simulador aberto (EdgeSimPy)? E
  continuam valendo em cenários mais realistas (outras topologias, imagens reais, carga contínua)?
- **Método do artigo:** posicionar K *registries* com o algoritmo de comunidades FluidC e, dentro de
  cada comunidade, escolher o nó de maior centralidade de autovetor. A comparação é com o
  posicionamento aleatório.
- **Métricas:** tempo médio de provisionamento dos containers e % de requisições não iniciadas
  dentro do prazo (deadline).
- **Critério:** comparação pareada por seed (mesmo cenário para as duas estratégias), com média ±
  desvio-padrão e teste de permutação pareado.

---

## 24/09/2026 – Estrutura inicial (Felipe)

- **Feito:** criou o repositório no GitHub, a estrutura de pastas e o cenário base
  (`cenarios/cenario_base.json`).
- **Decisão:** usar o EdgeSimPy porque é aberto e escrito em Python, enquanto o simulador do artigo
  não foi publicado.
- **Próximo:** conseguir rodar uma simulação de ponta a ponta.

## 01/10/2026 – Primeira reprodução no EdgeSimPy (Pedro)

- **Feito:** escreveu `run_cenario.py`, que roda um cenário e mede o tempo de provisionamento, e
  `experimento.py`, que roda várias simulações. Também gerou o primeiro dataset com registries e o
  primeiro gráfico de provisionamento.
- **Resultado:** a simulação funciona de ponta a ponta e já mostra diferença entre as estratégias.
- **Próximo:** gerar as topologias do artigo e implementar o FluidC.

## 08–09/10/2026 – Gerador da topologia aleatória (Felipe)

- **Feito:** criou o `gerar_cenario.py` com a topologia aleatória do artigo e cenários com K = 1 e
  K = 4. Também ajustou os scripts.
- **Próximo:** posicionamento com o FluidC.

## 16/10/2026 – FluidC e primeira GARR (Gerson)

- **Feito:** criou o `fluidc_placement.py`, que divide a rede em K comunidades com o FluidC e põe o
  registry no nó de maior centralidade de autovetor de cada uma. Também criou o `topologia.py`, com a
  primeira versão da GARR, e integrou tudo ao `experimento.py` e ao `run_cenario.py`.
- **Resultado:** as duas estratégias (FluidC e aleatório) passam a rodar no mesmo cenário.

## 21/10/2026 – Topologias reais, Erdős-Rényi e 20 seeds (Pedro)

- **Feito:** adicionou a GARR real do *Internet Topology Zoo* (61 nós, 75 enlaces) e a Erdős-Rényi
  G(n, p) com 100 nós. Criou o `analise_estrategias.py` (média ± dp, ganho pareado, teste de
  permutação) e rodou 20 seeds por configuração.
- **Resultado:** o FluidC é mais rápido que o aleatório em todos os K, nas duas topologias.
- **Problema e decisão:** o arquivo GML da GARR já trazia a banda dos enlaces, e por isso a opção
  `--banda-link` era ignorada. Agora a banda do arquivo só é usada com `--banda-real`.
- **Próximo:** usar a GARR exata do artigo e imagens realistas.

## 22/10/2026 – Problema de memória (Felipe)

- **Problema:** em simulações longas, a memória crescia a cada tick.
- **Causa:** a coleta interna de métricas do EdgeSimPy guardava tudo.
- **Correção:** a coleta interna foi desligada (`sim.monitor`), e passamos a medir só o que o
  experimento usa.

## 29/10/2026 – GARR do artigo e Docker Hub (Gerson)

- **Feito:** criou o leitor do JSON da GARR usada no artigo (70 nós, 111 enlaces, recebido do
  professor) e rodou essa GARR. Também fez o `coletar_dockerhub.py`, que coleta as 50 imagens mais
  baixadas do Docker Hub com tamanho e camadas.

## 29/10/2026 – Hexagonal, imagens reais e carga contínua (Pedro)

- **Feito:**
  - grade hexagonal 10×10 (rede celular, 100 nós e 261 enlaces), igual ao gerador do próprio
    EdgeSimPy;
  - imagens do Docker Hub com as camadas reais e compartilhadas;
  - modo de carga contínua (`carga_trabalho.py`), com chegadas de Poisson, deadline de 25 s e cache
    LRU de 600 MB.
- **Resultados (rajada, 20 seeds):** o FluidC é mais rápido em todas as 28 combinações de topologia,
  imagens e K, com p < 0,05. Com imagens reais os tempos caem, mas o ganho relativo quase não muda.
- **Problemas encontrados no EdgeSimPy:**
  1. Uma imagem com a mesma camada repetida travava outra imagem no mesmo servidor. Corrigimos
     removendo os digests repetidos.
  2. Com tick de 1 s, as duas estratégias davam resultados idênticos, porque as camadas baixavam
     dentro do primeiro tick. Passamos a usar 0,1 s por tick.
- **Suposições (o artigo não informa):** o container vive 30 s e cada servidor aceita 4 containers.
- **Próximo:** mais seeds na carga de 5 req/s, porque com 10 seeds o p foi 0,25.

## 29/10/2026 – Relatório no formato SBC (Pedro)

- **Feito:** converteu a proposta do Overleaf em relatório (introdução, base, metodologia,
  implementação, configuração e resultados), com as figuras geradas por `figuras_artigo.py`.

## 05/11/2026 – Carga com 30 seeds e verificação com 1 hora (Pedro)

- **Resultado (5 req/s, 30 seeds):** o FluidC não perdeu nenhuma requisição nas 120 simulações. O
  aleatório perdeu em 8 a 12 de cada 30 seeds. A diferença é significativa para todo K (p < 0,01).
- **Verificação:** com 1 hora de chegadas (10 seeds), o resultado repete o de 10 minutos seed a seed,
  com diferença máxima de 5 pontos.
- **Problema:** 10 simulações de 1 hora em paralelo esgotaram a RAM (8 GB). Limitamos a 3 em paralelo.

## 10/11/2026 – Tese do Knob, PESS e cenário fiel (Pedro)

- **Descoberta:** os parâmetros exatos estão na tese do Knob (PUCRS, 2022, seção 4.5), e a Tabela 4.3
  tem os números de referência. Havia três diferenças em relação ao que fazíamos:
  - a GARR usa só 10% da banda do mapa;
  - os nós não têm limite de capacidade;
  - o container vive até o próprio deadline.
- **Feito:**
  - escalonador PESS (`escalonador_pess.py`), adaptado de Doriguzzi-Corin et al. (2020);
  - modo fiel à tese (`--fator-banda 0.1`, `--sem-limite-capacidade`, `--vida-ate-deadline`);
  - 240 simulações, comparadas com a tese em `comparacao_knob.py`;
  - nova coleta do Docker Hub, que corrigiu a percona (de 0,04 para 145 MB) e as tags de teste.
- **Validação do PESS:** 62% dos containers ficaram nos 6 nós mais usados. A tese relata 67%.
- **Resultado:**
  - em 11 de 12 casos o FluidC perde menos requisições que o aleatório, com diferença significativa;
    no 12º os dois zeram, como na tese;
  - os valores exatos batem só em parte (ver o README).
- **Problemas:**
  - simulações congestionadas passavam de 1 GB cada, então limitamos a 2 em paralelo;
  - o notebook suspendeu de madrugada, e as simulações interrompidas foram refeitas;
  - corrigimos o `experimento.py` para que um timeout não derrube a varredura inteira.
- **Verificação de determinismo:** repetimos uma simulação e o resultado foi idêntico byte a byte.

## 13/11/2026 – Fechamento (Pedro)

- **Feito:** título final do relatório ("Replicação e Extensão do Posicionamento de Registries
  Baseado em Comunidades na Computação de Borda") e número de citações do artigo base (12, segundo o
  Semantic Scholar). Também escreveu este labbook e a apresentação.

---

## Conclusões

- **Reprodução qualitativa confirmada:** o FluidC é melhor que o aleatório em todas as topologias,
  conjuntos de imagens, cargas e escalonadores testados.
- **Reprodução quantitativa parcial:** os valores exatos dependem de detalhes que o artigo e a tese
  não publicam:
  - a distribuição dos deadlines;
  - o código do PESS;
  - a escolha do registry, que no EdgeSimPy é feita por saltos e na tese por banda.
- **Contribuições além do artigo:**
  - três topologias novas;
  - imagens reais do Docker Hub;
  - carga contínua com 30 seeds e testes de significância;
  - código aberto e reproduzível.

## Trabalhos futuros

- Cenário fiel com 1 hora de chegadas e escolha de registry por banda.
- Carga com 30 seeds em 10 e 20 req/s, e popularidade zipf.
- Uma estratégia nova que considere a banda de borda dos nós, que parece ser o gargalo do FluidC na
  GARR.
