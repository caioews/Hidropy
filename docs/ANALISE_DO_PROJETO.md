# Análise do projeto existente — `Simulador e otimizador`

Data da análise: 2026-10-15

## 1. Conteúdo encontrado

| Item | Situação |
|---|---|
| `main4.py` (880 linhas) | **Único script de cálculo.** Faz simulação (via WNTR/EPANET) e otimização de diâmetros (via DEAP). |
| `.venv/` | Ambiente virtual criado em **Linux** (`bin/`, bibliotecas `.so`, Python 3.14.4). **Não é utilizável no Windows.** Lista útil das dependências reais: `wntr 1.4.0`, `deap 1.4.4`, `numpy`, `pandas`, `scipy`, `networkx`, `matplotlib`, `python-docx`. |
| `__pycache__/main3_comentado...pyc` | Resto de uma versão anterior (`main3_comentado.py`), cujo fonte não está presente. Não faz parte do fluxo. |
| `.claude/settings.local.json` | Histórico de permissões. Mostra que o script era executado como `python main4.py` e que já foi rodado com as redes `ZN_Assentamento.inp`, `rede.inp` e `SAA_RDA_CAN_DINAMICA_R0.inp` (nenhuma delas está na pasta). |

Não existe nenhum arquivo `.inp` de exemplo na pasta. Por isso foi criada a rede de teste
`examples/rede_exemplo.inp` (gerada pelo próprio programa, ver `examples/gerar_exemplos.py`).

## 2. Funcionamento de `main4.py`

### 2.1. Bibliotecas
- **WNTR** — leitura do `.inp` (`wntr.network.WaterNetworkModel`), simulação
  (`wntr.sim.EpanetSimulator`, ou seja, o EPANET 2.2 embutido no WNTR) e escrita do `.inp` otimizado
  (`wntr.network.write_inpfile`).
- **DEAP** — algoritmo genético (`creator`, `base.Toolbox`, `tools.cxUniform`, `tools.selTournament`,
  `tools.HallOfFame`, `tools.selBest`).
- **NumPy** — vetores de resultados e penalidades.

### 2.2. Entrada
- Um arquivo **EPANET `.inp`** definido pela constante `ARQUIVO_REDE` (caminho relativo ao diretório
  corrente). Todos os elementos são identificados **pelo nome (ID) do EPANET**.
- Propriedades realmente usadas: comprimento e diâmetro dos tubos (`pipe.length`, `pipe.diameter`),
  cotas das junções, carga dos reservatórios, nível inicial dos tanques, opções de tempo
  (`duration`, `hydraulic_timestep`) e todo o restante que o EPANET precisa para simular
  (rugosidade, demandas, padrões, bombas, válvulas, controles).

### 2.3. Parâmetros (constantes no topo do módulo)
Não há argumentos de linha de comando nem arquivo de configuração. Os parâmetros são **constantes de
módulo**:

| Grupo | Constantes |
|---|---|
| Arquivos | `ARQUIVO_REDE`, `ARQUIVO_SAIDA` |
| Algoritmo genético | `SEMENTE`, `TAM_POPULACAO`, `NUM_GERACOES`, `PROB_CRUZAMENTO`, `PROB_MUTACAO`, `PROB_MUT_GENE`, `TAM_TORNEIO`, `PARADA_SEM_MELHORA` |
| Catálogo | `CATALOGO_COMPLETO` = lista de (DN mm, diâmetro de cálculo m, custo R$/m) |
| Faixa de DN | `DN_MIN_PERMITIDO`, `DN_MAX_PERMITIDO` (None = automático), `MARGEM_DN_ACIMA` |
| Trechos fixos | `TRECHOS_FIXOS` (nomes dos tubos que não são dimensionados) |
| Restrições | `PRESSAO_MIN`, `PRESSAO_MAX`, `TOLERANCIA_PRESSAO`, `PERDA_ADMITIDA_EXCECAO`, `PRESSAO_MIN_ABSOLUTA`, `VELOCIDADE_MAX`, `APLICAR_LIMITE_PERDA_UNITARIA`, `PERDA_CARGA_MAX` |

### 2.4. Fluxo de execução
1. **Na importação do módulo** (não só em `__main__`): lê a rede, define `TUBOS`, `JUNCOES`,
   `COMPRIMENTOS`, cria diretório temporário, imprime o inventário, executa
   `definir_alvos_pressao()` (1 simulação) e `escolher_faixa()` (até 17 simulações), recorta o catálogo
   e registra o `toolbox` do DEAP.
2. `main()`: `teste_viabilidade()` → relatório da rede no menor DN → laço evolutivo
   (µ+λ com elitismo, cache de avaliações, parada antecipada) → relatório da melhor solução →
   escreve `ARQUIVO_SAIDA` com os diâmetros otimizados.

### 2.5. Saídas
- Texto no `stdout` (inventário, viabilidade, progresso a cada 10 gerações no formato
  `Geracao   N | melhor = R$ ... | avaliacoes unicas = ...`, relatórios).
- Arquivo `.inp` otimizado (`ARQUIVO_SAIDA`).
- Funções reutilizáveis no namespace do módulo: `rodar_epanet(diam_por_tubo)` (envoltória
  p_min/p_max/v_max/j_max/q_max por nó/trecho, na ordem de `JUNCOES`/`TUBOS`) e `detalhar(indices)`
  (custo, viabilidade, violações).

### 2.6. Limitações identificadas
1. Configuração por constantes editadas no código; não há API nem argumentos.
2. O trabalho pesado ocorre **na importação** do módulo — não dá para importar e configurar depois.
3. O melhor indivíduo (`melhor`) é variável local de `main()`; o resultado estruturado só existe como
   texto impresso e como `.inp` de saída.
4. Otimiza **apenas tubulações**; bombas e válvulas não são dimensionadas.
5. Avalia restrições pela **envoltória temporal** (mínimo/máximo ao longo do período).
6. Simulação só por demanda (*demand driven*), modelo padrão do `EpanetSimulator`.
7. O custo vem do **catálogo** (R$/m por DN), não de um custo por trecho.
8. Resultados da simulação não são exportados em série temporal; o script não tem modo
   "apenas simular".
9. Caminho do arquivo de rede relativo ao diretório corrente.

## 3. Estratégia de integração adotada

**O arquivo `main4.py` não é modificado.** A integração é feita por dois processos-trabalhadores
executados em **subprocesso** (QProcess na interface, `subprocess` nos testes):

### 3.1. Otimização (`src/integration/workers/optimization_worker.py`)
1. A interface exporta a rede para `.inp` (unidades LPS, Hazen-Williams) num diretório de trabalho
   absoluto e escreve um `job.json` com os parâmetros.
2. O trabalhador lê o **código-fonte** de `main4.py`, faz o *parse* com `ast` e substitui **apenas os
   valores das atribuições de topo** das constantes listadas em 2.3 (ex.: `ARQUIVO_REDE` → caminho
   absoluto do `.inp` exportado). Se alguma constante esperada não existir, a execução é abortada com
   erro — a integração não inventa parâmetros.
3. O código resultante é executado com `__name__ = "main4_integrado"` (o bloco `if __name__ ==
   "__main__"` não dispara), e o trabalhador chama `main()` do próprio script. Toda a saída de texto do
   script é repassada à interface em tempo real (progresso das gerações é lido dessa saída).
4. Após `main()`, o trabalhador lê o `.inp` gerado pelo script (`ARQUIVO_SAIDA`), converte os diâmetros
   em índices do catálogo e chama **`detalhar()` do próprio script** para obter custo, viabilidade e as
   envoltórias por nó/trecho. Também chama `rodar_epanet()` com os diâmetros originais para a
   comparação "antes × depois".
5. Os resultados são gravados em `result.json`, **indexados por nome EPANET**; a interface converte
   nomes → identificadores persistentes (UID) usando a tabela de nomes gerada na exportação.

### 3.2. Simulação (`src/integration/workers/simulation_worker.py`)
`main4.py` não possui modo de "apenas simular" e não devolve séries temporais. Para a simulação
hidráulica o trabalhador usa **exatamente o mesmo motor e a mesma chamada** do script
(`wntr.sim.EpanetSimulator(wn).run_sim(file_prefix=...)`), lendo o `.inp` exportado, e devolve as
séries temporais de pressão, carga, demanda, vazão, velocidade, perda de carga (convertida de m/m para
m/km, como na `[CORRECAO 4]` do script) e estado. Nenhum cálculo hidráulico é reimplementado: é o
EPANET do WNTR. O relatório `.rpt` do EPANET é anexado ao log.

### 3.3. Associação dos resultados
- Cada exportação gera um mapa `nome EPANET → UID` (`name_map`). Os resultados são associados pelos
  nomes, nunca pela posição em listas.
- Cada resultado guarda o **hash SHA-256 do `.inp` exportado**. Se a rede mudar, o resultado é marcado
  como *desatualizado* (comparação do hash com a exportação atual).

### 3.4. Ambiente Python
O interpretador dos trabalhadores é configurável (Configurações → Interpretador Python). Padrão: o
mesmo interpretador da interface. Dependências: ver `requirements.txt`.

## 4. Funcionalidades que dependem de suporte do motor

| Funcionalidade | Situação |
|---|---|
| Regime permanente / período estendido | Suportado (EPANET via WNTR). |
| Padrões de demanda, curvas de bomba, tanques, válvulas PRV/PSV/PBV/FCV/TCV/GPV, válvula de retenção (status CV) | Suportado no modelo, na exportação `.inp` e na simulação. |
| Controles simples (`[CONTROLS]`) | Suportados (por horário, hora do dia, nível/pressão de nó). |
| Regras (`[RULES]`, condições de estado) | **Pendente** — não exportadas. |
| Otimização de bombas/válvulas | **Não suportada** pelo `main4.py`. |
| Custo por trecho na otimização | **Não suportado** — o script usa custo do catálogo. O campo "custo unitário" do tubo é informativo. |
| Simulação dirigida por pressão (PDD) | **Não integrada** (o script usa DD). |
| Qualidade da água | **Não integrada**. |
