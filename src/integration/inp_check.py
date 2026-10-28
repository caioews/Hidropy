"""Verificação e preparo de arquivos EPANET .inp antes da importação.

1. Codificação: aceita UTF-8 (com ou sem BOM), UTF-16 e ANSI do Windows (Windows-1252,
   como o EPANET costuma gravar). O arquivo é convertido para UTF-8 automaticamente.
2. Arquivo inválido: detecta arquivo binário/corrompido (por exemplo, o projeto binário do
   EPANET salvo com extensão .inp) e texto sem as seções de uma rede EPANET.
3. Problemas corrigíveis: palavras-chave traduzidas para o português (ex.: "Metros" em vez
   de "METERS") e números com vírgula decimal. São listados para o usuário autorizar a
   correção.

O arquivo original nunca é alterado: a importação usa uma cópia temporária em UTF-8.
"""

from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field

KNOWN_SECTIONS = {
    'TITLE', 'JUNCTIONS', 'RESERVOIRS', 'TANKS', 'PIPES', 'PUMPS', 'VALVES', 'EMITTERS',
    'CURVES', 'PATTERNS', 'ENERGY', 'STATUS', 'CONTROLS', 'RULES', 'DEMANDS', 'QUALITY',
    'REACTIONS', 'SOURCES', 'MIXING', 'OPTIONS', 'TIMES', 'REPORT', 'COORDINATES',
    'VERTICES', 'LABELS', 'BACKDROP', 'TAGS', 'END', 'LEAKAGE',
}
NETWORK_SECTIONS = {'JUNCTIONS', 'RESERVOIRS', 'TANKS', 'PIPES'}

ENCODING_NAMES = {'utf-8': 'UTF-8', 'utf-8-sig': 'UTF-8 (com BOM)', 'utf-16': 'UTF-16',
                  'cp1252': 'ANSI (Windows-1252)', 'latin-1': 'ISO-8859-1'}


def _norm(s: str) -> str:
    """Minúsculas e sem acentos (para reconhecer 'Pés', 'pes', 'PÉS'...)."""
    s = unicodedata.normalize('NFKD', s.strip().lower())
    return ''.join(c for c in s if not unicodedata.combining(c))


# valores traduzidos -> palavra-chave do EPANET, por (seção, chave)
BACKDROP_UNITS = {'metros': 'METERS', 'metro': 'METERS', 'm': 'METERS', 'pes': 'FEET',
                  'pe': 'FEET', 'graus': 'DEGREES', 'grau': 'DEGREES', 'nenhum': 'NONE',
                  'nenhuma': 'NONE', 'nada': 'NONE'}
YES_NO = {'sim': 'YES', 'nao': 'NO'}
NONE_WORDS = {'nenhum': 'NONE', 'nenhuma': 'NONE'}
UNBALANCED = {'parar': 'STOP', 'continuar': 'CONTINUE'}
STATUS_WORDS = {'aberto': 'OPEN', 'aberta': 'OPEN', 'fechado': 'CLOSED', 'fechada': 'CLOSED',
                'ativo': 'ACTIVE', 'ativa': 'ACTIVE'}
STATISTIC = {'nenhum': 'NONE', 'nenhuma': 'NONE', 'media': 'AVERAGED', 'minimo': 'MINIMUM',
             'maximo': 'MAXIMUM', 'intervalo': 'RANGE'}
# colunas numéricas (a partir da 2ª) por seção, para corrigir vírgula decimal
NUMERIC_SECTIONS = {'JUNCTIONS', 'RESERVOIRS', 'TANKS', 'PIPES', 'VALVES', 'COORDINATES',
                    'VERTICES', 'CURVES', 'PATTERNS', 'DEMANDS', 'EMITTERS', 'QUALITY'}
COMMA_NUMBER = re.compile(r'^-?\d+,\d+$')


class InpError(Exception):
    """Arquivo que não pode ser importado (corrompido ou não é um .inp)."""


@dataclass
class InpIssue:
    line: int                 # número da linha (1 = primeira)
    section: str
    message: str
    original: str
    fixed: str


@dataclass
class InpCheck:
    path: str
    encoding: str
    text: str                 # conteúdo decodificado (sem correções)
    fixed_text: str           # conteúdo com as correções propostas
    issues: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def encoding_label(self) -> str:
        return ENCODING_NAMES.get(self.encoding, self.encoding)

    @property
    def converted(self) -> bool:
        return self.encoding not in ('utf-8',)

    def summary(self, max_items: int = 15) -> str:
        lines = [f'Linha {i.line} [{i.section}]: {i.message}' for i in self.issues[:max_items]]
        if len(self.issues) > max_items:
            lines.append(f'… e mais {len(self.issues) - max_items} ocorrência(s).')
        return '\n'.join(lines)


# ----------------------------------------------------------------------------- leitura
def _looks_binary(raw: bytes) -> str | None:
    head = raw[:64]
    if b'<EPANET2>' in head or b'<EPANET>' in head:
        return ('O arquivo é um projeto binário do EPANET (formato .net) com extensão .inp, '
                'ou está corrompido. No EPANET, abra a rede e use Arquivo → Exportar → Rede '
                'para gerar um .inp em texto.')
    if not raw.strip():
        return 'O arquivo está vazio.'
    sample = raw[:20000]
    if sample.startswith((b'\xff\xfe', b'\xfe\xff')):       # UTF-16 com BOM: é texto
        return None
    if b'\x00' in sample:
        return 'O arquivo contém dados binários e está corrompido.'
    ctrl = sum(1 for b in sample if b < 32 and b not in (9, 10, 12, 13))
    if ctrl > max(3, len(sample) * 0.005):
        return 'O arquivo contém caracteres inválidos e está corrompido.'
    return None


def decode(raw: bytes) -> tuple[str, str]:
    if raw.startswith(b'\xef\xbb\xbf'):
        return raw[3:].decode('utf-8'), 'utf-8-sig'
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16'), 'utf-16'
    try:
        return raw.decode('utf-8'), 'utf-8'
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode('cp1252'), 'cp1252'
    except UnicodeDecodeError:
        return raw.decode('latin-1'), 'latin-1'


# ----------------------------------------------------------------------------- correções
def _split(line: str):
    """(dados, comentário) — o comentário começa em ';'."""
    i = line.find(';')
    return (line, '') if i < 0 else (line[:i], line[i:])


def _replace_token(data: str, idx: int, new: str) -> str:
    """Troca o token de posição idx preservando os espaços/tabulações originais."""
    parts = re.split(r'(\s+)', data)
    k = -1
    for j, p in enumerate(parts):
        if p and not p.isspace():
            k += 1
            if k == idx:
                parts[j] = new
                break
    return ''.join(parts)


def _value_fix(section, tokens):
    """[(índice do token, valor corrigido, descrição)] para palavras traduzidas."""
    out = []
    if not tokens:
        return out
    key = tokens[0].upper()
    last = tokens[-1]
    if section == 'BACKDROP' and key == 'UNITS' and len(tokens) >= 2:
        v = _norm(tokens[1])
        if tokens[1].upper() not in ('FEET', 'METERS', 'DEGREES', 'NONE'):
            new = BACKDROP_UNITS.get(v, 'NONE')
            out.append((1, new, f"unidade do plano de fundo '{tokens[1]}' → {new}"))
    elif section == 'REPORT' and len(tokens) == 2 and _norm(last) in YES_NO:
        out.append((1, YES_NO[_norm(last)], f"'{last}' → {YES_NO[_norm(last)]}"))
    elif section == 'TIMES' and key == 'STATISTIC' and len(tokens) >= 2 \
            and _norm(tokens[1]) in STATISTIC:
        out.append((1, STATISTIC[_norm(tokens[1])],
                     f"estatística '{tokens[1]}' → {STATISTIC[_norm(tokens[1])]}"))
    elif section == 'OPTIONS' and len(tokens) >= 2:
        if key == 'UNBALANCED' and _norm(tokens[1]) in UNBALANCED:
            out.append((1, UNBALANCED[_norm(tokens[1])],
                        f"'{tokens[1]}' → {UNBALANCED[_norm(tokens[1])]}"))
        if key == 'QUALITY' and _norm(tokens[1]) in NONE_WORDS:
            out.append((1, 'NONE', f"qualidade '{tokens[1]}' → NONE"))
    elif section == 'PIPES' and len(tokens) >= 8 and _norm(tokens[7]) in STATUS_WORDS:
        out.append((7, STATUS_WORDS[_norm(tokens[7])],
                    f"estado '{tokens[7]}' → {STATUS_WORDS[_norm(tokens[7])]}"))
    elif section == 'STATUS' and len(tokens) == 2 and _norm(last) in STATUS_WORDS:
        out.append((1, STATUS_WORDS[_norm(last)],
                    f"estado '{last}' → {STATUS_WORDS[_norm(last)]}"))
    if section in NUMERIC_SECTIONS:
        for k, t in enumerate(tokens[1:], 1):
            if COMMA_NUMBER.match(t):
                out.append((k, t.replace(',', '.'), f"número com vírgula '{t}' → "
                                                    f"{t.replace(',', '.')}"))
    return out


def check_text(text: str, path: str = '', encoding: str = 'utf-8') -> InpCheck:
    lines = text.splitlines()
    sections_found = set()
    unknown = []
    fixed_lines = []
    issues = []
    section = ''
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith('['):
            name = s[1:s.find(']')].strip().upper() if ']' in s else s[1:].upper()
            section = name
            sections_found.add(name)
            if name not in KNOWN_SECTIONS:
                unknown.append(f'[{name}] (linha {n})')
            fixed_lines.append(line)
            continue
        if section == 'TITLE' or not s or s.startswith(';'):
            fixed_lines.append(line)
            continue
        data, comment = _split(line)
        tokens = data.split()
        new_data = data
        for idx, value, msg in _value_fix(section, tokens):
            new_data = _replace_token(new_data, idx, value)
            issues.append(InpIssue(n, section, msg, line.strip(), (new_data + comment).strip()))
        fixed_lines.append(new_data + comment)
    if not sections_found & NETWORK_SECTIONS:
        raise InpError('O arquivo não contém as seções de uma rede EPANET ([JUNCTIONS], '
                       '[PIPES]...). Ele está corrompido ou não é um arquivo .inp.')
    chk = InpCheck(path=path, encoding=encoding, text=text,
                   fixed_text='\n'.join(fixed_lines) + '\n', issues=issues)
    if 'END' not in sections_found:
        chk.warnings.append('O arquivo não termina com [END]: pode estar incompleto.')
    if unknown:
        chk.warnings.append('Seções desconhecidas (serão ignoradas pelo EPANET): ' +
                            ', '.join(unknown[:5]))
    return chk


def check_inp(path: str) -> InpCheck:
    """Lê e verifica o .inp. Lança InpError se o arquivo for inutilizável."""
    try:
        with open(path, 'rb') as f:
            raw = f.read()
    except OSError as e:
        raise InpError(f'Não foi possível ler o arquivo: {e}') from e
    msg = _looks_binary(raw)
    if msg:
        raise InpError(msg)
    text, enc = decode(raw)
    return check_text(text, os.path.abspath(path), enc)


def prepare(check: InpCheck, apply_fixes: bool) -> str:
    """Grava uma cópia temporária em UTF-8 (com ou sem as correções) e devolve o caminho."""
    d = tempfile.mkdtemp(prefix='hidropy_inp_')
    name = os.path.splitext(os.path.basename(check.path or 'rede.inp'))[0] + '.inp'
    dest = os.path.join(d, name)
    with open(dest, 'w', encoding='utf-8', newline='\n') as f:
        f.write(check.fixed_text if apply_fixes else check.text)
    return dest
