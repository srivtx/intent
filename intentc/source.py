"""Turning program text into sentences of tokens, each remembering where it came from."""
import re
from dataclasses import dataclass

TOKEN_RE = re.compile(r'''
   (?P<str>"[^"]*"|“[^”]*”)
 | (?P<num>(?<![\w.)])-?\d+(?:\.\d+)?)
 | (?P<word>[A-Za-z_][A-Za-z0-9_]*(?:['’](?:t|d|ll|re|ve|m)\b)?)
 | (?P<poss>['’]s\b|['’])
 | (?P<sym>>=|<=|!=|==|[*+\-/=<>:,();.?!×÷&])
 | (?P<ws>\s+)
 | (?P<bad>.)
''', re.X)

TERMINATORS = {'.', '?', '!', ';'}
BULLETS = {'-', '*'}


@dataclass
class Tok:
    kind: str      # word | num | str | sym | bad
    text: str      # lower-cased for words, contents for strings
    raw: str
    line: int      # 1-based
    start: int
    end: int


def tokenize(text, line):
    out = []
    for m in TOKEN_RE.finditer(text):
        kind = m.lastgroup
        if kind in ('ws', 'poss'):
            continue
        raw = m.group()
        val = raw
        if kind == 'word':
            val = raw.lower().replace('’', "'")
        elif kind == 'str':
            val = raw[1:-1]
        out.append(Tok(kind, val, raw, line, m.start(), m.end()))
    return out


def strip_comment(line):
    in_str = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_str = not in_str
        elif not in_str and (ch == '#' or line.startswith('//', i)):
            return line[:i]
    return line


def indent_of(line):
    return len(line) - len(line.lstrip())


def split_sentences(toks):
    out, cur = [], []
    for t in toks:
        if t.kind == 'sym' and t.text in TERMINATORS:
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        out.append(cur)
    return out


def drop_bullet(toks):
    if toks and toks[0].kind == 'sym' and toks[0].text in BULLETS:
        return toks[1:]
    return toks


class Source:
    def __init__(self, text, filename='<intent>'):
        self.filename = filename
        self.lines = text.split('\n')

    def line_text(self, n):
        return self.lines[n - 1] if 1 <= n <= len(self.lines) else ''

    def items(self):
        """Yield ('sent', toks) or ('block', header_toks, [item_toks, ...]).

        A block is a line ending in ':' followed by indented or bulleted lines.
        """
        lines = [strip_comment(l) for l in self.lines]
        n = len(lines)
        i = 0
        pending = []
        while i < n:
            raw = lines[i]
            if not raw.strip():
                for s in split_sentences(pending):
                    yield ('sent', s)
                pending = []
                i += 1
                continue
            toks = drop_bullet(tokenize(raw, i + 1))
            if raw.rstrip().endswith(':') and not pending:
                ind = indent_of(raw)
                items = []
                j = i + 1
                while j < n and lines[j].strip() and (
                        indent_of(lines[j]) > ind or lines[j].lstrip()[0] in '-*•'):
                    items.append(drop_bullet(tokenize(lines[j], j + 1)))
                    j += 1
                if items:
                    yield ('block', toks[:-1], items)
                    i = j
                    continue
            pending += toks
            i += 1
            if raw.rstrip().endswith(','):
                continue            # sentence continues on the next line
            for s in split_sentences(pending):
                yield ('sent', s)
            pending = []
        for s in split_sentences(pending):
            yield ('sent', s)
