# HidroPy — linha de comando

Referência completa da interface de linha de comando, para scripts e automação.

Validação, simulação, otimização e exportações rodam sem abrir a janela, com os mesmos
cálculos dos comandos F4, F5 e F6 da interface:

```bash
python main.py cli <comando> projeto.shcad|rede.inp [opções] [--json]
```

No executável: `HidroPy.exe cli <comando> ...`. `python main.py cli --help` e
`python main.py cli <comando> --help` listam as opções.

| Comando | O que faz |
|---|---|
| `info` | contagens, comprimentos, diâmetros, custo pelo catálogo, cenários (última simulação/otimização e se estão atuais), opções de simulação e otimização, população adotada |
| `validar` | erros impeditivos × advertências, com códigos (`DIAMETRO_INVALIDO`, `NO_DESCONECTADO`...) |
| `simular` | EPANET do cenário: pressões mín./máx., velocidade máx., nós/trechos fora dos limites das opções de simulação; `--gravar` salva o resultado no projeto |
| `otimizar` | `main4.py` com sobrescrita das constantes reais (ver abaixo); `--criar-cenario NOME` grava um cenário com os diâmetros otimizados (trechos existentes intactos; `--substituir`, `--ativar`); `--gravar` guarda o resultado no próprio cenário; `--detalhes` lista os trechos alterados |
| `comparar` | por cenário: custo pelo catálogo, trechos diferentes da referência, pressões/velocidades da simulação atual (`--simular` calcula as que faltam, `--gravar` salva) e última otimização; indica o `melhor` |
| `aplicar-otimizacao` | aplica ao cenário (padrão: o ativo) a última otimização dele, de `--de-cenario NOME` ou `--resultado UID`; recusa se a rede mudou desde a otimização (`--forcar`); cria a cópia `<projeto>.<data_hora>.bak` |
| `ativar-cenario` | torna ativo `--cenario NOME` no arquivo |
| `exportar-dxf` | `--planta calculo` ou `execucao`, `--saida x.dxf` (usa as opções de DXF salvas no projeto; `--altura-texto`, `--sem-cad`, `--simular`) |
| `planilha` | `--tipo resultados`, `otimizacao`, `cadastro` ou `existentes`; `--saida x.xlsx` ou `x.csv` |
| `relatorio` | `--saida x.html` ou `x.pdf`; `--secoes cadastro,resultados,otimizacao,restricoes,validacao,populacao` |
| `importar` | converte `rede.inp` em `--saida projeto.shcad` |

Parâmetros de `otimizar` (constante do `main4.py` entre parênteses): `--geracoes`
(NUM_GERACOES), `--populacao` (TAM_POPULACAO), `--semente` (SEMENTE), `--pressao-min`,
`--pressao-max`, `--pressao-min-absoluta`, `--tolerancia-pressao`, `--vel-max`
(VELOCIDADE_MAX), `--dn-min`/`--dn-max` (DN_MIN/MAX_PERMITIDO, em DN), `--margem-dn`
(MARGEM_DN_ACIMA), `--prob-cruzamento`, `--prob-mutacao`, `--torneio`,
`--parada-sem-melhora`, `--perda-max` (PERDA_CARGA_MAX, liga o limite de perda unitária) e
`--catalogo arquivo.json` (CATALOGO_COMPLETO). Os valores valem só para aquela execução: as
opções salvas no projeto não mudam, mas a configuração usada fica guardada no resultado.

Opções comuns: `--cenario NOME|uid` (padrão: o ativo), `--saida`, `--timeout s`, `-v` (todo o
log do cálculo no stderr; sem ele, uma linha de progresso a cada 15 s), `--max N` (itens
listados), `--ignorar-validacao`, `--corrigir-inp`.

**Entrada `.inp`.** O arquivo é verificado antes da leitura: ANSI, UTF-16 e UTF-8 com BOM são
convertidos para UTF-8 automaticamente (aviso em `avisos_importacao`). Arquivo corrompido ou
projeto binário do EPANET salvo como `.inp` encerra com código `2` e a explicação em `erro`.
Palavras-chave traduzidas (ex.: `UNITS Metros` no `[BACKDROP]`) e números com vírgula decimal
encerram com código `2` listando as linhas; com `--corrigir-inp` elas são corrigidas numa cópia
(o original não muda) e cada correção aparece em `avisos_importacao`.

**Gravação segura.** Os comandos que gravam releem o `.shcad` do disco sob trava
(`<projeto>.shcad.lock`), aplicam só a sua alteração e salvam (com `.bak`); antes conferem
que a rede do cenário no arquivo é a mesma que foi calculada (hash do `.inp`). Por isso
várias otimizações podem rodar **em paralelo** gravando cenários no mesmo projeto. Se a
entrada for `.inp`, a primeira gravação cria `<rede>.shcad` (ou `--saida`); depois use o
`.shcad` como entrada. Feche o projeto na interface antes (ou reabra-o depois): um "Salvar"
na interface sobrescreve o que a linha de comando gravou.

## Saída JSON (`--json`, versão 1)

O stdout recebe **um** objeto JSON numa linha; mensagens humanas e progresso vão para o
stderr. Código de saída: `0` sucesso, `1` falha do cálculo/validação ou gravação recusada,
`2` erro de uso ou de arquivo. Campos sempre presentes:

```json
{"cli_versao": 1, "comando": "otimizar", "ok": true, "erro": null, "arquivo": "C:\\...\\rede.shcad"}
```

Campos por comando (m, mca, m/s, mm, L/s, R$):

- `info`: `tipo` (`shcad`/`inp`), `titulo`, `cenario {uid, nome}`, `cenarios [{uid, nome,
  ativo, descricao, criado, pai, ultima_simulacao {uid, criado, atual}, ultima_otimizacao
  {uid, criado, atual, custo, viavel}}]`, `rede {juncoes, reservatorios, tanques, tubulacoes,
  bombas, valvulas, trechos_existentes, comprimento_total_m, comprimento_existente_m,
  demanda_base_total_lps, diametros_mm {"150": n}}`, `custos_catalogo {custo_projetado,
  custo_total, fora_do_catalogo {n, ids, truncado}}`, `opcoes_simulacao`, `opcoes_otimizacao`
  (campos de `OptimizationSettings` = constantes do `main4.py` em minúsculas), `populacao
  {nome, metodo, ano_final, populacao_projeto}` ou `null`, `avisos_importacao`.
- `validar`: `cenario`, `valido`, `erros`, `advertencias`, `por_codigo {CODIGO: {severidade,
  n}}`, `problemas [{severidade (erro/advertência), codigo, mensagem, elemento}]`, `truncado`.
- `simular`: `cenario`, `duracao_s`, `status` (`ok`/`failed`), `resultado_uid`, `motor`,
  `criado`, `workdir`, `instantes`, `duracao_h`, `pressao_min {valor, no}`, `pressao_max
  {valor, no}`, `velocidade_max {valor, trecho}`, `limites {pressao_min, pressao_max,
  velocidade_min, velocidade_max}`, `fora_dos_limites {pressao_baixa, pressao_alta,
  velocidade_alta, velocidade_baixa, inversao_fluxo: {n, ids, truncado}}`, `atende_limites`,
  `avisos_epanet`, `nao_mapeados`, `gravado {arquivo, backup}` ou `null`. Em falha:
  `traceback`, `relatorio_epanet`.
- `otimizar`: `cenario`, `duracao_s`, `parametros_alterados`, `status`, `resultado_uid`,
  `motor`, `workdir`, `script_inalterado`, `custo`, `custo_original` (rede de entrada pelo
  catálogo), `viavel`, `violacao`, `fitness`, `n_pressao_baixa`, `n_pressao_alta`,
  `n_velocidade_alta`, `n_perda_alta`, `pressao_min`, `pressao_max`, `velocidade_max`,
  `hora_critica`, `faixa_dn`, `avaliacoes_unicas`, `trechos_projetados`,
  `trechos_existentes_preservados`, `trechos_alterados`, `comprimento_alterado_m`,
  `configuracao {semente, tam_populacao, num_geracoes, pressao_min, pressao_max,
  velocidade_max, dn_min_permitido, dn_max_permitido, margem_dn_acima}`, `alteracoes [{id,
  de_mm, para_mm, comprimento_m}]` (com `--detalhes`), `gravado`, `cenario_criado {arquivo,
  backup, cenario_uid, cenario_nome, ativado, trechos_alterados}` ou `null`. Em falha:
  `traceback`, `log_final`.
- `comparar`: `referencia`, `limites`, `cenarios [{uid, nome, ativo, descricao,
  trechos_diferentes_da_referencia, custo_projetado, custo_total, fora_do_catalogo,
  simulacao {resultado_uid, simulado_agora, pressao_min, pressao_max, velocidade_max,
  n_pressao_baixa, n_pressao_alta, n_velocidade_alta, atende_limites} ou null, otimizacao
  {resultado_uid, custo, viavel, violacao, atual} ou null}]`, `melhor {nome, uid,
  custo_projetado}` (menor custo projetado entre os cenários cuja simulação atual atende aos
  limites; `null` se nenhum), `gravado`.
- `aplicar-otimizacao`: `cenario`, `resultado_uid`, `resultado_atual`, `custo`,
  `trechos_alterados`, `alteracoes` (com `--detalhes`), `gravado {arquivo, backup}`.
- `ativar-cenario`: `cenario`, `cenario_uid`, `gravado`.
- `exportar-dxf`: `cenario`, `saida`, `planta`; execução: `pecas`, `quantidades`,
  `pontos_com_pecas`, `pontos_com_observacoes`; cálculo: `resultados_usados`,
  `campos_trechos`, `campos_nos`, `aviso`.
- `planilha`: `cenario`, `tipo`, `arquivos`, `linhas {aba: n}`.
- `relatorio`: `cenario`, `saida`, `secoes`, `simulacao_atual`, `otimizacao_atual`.
- `importar`: `saida`, `nos`, `ligacoes`, `tubulacoes`, `avisos_importacao`.

Catálogo (`--catalogo`): `[[DN, diâmetro_m, R$/m], ...]`, como o `CATALOGO_COMPLETO` do
`main4.py`, ou `[{"dn": 100, "diametro_mm": 100, "custo": 62.0}, ...]`.
