"""
Dimensionamento economico de rede de distribuicao de agua por Algoritmo Genetico.

Versao corrigida e generalizada de main3.py. As alteracoes estao marcadas com
  # [CORRECAO n]  e explicadas no cabecalho de cada bloco.

Para rodar outra rede basta trocar ARQUIVO_REDE. A faixa de diametros, a escala
das penalidades e a viabilidade do problema sao determinadas automaticamente a
partir da propria rede -- nao ha nada calibrado para uma rede especifica.

Requisitos: wntr, deap
"""

import atexit
import os
import random
import shutil
import tempfile
import warnings

import numpy as np
import wntr
from deap import base, creator, tools

warnings.filterwarnings('ignore')

# =========================================================================
# CONFIGURACOES GERAIS
# =========================================================================

ARQUIVO_REDE = 'ZN_Assentamento.inp'
ARQUIVO_SAIDA = 'rede_otimizada.inp'

SEMENTE = 42          # reprodutibilidade (importante para o TCC)

TAM_POPULACAO = 120
NUM_GERACOES = 150
PROB_CRUZAMENTO = 0.7
PROB_MUTACAO = 0.3    # probabilidade de o individuo sofrer mutacao
PROB_MUT_GENE = None  # None -> usa 2/NUM_TUBOS (regra pratica)
TAM_TORNEIO = 3
PARADA_SEM_MELHORA = 40   # encerra se nao melhorar por N geracoes

random.seed(SEMENTE)
np.random.seed(SEMENTE)

# =========================================================================
# [CORRECAO 1] CATALOGO COMERCIAL DE DIAMETROS + CUSTO REAL
#
# main3.py usava 21 diametros de 50 a 1000 mm com custo arbitrario
# L * D^2.5 * 10000. Aqui o gene e o INDICE nesta tabela e o custo vem de um
# preco unitario por metro, que e o que torna o resultado comparavel a um
# orcamento real.
#
# >>> SUBSTITUA os precos pelos valores da sua fonte (SINAPI/SICRO da data
# >>> base do TCC, tubo + assentamento). Os valores abaixo sao apenas uma
# >>> ordem de grandeza tipica de PVC PBA/DEFOFO.
#
# A coluna "diametro de calculo" esta igual ao DN. Se quiser rigor, troque
# pelos diametros INTERNOS reais (PVC PBA classe 12: DN50=53,4mm
# DN75=78,4mm DN100=103,4mm; DEFOFO: DN150=160,2mm DN200=211,8mm
# DN250=263,6mm DN300=315,4mm).
# =========================================================================

CATALOGO_COMPLETO = [
    # DN (mm),  diametro de calculo (m),  custo (R$/m)
    (50,   0.050,   25.00),  # DN minimo da rede de distribuicao (NBR 12218)
    (75,   0.075,   40.00),
    (100,  0.100,   62.00),
    (150,  0.150,  125.00),
    (200,  0.200,  205.00),
    (250,  0.250,  310.00),
    (300,  0.300,  440.00),
    (350,  0.350,  550.00),
    (400,  0.400,  700.00),
    (450,  0.450,  860.00),
    (500,  0.500, 1000.00),
    (600,  0.600, 1330.00),
    (700,  0.700, 1690.00),
    (800,  0.800, 2090.00),
    (900,  0.900, 2500.00),
    (1000, 1.000, 2950.00),
]

# =========================================================================
# [CORRECAO 17] FAIXA DE DIAMETROS AUTOMATICA
#
# Antes esta faixa era fixada a mao (DN_MIN_PERMITIDO / DN_MAX_PERMITIDO).
# Isso quebrou ao trocar de rede: com o catalogo limitado a DN300, o
# rede.inp (782 L/s) ficava INSOLUVEL -- o trecho RA dava v = 11,07 m/s e
# pressao de -1,85 mca, porque o diametro necessario nao existia como opcao.
# Um programa que so funciona depois de o usuario adivinhar a faixa certa
# nao e generico.
#
# Com None, o programa deduz a faixa da propria rede (ver escolher_faixa()):
#   - limite inferior: menor DN do catalogo (minimo normativo);
#   - limite superior: o maior entre o DN exigido pela velocidade maxima e
#     o menor DN uniforme que atende a pressao minima, mais uma margem.
# Preencha com numeros so se quiser forcar uma faixa.
# =========================================================================

DN_MIN_PERMITIDO = None    # None = automatico
DN_MAX_PERMITIDO = None    # None = automatico
MARGEM_DN_ACIMA = 2        # degraus de folga acima do DN minimo necessario

# =========================================================================
# [CORRECAO 18] TRECHOS NAO DIMENSIONAVEIS
#
# Numa rede real quase sempre ha trechos que nao entram no dimensionamento:
# adutora ja construida, travessia, trecho de rede existente em obra de
# ampliacao. Liste os nomes aqui: eles mantem o diametro do .inp, continuam
# na simulacao hidraulica e ficam FORA do custo (sao patrimonio existente).
# =========================================================================

TRECHOS_FIXOS = []

# =========================================================================
# [CORRECAO 2] RESTRICOES HIDRAULICAS COERENTES COM A NBR 12218
#
# main3.py usava PRESSAO_MAX = 25 m. Na ColoniaII o ponto de injecao esta na
# cota 44,98 m e os nos entre 2 m e 15,5 m: a pressao ESTATICA vai de 30 a
# 43 m e NAO EXISTE combinacao de diametros que atenda 25 m -- so um VRP
# resolveria. Era uma penalidade permanente de milhoes contra um custo de
# rede de dezenas de milhares: o GA otimizava ruido.
#
# NBR 12218:2017 -> pressao dinamica minima 100 kPa (10 mca)
#                   pressao estatica maxima 500 kPa (50 mca)
# =========================================================================

PRESSAO_MIN = 10.0    # mca
PRESSAO_MAX = 50.0    # mca

# [CORRECAO 14] Tolerancia numerica na pressao.
# O projeto de referencia do rede.inp entrega 9,996284 mca no no A. Isso e
# 10 mca para qualquer efeito de engenharia (3,7 mm de coluna d'agua), mas
# uma comparacao  p < 10.0  crua marca o proprio projeto como inviavel e faz
# o GA gastar diametro atras de um milimetro. A tolerancia so absorve o erro
# de convergencia do EPANET -- nao afrouxa a norma.
TOLERANCIA_PRESSAO = 0.01   # mca

# =========================================================================
# [CORRECAO 19] ALVO DE PRESSAO LIMITADO PELA TOPOGRAFIA
#
# Tratar PRESSAO_MIN como um valor unico e igual para todos os nos so
# funciona quando a fonte tem carga para isso em TODOS eles. Na
# ZN_Assentamento nao tem: o ponto de injecao esta na cota 40,96 m e o no
# J-808 na cota 31,58 m, ou seja, 9,38 mca de carga estatica. Mesmo com
# vazao zero e diametro infinito aquele no nunca passa de 9,38 mca -- os
# 10 mca sao inalcancaveis por TOPOGRAFIA, nao por dimensionamento.
#
# O programa entao declarava o problema insoluvel e nem rodava, enquanto no
# escritorio a rede e dimensionada normalmente aceitando 6 a 8 mca nos
# trechos de menor pressao. O programa estava errado, nao o projeto.
#
# Agora o alvo e POR NO:
#     alvo_i = min(PRESSAO_MIN, pressao_maxima_alcancavel_i - PERDA_ADMITIDA)
# A "pressao maxima alcancavel" e medida rodando a rede toda no maior
# diametro do catalogo -- funciona com bomba, varios reservatorios,
# valvulas e periodo estendido, sem supor nada sobre a fonte. Para a imensa
# maioria dos nos isso da exatamente PRESSAO_MIN; so os nos no limite
# topografico recebem alvo reduzido, e todos sao listados no relatorio.
#
# PERDA_ADMITIDA_EXCECAO e quanta perda de carga se aceita gastar para
# chegar num no que ja esta no limite. Quanto maior, mais barata a rede e
# menor a pressao nesses nos.
# =========================================================================

PERDA_ADMITIDA_EXCECAO = 1.0   # m
PRESSAO_MIN_ABSOLUTA = 6.0     # piso que voce aceita; abaixo disso, so avisa

# =========================================================================
# [CORRECAO 3] VELOCIDADE MINIMA REMOVIDA
#
# main3.py penalizava v < 0,30 m/s. Na ColoniaII, 99 dos 111 trechos ficam
# abaixo disso mesmo em DN50 -- e impossivel atender. Velocidade minima e
# criterio de rede coletora de esgoto (autolimpeza), nao de rede de agua; a
# NBR 12218 nao impoe minimo. O superdimensionamento ja e combatido pelo
# proprio custo.
# =========================================================================

VELOCIDADE_MAX = 3.00  # m/s

# =========================================================================
# [CORRECAO 4] PERDA DE CARGA UNITARIA: UNIDADE CORRIGIDA E CRITERIO OPCIONAL
#
# Bug de unidade: results.link['headloss'] do EpanetSimulator do WNTR ja vem
# em m/m (gradiente hidraulico), NAO em metros. main3.py fazia
#     j = abs(hf) / comprimento * 1000
# ou seja, dividia pelo comprimento uma grandeza que ja era unitaria.
# Verificacao no TRECHO-5 da ColoniaII (L=9,36 m, DN50, Q=3,19 L/s):
#     Delta H entre os nos ...... 0,5485 m  -> J real = 58,3 m/km
#     Hazen-Williams a mao ...... 0,5460 m  -> J real = 58,3 m/km
#     headloss do WNTR .......... 0,058579  -> x1000 = 58,6 m/km  OK
#     formula do main3.py ....... 6,26 m/km  (10x menor, e o erro cresce
#                                             com o comprimento do tubo)
# Correto:  j_m_por_km = abs(hf) * 1000
#
# Alem disso o limite de 10 m/km era aplicado tubo a tubo com peso enorme.
# Perda unitaria e criterio ECONOMICO de adutora; numa rede malhada quem
# manda e a pressao minima no no critico. Um trecho de 4 m com 58 m/km perde
# 0,23 m -- irrelevante. Por isso o criterio entra ponderado pelo comprimento
# e vem DESLIGADO por padrao.
# =========================================================================

APLICAR_LIMITE_PERDA_UNITARIA = False
PERDA_CARGA_MAX = 10.0   # m/km (so usado se a flag acima for True)


# =========================================================================
# CARREGA A REDE (uma unica vez)
#
# [CORRECAO 5] main3.py fazia WaterNetworkModel(ARQUIVO_REDE) dentro da
# funcao de avaliacao -- 20.000 leituras de disco por execucao. O modelo e
# criado uma vez e so os diametros mudam entre avaliacoes.
# =========================================================================

wn = wntr.network.WaterNetworkModel(ARQUIVO_REDE)

TODOS_TUBOS = wn.pipe_name_list

_fixos_invalidos = [t for t in TRECHOS_FIXOS if t not in TODOS_TUBOS]
if _fixos_invalidos:
    raise ValueError(f"TRECHOS_FIXOS inexistentes na rede: {_fixos_invalidos}")

# tubos que o GA dimensiona (os fixos ficam com o diametro do .inp)
TUBOS = [t for t in TODOS_TUBOS if t not in TRECHOS_FIXOS]
NUM_TUBOS = len(TUBOS)
if NUM_TUBOS == 0:
    raise ValueError("Nenhum trecho a dimensionar: revise TRECHOS_FIXOS.")

COMPRIMENTOS = np.array([wn.get_link(t).length for t in TUBOS])
COMPRIMENTO_TOTAL = float(COMPRIMENTOS.sum())
DIAM_FIXOS = {t: wn.get_link(t).diameter for t in TRECHOS_FIXOS}

# [CORRECAO 6] So JUNCOES entram na verificacao de pressao.
# main3.py percorria results.node['pressure'] inteiro, que inclui o
# reservatorio. O EPANET reporta pressao 0 no reservatorio, entao todo
# individuo levava (10 - 0) * 100000 = 1.000.000 de penalidade fixa.
# Tanques tambem ficam de fora: o nivel deles nao e criterio de atendimento.
JUNCOES = wn.junction_name_list

if PROB_MUT_GENE is None:
    PROB_MUT_GENE = 2.0 / NUM_TUBOS

# diretorio proprio para os arquivos temporarios do EPANET
DIR_TEMP = tempfile.mkdtemp(prefix='epanet_ga_')
PREFIXO_TEMP = os.path.join(DIR_TEMP, 'run')
atexit.register(shutil.rmtree, DIR_TEMP, True)

DURACAO = wn.options.time.duration
PERIODO_ESTENDIDO = DURACAO > 0


def inventario():
    print("=" * 74)
    print("REDE CARREGADA")
    print("=" * 74)
    print(f"  Arquivo .............: {ARQUIVO_REDE}")
    print(f"  Trechos (tubos) .....: {len(TODOS_TUBOS)}"
          + (f"  ({NUM_TUBOS} dimensionaveis, "
             f"{len(TRECHOS_FIXOS)} fixos)" if TRECHOS_FIXOS else ""))
    print(f"  Comprimento total ...: {COMPRIMENTO_TOTAL:,.1f} m "
          f"(so os dimensionaveis)")
    print(f"  Juncoes .............: {len(JUNCOES)}")
    print(f"  Reservatorios .......: {len(wn.reservoir_name_list)}"
          f"   Tanques: {len(wn.tank_name_list)}")
    print(f"  Bombas ..............: {len(wn.pump_name_list)}"
          f"   Valvulas: {len(wn.valve_name_list)}"
          f"   (nao sao dimensionadas)")
    if PERIODO_ESTENDIDO:
        print(f"  Simulacao ...........: PERIODO ESTENDIDO, "
              f"{DURACAO / 3600:.0f} h "
              f"(passo {wn.options.time.hydraulic_timestep / 3600:.2f} h)")
    else:
        print("  Simulacao ...........: estatica (duracao 0) -- "
              "um unico instante")
    fechados = [t for t in TODOS_TUBOS
                if str(wn.get_link(t).initial_status).upper() == 'CLOSED']
    if fechados:
        print(f"  ATENCAO: {len(fechados)} trecho(s) com status CLOSED no "
              f".inp: {fechados[:5]}")
    print()


# =========================================================================
# SIMULACAO
#
# [CORRECAO 16] AVALIA TODOS OS PASSOS DE TEMPO, nao so o ultimo.
#
# main3.py e as versoes anteriores usavam results.node['pressure'].iloc[-1],
# ou seja, o ULTIMO instante simulado. Nas duas redes de teste isso passou
# despercebido porque ambas tem Duration = 0 (um unico instante). Em qualquer
# rede com simulacao de periodo estendido o erro e grave e SILENCIOSO:
# gerei uma versao do rede.inp com padrao de 24 h e o resultado foi
#     .iloc[-1] (hora 24) ...: P min = 10,18 mca -> 0 nos violados  (ERRADO)
#     minimo sobre 24 h .....: P min =  9,81 mca -> 1 no violado as 7 h
# O programa aprovaria uma rede que nao atende a norma na hora de pico.
#
# O correto e o envelope:
#   pressao   -> MINIMO ao longo do tempo (hora de maior consumo)
#   pressao   -> MAXIMO ao longo do tempo (madrugada, condicao estatica)
#   velocidade-> MAXIMO
#   perda     -> MAXIMO
# Com Duration = 0 isso recai exatamente no comportamento anterior.
# =========================================================================

def rodar_epanet(diam_por_tubo):
    """diam_por_tubo: dict {nome: diametro em m} para os trechos dimensionaveis."""
    for nome, d in diam_por_tubo.items():
        wn.get_link(nome).diameter = d
    for nome, d in DIAM_FIXOS.items():
        wn.get_link(nome).diameter = d

    res = wntr.sim.EpanetSimulator(wn).run_sim(file_prefix=PREFIXO_TEMP)

    p = res.node['pressure'].loc[:, JUNCOES]
    v = res.link['velocity'].loc[:, TUBOS].abs()
    hl = res.link['headloss'].loc[:, TUBOS].abs()
    q = res.link['flowrate'].loc[:, TUBOS].abs()

    return {
        'p_min': p.min(axis=0).values,        # por no, ao longo do tempo
        'p_max': p.max(axis=0).values,
        'v_max': v.max(axis=0).values,        # por trecho
        'j_max': hl.max(axis=0).values * 1000.0,   # m/m -> m/km [CORRECAO 4]
        'q_max': q.max(axis=0).values,
        'hora_critica': float(p.min(axis=1).idxmin()) / 3600.0,
    }


# =========================================================================
# [CORRECAO 17] ESCOLHA AUTOMATICA DA FAIXA DE DIAMETROS
# =========================================================================

def _idx_por_velocidade(q_max):
    """Menor indice do catalogo completo que atende v <= VELOCIDADE_MAX."""
    exigido = 0
    for qi in q_max:
        d_nec = np.sqrt(4.0 * qi / (np.pi * VELOCIDADE_MAX)) if qi > 0 else 0.0
        k = 0
        while k < len(CATALOGO_COMPLETO) - 1 and CATALOGO_COMPLETO[k][1] < d_nec:
            k += 1
        exigido = max(exigido, k)
    return exigido


def definir_alvos_pressao():
    """
    [CORRECAO 19] Alvo de pressao por no, limitado pelo que a rede consegue
    fisicamente entregar. Devolve (alvos, teto) em mca.
    """
    print("=" * 74)
    print("ALVO DE PRESSAO POR NO")
    print("=" * 74)

    # teto fisico: rede toda no maior diametro do catalogo = perda minima
    teto = rodar_epanet({t: CATALOGO_COMPLETO[-1][1] for t in TUBOS})['p_min']
    alvos = np.minimum(PRESSAO_MIN, np.maximum(0.0,
                                               teto - PERDA_ADMITIDA_EXCECAO))

    excecoes = np.where(alvos < PRESSAO_MIN - 1e-9)[0]
    print(f"  Pressao minima adotada ..: {PRESSAO_MIN:.2f} mca "
          f"(NBR 12218)")
    print(f"  Nos no limite topografico: {len(excecoes)} de {len(JUNCOES)}")

    if len(excecoes):
        print()
        print("  No           cota (m)   teto fisico (mca)   alvo adotado (mca)")
        print("  " + "-" * 68)
        for i in sorted(excecoes, key=lambda k: alvos[k])[:15]:
            print(f"  {JUNCOES[i]:<12} {wn.get_node(JUNCOES[i]).elevation:8.2f} "
                  f"{teto[i]:18.2f} {alvos[i]:20.2f}")
        if len(excecoes) > 15:
            print(f"  ... (+{len(excecoes) - 15} nos)")
        print()
        print(f"  Nestes nos {PRESSAO_MIN:.0f} mca e inalcancavel: a carga da "
              "fonte nao chega la nem com")
        print(f"  vazao zero. O alvo vira o teto fisico menos "
              f"{PERDA_ADMITIDA_EXCECAO:.1f} m de perda admitida.")
        abaixo = [JUNCOES[i] for i in excecoes if alvos[i] < PRESSAO_MIN_ABSOLUTA]
        if abaixo:
            print(f"  >>> ATENCAO: {len(abaixo)} no(s) com alvo abaixo de "
                  f"{PRESSAO_MIN_ABSOLUTA:.0f} mca: {abaixo[:8]}")
            print("  >>> Considere setor separado, booster ou revisao de cota.")
    print()
    return alvos, teto


def escolher_faixa():
    """
    Deduz a faixa util de diametros a partir da hidraulica da propria rede.
    Devolve (i_min, i_max) como indices em CATALOGO_COMPLETO.
    """
    print("=" * 74)
    print("FAIXA DE DIAMETROS")
    print("=" * 74)

    n = len(CATALOGO_COMPLETO)

    # -- limite inferior --------------------------------------------------
    if DN_MIN_PERMITIDO is not None:
        i_min = min(k for k in range(n)
                    if CATALOGO_COMPLETO[k][0] >= DN_MIN_PERMITIDO)
        print(f"  Limite inferior .....: DN{CATALOGO_COMPLETO[i_min][0]} "
              f"(fixado manualmente)")
    else:
        i_min = 0
        print(f"  Limite inferior .....: DN{CATALOGO_COMPLETO[i_min][0]} "
              f"(menor DN do catalogo / minimo normativo)")

    # -- limite superior --------------------------------------------------
    if DN_MAX_PERMITIDO is not None:
        i_max = max(k for k in range(n)
                    if CATALOGO_COMPLETO[k][0] <= DN_MAX_PERMITIDO)
        print(f"  Limite superior .....: DN{CATALOGO_COMPLETO[i_max][0]} "
              f"(fixado manualmente)")
        print()
        return i_min, i_max

    # (a) DN exigido pela velocidade maxima, medido com a rede toda no maior
    #     diametro (vazoes praticamente independentes do diametro escolhido)
    ref = rodar_epanet({t: CATALOGO_COMPLETO[-1][1] for t in TUBOS})
    i_vel = _idx_por_velocidade(ref['q_max'])
    print(f"  Vazao maxima em um trecho: {ref['q_max'].max() * 1000:.2f} L/s")
    print(f"  DN minimo por velocidade ({VELOCIDADE_MAX:.1f} m/s): "
          f"DN{CATALOGO_COMPLETO[i_vel][0]}")

    # (b) menor DN uniforme que ainda atende o ALVO de pressao de cada no
    i_press = None
    for k in range(n):
        r = rodar_epanet({t: CATALOGO_COMPLETO[k][1] for t in TUBOS})
        if np.all(r['p_min'] >= ALVO_PRESSAO - TOLERANCIA_PRESSAO):
            i_press = k
            break

    # [CORRECAO 20] Antes isto devolvia None e o programa ENCERRAVA sem rodar.
    # Um teste de viabilidade deve informar, nao impedir: mesmo sem solucao
    # plenamente viavel, a rede de menor violacao e um resultado util e e o
    # ponto de partida para decidir booster, setorizacao ou revisao de cota.
    if i_press is None:
        print(f"  DN minimo por pressao ...: NENHUM DN uniforme atende, nem "
              f"DN{CATALOGO_COMPLETO[-1][0]}")
        print("  -> usando o catalogo inteiro; o GA busca a menor violacao.")
        print()
        return i_min, n - 1

    print(f"  DN minimo por pressao ...: DN{CATALOGO_COMPLETO[i_press][0]} "
          f"(menor rede uniforme viavel)")

    i_max = min(n - 1, max(i_vel, i_press) + MARGEM_DN_ACIMA)
    print(f"  Limite superior .....: DN{CATALOGO_COMPLETO[i_max][0]} "
          f"(o maior dos dois + {MARGEM_DN_ACIMA} degraus de margem)")

    if i_max < i_min:
        i_min, i_max = i_max, i_max
    print()
    return i_min, i_max


inventario()
ALVO_PRESSAO, TETO_PRESSAO = definir_alvos_pressao()
_faixa = escolher_faixa()

CATALOGO = CATALOGO_COMPLETO[_faixa[0]:_faixa[1] + 1]

DN_MM = [c[0] for c in CATALOGO]
DIAM_M = [c[1] for c in CATALOGO]
CUSTO_M = [c[2] for c in CATALOGO]
N_OPCOES = len(CATALOGO)

# =========================================================================
# ESCALA DE REFERENCIA PARA AS PENALIDADES
#
# [CORRECAO 7] Em main3.py os pesos (100000, 50000, 10000...) eram numeros
# soltos, sem relacao com a escala do custo. A rede ColoniaII inteira em DN50
# custava 45.832 na funcao de custo, enquanto UM no com 1 m de pressao
# faltando valia 100.000. Resultado: o custo era irrelevante e o GA nao tinha
# gradiente util para reduzir diametros.
#
# Aqui a penalidade e ancorada no custo da rede toda no menor DN da faixa --
# uma escala derivada da propria rede, nao um numero digitado:
#   - qualquer solucao inviavel fica pior que qualquer solucao viavel
#     (degrau PENAL_DEGRAU);
#   - dentro da regiao inviavel, a penalidade cresce com a violacao RELATIVA
#     (adimensional), o que da gradiente para o GA seguir.
# =========================================================================

CUSTO_REF = COMPRIMENTO_TOTAL * CUSTO_M[0]
PENAL_DEGRAU = 2.0 * CUSTO_REF
PENAL_ESCALA = 10.0 * CUSTO_REF


# =========================================================================
# AVALIACAO
# =========================================================================

def detalhar(indices):
    """Avaliacao completa, com as parcelas separadas (usada nos relatorios)."""
    idx = np.asarray(indices, dtype=int)
    custo = float((COMPRIMENTOS * np.array(CUSTO_M)[idx]).sum())

    try:
        r = rodar_epanet({t: DIAM_M[idx[i]] for i, t in enumerate(TUBOS)})
    except Exception as erro:
        return {'ok': False, 'erro': str(erro), 'fitness': 1e15, 'custo': custo}

    if not (np.all(np.isfinite(r['p_min'])) and np.all(np.isfinite(r['v_max']))):
        return {'ok': False, 'erro': 'simulacao nao convergiu',
                'fitness': 1e15, 'custo': custo}

    # ---- violacoes RELATIVAS (adimensionais) ----------------------------
    # [CORRECAO 19] alvo POR NO, nao um PRESSAO_MIN unico
    v_pmin = (np.maximum(0.0, ALVO_PRESSAO - TOLERANCIA_PRESSAO - r['p_min'])
              / PRESSAO_MIN)
    v_pmax = (np.maximum(0.0, r['p_max'] - PRESSAO_MAX - TOLERANCIA_PRESSAO)
              / PRESSAO_MAX)
    v_vmax = np.maximum(0.0, r['v_max'] - VELOCIDADE_MAX) / VELOCIDADE_MAX

    if APLICAR_LIMITE_PERDA_UNITARIA:
        # ponderado pelo comprimento: o que importa e a carga perdida, nao o
        # gradiente de um trecho de 4 m
        peso = COMPRIMENTOS / COMPRIMENTO_TOTAL
        v_j = (np.maximum(0.0, r['j_max'] - PERDA_CARGA_MAX)
               / PERDA_CARGA_MAX) * peso
    else:
        v_j = np.zeros(NUM_TUBOS)

    viol = float(v_pmin.sum() + v_pmax.sum() + v_vmax.sum() + v_j.sum())
    fitness = custo + PENAL_DEGRAU + PENAL_ESCALA * viol if viol > 0 else custo

    d = dict(r)
    d.update({
        'ok': True, 'fitness': fitness, 'custo': custo,
        'viavel': viol == 0.0, 'violacao': viol,
        'n_p_baixa': int((v_pmin > 0).sum()),
        'n_p_alta': int((v_pmax > 0).sum()),
        'n_v_alta': int((v_vmax > 0).sum()),
        'n_j_alta': int((r['j_max'] > PERDA_CARGA_MAX).sum()),
    })
    return d


# [CORRECAO 8] Cache de avaliacoes. Numa populacao convergida a maioria dos
# individuos se repete; sem cache o EPANET era chamado 20.000 vezes por
# execucao mesmo com genotipos identicos.
_cache = {}


def avaliar(individuo):
    chave = tuple(individuo)
    if chave not in _cache:
        _cache[chave] = detalhar(individuo)['fitness']
    return _cache[chave],


# =========================================================================
# OPERADORES GENETICOS
# =========================================================================

def mutar_passo(individuo):
    """
    [CORRECAO 9] main3.py sorteava um diametro NOVO ao acaso em 35% dos
    genes. Com 21 opcoes, a mutacao empurrava a populacao de volta para a
    media do catalogo (DN 500) a cada geracao: era um equilibrio
    mutacao-selecao, e por isso a rede saia com DN 350/550/950 mesmo apos
    200 geracoes.

    Aqui a mutacao anda UM degrau (as vezes dois) para cima ou para baixo no
    catalogo, com baixa probabilidade por gene. Isso preserva as boas
    combinacoes ja encontradas e faz busca local de verdade.
    """
    for i in range(len(individuo)):
        if random.random() < PROB_MUT_GENE:
            passo = random.choice((-2, -1, -1, 1, 1, 2))
            individuo[i] = min(N_OPCOES - 1, max(0, individuo[i] + passo))
    return individuo,


if "FitnessMin" not in creator.__dict__:
    creator.create("FitnessMin", base.Fitness, weights=(-1.0,))
if "Individual" not in creator.__dict__:
    creator.create("Individual", list, fitness=creator.FitnessMin)

toolbox = base.Toolbox()
toolbox.register("attr_idx", random.randrange, N_OPCOES)
toolbox.register("individual", tools.initRepeat, creator.Individual,
                 toolbox.attr_idx, n=NUM_TUBOS)
toolbox.register("population", tools.initRepeat, list, toolbox.individual)
toolbox.register("evaluate", avaliar)
# crossover uniforme: a ordem dos genes (nome do trecho) nao tem significado
# espacial, entao cxTwoPoint nao preserva bloco nenhum de verdade
toolbox.register("mate", tools.cxUniform, indpb=0.5)
toolbox.register("mutate", mutar_passo)
toolbox.register("select", tools.selTournament, tournsize=TAM_TORNEIO)


def populacao_inicial(n):
    """
    [CORRECAO 10] Populacao semeada. Inclui uma rede uniforme em CADA
    diametro da faixa, o que garante que a solucao "tudo no DN maximo" (a
    unica que sempre atende a pressao, se alguma atende) esteja presente
    desde a geracao 1: o GA nunca devolve algo pior que ela, so pode
    baratear a partir dai.
    """
    pop = [creator.Individual([k] * NUM_TUBOS) for k in range(N_OPCOES)]
    while len(pop) < n:
        teto = random.randrange(1, N_OPCOES + 1)   # vies para os menores
        pop.append(creator.Individual(
            [random.randrange(teto) for _ in range(NUM_TUBOS)]))
    return pop[:max(n, N_OPCOES)]


# =========================================================================
# RELATORIOS
# =========================================================================

def relatorio(indices, titulo):
    d = detalhar(indices)
    print(f"--- {titulo} ---")
    if not d['ok']:
        print(f"  FALHA: {d['erro']}")
        return d
    print(f"  Custo ...................: R$ {d['custo']:,.2f}")
    print(f"  Viavel ..................: {'SIM' if d['viavel'] else 'NAO'}")
    print(f"  Pressao (min / max) .....: {d['p_min'].min():.2f} / "
          f"{d['p_max'].max():.2f} mca"
          f"   [limites {PRESSAO_MIN:.0f} - {PRESSAO_MAX:.0f}]")
    print(f"  Nos abaixo do alvo ......: {d['n_p_baixa']}"
          f"   (nos acima do maximo: {d['n_p_alta']})")
    print(f"  Velocidade maxima .......: {d['v_max'].max():.3f} m/s"
          f"   [limite {VELOCIDADE_MAX:.2f}]   ({d['n_v_alta']} trechos acima)")
    print(f"  Perda unitaria maxima ...: {d['j_max'].max():.2f} m/km"
          f"   ({d['n_j_alta']} trechos acima de {PERDA_CARGA_MAX:.0f} m/km)")
    if PERIODO_ESTENDIDO:
        print(f"  Hora critica ............: {d['hora_critica']:.1f} h")
    dns = [DN_MM[i] for i in indices]
    print("  Distribuicao de DN ......: " + ", ".join(
        f"DN{dn}: {dns.count(dn)}" for dn in DN_MM if dns.count(dn)))
    print()
    return d


def teste_viabilidade():
    """
    [CORRECAO 15] Teste de viabilidade ANTES de otimizar.

    Roda a rede inteira no MAIOR diametro da faixa. Essa e a solucao de menor
    perda de carga possivel: se nem ela atende a pressao minima, o problema e
    insoluvel e nenhum ajuste do GA vai consertar. Sem este teste, o programa
    rodava 150 geracoes e devolvia calado uma rede com pressao negativa.

    Tambem imprime a carga disponivel por no (carga da fonte - cota), que
    mostra qual e o no critico e quanta perda de carga o projeto pode gastar
    ate ele.
    """
    print("=" * 74)
    print("TESTE DE VIABILIDADE")
    print("=" * 74)

    def carga(nome):
        no = wn.get_node(nome)
        if nome in wn.reservoir_name_list:
            return no.base_head
        return no.elevation + no.init_level   # tanque: nivel inicial

    fontes = wn.reservoir_name_list + wn.tank_name_list
    if fontes and not wn.pump_name_list:
        carga_fonte = max(carga(f) for f in fontes)
        print(f"  Carga na fonte ......: {carga_fonte:.2f} m "
              f"({', '.join(fontes)})")
        print()
        print("  No       cota (m)   carga disponivel (m)   folga sobre "
              f"{PRESSAO_MIN:.0f} mca")
        print("  " + "-" * 66)
        criticos = sorted(
            ((wn.get_node(j).elevation, j) for j in JUNCOES), reverse=True)
        for cota, j in criticos[:5]:
            disp = carga_fonte - cota
            print(f"  {j:<8} {cota:9.2f} {disp:20.2f} {disp - PRESSAO_MIN:20.2f}")
        if len(criticos) > 5:
            print(f"  ... ({len(criticos) - 5} nos com mais folga)")
        cota_max, no_max = criticos[0]
        folga = carga_fonte - cota_max - PRESSAO_MIN
        print()
        print(f"  No mais critico .....: {no_max} (cota {cota_max:.2f} m)")
        print(f"  Orcamento TOTAL de perda de carga ate ele: {folga:.2f} m")
        if folga < 0:
            print("  >>> A fonte nao tem carga suficiente nem em regime "
                  "estatico. Rever cota do")
            print("  >>> reservatorio ou prever booster -- diametro nao "
                  "resolve.")
        elif folga < 1.0:
            print("  >>> ATENCAO: orcamento de perda de carga muito apertado. "
                  "A rede vai exigir")
            print("  >>> diametros grandes por carga disponivel, nao por "
                  "velocidade ou custo.")
    elif wn.pump_name_list:
        print("  Rede com bombeamento: a carga disponivel depende da curva "
              "das bombas,")
        print("  entao a tabela de cotas nao se aplica. Vale o teste "
              "hidraulico abaixo.")
    print()

    d = detalhar([N_OPCOES - 1] * NUM_TUBOS)
    if not d['ok']:
        print(f"  >>> A simulacao no maior DN FALHOU: {d['erro']}")
        print("  >>> Nao da para seguir: revise a rede no EPANET "
              "(nos desconectados, dados faltando).")
        print()
        return False

    print(f"  Rede inteira em DN{DN_MM[-1]} (perda de carga minima possivel):")
    print(f"    pressao minima ....: {d['p_min'].min():.2f} mca em "
          f"{JUNCOES[int(d['p_min'].argmin())]}")
    print(f"    nos abaixo do alvo : {d['n_p_baixa']}")

    # [CORRECAO 20] Isto era um ABORT: o programa encerrava sem rodar o GA.
    # Errado por dois motivos. Primeiro, com o alvo por no [CORRECAO 19] o
    # caso comum (no no limite topografico) deixa de ser violacao. Segundo,
    # quando sobra violacao de verdade, a rede de menor violacao continua
    # sendo um resultado util -- e ela que mostra o quanto falta e onde,
    # embasando a decisao de booster, setorizacao ou revisao de cota.
    # Agora o programa AVISA e roda assim mesmo.
    if d['n_p_baixa'] > 0:
        print()
        print("  >>> AVISO: nem no maior diametro todos os nos alcancam o "
              "alvo de pressao.")
        print("  >>> A otimizacao vai rodar mesmo assim e devolver a rede de "
              "MENOR VIOLACAO,")
        print("  >>> mas o resultado NAO atende integralmente. Para fechar o "
              "atendimento:")
        print("  >>>   1) elevar a cota do reservatorio / prever booster;")
        print("  >>>   2) setorizar (zona alta separada);")
        print("  >>>   3) revisar as demandas nodais e as cotas dos nos "
              "criticos;")
        print("  >>>   4) rever PRESSAO_MIN / PERDA_ADMITIDA_EXCECAO.")
    else:
        print("    -> existe pelo menos uma solucao viavel. Otimizacao faz "
              "sentido.")

    if d['n_v_alta'] > 0:
        print(f"    ATENCAO: {d['n_v_alta']} trecho(s) ainda acima de "
              f"{VELOCIDADE_MAX} m/s no maior DN.")
    print()
    return True


# =========================================================================
# EXECUCAO
# =========================================================================

def main():
    # so encerra se a propria simulacao falhar; violacao de pressao nao
    # impede a otimizacao [CORRECAO 20]
    if not teste_viabilidade():
        return

    print(f"  Faixa de busca ......: {DN_MM}")
    print(f"  Custo de referencia .: R$ {CUSTO_REF:,.2f} "
          f"(rede toda em DN{DN_MM[0]})")
    print()

    print("=" * 74)
    print("SOLUCAO DE REFERENCIA (tudo no menor DN da faixa)")
    print("=" * 74)
    relatorio([0] * NUM_TUBOS, f"Rede inteira em DN{DN_MM[0]}")

    # ---- laco evolutivo -------------------------------------------------
    print("=" * 74)
    print("OTIMIZACAO")
    print("=" * 74)

    pop = populacao_inicial(TAM_POPULACAO)
    for ind, fit in zip(pop, map(toolbox.evaluate, pop)):
        ind.fitness.values = fit

    # [CORRECAO 11] Elitismo. main3.py fazia
    #     pop = toolbox.select(offspring, k=len(pop))
    # descartando os pais: o melhor individuo podia ser perdido a qualquer
    # geracao. E o 'melhor' impresso no fim era o melhor da ULTIMA geracao,
    # nao o melhor de toda a execucao.
    hof = tools.HallOfFame(1)
    hof.update(pop)

    melhor_fit = hof[0].fitness.values[0]
    sem_melhora = 0

    for gen in range(1, NUM_GERACOES + 1):
        filhos = list(map(toolbox.clone, toolbox.select(pop, len(pop))))

        for a, b in zip(filhos[::2], filhos[1::2]):
            if random.random() < PROB_CRUZAMENTO:
                toolbox.mate(a, b)
                del a.fitness.values, b.fitness.values
        for ind in filhos:
            if random.random() < PROB_MUTACAO:
                toolbox.mutate(ind)
                del ind.fitness.values

        # [CORRECAO 12] so reavalia quem mudou (main3.py reavaliava todos)
        invalidos = [ind for ind in filhos if not ind.fitness.valid]
        for ind, fit in zip(invalidos, map(toolbox.evaluate, invalidos)):
            ind.fitness.values = fit

        # elitismo mu+lambda: pais e filhos disputam juntos
        pop = tools.selBest(pop + filhos, len(pop))
        hof.update(pop)

        atual = hof[0].fitness.values[0]
        if atual < melhor_fit - 1e-9:
            melhor_fit = atual
            sem_melhora = 0
        else:
            sem_melhora += 1

        if gen % 10 == 0 or gen == 1:
            print(f"  Geracao {gen:4d} | melhor = R$ {atual:>15,.2f} "
                  f"| avaliacoes unicas = {len(_cache)}")

        if sem_melhora >= PARADA_SEM_MELHORA:
            print(f"  Parada antecipada: {PARADA_SEM_MELHORA} geracoes sem "
                  f"melhora (geracao {gen}).")
            break

    melhor = hof[0]

    # ---- resultado ------------------------------------------------------
    print()
    print("=" * 74)
    print("MELHOR SOLUCAO ENCONTRADA")
    print("=" * 74)
    d = relatorio(melhor, "Solucao otimizada")

    if not d['viavel']:
        print("  >>> ATENCAO: a melhor solucao encontrada ainda viola alguma")
        print("  >>> restricao. Verifique o teste de viabilidade acima e/ou")
        print("  >>> aumente NUM_GERACOES.")
        print()

    print("DIAMETROS POR TRECHO")
    print("-" * 74)
    for i, nome in enumerate(TUBOS):
        print(f"  {nome:<14} L={COMPRIMENTOS[i]:8.2f} m  ->  "
              f"DN{DN_MM[melhor[i]]:<5} "
              f"v={d['v_max'][i]:5.3f} m/s  J={d['j_max'][i]:7.2f} m/km")
    for nome in TRECHOS_FIXOS:
        print(f"  {nome:<14} (fixo, DN{DIAM_FIXOS[nome] * 1000:.0f})")

    print()
    print("PRESSOES NODAIS" + (" (minima ao longo do periodo)"
                               if PERIODO_ESTENDIDO else ""))
    print("-" * 74)
    for j, pmin, pmax, alvo in zip(JUNCOES, d['p_min'], d['p_max'],
                                   ALVO_PRESSAO):
        marca = ""
        if pmin < alvo - TOLERANCIA_PRESSAO:
            marca = f"  << ABAIXO DO ALVO ({alvo:.2f} mca)"
        elif pmax > PRESSAO_MAX + TOLERANCIA_PRESSAO:
            marca = "  << ACIMA DO MAXIMO"
        elif alvo < PRESSAO_MIN - 1e-9:
            marca = f"  (limite topografico, alvo {alvo:.2f} mca)"
        if PERIODO_ESTENDIDO:
            print(f"  {j:<12} min {pmin:7.2f} / max {pmax:7.2f} mca{marca}")
        else:
            print(f"  {j:<12} {pmin:7.2f} mca{marca}")

    # ---- exporta --------------------------------------------------------
    for i, nome in enumerate(TUBOS):
        wn.get_link(nome).diameter = DIAM_M[melhor[i]]
    for nome, dm in DIAM_FIXOS.items():
        wn.get_link(nome).diameter = dm
    wntr.network.write_inpfile(wn, ARQUIVO_SAIDA)

    print()
    print(f"Arquivo '{ARQUIVO_SAIDA}' exportado com sucesso.")
    print(f"Custo total da rede otimizada: R$ {d['custo']:,.2f}")


if __name__ == "__main__":
    main()
