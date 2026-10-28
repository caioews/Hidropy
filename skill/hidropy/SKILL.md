---
name: hidropy
description: Rodar o HidroPy (simulador hidráulico CAD em Python, https://github.com/caioews/Hidropy) pela linha de comando com saída JSON - informações da rede, validação, simulação EPANET, otimização de diâmetros pelo main4.py (algoritmo genético), comparação de cenários, gravação de cenários otimizados no projeto .shcad, aplicação da otimização, exportação DXF (planta de cálculo/execução), planilhas e relatórios. Use sempre que o usuário pedir para simular, otimizar, dimensionar ou "achar o melhor cenário" de uma rede de água (.shcad ou .inp), comparar cenários ou gerar saídas do HidroPy.
---

# HidroPy pela linha de comando

O HidroPy tem uma CLI feita para agentes. Ela usa exatamente o mesmo caminho da interface
(F4 validar, F5 simular, F6 otimizar): EPANET via WNTR em subprocesso e o `main4.py` original
(nunca o modifique). Os resultados gravados aparecem na interface como cenários.

## Como chamar

Pasta do programa: a pasta onde está o `main.py` do HidroPy (código-fonte) ou o `HidroPy.exe`
(versão executável). Se não souber onde ela fica, pergunte ao usuário.

```bash
cd "<pasta do HidroPy>"
python main.py cli <comando> "<projeto.shcad | rede.inp>" [opções] --json
```

- Sempre use `--json`: o **stdout** traz um único objeto JSON numa linha; progresso e
  mensagens vão para o **stderr**. Para ler só o JSON: `2>/dev/null`.
- Campos fixos: `cli_versao`, `comando`, `ok`, `erro`, `arquivo`. Código de saída: `0` ok,
  `1` falha do cálculo/validação ou gravação recusada, `2` erro de uso/arquivo.
- Versão executável: `HidroPy.exe cli ...` com os mesmos argumentos (no código-fonte,
  `python main.py cli`).
- Ajuda: `python main.py cli --help`, `python main.py cli otimizar --help`.
- Entrada `.inp`: arquivos em ANSI são convertidos sozinhos. Se o comando falhar listando
  palavras traduzidas (ex.: `Metros`) ou vírgula decimal, mostre as linhas ao usuário e, com a
  autorização dele, repita com `--corrigir-inp` (corrige numa cópia; o original não muda).
  Arquivo corrompido ou binário do EPANET não tem correção: peça um `.inp` exportado de novo.
- Esquema completo do JSON: `docs/CLI.md` do repositório.

| Comando | Para quê |
|---|---|
| `info` | contagens, comprimento, diâmetros, custo pelo catálogo, cenários e se os resultados estão atuais, opções |
| `validar` | erros × advertências com códigos (sai 1 se houver erro) |
| `simular [--gravar]` | pressões mín./máx., velocidade máx., nós/trechos fora dos limites |
| `otimizar [overrides] [--criar-cenario NOME] [--detalhes]` | roda o `main4.py`; grava cenário com os diâmetros otimizados |
| `comparar [--cenarios A B] [--simular --gravar]` | tabela de cenários: custo, pressões, velocidades, viabilidade, `melhor` |
| `aplicar-otimizacao --de-cenario NOME` | aplica os diâmetros ao cenário ativo (cópia `.bak` com data) |
| `ativar-cenario --cenario NOME` | deixa um cenário ativo no arquivo |
| `exportar-dxf --planta calculo|execucao --saida x.dxf` | plantas DXF |
| `planilha --tipo resultados|otimizacao|cadastro|existentes --saida x.xlsx` | tabelas |
| `relatorio --saida x.html|x.pdf` | relatório |
| `importar rede.inp --saida projeto.shcad` | converte .inp em projeto |

Opções comuns: `--cenario NOME` (padrão: o ativo), `--timeout s`, `-v` (log completo),
`--max N`.

Overrides de `otimizar` (constantes reais do `main4.py`; valem só para a execução, a
configuração usada fica guardada no resultado): `--geracoes` (NUM_GERACOES, padrão 150),
`--populacao` (TAM_POPULACAO, 120), `--semente` (SEMENTE, 42), `--pressao-min` (10 mca),
`--pressao-max` (50 mca), `--pressao-min-absoluta` (6), `--vel-max` (3 m/s), `--dn-min`,
`--dn-max` (DN; padrão automático), `--margem-dn` (2), `--prob-cruzamento`, `--prob-mutacao`,
`--torneio`, `--parada-sem-melhora` (40), `--perda-max` (m/km, liga o limite de perda),
`--catalogo arquivo.json` (`[[DN, diâmetro_m, R$/m], ...]`).

## Fluxo: "simular e otimizar para o melhor cenário"

1. **Preparar.** Se a entrada for `.inp`, converta uma vez e trabalhe só com o `.shcad`:
   `importar rede.inp --saida rede.shcad`. Se o usuário estiver com o projeto aberto no
   HidroPy, peça para fechar (ou avise que deve reabrir depois sem salvar por cima): um
   "Salvar" na interface apaga o que a CLI gravou.
2. **Conhecer:** `info`. Anote nº de tubulações, `trechos_existentes`, custo pelo catálogo da
   rede atual, limites de pressão/velocidade e cenários já existentes.
3. **Validar:** `validar`. Com erros, pare e mostre os erros ao usuário (não use
   `--ignorar-validacao` sem ele pedir).
4. **Simular a rede atual:** `simular --gravar`. Isso dá a referência (pressão mínima, nós
   abaixo de 10 mca, velocidades) e deixa resultado visível na interface.
5. **Teste rápido da otimização** (rede nova ou grande): `otimizar --geracoes 3 --populacao 10`
   sem gravar, só para confirmar que roda e medir o tempo.
6. **Otimizar com 2 a 4 configurações**, cada uma gravando um cenário com nome claro.
   Rode em paralelo em segundo plano (`run_in_background`), uma chamada por configuração:
   ```bash
   python main.py cli otimizar rede.shcad --semente 1 --criar-cenario "Otim s1" --json 2>/dev/null
   python main.py cli otimizar rede.shcad --semente 2 --criar-cenario "Otim s2" --json 2>/dev/null
   python main.py cli otimizar rede.shcad --semente 3 --dn-min 75 --criar-cenario "Otim s3 DN75+" --json 2>/dev/null
   ```
   Variações úteis: sementes diferentes (o GA é estocástico), faixa de DN (`--dn-min 75`
   evita DN50 em rede de distribuição se o usuário quiser), `--margem-dn`, mais gerações.
   A gravação em paralelo no mesmo `.shcad` é segura (trava + releitura do arquivo).
   Nome repetido é recusado antes de calcular; use outro nome ou `--substituir`.
7. **Comparar:** `comparar --simular --gravar`. Simula cada cenário otimizado pelo EPANET e
   devolve uma linha por cenário.
8. **Apresentar uma tabela ao usuário** (em português), por exemplo:

   | Cenário | Custo projetado (R$) | Viável (main4) | P mín (mca) | P máx | V máx (m/s) | Trechos alterados |
   |---|---|---|---|---|---|---|

   Use `custo_projetado`, `otimizacao.viavel`, `simulacao.pressao_min/max`,
   `simulacao.velocidade_max` e `trechos_diferentes_da_referencia`. Inclua a "Rede original".
   Recomende um cenário e diga por quê.
9. **Só com aprovação explícita do usuário**: `aplicar-otimizacao --de-cenario "Otim s2"`
   (muda os diâmetros do cenário ativo, guarda cópia `.bak` com data) ou
   `ativar-cenario --cenario "Otim s2"` (só troca o cenário ativo). Depois, se ele quiser:
   `simular --gravar`, `exportar-dxf`, `planilha`, `relatorio`.

## Critério de "melhor cenário"

- Primeiro **viável**: `viavel: true` na otimização (pressões atendem ao alvo do `main4.py`,
  velocidade ≤ máxima) **e** `simulacao.atende_limites: true` no `comparar`.
- Entre os viáveis, **menor `custo_projetado`** (custo pelo catálogo só dos trechos
  projetados; trechos existentes ficam fora, como no `main4.py`). O campo `melhor` do
  `comparar` aplica essa regra; confirme também `viavel`.
- **Trechos existentes** (marcados como executados) nunca mudam: confira que
  `trechos_existentes_preservados` = `trechos_existentes` do `info`.
- Se nenhuma solução for viável, diga isso e mostre `violacao`, `n_pressao_baixa`,
  `n_velocidade_alta`; sugira mais gerações, outra faixa de DN ou revisar cotas/booster.
- Se a rede original já atende e custa menos que as otimizações, diga isso. Com poucas
  gerações o GA pode sair mais caro que a rede de entrada (`custo` > `custo_original`).

## Armadilhas

- **Tempo:** a otimização padrão (150 gerações × 120 indivíduos) leva cerca de 10 min em
  redes grandes (~150-300 trechos); a rede de exemplo leva segundos. Rode em segundo plano
  e espere a notificação; não faça polling. Use `--timeout` acima do tempo esperado (padrão
  sem limite). Várias em paralelo dividem a CPU: com 4 ao mesmo tempo, cada uma fica mais
  lenta.
- Para **testes** use `--geracoes 2-5 --populacao 8-10`; nunca apresente ao usuário uma
  solução de teste como resultado final.
- `pressao_min/max` da otimização vêm de `opcoes_otimizacao`; os limites do `simular` e do
  `comparar` vêm de `opcoes_simulacao`. Se forem diferentes, avise.
- Resultado "desatualizado" (`atual: false`) significa que a rede mudou depois do cálculo.
  `aplicar-otimizacao` recusa resultado desatualizado; não use `--forcar` sem o usuário pedir.
- Cenário criado por `--criar-cenario` guarda a otimização **dentro dele**; por isso
  `aplicar-otimizacao` precisa de `--de-cenario NOME` (ou `--resultado UID`).
- Entrada `.inp` + `--saida` que já existe é recusada (os identificadores internos mudam a
  cada importação): use o `.shcad`.
- Caminhos com espaço: sempre entre aspas. No Git Bash use barras normais.
- Nunca edite o `main4.py` nem o `.shcad` à mão; tudo pela CLI.
- Não regenere o executável (`PyInstaller`) sem o usuário pedir.
