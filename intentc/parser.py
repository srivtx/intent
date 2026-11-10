"""Fluid sentences -> Intent IR.

The pipeline for one sentence:
  1. normalise: map every word/phrase to a concept, a declared name, filler, or UNKNOWN
  2. refuse to continue if anything is UNKNOWN (outside a declaration, where new words are names)
  3. work out which collection the sentence is about, then forget the words that said so
  4. resolve pronouns, pull out ordering and condition clauses
  5. read what is left as one action; every remaining token must be accounted for
Any step that cannot proceed raises a Problem pointing at the exact words.
"""
import copy
import difflib
from dataclasses import dataclass, replace

from .ir import Collection, Diag, Field, Program, Task, binop, canon, negate
from .lexicon import (CONVENTION, MAX_PHRASE, PHRASES, SYMS, TYPE_WORDS, UNSUPPORTED_TYPES, all_known_words,
                      singular)
from .source import Source, Tok, split_sentences

ARTICLES = {'a', 'an', 'the', 'their', 'its', 'some', 'one'}
LEADING_TYPES = {'numeric': 'int', 'integer': 'int', 'text': 'text', 'string': 'text', 'textual': 'text'}
SCALE_NAME = {2: 'double', 3: 'triple', 4: 'quadruple'}


class Problem(Exception):
    def __init__(self, diag, unk=None):
        self.diag = diag
        self.unk = unk              # the unknown word token, when that is what went wrong


def edit_distance(a, b):
    """Damerau-Levenshtein distance: a swapped pair of neighbouring letters counts as one slip."""
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


@dataclass
class CT:
    kind: str
    val: object
    toks: list

    @property
    def text(self):
        return ' '.join(t.raw for t in self.toks)


def flat(where):
    if isinstance(where, (CT, Tok)):
        where = [where]
    out = []
    for w in where:
        out += w.toks if isinstance(w, CT) else [w]
    return out


def lstrip(toks):
    while toks and toks[0].kind in ('COMMA', 'AND', 'THEN'):
        toks = toks[1:]
    return toks


def rstrip(toks):
    while toks and toks[-1].kind in ('COMMA', 'AND', 'THEN', 'FROM'):
        toks = toks[:-1]
    return toks


def index_of(toks, kind, val=None, start=0):
    for i in range(start, len(toks)):
        if toks[i].kind == kind and (val is None or toks[i].val == val):
            return i
    return None


class Parser:
    def __init__(self, text, filename='<intent>'):
        self.src = Source(text, filename)
        self.prog = Program()
        self.diags = []
        self.cur = []
        self.readings = []          # (line, sentence text, what it was understood as)

    # ------------------------------------------------------------------ diagnostics
    def p(self, level, where, msg, label='', hint=''):
        toks = flat(where) or self.cur
        first = toks[0]
        last = [t for t in toks if t.line == first.line][-1]
        return Problem(Diag(level, msg, first.line, first.start, last.end, label, hint))

    def note(self, where, msg, hint=''):
        self.diags.append(self.p('note', where, msg, hint=hint).diag)

    def could_be(self, coll, numeric_only=False):
        fs = [f.name for f in coll.fields.values()
              if not numeric_only or (f.type or CONVENTION.get(f.name)) != 'text']
        return 'could be: ' + ', '.join(fs) if fs else f'{coll.label} has no properties yet'

    def unknown_word(self, c):
        word = c.toks[0].text
        pool = list(self.prog.field_names()) + list(self.prog.collections) + all_known_words()
        close = [w for w in difflib.get_close_matches(word, pool, n=3, cutoff=0.8) if w != word]
        hint = (f'did you mean "{close[0]}"? ' if close else '') + \
            "I never drop a word I don't understand, because it might change the meaning."
        e = self.p('error', c, f'I don\'t know the word "{c.text}"',
                   'not a concept I know, and not a name this program declared', hint)
        e.unk = c.toks[0]
        return e

    # ------------------------------------------------------------------ spelling
    def vocabulary(self):
        names = set(self.prog.collections)
        for f in self.prog.field_names():
            names.update(f.split('_'))
        words = set(all_known_words()) | names | {n + 's' for n in names}
        return {w for w in words if w.isalpha()}

    def spellings(self, word):
        """Known words a slip of the fingers away from `word`. Short words are never corrected."""
        if len(word) < 3:
            return []
        if len(word) == 3:          # only two swapped letters: "teh" -> "the"
            return sorted(w for w in self.vocabulary() if sorted(w) == sorted(word) and edit_distance(word, w) == 1)
        limit = 1 if len(word) < 8 else 2
        found = [(edit_distance(word, w), w) for w in self.vocabulary()
                 if len(w) >= 3 and abs(len(w) - len(word)) <= limit]
        return [w for d, w in sorted(found) if d <= limit]

    def snapshot(self):
        return copy.deepcopy(self.prog), list(self.diags), list(self.readings)

    def restore(self, snap):
        self.prog, self.diags, self.readings = copy.deepcopy(snap[0]), list(snap[1]), list(snap[2])

    def respell(self, toks, problem, depth=0):
        """Every way of correcting the unknown word(s) that makes the whole sentence readable.

        Returns [(tokens, reading, [(original token, correction), ...])].
        """
        out = []
        snap = self.snapshot()
        for cand in self.spellings(problem.unk.text):
            trial = [replace(t, text=cand) if t is problem.unk else t for t in toks]
            fix = (problem.unk, cand)
            self.cur = trial
            try:
                reading = self._sentence(trial)
                if reading:
                    out.append((trial, reading, [fix]))
            except Problem as e:
                if e.unk is not None and depth < 4:
                    self.restore(snap)
                    out += [(t, r, [fix] + fx) for t, r, fx in self.respell(trial, e, depth + 1)]
            finally:
                self.restore(snap)
        self.cur = toks
        return out

    def sent_text(self, toks):
        by_line = {}
        for t in toks:
            lo, hi = by_line.get(t.line, (t.start, t.end))
            by_line[t.line] = (min(lo, t.start), max(hi, t.end))
        return ' '.join(self.src.line_text(l)[a:b] for l, (a, b) in sorted(by_line.items()))

    # ------------------------------------------------------------------ driver
    def parse(self):
        for item in self.src.items():
            if item[0] == 'sent':
                self.sentence(item[1])
                continue
            _, header, items = item
            try:
                kinds = [c.kind for c in self.normalize(header)]
            except Problem:
                kinds = ['?']
            if 'HAS' in kinds:
                toks = list(header)
                for it in items:
                    it = [t for t in it if not (t.kind == 'sym' and t.text in '.;')]
                    if it:
                        last = toks[-1]
                        toks.append(Tok('sym', ',', ',', last.line, last.end, last.end))
                        toks += it
                self.sentence(toks)
            elif all(k == 'FILLER' for k in kinds):
                for it in items:
                    for s in split_sentences(it):
                        self.sentence(s)
            else:
                for it in items:
                    for s in split_sentences(it):
                        last = header[-1]
                        colon = Tok('sym', ':', ':', last.line, last.end, last.end + 1)
                        self.sentence(list(header) + [colon] + s)
        self.finish()
        return self.prog

    def sentence(self, toks):
        if not toks:
            return
        self.cur = toks
        snap = self.snapshot()
        try:
            reading = self._sentence(toks)
        except Problem as e:
            self.restore(snap)
            if e.unk is None:
                self.diags.append(e.diag)
                return
            ways = self.respell(toks, e)
            readings = sorted({r for _, r, _ in ways})
            if not ways:
                self.diags.append(e.diag)
                return
            if len(readings) > 1:
                d = e.diag
                self.diags.append(Diag('question', f'I don\'t know the word "{e.unk.raw}", and it could be a '
                                       f'slip for more than one word', d.line, d.start, d.end,
                                       'could be: ' + ', '.join(sorted({fx[0][1] for _, _, fx in ways})),
                                       'the sentence reads differently for each: ' + ' / '.join(readings)))
                return
            toks, _, fixes = min(ways, key=lambda w: sum(edit_distance(t.text, c) for t, c in w[2]))
            self.cur = toks
            reading = self._sentence(toks)
            for tok, word in fixes:
                self.note(tok, f'read "{tok.raw}" as "{word}"',
                          'the only known word this close that makes the sentence make sense')
        if reading:
            self.readings.append((toks[0].line, self.sent_text(toks), reading))

    def _sentence(self, toks):
        cts = self.normalize(toks)
        content = [c for c in cts if c.kind != 'FILLER']
        kinds = {c.kind for c in content}
        colls = [c for c in content if c.kind == 'COLL']
        unk = [c for c in content if c.kind == 'UNK']
        if kinds & {'ISCOLL', 'COLLWORD'} and not colls and (unk or ('ISCOLL' in kinds and 'GEN' in kinds)):
            return self.decl_collection(content)
        if 'NOTWO' in kinds:
            return self.decl_unique(content)
        h = index_of(content, 'HAS')
        if h is not None and h > 0 and all(c.kind in ('QUANT', 'COLL', 'GEN') for c in content[:h]):
            return self.decl_fields(toks, content, h)
        if 'UNIQUE' in kinds:
            return self.decl_unique(content)
        if kinds & {'INSORDER', 'NOORDER'}:
            return self.decl_order(content)
        if 'DUP' in kinds and 'POLICY' in kinds:
            return self.decl_dup(content)
        return self.task(content)

    # ------------------------------------------------------------------ normalisation
    def normalize(self, toks):
        out = []
        i, n = 0, len(toks)
        fields = self.prog.field_names()
        while i < n:
            t = toks[i]
            if t.kind == 'num':
                if '.' in t.text:
                    raise self.p('error', t, 'decimal numbers are not supported yet',
                                 'whole numbers only in this version')
                out.append(CT('NUM', int(t.text), [t]))
                i += 1
                continue
            if t.kind == 'str':
                out.append(CT('STR', t.text, [t]))
                i += 1
                continue
            if t.kind == 'sym':
                if t.text not in SYMS:
                    raise self.p('error', t, f'I don\'t know what "{t.raw}" means here')
                k, v = SYMS[t.text]
                out.append(CT(k, v, [t]))
                i += 1
                continue
            if t.kind == 'bad':
                raise self.p('error', t, f'I can\'t read the character "{t.raw}"',
                             hint='put literal text in double quotes')
            pl, pv = 0, None
            for L in range(min(MAX_PHRASE, n - i), 0, -1):
                seg = toks[i:i + L]
                if all(x.kind == 'word' for x in seg) and tuple(x.text for x in seg) in PHRASES:
                    pl, pv = L, PHRASES[tuple(x.text for x in seg)]
                    break
            el, ev = 0, None
            for L in range(min(3, n - i), 0, -1):
                seg = toks[i:i + L]
                if all(x.kind == 'word' for x in seg):
                    key = '_'.join([x.text for x in seg[:-1]] + [singular(seg[-1].text)])
                    if key in fields:
                        el, ev = L, ('FIELD', key)
                        break
            if not el and singular(t.text) in self.prog.collections:
                el, ev = 1, ('COLL', singular(t.text))
            if el and el >= pl:
                out.append(CT(ev[0], ev[1], toks[i:i + el]))
                i += el
            elif pl:
                seg = toks[i:i + pl]
                if pv[0][0] == 'GIVEN':
                    if i + pl < n and toks[i + pl].kind == 'word':
                        out.append(CT('PARAM', singular(toks[i + pl].text), toks[i:i + pl + 1]))
                        i += pl + 1
                    else:
                        out.append(CT('GIVENBARE', None, seg))
                        i += pl
                    continue
                for k, v in pv:
                    out.append(CT(k, v, seg))
                i += pl
            else:
                out.append(CT('UNK', t.text, [t]))
                i += 1
        return out

    # ------------------------------------------------------------------ scope
    def scope(self, content, anchor=None):
        names = []
        for c in content:
            if c.kind == 'COLL' and c.val not in names:
                names.append(c.val)
        cs = self.prog.collections
        if len(names) == 1:
            return cs[names[0]]
        if len(names) > 1:
            raise self.p('error', [c for c in content if c.kind == 'COLL'],
                         'one sentence can only be about one collection in this version')
        if len(cs) == 1:
            return next(iter(cs.values()))
        if not cs:
            raise self.p('error', anchor or self.cur, 'there is nothing to work on yet',
                         hint='declare a collection first, e.g. "Customers is a collection."')
        raise self.p('question', anchor or self.cur, 'which collection is this about?',
                     'could be: ' + ', '.join(c.label for c in cs.values()))

    # ------------------------------------------------------------------ declarations
    def decl_collection(self, content):
        extra = [c for c in content if c.kind not in ('ISCOLL', 'COLLWORD', 'IS', 'GEN', 'UNK')]
        if extra:
            raise self.p('error', extra, 'I can only read a collection name in this sentence',
                         hint='describe its properties in their own sentence: "Each customer has ..."')
        names = [c for c in content if c.kind == 'UNK'] or [c for c in content if c.kind == 'GEN'][:1]
        if len(names) != 1:
            raise self.p('error', names, 'a collection needs a one-word name')
        tok = names[0].toks[0]
        name = singular(tok.text)
        self.prog.collections[name] = Collection(name, tok.raw, tok.line)
        return f'collection {name}'

    def decl_fields(self, toks, content, h):
        coll = self.scope(content[:h])
        start = toks.index(content[h].toks[-1]) + 1
        items, cur = [], []
        for t in toks[start:]:
            if (t.kind == 'sym' and t.text in (',', '&')) or (t.kind == 'word' and t.text == 'and'):
                items.append(cur)
                cur = []
            else:
                cur.append(t)
        items.append(cur)
        added = []
        for it in items:
            f = self.field_item(it, coll)
            if f:
                added.append(f)
        if not added:
            raise self.p('error', self.cur, f'I expected the properties of {coll.label} here')
        return f'{coll.name} has ' + ', '.join(
            f'{f.name}' + (f': {f.type}' if f.type else '') + (' (unique)' if f.unique else '') for f in added)

    def field_item(self, item, coll):
        ws = list(item)
        while ws and ((ws[0].kind == 'sym' and ws[0].text == ':') or
                      (ws[0].kind == 'word' and ws[0].text in ARTICLES)):
            ws.pop(0)
        if not ws:
            return None
        whole = list(ws)
        unique = any(w.text in ('unique', 'distinct') for w in ws)
        ws = [w for w in ws if w.text not in ('unique', 'distinct')]
        tw = None

        def sym(s):
            return next((i for i, w in enumerate(ws) if w.kind == 'sym' and w.text == s), None)

        def word(s):
            return next((i for i, w in enumerate(ws) if w.kind == 'word' and w.text == s), None)

        lp, rp = sym('('), sym(')')
        if lp is not None and rp is not None and rp > lp:
            tw, ws = ws[lp + 1:rp], ws[:lp] + ws[rp + 1:]
        elif sym(':') is not None:
            tw, ws = ws[sym(':') + 1:], ws[:sym(':')]
        elif word('as') is not None:
            tw, ws = ws[word('as') + 1:], ws[:word('as')]
        elif word('is') is not None and word('is') > 0 and ws[word('is') - 1].text in ('which', 'that'):
            tw, ws = ws[word('is') + 1:], ws[:word('is') - 1]
        ftype = None
        if tw is None and len(ws) > 1 and ws[0].text in LEADING_TYPES:
            ftype, ws = LEADING_TYPES[ws[0].text], ws[1:]
        if tw is not None:
            words = [w.text for w in tw if w.text not in ARTICLES]
            if ' '.join(words) in ('whole number', 'whole numbers'):
                ftype = 'int'
            elif len(words) == 1 and words[0] in TYPE_WORDS:
                ftype = TYPE_WORDS[words[0]]
            elif any(w in UNSUPPORTED_TYPES for w in words):
                raise self.p('error', tw, f'the type "{" ".join(words)}" is not supported yet',
                             'this version knows text and whole numbers')
            else:
                raise self.p('error', tw or whole, 'I don\'t know this type',
                             'this version knows text and whole numbers')
        ws = [w for w in ws if w.text not in ARTICLES]
        if not ws or any(w.kind != 'word' for w in ws) or len(ws) > 3:
            raise self.p('error', whole, 'I can\'t read this as a property name')
        name = '_'.join([w.text for w in ws[:-1]] + [singular(ws[-1].text)])
        f = coll.fields.get(name)
        if f is None:
            f = coll.fields[name] = Field(name, ftype, line=ws[0].line)
            known = PHRASES.get((name,))
            if known and known[0][0] != 'FILLER':
                self.note(ws, f'"{name}" is also a word I know; in this program it will always mean the property')
        elif ftype:
            if f.type and f.type != ftype:
                raise self.p('error', whole, f'"{name}" was already declared as {f.type}')
            f.type = ftype
        if unique:
            f.unique, f.unique_line = True, ws[0].line
        return f

    def decl_unique(self, content):
        unk = [c for c in content if c.kind == 'UNK']
        if unk:
            raise self.unknown_word(unk[0])
        coll = self.scope(content)
        fs = [c for c in content if c.kind == 'FIELD']
        if not fs:
            raise self.p('question', self.cur, 'which property must be unique?', self.could_be(coll))
        for c in fs:
            if c.val not in coll.fields:
                raise self.p('error', c, f'{coll.label} has no property "{c.val}"')
            coll.fields[c.val].unique = True
            coll.fields[c.val].unique_line = c.toks[0].line
        return f'{coll.name}: ' + ', '.join(c.val for c in fs) + ' unique'

    def decl_order(self, content):
        unk = [c for c in content if c.kind == 'UNK']
        if unk:
            raise self.unknown_word(unk[0])
        coll = self.scope(content)
        coll.ordered = any(c.kind == 'INSORDER' for c in content)
        coll.ordered_line = self.cur[0].line
        return f'{coll.name}: ' + ('insertion order is part of the meaning' if coll.ordered else 'order does not matter')

    def decl_dup(self, content):
        unk = [c for c in content if c.kind == 'UNK']
        if unk:
            raise self.unknown_word(unk[0])
        coll = self.scope(content)
        pol = [c for c in content if c.kind == 'POLICY']
        if len({c.val for c in pol}) > 1:
            raise self.p('question', pol, 'reject or replace? I see both')
        coll.on_dup, coll.on_dup_line = pol[0].val, self.cur[0].line
        return f'{coll.name}: on duplicate, {coll.on_dup}'

    # ------------------------------------------------------------------ expressions
    def parse_expr(self, toks, implicit=None):
        """Parse a value from the front of toks. Returns (expr, tokens consumed)."""
        pos = 0

        def prim(after_op):
            nonlocal pos
            if pos >= len(toks) or toks[pos].kind in ('AND', 'COMMA', 'THEN'):
                if implicit and after_op:
                    return ('field', implicit)
                raise self.p('error', toks[pos - 1] if pos else self.cur[-1], 'a value is missing after this')
            c = toks[pos]
            pos += 1
            if c.kind == 'NUM':
                return ('num', c.val)
            if c.kind == 'STR':
                return ('str', c.val)
            if c.kind == 'FIELD':
                return ('field', c.val)
            if c.kind == 'PARAM':
                return ('param', c.val)
            if c.kind == 'SCALE':
                return binop('mul', prim(False), ('num', c.val))
            if c.kind == 'LP':
                e = add()
                if pos >= len(toks) or toks[pos].kind != 'RP':
                    raise self.p('error', c, 'this bracket is never closed')
                pos += 1
                return e
            raise self.p('error', c, f'I expected a value here, not "{c.text}"')

        def mul():
            nonlocal pos
            a = prim(False)
            while pos < len(toks) and toks[pos].kind == 'OP' and toks[pos].val in ('mul', 'div'):
                op = toks[pos].val
                pos += 1
                a = binop(op, a, prim(True))
            return a

        def add():
            nonlocal pos
            a = mul()
            while pos < len(toks) and toks[pos].kind == 'OP' and toks[pos].val in ('add', 'sub'):
                op = toks[pos].val
                pos += 1
                a = binop(op, a, mul())
            return a

        return add(), pos

    def whole_expr(self, toks, implicit=None):
        e, n = self.parse_expr(toks, implicit)
        if n < len(toks):
            raise self.leftover(toks[n:])
        return e

    def leftover(self, toks):
        return self.p('error', toks, f'I don\'t see how "{" ".join(c.text for c in toks)}" fits in',
                      'I understood the rest of the sentence, but not this part')

    # ------------------------------------------------------------------ conditions
    def parse_cond(self, toks, coll):
        parts, ops, cur = [], [], []
        for c in toks:
            if c.kind in ('AND', 'OR'):
                parts.append(cur)
                ops.append(c)
                cur = []
            else:
                cur.append(c)
        parts.append(cur)
        if len({o.kind for o in ops}) > 1:
            raise self.p('question', ops, 'this condition mixes "and" and "or"; which parts belong together?',
                         'two readings are possible',
                         'use only "and" or only "or" in one condition for now')
        out, prev = None, None
        for i, part in enumerate(parts):
            term, prev = self.parse_term(part, coll, prev, ops[i - 1] if i else None)
            out = term if out is None else (ops[i - 1].kind.lower(), out, term)
        return out

    def parse_term(self, p, coll, prev, anchor):
        while p and p[0].kind in ('COMMA', 'WHERE'):
            p = p[1:]
        p = rstrip(p)
        if not p:
            raise self.p('error', anchor or self.cur[-1], 'a condition is missing here')
        if p[0].kind == 'PARAM' and len(p) == 1 and p[0].val in coll.fields:
            return ('cmp', 'eq', ('field', p[0].val), ('param', p[0].val)), p[0].val
        i, fld = 0, None
        if p[0].kind == 'FIELD':
            fld, i = p[0].val, 1
        op, neg, explicit = None, False, False
        while i < len(p) and p[i].kind in ('IS', 'NOT', 'CMP', 'EQSYM'):
            c = p[i]
            if c.kind == 'NOT':
                neg = not neg
            elif c.kind == 'CMP':
                op, explicit = c.val, True
            elif c.kind == 'EQSYM':
                op = 'eq'
            i += 1
        if fld is None:
            if prev and explicit:
                fld = prev                  # "at least 18 and at most 65": same property, elided
            else:
                raise self.p('question', p, 'which property is this comparing?', self.could_be(coll, explicit),
                             'e.g. "whose age is over 25"')
        rest = p[i:]
        if not rest:
            raise self.p('error', p, 'compared with what?', 'a value is missing')
        if len(rest) == 1 and rest[0].kind == 'GIVENBARE':
            rhs = ('param', fld)
        else:
            rhs = self.whole_expr(rest)
        op = op or 'eq'
        if neg:
            op = negate(('cmp', op, 0, 0))[1]
        return ('cmp', op, ('field', fld), rhs), fld

    # ------------------------------------------------------------------ updates
    def need_field(self, t, i, coll, what):
        if i < len(t) and t[i].kind == 'FIELD':
            return t[i].val
        raise self.p('question', t[:max(i, 1)], f'{what} what?', self.could_be(coll, True),
                     f'e.g. "{t[0].text} the {next(iter(coll.fields), "age")}"')

    def parse_updates(self, toks, coll):
        out = []
        t = lstrip(toks)
        while t:
            f, e, t = self.one_update(t, coll)
            out.append((f, e))
            t = lstrip(t)
        return out

    def one_update(self, t, coll):
        c = t[0]
        if c.kind == 'VERB' and c.val == 'generic':
            t = t[1:]
            if not t:
                raise self.p('question', c, f'{c.text} what, and how?', self.could_be(coll))
            if len(t) >= 3 and t[0].kind == 'FIELD' and t[1].kind == 'BY' and t[2].kind in ('VERB', 'SCALE', 'HALVE'):
                t = t[2:]
            elif len(t) >= 2 and t[0].kind == 'FIELD' and t[1].kind == 'TO':
                e, n = self.parse_expr(t[2:], t[0].val)
                return t[0].val, e, t[2 + n:]
            c = t[0]
        if c.kind == 'SCALE':
            f = self.need_field(t, 1, coll, c.text)
            return f, binop('mul', ('field', f), ('num', c.val)), t[2:]
        if c.kind == 'HALVE':
            f = self.need_field(t, 1, coll, c.text)
            return f, binop('div', ('field', f), ('num', 2)), t[2:]
        if c.kind == 'VERB' and c.val in ('set', 'make'):
            f = self.need_field(t, 1, coll, c.text)
            i = 2
            if i < len(t) and t[i].kind in ('TO', 'BECOMES', 'EQSYM'):
                i += 1
            elif c.val == 'set':
                raise self.p('error', t[:2], f'set {f} to what?', hint=f'e.g. "set {f} to 0"')
            e, n = self.parse_expr(t[i:], f)
            return f, e, t[i + n:]
        if c.kind == 'VERB' and c.val in ('multiply', 'divide', 'increase', 'decrease'):
            if len(t) > 1 and t[1].kind in ('BY', 'TO'):
                raise self.p('question', t[:2], f'{c.text} what?', self.could_be(coll, True))
            f = self.need_field(t, 1, coll, c.text)
            if len(t) > 2 and t[2].kind == 'BY':
                e, n = self.parse_expr(t[3:])
                op = {'multiply': 'mul', 'divide': 'div', 'increase': 'add', 'decrease': 'sub'}[c.val]
                return f, binop(op, ('field', f), e), t[3 + n:]
            if len(t) > 2 and t[2].kind == 'TO' and c.val in ('increase', 'decrease'):
                e, n = self.parse_expr(t[3:], f)
                return f, e, t[3 + n:]
            raise self.p('error', t[:2], f'{c.text} {f} by how much?', hint=f'e.g. "{c.text} {f} by 2"')
        if c.kind == 'VERB' and c.val in ('addv', 'subv'):
            e, n = self.parse_expr(t[1:])
            i = 1 + n
            if i < len(t) and t[i].kind in ('TO', 'FROM'):
                i += 1
            f = self.need_field(t, i, coll, c.text + ' ' + ' '.join(x.text for x in t[1:1 + n]) +
                                (' to' if c.val == 'addv' else ' from'))
            return f, binop('add' if c.val == 'addv' else 'sub', ('field', f), e), t[i + 1:]
        if c.kind == 'FIELD':
            f = c.val
            nxt = t[1] if len(t) > 1 else None
            if nxt and nxt.kind in ('BECOMES', 'EQSYM'):
                e, n = self.parse_expr(t[2:], f)
                return f, e, t[2 + n:]
            if nxt and nxt.kind == 'MODAL':
                return self.modal_tail(f, t, 2, coll)
            if nxt and nxt.kind in ('OP', 'SCALE', 'HALVE'):
                raise self.p('question', t, f'should {f} change, or do you just want to see the result?',
                             'this describes a value, not an action',
                             f'to change it say "{f} becomes {" ".join(x.text for x in t)}"')
            raise self.p('error', t, f'what should happen to {f}?')
        if c.kind in ('MODAL', 'OP'):
            raise self.p('question', t, f'which property of {coll.name} is this about?',
                         self.could_be(coll, True), 'e.g. "each customer\'s age should be multiplied by 2"')
        raise self.leftover(t)

    def modal_tail(self, f, t, i, coll):
        if i >= len(t):
            raise self.p('error', t, f'{f} should be what?')
        c = t[i]
        fe = ('field', f)
        if c.kind == 'OP':
            e, n = self.parse_expr(t[i + 1:])
            return f, binop(c.val, fe, e), t[i + 1 + n:]
        if c.kind == 'SCALE':
            return f, binop('mul', fe, ('num', c.val)), t[i + 1:]
        if c.kind == 'HALVE':
            return f, binop('div', fe, ('num', 2)), t[i + 1:]
        if c.kind == 'VERB' and c.val in ('increase', 'decrease') and i + 1 < len(t) and t[i + 1].kind == 'BY':
            e, n = self.parse_expr(t[i + 2:])
            return f, binop('add' if c.val == 'increase' else 'sub', fe, e), t[i + 2 + n:]
        if c.kind == 'VERB' and c.val == 'set' and i + 1 < len(t) and t[i + 1].kind == 'TO':
            i += 2
        e, n = self.parse_expr(t[i:], f)
        return f, e, t[i + n:]

    # ------------------------------------------------------------------ tasks
    def task(self, content):
        sent = self.cur
        name = None
        ci = index_of(content, 'COLON')
        if ci is not None:
            pre, post = content[:ci], content[ci + 1:]
            if pre and all(c.kind in ('COLL', 'QUANT', 'GEN') or (c.kind == 'VERB' and c.val == 'generic')
                           for c in pre):
                content = [c for c in pre if c.kind in ('COLL', 'GEN')] + post
            else:
                words = [t for t in flat(pre) if not (t.kind == 'sym' and t.text == '-')]
                if not words or len(words) > 6 or any(t.kind not in ('word', 'num') for t in words):
                    raise self.p('error', pre or content[ci], 'I can\'t read what comes before ":" as a name')
                name = '-'.join(t.text for t in words)
                content = post
            if index_of(content, 'COLON') is not None:
                raise self.leftover(content[index_of(content, 'COLON'):])
        content = [c for c in content if c.kind not in ('ISCOLL', 'COLLWORD')]
        if not content:
            raise self.p('error', sent, 'this sentence has nothing I can act on')

        ti = index_of(content, 'TAKE')
        if ti is not None:
            t = self.calc(content, ti, name)
            if t:
                return self.emit(t)
            content = [c for c in content if c.kind != 'TAKE']

        unk = [c for c in content if c.kind == 'UNK']
        if unk:
            raise self.unknown_word(unk[0])
        coll = self.scope(content)
        content = [CT('WHERE', None, c.toks) if c.kind == 'HAS' else c
                   for c in content if c.kind not in ('COLL', 'QUANT', 'GEN')]
        for c in content:
            if c.kind == 'FIELD' and c.val not in coll.fields:
                raise self.p('error', c, f'{coll.label} has no property "{c.val}"', self.could_be(coll))
        content = self.resolve_pronouns(content, coll)
        order, content = self.take_order(content, coll)
        main, cond_t = self.split_where(content)
        main = rstrip(lstrip(main))

        def is_verb(c, *vals):
            return c.kind == 'VERB' and c.val in vals

        upd = any(c.kind in ('SCALE', 'HALVE', 'BECOMES', 'MODAL', 'EQSYM') or
                  is_verb(c, 'multiply', 'divide', 'increase', 'decrease', 'subv', 'set', 'make', 'generic')
                  for c in main)
        if len(main) > 1 and main[0].kind == 'FIELD' and main[1].kind == 'OP':
            upd = True          # "age times 2": a value, not an action; the update reader will ask
        addv = [c for c in main if is_verb(c, 'addv')]
        add_kind = None
        if addv and not upd:
            if any(c.kind in ('NUM', 'TO', 'PARAM') for c in main):
                upd = True
            elif any(c.kind == 'FIELD' for c in main):
                add_kind = 'sum'
            else:
                add_kind = 'add'
        acts = [c for c in main if c.kind == 'ACT']
        if upd and acts:
            raise self.p('question', acts, 'is this a change or a query?',
                         f'"{acts[0].text}" asks for something, but the rest changes something',
                         'say them in two sentences')

        if cond_t is None and not upd:
            k = index_of(main, 'CMP')
            if k is not None:
                s = k
                if s and main[s - 1].kind in ('IS', 'NOT'):
                    s -= 1
                if s and main[s - 1].kind == 'FIELD':
                    s -= 1
                main, cond_t = rstrip(main[:s]), main[s:]
        where = self.parse_cond(cond_t, coll) if cond_t is not None else None

        T = Task(name, '', coll.name, sent[0].line, self.sent_text(sent), named=name is not None)
        T.where = where
        act = acts[0].val if acts else None
        rest = [c for c in main if c.kind != 'ACT']

        if upd:
            T.kind, T.assigns = 'update', self.parse_updates(main, coll)
            if order:
                raise self.p('error', sent, 'a change cannot be sorted')
            return self.emit(T, coll)
        if order and act in ('remove', 'keep', 'find'):
            raise self.p('error', acts, f'"{acts[0].text}" and sorting don\'t go together in this version')

        by = index_of(rest, 'BY')
        key = None
        if by is not None:
            nxt = rest[by + 1] if by + 1 < len(rest) else None
            if nxt is None or nxt.kind not in ('FIELD', 'PARAM') or nxt.val not in coll.fields:
                raise self.p('question', rest[by:], 'by which property?', self.could_be(coll))
            if act in (None, 'show', 'sort') and not is_verb(rest[0], 'insert'):
                if act == 'show' or act is None:
                    raise self.p('question', rest[by:by + 2],
                                 f'"by {nxt.val}" — sorted by {nxt.val}, or looked up by a given {nxt.val}?',
                                 'two readings are possible',
                                 f'say "sorted by {nxt.val}" or "find a {coll.name} by {nxt.val}"')
            key = nxt.val
            rest = rest[:by] + rest[by + 2:]
            if where is not None:
                raise self.p('error', sent, f'"by {key}" and a condition together are not supported yet')

        if act in ('remove', 'find'):
            if rest:
                raise self.leftover(rest)
            if key is None and where is not None and where[0] == 'cmp' and where[1] == 'eq' and \
                    where[2][0] == 'field' and where[3] == ('param', where[2][1]):
                key, T.where = where[2][1], None
            if key:
                T.kind, T.key = ('find' if act == 'find' else 'remove_key'), key
            elif where is not None:
                T.kind = 'list' if act == 'find' else 'remove_where'
            else:
                u = [f.name for f in coll.unique_fields()] or list(coll.fields)
                eg = u[0] if u else 'email'
                raise self.p('question', sent, f'{acts[0].text} which {coll.name}?',
                             'nothing says how to pick it',
                             f'e.g. "{acts[0].text} a {coll.name} by {eg}" or '
                             f'"{acts[0].text} {coll.label} whose {eg} is ..."')
            return self.emit(T, coll)
        if act == 'keep':
            if rest:
                raise self.leftover(rest)
            if where is None:
                raise self.p('question', sent, f'keep which {coll.label}?', 'a condition is missing',
                             f'e.g. "keep the {coll.label} whose ..."')
            T.kind, T.where = 'remove_where', negate(where)
            T.fn = 'keep'
            return self.emit(T, coll)

        aggs = [c for c in rest if c.kind == 'AGG']
        if aggs or add_kind == 'sum':
            if len(aggs) > 1:
                raise self.p('question', aggs, 'which one do you want?', 'I can do one summary per sentence')
            fn = aggs[0].val if aggs else 'sum'
            fs = [c for c in rest if c.kind == 'FIELD']
            other = [c for c in rest if c.kind not in ('AGG', 'FIELD', 'IS') and not is_verb(c, 'addv')]
            if other:
                raise self.leftover(other)
            if len(fs) > 1:
                raise self.p('question', fs, f'{fn} of which one?', 'one property per summary')
            if fn != 'count' and not fs:
                raise self.p('question', aggs or addv, f'the {aggs[0].text if aggs else "total"} of which property?',
                             self.could_be(coll, True))
            T.kind, T.fn, T.field = 'agg', fn, (fs[0].val if fs and fn != 'count' else None)
            if order:
                raise self.p('error', sent, 'a single number cannot be sorted')
            return self.emit(T, coll)

        if add_kind == 'add' or (rest and is_verb(rest[0], 'insert')):
            left = [c for c in rest if not is_verb(c, 'addv', 'insert')]
            if left or where is not None or order:
                raise self.leftover(left or cond_t)
            T.kind = 'add'
            return self.emit(T, coll)

        fs = []
        for c in rest:
            if c.kind == 'FIELD':
                fs.append(c.val)
            elif c.kind not in ('COMMA', 'AND'):
                raise self.leftover([c])
        if not acts and not fs and where is None and not order:
            raise self.p('error', sent, f'I see this is about {coll.label}, but not what to do with them')
        T.kind, T.fields, T.order = 'list', (fs or None), order
        return self.emit(T, coll)

    def resolve_pronouns(self, content, coll):
        out = []
        for c in content:
            if c.kind != 'PRON':
                out.append(c)
                continue
            seen = []
            for d in out:
                if d.kind == 'FIELD' and d.val not in seen:
                    seen.append(d.val)
            if len(seen) == 1:
                out.append(CT('FIELD', seen[0], c.toks))
            elif seen:
                raise self.p('question', c, f'what does "{c.text}" refer to?', 'could be: ' + ', '.join(seen))
            else:
                raise self.p('question', c, f'what does "{c.text}" refer to?', self.could_be(coll, True),
                             'name the property, e.g. "double their age"')
        return out

    def take_order(self, content, coll):
        order = None
        i = index_of(content, 'SORTBY')
        if i is not None:
            if i + 1 < len(content) and content[i + 1].kind == 'FIELD':
                order = content[i + 1].val
                content = content[:i] + content[i + 2:]
            else:
                raise self.p('question', content[i], 'sorted by which property?', self.could_be(coll))
        else:
            s = index_of(content, 'ACT', 'sort')
            if s is not None:
                b = index_of(content, 'BY', start=s)
                if b is not None and b + 1 < len(content) and content[b + 1].kind == 'FIELD':
                    order = content[b + 1].val
                    content = content[:b] + content[b + 2:]
                else:
                    raise self.p('question', self.cur, f'sort the {coll.label} by which property?',
                                 self.could_be(coll), f'e.g. "sort the {coll.label} by {next(iter(coll.fields), "name")}"')
        d = index_of(content, 'DIR')
        desc = False
        if d is not None:
            if order is None:
                raise self.p('question', content[d], f'"{content[d].text}" by which property?', self.could_be(coll))
            desc = content[d].val == 'desc'
            content = content[:d] + content[d + 1:]
        return ((order, desc) if order else None), content

    def split_where(self, content):
        content = lstrip(content)
        w = index_of(content, 'WHERE')
        if w is None:
            return content, None
        if w == 0:
            end = next((i for i, c in enumerate(content) if i and c.kind in ('COMMA', 'THEN')), None)
            if end is None:
                return [], content[1:]
            return content[end + 1:], content[1:end]
        return content[:w], content[w + 1:]

    def calc(self, content, ti, name):
        j, params = ti + 1, []
        while j < len(content):
            c = content[j]
            if c.kind == 'TYPE':
                if c.val != 'int':
                    raise self.p('error', c, 'calculations work on whole numbers only in this version')
            elif c.kind == 'UNK':
                params.append(c.toks[0].text)
            elif c.kind in ('AND', 'COMMA') and params and j + 1 < len(content) and \
                    content[j + 1].kind in ('UNK', 'TYPE'):
                pass
            else:
                break
            j += 1
        if not params:
            return None
        rest = []
        for c in lstrip(content[j:]):
            if c.kind == 'UNK' and c.toks[0].text in params:
                rest.append(CT('PARAM', c.toks[0].text, c.toks))
            elif c.kind in ('PRON', 'TYPE'):
                if len(params) != 1:
                    raise self.p('question', c, f'what does "{c.text}" refer to?', 'could be: ' + ', '.join(params))
                rest.append(CT('PARAM', params[0], c.toks))
            elif c.kind == 'UNK':
                raise self.unknown_word(c)
            elif c.kind in ('FIELD', 'COLL'):
                rest.append(CT('UNK', c.text, c.toks))
                raise self.p('error', c, 'a calculation cannot use a collection in this version')
            else:
                rest.append(c)
        rest = [c for i, c in enumerate(rest) if not (c.kind == 'ACT' and c.val == 'show')]
        rest = lstrip(rest)
        if not rest:
            raise self.p('question', self.cur, 'what should it give back?', hint='e.g. "... and return n times 2"')
        T = Task(name, 'calc', None, self.cur[0].line, self.sent_text(self.cur), named=name is not None)
        T.params = params
        c = rest[0]
        P = lambda e: e
        if c.kind == 'VERB' and c.val in ('multiply', 'divide', 'increase', 'decrease'):
            a, n = self.parse_expr(rest[1:])
            if 1 + n >= len(rest) or rest[1 + n].kind != 'BY':
                raise self.p('error', rest, f'{c.text} by what?')
            b = self.whole_expr(rest[2 + n:])
            T.expr = binop({'multiply': 'mul', 'divide': 'div', 'increase': 'add', 'decrease': 'sub'}[c.val], a, b)
        elif c.kind == 'VERB' and c.val in ('addv', 'subv'):
            a, n = self.parse_expr(rest[1:])
            if 1 + n >= len(rest) or rest[1 + n].kind not in ('TO', 'FROM'):
                raise self.p('error', rest, f'{c.text} it to what?')
            b = self.whole_expr(rest[2 + n:])
            T.expr = binop('add', b, a) if c.val == 'addv' else binop('sub', b, a)
        elif c.kind == 'HALVE':
            T.expr = binop('div', self.whole_expr(rest[1:]), ('num', 2))
        else:
            T.expr = self.whole_expr(rest)
        return P(T)

    # ------------------------------------------------------------------ finishing
    def emit(self, T, coll=None):
        seen = []

        def visit(e):
            if e[0] == 'param' and e[1] not in seen:
                seen.append(e[1])
            elif e[0] == 'bin':
                visit(e[2])
                visit(e[3])

        def visit_c(c):
            if c is None:
                return
            if c[0] == 'cmp':
                visit(c[2])
                visit(c[3])
            else:
                visit_c(c[1])
                visit_c(c[2])

        if T.kind == 'calc':
            pass
        elif T.kind == 'add':
            T.params = list(coll.fields)
        elif T.kind in ('find', 'remove_key'):
            T.params = [T.key]
        else:
            for _, e in T.assigns:
                visit(e)
            visit_c(T.where)
            T.params = seen
        self.prog.tasks.append(T)
        return canon(T)

    def derived_name(self, t):
        def first_field(c):
            return c[2][1] if c[0] == 'cmp' and c[2][0] == 'field' else first_field(c[1])
        if t.kind == 'update':
            f, e = t.assigns[0]
            verb = 'set'
            if e[0] == 'bin' and e[2] == ('field', f):
                verb = {'mul': 'multiply', 'add': 'increase', 'sub': 'decrease', 'div': 'divide'}[e[1]]
                if e[1] == 'mul' and e[3][0] == 'num' and e[3][1] in SCALE_NAME:
                    verb = SCALE_NAME[e[3][1]]
                if e[1] == 'div' and e[3] == ('num', 2):
                    verb = 'halve'
            n = f'{verb}-{f}'
        elif t.kind == 'add':
            n = 'add'
        elif t.kind == 'find':
            n = f'find-by-{t.key}'
        elif t.kind == 'remove_key':
            n = f'remove-by-{t.key}'
        elif t.kind == 'remove_where':
            n = f'{"keep" if t.fn == "keep" else "remove"}-where-{first_field(t.where)}'
        elif t.kind == 'list':
            n = 'list' + ''.join(f'-{f}' for f in t.fields or [])
            if t.where:
                n += f'-where-{first_field(t.where)}'
            if t.order:
                n += f'-by-{t.order[0]}'
        elif t.kind == 'agg':
            n = {'avg': 'average', 'sum': 'total', 'count': 'count', 'max': 'largest', 'min': 'smallest'}[t.fn]
            if t.field:
                n += f'-{t.field}'
        else:
            n = 'calc'
        if t.coll and len(self.prog.collections) > 1:
            n = f'{t.coll}-{n}'
        return n

    def finish(self):
        used = {}
        for t in self.prog.tasks:
            if t.named:
                if t.name in used:
                    self.diags.append(Diag('error', f'two things are both named "{t.name}"', t.line, 0,
                                           len(self.src.line_text(t.line)),
                                           f'first used on line {used[t.name].line}'))
                used[t.name] = t
        for t in self.prog.tasks:
            if not t.named:
                base, n, k = self.derived_name(t), None, 1
                n = base
                while n in used:
                    k += 1
                    n = f'{base}-{k}'
                t.name = n
                used[n] = t


def parse(text, filename='<intent>'):
    p = Parser(text, filename)
    prog = p.parse()
    return prog, p.diags, p
