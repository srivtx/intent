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

from .ir import (KEYS, LONGEST_WAIT, STATE, Collection, Diag, Field, Program, Task, binop, canon, fmt_cond, fmt_event,
                 fmt_expr, negate, task_exprs, walk_expr)
from .lexicon import (BOARD_WORDS, CONVENTION, COUNT_NOUNS, DRAW_WORDS, HIGH_WORDS, MAX_PHRASE, PHRASES, PRESS_VERBS,
                      PRESSED, SYMS, TYPE_WORDS, UNITS, UNSUPPORTED_TYPES, WIDE_WORDS, all_known_words, singular)
from .source import Source, Tok, split_sentences, tokenize

ARTICLES = {'a', 'an', 'the', 'their', 'its', 'some', 'one'}
MANY = [('a', 'list', 'of'), ('a', 'set', 'of'), ('lists', 'of'), ('list', 'of'), ('set', 'of'), ('one', 'or', 'more'),
        ('zero', 'or', 'more'), ('any', 'number', 'of'), ('a', 'few'), ('several',), ('many',), ('multiple',),
        ('some',)]
LEADING_TYPES = {'numeric': 'int', 'integer': 'int', 'text': 'text', 'string': 'text', 'textual': 'text'}
SCALE_NAME = {2: 'double', 3: 'triple', 4: 'quadruple'}
STARTERS = [('as', 'soon', 'as'), ('every', 'time'), ('each', 'time'), ('when',), ('whenever',), ('if',), ('once',)]
KEY_ALIASES = {'return': 'enter', 'spacebar': 'space'}
OVER_WORDS = [('is', 'over'), ('is', 'lost'), ('is', 'finished'), ('is', 'done'), ('ends',), ('stops',), ('over',)]
BOARD_FILL = {'show', 'draw', 'make', 'the', 'a', 'an', 'is', 'are', 'has', 'have', 'with', 'and', 'of', 'that',
              'there', 'which', 'cells', 'squares', 'characters', 'big', 'by', 'x', 'on'}
OPENERS = [('at', 'the', 'start', 'there', 'is'), ('at', 'the', 'start', 'there', 'are'), ('to', 'begin', 'with'),
           ('at', 'first', 'there', 'is'), ('start', 'with'), ('begin', 'with'), ('starting', 'with'),
           ('there', 'is'), ('there', 'are'), ('at', 'the', 'start')]
BESIDE = {'above': 'above', 'over': 'above', 'below': 'below', 'under': 'below', 'beneath': 'below'}


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
        self.macros = {}            # words the program taught us: (w1, w2..) -> ('phrase'|'noun', tokens)
        self.state = Collection(STATE, 'single values')     # "The score is a number.": one record of values
        self.as_rule = False
        self.trigger = None         # set while reading a sentence that happens by itself, is drawn, or ends the game

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
        pool = list(self.state.fields) + list(self.prog.field_names()) + list(self.prog.collections) + \
            all_known_words()
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
        names.update(w for key in self.macros for w in key)
        for v in self.state.fields:
            names.update(v.split('_'))
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

    def near_a_name(self, word):
        """Is this word probably a slip for a collection the program already declared?"""
        return any(edit_distance(singular(word), n) <= (1 if len(n) < 8 else 2) for n in self.prog.collections)

    def snapshot(self):
        return copy.deepcopy(self.prog), list(self.diags), list(self.readings), dict(self.macros), \
            copy.deepcopy(self.state)

    def restore(self, snap):
        self.prog, self.diags, self.readings = copy.deepcopy(snap[0]), list(snap[1]), list(snap[2])
        self.macros = dict(snap[3])
        self.state = copy.deepcopy(snap[4])

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
        taught = self.teach_phrase(toks)
        if taught:
            return taught
        toks = self.cur = self.expand_sentence(toks)
        self.trigger = None
        lively = self.live(toks)
        if lively:
            return lively
        cts = self.short_names(self.normalize(toks))
        content = [c for c in cts if c.kind != 'FILLER']
        kinds = {c.kind for c in content}
        colls = [c for c in content if c.kind == 'COLL']
        unk = [c for c in content if c.kind == 'UNK']
        if kinds & {'ISCOLL', 'COLLWORD'} and not colls and (unk or ('ISCOLL' in kinds and 'GEN' in kinds)):
            mark = next(i for i, c in enumerate(content) if c.kind in ('ISCOLL', 'COLLWORD'))
            cut = next((i for i, c in enumerate(content) if i > mark and c.kind in ('WHERE', 'HAS')), None)
            if cut is None:
                return self.decl_collection(content)
            # "Customers is a collection where each customer has a name and an age."
            reading = self.decl_collection(content[:cut])
            coll = self.prog.collections[self.prog.recent]
            h = index_of(content, 'HAS', start=cut)
            h = cut if h is None else h
            for c in content[cut + 1:h]:
                if c.kind == 'UNK' and singular(c.toks[0].text) != coll.name:
                    raise self.unknown_word(c)
            return reading + '; ' + self.decl_fields(toks, content, h, coll)
        h = index_of(content, 'HAS')
        if h and not self.prog.collections.get(singular(content[h - 1].toks[0].text)) and \
                (content[h - 1].kind == 'UNK' or (content[h - 1].kind == 'GEN' and not self.prog.collections)) and \
                all(c.kind == 'QUANT' for c in content[:h - 1]) and \
                not kinds & {'CMP', 'BETWEEN'} and not any(c.kind == 'ACT' for c in content[:h]) and \
                not self.near_a_name(content[h - 1].toks[0].text):
            # "Each customer has a name and an age." with no earlier declaration: describing it declares it
            tok = content[h - 1].toks[0]
            name = singular(tok.text)
            label = tok.raw if tok.text != name else tok.raw + 's'
            self.prog.collections[name] = Collection(name, label, tok.line)
            return f'collection {name}; ' + self.decl_fields(toks, content, h, self.prog.collections[name])
        declared = self.decl_value(content)
        if declared:
            return declared
        taught = self.teach_noun(toks, content)
        if taught:
            return taught
        if 'BELONGS' in kinds:
            return self.decl_ref(content)
        rule = self.removal_rule(content, kinds)
        if rule:
            return rule
        if 'NOTWO' in kinds:
            return self.decl_unique(content)
        h = index_of(content, 'HAS')
        if h is not None and h > 0 and all(c.kind in ('QUANT', 'COLL', 'GEN') for c in content[:h]) and \
                not kinds & {'CMP', 'BETWEEN'} and not any(c.kind == 'ACT' for c in content[:h]):
            return self.decl_fields(toks, content, h)
        if 'UNIQUE' in kinds:
            return self.decl_unique(content)
        if kinds & {'INSORDER', 'NOORDER'}:
            return self.decl_order(content)
        if 'DUP' in kinds and 'POLICY' in kinds:
            return self.decl_dup(content)
        return self.task(content)

    # ------------------------------------------------------------------ definitions
    # A program can teach the compiler words. Both forms are plain substitution, done before
    # anything else looks at the sentence, so a taught word behaves exactly like its meaning.
    #   "older than" means age over.                     -> a phrase
    #   An adult is a customer whose age is at least 18. -> a kind of record
    def expand(self, toks):
        if not self.macros:
            return toks
        longest = max(len(k) for k in self.macros)
        out, i, n = [], 0, len(toks)
        while i < n:
            for L in range(min(longest, n - i), 0, -1):
                seg = toks[i:i + L]
                if any(x.kind != 'word' for x in seg):
                    continue
                words = tuple(x.text for x in seg)
                m = self.macros.get(words)
                if m is None:
                    m = self.macros.get(words[:-1] + (singular(words[-1]),))
                    if m and m[0] != 'noun':
                        m = None
                if m:
                    last = [x for x in seg if x.line == seg[0].line][-1]
                    out += [replace(b, line=seg[0].line, start=seg[0].start, end=last.end) for b in m[1]]
                    i += L
                    break
            else:
                out.append(toks[i])
                i += 1
        return out

    def expand_sentence(self, toks):
        """Expand taught words, except in a label that names a capability.

        "urgent: show ..." names a capability "urgent". "Adults: double the salary." is about
        adults, because nothing after the colon says which records it is about.
        """
        ci = next((i for i, t in enumerate(toks) if t.kind == 'sym' and t.text == ':'), None)
        if not self.macros or not ci:
            return self.expand(toks)
        pre, post = toks[:ci], self.expand(toks[ci + 1:])
        if any(t.kind == 'sym' and t.text == '-' for t in pre):
            return pre + [toks[ci]] + post          # "show-vip:" is a name, whatever "vip" means
        words = tuple(t.text for t in pre)
        m = self.macros.get(words) or self.macros.get(words[:-1] + (singular(words[-1]),))
        if any(t.kind != 'word' for t in pre) or m is None:
            return self.expand(pre) + [toks[ci]] + post
        about = any(t.kind == 'word' and singular(t.text) in self.prog.collections for t in post)
        if m[0] == 'phrase' or about:
            return pre + [toks[ci]] + post
        return self.expand(pre) + [toks[ci]] + post

    def taken(self, key, where):
        name = ' '.join(key)
        if key in PHRASES or key in self.macros or '_'.join(key) in self.prog.field_names() or \
                '_'.join(key) in self.state.fields or \
                (len(key) == 1 and key[0] in self.prog.collections):
            raise self.p('error', where, f'"{name}" already has a meaning',
                         'a word means one thing in one program', 'pick a different word')

    def teach_phrase(self, toks):
        m = next((i for i, t in enumerate(toks) if t.kind == 'word' and t.text == 'means'), None)
        if not m:
            return None
        lhs, rhs = toks[:m], toks[m + 1:]
        if len(lhs) == 1 and lhs[0].kind == 'str':
            key = tuple(lhs[0].text.lower().split())
        else:
            while len(lhs) > 1 and lhs[0].text in ARTICLES:
                lhs = lhs[1:]
            if any(t.kind != 'word' for t in lhs):
                raise self.p('error', lhs, 'I can\'t read this as a word or phrase to learn',
                             hint='put it in quotes: "older than" means age over.')
            key = tuple(t.text for t in lhs)
        if not key or len(key) > 5:
            raise self.p('error', lhs, 'a new phrase is one to five words')
        self.taken(key, lhs)
        if len(rhs) == 1 and rhs[0].kind == 'str':
            q = rhs[0]
            rhs = [replace(t, start=t.start + q.start + 1, end=t.end + q.start + 1)
                   for t in tokenize(q.text, q.line)]
        if not rhs:
            raise self.p('error', toks, f'"{" ".join(key)}" means what?')
        rhs = self.expand(rhs)
        for c in self.normalize(rhs):
            if c.kind == 'UNK':
                raise self.unknown_word(c)
        self.macros[key] = ('phrase', rhs)
        return f'"{" ".join(key)}" means: {" ".join(t.raw for t in rhs)}'

    def teach_noun(self, toks, content):
        k = 0
        while k < len(content) and content[k].kind == 'UNK':
            k += 1
        j = index_of(content, 'IS')
        if j and 2 <= j <= 4 and content[j - 1].kind == 'COLL' and j + 1 < len(content) and \
                content[j + 1].kind in ('COLL', 'GEN') and \
                all(len(c.toks) == 1 and c.toks[0].kind == 'word' and c.kind not in ('COLL', 'QUANT', 'GEN')
                    for c in content[:j - 1]):
            k = j - 1       # "An even stone is a stone whose ...": the program's meaning for "even stone" wins
        words = [c.toks[0].text for c in content[:k]]
        named = content[:k]
        if 1 <= k < len(content) and content[k].kind == 'COLL':       # "An open task is a task whose ..."
            words.append(content[k].val)
            k += 1
            named = content[:k]
        if not 1 <= len(words) <= 4 or k + 1 >= len(content) or \
                content[k].kind != 'IS' or content[k + 1].kind not in ('COLL', 'GEN') or \
                any(c.kind == 'UNK' for c in content[k:]):
            return None
        key = tuple(words[:-1] + [singular(words[-1])])
        self.taken(key, named)
        start = content[k + 1].toks[0]
        body = toks[next(i for i, t in enumerate(toks) if t is start):]
        rest = content[k + 1:]
        coll = self.scope(rest)
        what = coll.name
        if any(c.kind not in ('COLL', 'GEN', 'QUANT') for c in rest):
            before = len(self.prog.tasks)
            self.task(rest)
            t = self.prog.tasks.pop()
            assert len(self.prog.tasks) == before
            if t.kind != 'list' or t.order or t.fields or t.params:
                raise self.p('error', body, 'a definition can only narrow a collection with a fixed condition',
                             hint='e.g. "An adult is a customer whose age is at least 18."')
            if t.where:
                what += ' where ' + fmt_cond(t.where)
        self.macros[key] = ('noun', body)
        return f'"{" ".join(key)}" means: {what}'

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
                    raw = '_'.join(x.text for x in seg)
                    if key in self.state.fields or raw in self.state.fields:
                        el, ev = L, ('VALUE', key if key in self.state.fields else raw)
                        break
            if el <= 1 and singular(t.text) in self.prog.collections:
                el, ev = 1, ('COLL', singular(t.text))      # a collection name, even if a property shares it
            if el:                                          # a declared name beats any built-in phrase
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

    def short_names(self, cts):
        """"take a number a and a number b": here the second "a" is a name, not an article."""
        if not any(c.kind == 'TAKE' for c in cts):
            return cts
        named, out = False, []
        for i, c in enumerate(cts):
            if c.kind == 'FILLER' and len(c.toks) == 1 and c.toks[0].text == 'a':
                nxt = cts[i + 1].kind if i + 1 < len(cts) else None
                prev = cts[i - 1].kind if i else None
                if (named and nxt not in ('UNK', 'TYPE', 'FILLER')) or \
                        (prev == 'TYPE' and nxt not in ('UNK', 'TYPE', 'FILLER', 'NUM')) or \
                        (prev == 'TAKE' and nxt in ('AND', 'COMMA')):
                    named = True
                    c = CT('UNK', 'a', c.toks)
            out.append(c)
        return out

    # ------------------------------------------------------------------ time, keys and the board
    # These sentences are recognised from their shape, before any word is looked up, so that
    # none of their words is reserved: "the high score" and "each ticket has a key" stay names.
    def free(self, word):
        """Is this word still free to mean what the language means by it?"""
        names = set(self.prog.field_names()) | set(self.prog.collections) | set(self.state.fields)
        return word not in names and singular(word) not in names

    def content_of(self, toks):
        return [c for c in self.short_names(self.normalize(toks)) if c.kind != 'FILLER']

    def live(self, toks):
        words = [t.text if t.kind == 'word' else None for t in toks]
        colon = next((i for i, t in enumerate(toks) if t.kind == 'sym' and t.text == ':'), None)
        if colon is not None:
            tail = toks[colon + 1:]
            if tail and (self.timing(tail) or self.keypress(tail)):
                raise self.p('error', toks[:colon + 1], 'this happens by itself, so it needs no name',
                             hint='leave out the name and the colon')
            return None
        boards = [i for i, w in enumerate(words) if w in BOARD_WORDS and self.free(w)]
        if boards:
            board = self.decl_board(toks, words, boards[-1])
            if board:
                return board
        known = None
        for i, w in enumerate(words):   # "when space is presed": the slip is in "presed", whatever else is unknown
            if w and len(w) > 4 and w not in PRESSED | PRESS_VERBS and \
                    any(edit_distance(w, k) == 1 for k in ('pressed', 'presses')):
                known = known or self.vocabulary()
                if w not in known:
                    raise self.unknown_word(CT('UNK', w, [toks[i]]))
        if words[0] in DRAW_WORDS and self.free(words[0]):
            return self.decl_draw(toks)
        seeded = self.decl_seed(toks, words)
        if seeded:
            return seeded
        if 'game' in words and self.free('game'):
            ended = self.decl_end(toks, words)
            if ended:
                return ended
        span = self.timing(toks)
        if span:
            a, b, ms = span
            if not 1 <= ms <= LONGEST_WAIT:
                raise self.p('error', toks[a:b], 'this has to be between one millisecond and one hour')
            return self.event(self.cut(toks, a, b), ('every', ms))
        span = self.keypress(toks)
        if span:
            a, b, key = span
            return self.event(self.cut(toks, a, b), ('key', key))
        return None

    def cut(self, toks, a, b):
        """The sentence without toks[a:b] and the comma that tied it on."""
        if b < len(toks) and toks[b].kind == 'sym' and toks[b].text == ',':
            b += 1
        elif a and toks[a - 1].kind == 'sym' and toks[a - 1].text == ',':
            a -= 1
        return toks[:a] + toks[b:]

    def timing(self, toks):
        """"every 200 milliseconds" / "each second" / "5 times a second" -> (start, end, milliseconds)."""
        n = len(toks)

        def unit(j):
            return j < n and toks[j].kind == 'word' and toks[j].text in UNITS and self.free(toks[j].text)

        def count(j):
            t = toks[j] if j < n else None
            if t is None:
                return None
            if t.kind == 'num':
                if '.' in t.text:
                    raise self.p('error', t, 'decimal numbers are not supported yet',
                                 'say it in milliseconds: "every 500 milliseconds"')
                return int(t.text)
            got = PHRASES.get((t.text,)) if t.kind == 'word' else None
            return got[0][1] if got and len(got) == 1 and got[0][0] == 'NUM' else None

        for i, t in enumerate(toks):
            if t.kind == 'word' and t.text in ('every', 'each'):
                if unit(i + 1):
                    return i, i + 2, UNITS[toks[i + 1].text]
                k = count(i + 1)
                if k is not None and unit(i + 2):
                    return i, i + 3, k * UNITS[toks[i + 2].text]
            k = count(i)
            times = k if k is not None and i + 1 < n and toks[i + 1].text == 'times' else \
                {'once': 1, 'twice': 2}.get(t.text) if t.kind == 'word' else None
            j = i + (2 if times == k and k is not None else 1)
            if times and j < n and toks[j].text in ('a', 'per', 'each', 'every') and unit(j + 1):
                return i, j + 2, UNITS[toks[j + 1].text] // times
        return None

    def keypress(self, toks):
        """"when the left key is pressed" / "when the player presses space" -> (start, end, key)."""
        n = len(toks)
        w = [t.text if t.kind in ('word', 'num') else '' for t in toks]
        for s in range(n):
            L = next((len(st) for st in STARTERS if tuple(w[s:s + len(st)]) == st), 0)
            if not L:
                continue
            k = s + L
            if k < n and w[k] in ('the', 'a'):
                k += 1
            if k < n and w[k] in ('player', 'user', 'someone', 'you', 'i', 'we'):
                k += 1
            pressing = k < n and w[k] in PRESS_VERBS
            k = k + 1 if pressing else s + L
            if k < n and w[k] == 'the':
                k += 1
            if k >= n:
                continue
            kt = k
            k += 1
            said_key = False
            while k < n and w[k] in ('arrow', 'key', 'button'):
                said_key = True
                k += 1
            if not pressing:
                while k < n and w[k] in ('is', 'gets', 'are'):
                    k += 1
                if not (k < n and w[k] in PRESSED):
                    continue
                k += 1
                if k < n and w[k] == 'down':
                    k += 1
            if not (k == n or (s == 0 and toks[k].kind == 'sym' and toks[k].text == ',')):
                continue
            key = KEY_ALIASES.get(w[kt], w[kt])
            if key not in KEYS:
                if said_key or pressing:
                    raise self.p('error', toks[kt], f'I don\'t know a key called "{toks[kt].raw}"',
                                 hint='keys I know: left, right, up, down, space, enter, and any letter or digit')
                continue
            return s, k, key
        return None

    def event(self, rest, on):
        if not rest:
            raise self.p('error', self.cur, 'and then what happens?', 'this says when, but not what',
                         'e.g. "Every second, the score increases by 1."')
        self.trigger = on
        return self.task(self.content_of(rest))

    def decl_board(self, toks, words, b):
        """"The board is 30 wide and 15 high."  "Show the score and the lives above the board."."""
        nums = [i for i, t in enumerate(toks) if t.kind == 'num']
        if not nums:
            side = next((i for i in range(b) if words[i] in BESIDE and all(w == 'the' for w in words[i + 1:b])), None)
            if side is None and words[0] not in DRAW_WORDS | {'show'}:
                return None             # "Each ticket has a key and a board.": an ordinary name here
            if side is None or b != len(toks) - 1:
                raise self.p('error', toks, 'I can\'t tell what this says about the board',
                             hint='e.g. "The board is 30 wide and 15 high." or "Show the score above the board."')
            content = self.content_of(toks[:side])
            for c in content:
                if c.kind == 'UNK':
                    raise self.unknown_word(c)
                if c.kind not in ('VALUE', 'AND', 'COMMA') and not (c.kind == 'ACT' and c.val == 'show'):
                    raise self.p('error', c, 'only single values can be shown beside the board in this version',
                                 hint='e.g. "The score is a number." then "Show the score above the board."')
            names = [c.val for c in content if c.kind == 'VALUE']
            if not names:
                raise self.p('error', toks, 'show what there?', hint='e.g. "Show the score above the board."')
            where = BESIDE[words[side]]
            getattr(self.prog, where).extend(n for n in names if n not in getattr(self.prog, where))
            return f'{where} the board: ' + ', '.join(names)
        if self.prog.board:
            raise self.p('error', toks, 'the board already has a size', f'line {self.prog.board_line} gives it')
        w = h = None
        for i, t in enumerate(toks):
            if t.kind == 'num':
                if '.' in t.text or int(t.text) < 1:
                    raise self.p('error', t, 'a board is a whole number of characters wide and high')
                v, nxt = int(t.text), words[i + 1] if i + 1 < len(toks) else None
                prev = words[i - 1] if i else None
                if nxt in WIDE_WORDS or (nxt in ('by', 'x') and w is None):
                    w = v
                elif nxt in HIGH_WORDS or prev in ('by', 'x'):
                    h = v
                else:
                    raise self.p('error', t, 'is this how wide the board is, or how high?',
                                 hint='e.g. "The board is 30 wide and 15 high."')
            elif t.kind == 'sym' and t.text == ',':
                continue
            elif words[i] is None or not (words[i] in BOARD_FILL | BOARD_WORDS | WIDE_WORDS | HIGH_WORDS):
                raise self.leftover([CT('UNK', t.text, [t])])
        if w is None or h is None:
            raise self.p('error', toks, f'how {"wide" if w is None else "high"} is the board?',
                         hint='e.g. "The board is 30 wide and 15 high."')
        if w > 200 or h > 60:
            raise self.p('error', toks, 'a board can be at most 200 wide and 60 high in this version')
        self.prog.board, self.prog.board_line = (w, h), toks[0].line
        return f'board {w} wide, {h} high'

    def decl_draw(self, toks):
        """"Draw each rock at its x and y as "#"."  "Draw "@" at the column and the row."."""
        hint = 'e.g. Draw each rock at its x and y as "#".'
        looks = [i for i, t in enumerate(toks) if t.kind in ('str', 'bad')]
        if len(looks) != 1:
            raise self.p('error', toks, 'what should it look like?' if not looks else
                         'one thing is drawn as one character', hint=hint)
        g = looks[0]
        glyph = toks[g].text if toks[g].kind == 'str' else toks[g].raw
        if len(glyph) != 1 or not 33 <= ord(glyph) <= 126:
            raise self.p('error', toks[g], 'one thing is drawn as one plain character', hint=hint)
        a = g - 1 if g and toks[g - 1].kind == 'word' and toks[g - 1].text in ('as', 'with', 'like', 'using') else g
        rest = toks[1:a] + toks[g + 1:]
        at = next((i for i, t in enumerate(rest) if t.kind == 'word' and t.text == 'at' and
                   not (i + 1 < len(rest) and rest[i + 1].text in ('least', 'most'))), None)
        if at is None:
            raise self.p('error', toks, 'where should it be drawn?', 'this needs an "at"', hint)
        place = self.content_of(rest[at + 1:])
        cutoff = next((i for i, c in enumerate(place) if c.kind in ('WHERE', 'HAS')), len(place))
        place, cond = place[:cutoff], place[cutoff:]
        who = [c for c in place if c.kind in ('COLL', 'QUANT', 'GEN')]
        place = [c for c in place if c not in who]
        for c in place:
            if c.kind == 'UNK':
                raise self.unknown_word(c)
        sep = next((i for i, c in enumerate(place) if c.kind in ('AND', 'COMMA')), None)
        if sep is None:
            raise self.p('error', place or toks, 'a place on the board is two numbers: how far across, and how far down',
                         hint=hint)
        xy = (self.whole_expr(place[:sep]), self.whole_expr(place[sep + 1:]))
        subject = self.content_of(rest[:at]) + who + cond
        used = [c for c in place if c.kind == 'FIELD']
        if used and not any(c.kind == 'COLL' for c in subject):
            subject = [CT('COLL', self.scope(used).name, used[0].toks)] + subject
        if not subject:
            T = Task(f'draw {len(self.prog.draws) + 1}', 'draw', None, toks[0].line, self.sent_text(toks), True)
            T.at, T.glyph = xy, glyph
            self.prog.draws.append(T)
            return f'draw "{glyph}" at ({fmt_expr(xy[0])}, {fmt_expr(xy[1])})'
        self.trigger = ('draw', xy, glyph)
        return self.task([CT('ACT', 'show', [toks[0]])] + subject)

    def decl_seed(self, toks, words):
        """A record that is there from the start: "Start with a rock at x 5, y 1 and speed 2"."""
        L = next((len(o) for o in OPENERS if tuple(words[:len(o)]) == o), 0)
        if not L:
            return None
        rest = [t for t in toks[L:] if not (t.kind == 'word' and t.text == 'at' and self.free('at'))]
        try:
            content = self.content_of(rest)
        except Problem:
            return None
        while content and (content[0].kind == 'QUANT' or (content[0].kind == 'NUM' and content[0].val == 1)):
            content = content[1:]
        if not content or content[0].kind != 'COLL' or \
                any(c.kind not in ('FIELD', 'NUM', 'STR', 'IS', 'EQSYM', 'AND', 'COMMA', 'WHERE', 'HAS')
                    for c in content[1:]):
            return None
        coll = self.prog.collections[content[0].val]
        given, f = {}, None
        for c in content[1:]:
            if c.kind == 'FIELD':
                if f or c.val not in coll.fields or c.val in given:
                    raise self.p('error', c, f'I expected a value for "{f}" here' if f else
                                 f'"{c.val}" is given twice' if c.val in given else
                                 f'{coll.label} has no property "{c.val}"')
                f = c.val
            elif c.kind in ('NUM', 'STR'):
                if not f:
                    raise self.p('error', c, 'which property is this the value of?', self.could_be(coll))
                given[f], f = ('num' if c.kind == 'NUM' else 'str', c.val), None
        missing = [n for n in coll.fields if n not in given]
        if f or missing:
            raise self.p('question', toks, f'what is the {f or missing[0]} of this {coll.name}?',
                         'something that is there from the start needs a value for every property',
                         f'e.g. "... {f or missing[0]} 1"')
        if any(fl.ref for fl in coll.fields.values()):
            raise self.p('error', toks, f'starting with {coll.label.lower()} that belong to something is not supported yet')
        T = Task(f'start {len(self.prog.seeds) + 1}', 'seed', coll.name, toks[0].line, self.sent_text(toks), True)
        T.assigns = [(n, given[n]) for n in coll.fields]
        self.prog.seeds.append(T)
        return f'at the start, a {coll.name}: ' + ', '.join(f'{n} = {fmt_expr(e)}' for n, e in T.assigns)

    def decl_end(self, toks, words):
        """"The game is over when the lives are 0."  "When any rock is ..., the game ends."."""
        i = words.index('game')
        tail = next((len(o) for o in OVER_WORDS if tuple(words[i + 1:i + 1 + len(o)]) == o), 0)
        if not tail:
            return None
        a = i
        while a and words[a - 1] in ('the', 'it', 'is'):
            a -= 1
        rest = self.cut(toks, a, i + 1 + tail)
        w = [t.text if t.kind == 'word' else '' for t in rest]
        L = next((len(st) for st in STARTERS if tuple(w[:len(st)]) == st), 0)
        if not L:
            raise self.p('error', toks, 'when is the game over?',
                         hint='e.g. "The game is over when the lives are 0."')
        self.trigger = ('end',)
        return self.task([CT('ACT', 'show', [toks[i]]), CT('WHERE', None, rest[:L])] + self.content_of(rest[L:]))

    # ------------------------------------------------------------------ single values
    def decl_value(self, content):
        """"The score is a number."  "The limit is 100."  "The score starts at 0."  -> one value, kept."""
        k = 0
        while k < len(content) and content[k].kind == 'UNK':
            k += 1
        rest = [c for c in content[k:] if c.kind != 'WHERE']
        kinds = [c.kind for c in rest]
        if k == 0 and kinds[:2] == ['VALUE', 'STARTS'] and len(rest) == 3 and rest[2].kind in ('NUM', 'STR'):
            f = self.state.fields[rest[0].val]
            if (f.type == 'int') != (rest[2].kind == 'NUM'):
                raise self.p('error', rest[2], f'"{f.name}" is {"a number" if f.type == "int" else "text"}, '
                             f'so it cannot start as this')
            f.init = rest[2].val
            return f'value {f.name} starts at {fmt_expr((rest[2].kind.lower(), rest[2].val))}'
        lit = ('NUM', 'STR')
        shape = (kinds == ['IS', 'TYPE'] or (kinds[:3] == ['IS', 'TYPE', 'STARTS'] and len(rest) == 4 and
                                             rest[3].kind in lit) or
                 (len(rest) == 2 and kinds[0] in ('IS', 'STARTS') and rest[1].kind in lit))
        if not 1 <= k <= 3 or not shape:
            return None
        words = content[:k]
        name = '_'.join(c.toks[0].text for c in words)
        known = list(self.state.fields) + list(self.prog.field_names()) + list(self.prog.collections)
        for c in words:             # "The scroe is 5." is a slip for the score, not a new value
            w = singular(c.toks[0].text)
            if len(w) > 3 and any(w != n and edit_distance(w, n) <= (1 if len(n) < 8 else 2) for n in known):
                raise self.unknown_word(c)
        self.taken(tuple(c.toks[0].text for c in words), words)
        typ = rest[1].val if rest[1].kind == 'TYPE' else None
        first = rest[-1] if rest[-1].kind in lit else None
        if first is not None:
            given = 'int' if first.kind == 'NUM' else 'text'
            if typ and typ != given:
                raise self.p('error', first, f'this is not {"a number" if typ == "int" else "text"}')
            typ = given
        f = Field(name, typ, line=self.cur[0].line)
        f.init = first.val if first is not None else (0 if typ == 'int' else '')
        self.state.fields[name] = f
        self.state.line = self.state.line or f.line
        if first is None:
            self.note(words, f'"{name}" starts {"at 0" if typ == "int" else "empty"}, since nothing says otherwise',
                      f'e.g. "The {name.replace("_", " ")} starts at {"10" if typ == "int" else chr(34) + "hello" + chr(34)}."')
        return f'value {name}: {"number" if typ == "int" else "text"}, starts at {fmt_expr(("num" if typ == "int" else "str", f.init))}'

    # ------------------------------------------------------------------ scope
    def scope(self, content, anchor=None, recent=False):
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
        if recent and getattr(self.prog, 'recent', None) in cs:
            return cs[self.prog.recent]             # "Reject duplicates." right after describing orders
        used = {c.val for c in content if c.kind == 'FIELD'}
        owners = [c for c in cs.values() if used and used <= set(c.fields)]
        if len(owners) == 1:
            return owners[0]                        # "What is the largest cost?": only visits have a cost
        if not cs:
            raise self.p('error', anchor or self.cur, 'there is nothing to work on yet',
                         hint='declare a collection first, e.g. "Customers is a collection."')
        raise self.p('question', anchor or self.cur, 'which collection is this about?',
                     'could be: ' + ', '.join(c.label for c in cs.values()))

    def relate(self, content):
        """A property may share its name with a collection ("each booking has a customer").

        When a sentence names two collections and one of them is such a property of the other,
        the sentence is about the owner and the other word is its property.
        """
        names = []
        for c in content:
            if c.kind == 'COLL' and c.val not in names:
                names.append(c.val)
        cs = self.prog.collections
        owners = [n for n in names if not any(n in cs[m].fields for m in names if m != n)]
        if len(names) < 2 or len(owners) != 1:
            return content
        owner = cs[owners[0]]
        links = [n for n in names if n != owner.name and n in owner.fields]
        if not links:
            return content
        out, i = [], 0
        while i < len(content):
            c = content[i]
            i += 1
            if not (c.kind == 'COLL' and c.val in links):
                out.append(c)
                continue
            b = c.val
            other, link = cs[b], owner.fields[b]
            nxt = content[i] if i < len(content) else None
            prev = out[-1] if out else None
            if link.ref and nxt and nxt.kind in ('FIELD', 'COLL') and nxt.val in other.fields:
                out.append(CT('PFIELD', (b, nxt.val), c.toks + nxt.toks))       # "the customer's age"
                i += 1
            elif link.ref and prev and prev.kind == 'FIELD' and prev.val in other.fields:
                out[-1] = CT('PFIELD', (b, prev.val), prev.toks + c.toks)       # "the age of the customer"
            elif link.ref and not ((prev and prev.kind in ('WHERE', 'BY', 'SORTBY', 'AND', 'OR')) or
                                   (nxt and nxt.kind in ('IS', 'CMP', 'EQSYM', 'NOT'))):
                raise self.p('error', c, f'asking about {other.label} through their {owner.label} '
                             f'is not supported yet', 'this would need a summary per ' + other.name,
                             f'the other direction works: "{owner.label} whose {b}\'s ... is ..."')
            else:
                out.append(CT('FIELD', b, c.toks))
        return out

    def make_ref(self, child, parent, where):
        if child is parent:
            raise self.p('error', where, f'a {child.name} that belongs to another {child.name} is not supported yet')
        f = child.fields.get(parent.name)
        if f is None:
            f = child.fields[parent.name] = Field(parent.name, None, line=flat(where)[0].line)
        elif not f.ref and f.type:
            raise self.p('error', where, f'"{parent.name}" is already a plain property of {child.label}',
                         hint='drop its type to make it the relationship')
        f.ref = parent.name
        return f

    def decl_ref(self, content):
        unk = [c for c in content if c.kind == 'UNK']
        if unk:
            raise self.unknown_word(unk[0])
        b = index_of(content, 'BELONGS')
        left = [c for c in content[:b] if c.kind == 'COLL']
        right = [c for c in content[b + 1:] if c.kind == 'COLL']
        if len(left) != 1 or len(right) != 1:
            raise self.p('error', content[b], 'what belongs to what?',
                         hint='e.g. "Each order belongs to a customer." (both must be collections)')
        child, parent = self.prog.collections[left[0].val], self.prog.collections[right[0].val]
        self.make_ref(child, parent, right)
        self.prog.recent = child.name
        return f'{child.name} belongs to {parent.name}'

    def removal_rule(self, content, kinds):
        """'When a customer is removed, remove its orders.' / 'A customer with orders cannot be removed.'"""
        names = []
        for c in content:
            if c.kind == 'COLL' and c.val not in names:
                names.append(c.val)
        removes = [c for c in content if c.kind == 'ACT' and c.val == 'remove']
        if len(names) != 2 or not removes or kinds & {'FIELD', 'PARAM', 'CMP', 'NUM', 'STR', 'AGG', 'BY', 'UNK'}:
            return None
        cs = self.prog.collections
        a, b = names
        if cs[b].fields.get(a) and cs[b].fields[a].ref:
            a, b = b, a
        elif not (cs[a].fields.get(b) and cs[a].fields[b].ref):
            return None
        child, parent, link = cs[a], cs[b], cs[a].fields[b]
        if 'CANNOT' in kinds:
            link.on_removed = 'restrict'
        elif len(removes) >= 2:
            link.on_removed = 'cascade'
        else:
            raise self.p('question', removes, f'should removing a {parent.name} also remove its '
                         f'{child.label.lower()}, or be refused?', 'I can read this either way',
                         f'say "When a {parent.name} is removed, remove its {child.label.lower()}." or '
                         f'"A {parent.name} with {child.label.lower()} cannot be removed."')
        link.on_removed_line = self.cur[0].line
        if link.on_removed == 'cascade':
            return f'removing {parent.name} removes its {child.label.lower()}'
        return f'a {parent.name} with {child.label.lower()} cannot be removed'

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
        self.prog.recent = name
        return f'collection {name}'

    def decl_fields(self, toks, content, h, coll=None):
        coll = coll or self.scope(content[:h])
        self.prog.recent = coll.name
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
            f'{f.name}' + (f': {f.type}' if f.type else '') + (' (unique)' if f.unique else '') +
            (f' (the {f.ref} it belongs to)' if f.ref else '') for f in added)

    def field_item(self, item, coll):
        ws = list(item)
        while ws and ws[0].kind == 'sym' and ws[0].text == ':':
            ws.pop(0)
        lead = tuple(w.text for w in ws[:3])
        many = next((m for m in MANY if lead[:len(m)] == m), None)
        one = bool(ws) and ws[0].text in ('a', 'an', 'one') and not many
        if many:
            ws = ws[len(many):]
        while ws and ws[0].kind == 'word' and ws[0].text in ARTICLES:
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
        plural = ws[-1].text != singular(ws[-1].text)
        if plural and not one and not many and tw is None and ftype is None and name not in coll.fields and \
                ws[-1].text not in COUNT_NOUNS:
            many = True
            self.note(ws, f'reading "{ws[-1].raw}" as several values per {coll.name}, because it is plural',
                      f'write "{ws[-1].raw} (number)" or "a {name}" if each {coll.name} has just one')
        if many and name != coll.name:
            return self.many_valued(coll, name, ws, ftype)
        if name in self.prog.collections and name != coll.name and ftype is None and name not in coll.fields:
            return self.make_ref(coll, self.prog.collections[name], ws)      # "each order has a customer"
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

    def many_valued(self, coll, name, ws, ftype):
        """'each customer has several phones': the phones are records of their own that belong to
        the customer and go when the customer goes. Everything that works on a collection works on them."""
        other = self.prog.collections.get(name)
        made = other is None
        if made:
            other = self.prog.collections[name] = Collection(name, ws[-1].raw, ws[0].line)
            other.fields[name] = Field(name, ftype, line=ws[0].line)
        elif coll.name in other.fields and not other.fields[coll.name].ref:
            raise self.p('error', ws, f'{other.label} already have a plain property called "{coll.name}"')
        link = self.make_ref(other, coll, ws)
        if made:
            link.on_removed, link.on_removed_line = 'cascade', ws[0].line
        return Field(f'several {other.label.lower()}' + ('' if made else f' (each {name} belongs to a {coll.name})'))

    def decl_unique(self, content):
        unk = [c for c in content if c.kind == 'UNK']
        if unk:
            raise self.unknown_word(unk[0])
        content = self.relate(content)
        coll = self.scope(content, recent=True)
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
        coll = self.scope(content, recent=True)
        coll.ordered = any(c.kind == 'INSORDER' for c in content)
        coll.ordered_line = self.cur[0].line
        return f'{coll.name}: ' + ('insertion order is part of the meaning' if coll.ordered else 'order does not matter')

    def decl_dup(self, content):
        unk = [c for c in content if c.kind == 'UNK']
        if unk:
            raise self.unknown_word(unk[0])
        coll = self.scope(content, recent=True)
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
            if c.kind == 'PFIELD':
                return ('pfield',) + c.val
            if c.kind == 'PARAM':
                return ('param', c.val)
            if c.kind == 'VALUE':
                return ('value', c.val)
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
            while pos < len(toks) and toks[pos].kind == 'OP' and toks[pos].val in ('mul', 'div', 'rem'):
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

    def either(self, toks, coll, f=None):
        """A value that depends on a condition: "2 if the score is over 100, otherwise 1"."""
        toks = lstrip(toks)
        o = index_of(toks, 'OTHERWISE')
        if o is None:
            w = index_of(toks, 'WHERE')
            if w is not None and f is None:
                raise self.p('question', toks[w:], 'and what if not?', 'this gives a value only some of the time',
                             'finish it: "... if a is over b, otherwise b"')
            return self.one_value(toks, coll, f)
        head, tail = rstrip(toks[:o]), toks[o + 1:]
        w = index_of(head, 'WHERE')
        if w is None:
            raise self.p('error', toks[o], '"otherwise" needs an "if" before it',
                         hint='e.g. "... 2 if the score is over 100, otherwise 1"')
        if w == 0:
            end = next((i for i, c in enumerate(head) if i and c.kind in ('COMMA', 'THEN')), None)
            if end is None:
                raise self.p('error', head, 'I can\'t see where the condition ends',
                             hint='put a comma or "then" after it: "if a is over b then a, otherwise b"')
            cond_t, val_t = head[1:end], head[end + 1:]
        else:
            val_t, cond_t = head[:w], head[w + 1:]
        return ('if', self.parse_cond(cond_t, coll), self.one_value(val_t, coll, f), self.either(tail, coll, f))

    def one_value(self, toks, coll, f):
        toks = rstrip(lstrip([c for c in toks if not (c.kind == 'ACT' and c.val == 'show')]))
        if not toks:
            raise self.p('error', self.cur[-1], 'a value is missing here')
        if f is not None and (toks[0].kind in ('VERB', 'SCALE', 'HALVE') or
                              (toks[0].kind == 'FIELD' and len(toks) > 1 and
                               toks[1].kind in ('BECOMES', 'MODAL', 'EQSYM'))):
            g, e, rest = self.one_update(toks, coll)        # "... otherwise set it to 1"
            if g != f:
                raise self.p('error', toks, f'both outcomes have to set the same thing; the first sets "{f}"')
            if rest:
                raise self.leftover(rest)
            return e
        return self.whole_expr(toks, f)

    def leftover(self, toks):
        return self.p('error', toks, f'I don\'t see how "{" ".join(c.text for c in toks)}" fits in',
                      'I understood the rest of the sentence, but not this part')

    # ------------------------------------------------------------------ conditions
    def parse_cond(self, toks, coll):
        joined = []
        for c in toks:              # "... whose age is over 18 whose salary is under 100": a second clause adds
            if c.kind == 'WHERE' and joined:
                if joined[-1].kind not in ('AND', 'OR', 'COMMA'):
                    joined.append(CT('AND', None, c.toks))
                continue
            if c.kind == 'FIELD' and joined and joined[-1].kind in ('NUM', 'STR', 'PARAM', 'GIVENBARE'):
                joined.append(CT('AND', None, c.toks))      # "... at least 18 age over 64"
            joined.append(c)
        parts, ops, cur = [], [], []
        for c in joined:
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
        i, lhs = 0, None
        stop = next((k for k, c in enumerate(p) if c.kind in ('IS', 'NOT', 'CMP', 'EQSYM')), len(p))
        if p[0].kind in ('FIELD', 'PFIELD', 'VALUE') or \
                (p[0].kind in ('NUM', 'LP', 'PARAM', 'SCALE') and any(c.kind == 'OP' for c in p[:stop])) or \
                (p[0].kind == 'PARAM' and 0 < stop < len(p)):
            lhs, i = self.parse_expr(p[:stop])       # "whose price times quantity is over 100"
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
        if lhs is None:
            if prev and explicit:
                lhs = prev                  # "at least 18 and at most 65": same property, elided
            else:
                raise self.p('question', p, 'which property is this comparing?', self.could_be(coll, explicit),
                             'e.g. "whose age is over 25"')
        rest = p[i:]
        if not rest:
            raise self.p('error', p, 'compared with what?', 'a value is missing')
        if len(rest) == 1 and rest[0].kind == 'PARITY':
            odd = (rest[0].val == 1) != neg
            return ('cmp', 'ne' if odd else 'eq', ('bin', 'rem', lhs, ('num', 2)), ('num', 0)), lhs
        if len(rest) == 1 and rest[0].kind == 'GIVENBARE':
            if lhs[0] not in ('field', 'pfield'):
                raise self.p('error', rest, 'a given what?', hint='name it, e.g. "a given limit"')
            rhs = ('param', lhs[-1])
        else:
            rhs = self.whole_expr(rest)
        op = op or 'eq'
        if neg:
            op = negate(('cmp', op, 0, 0))[1]
        return ('cmp', op, lhs, rhs), lhs

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
                if 3 + n < len(t) and t[3 + n].kind == 'PCT':
                    if op not in ('add', 'sub'):
                        raise self.p('error', t[3 + n], 'percent only goes with increase or decrease')
                    e, n = ('bin', 'div', binop('mul', ('field', f), e), ('num', 100)), n + 1
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
            if nxt and ((nxt.kind == 'VERB' and nxt.val in ('multiply', 'divide', 'increase', 'decrease')) or
                        (nxt.kind in ('SCALE', 'HALVE') and nxt.toks[-1].text.endswith('s'))):
                return self.one_update([nxt, c] + t[2:], coll)      # "the score increases by 1", "the speed doubles"
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
        self.as_rule = False
        if content and (content[0].kind == 'RULE' or
                        (content[0].kind == 'WHERE' and content[0].toks[0].text in ('when', 'once'))) and \
                index_of(content, 'COLON') is None and index_of(content, 'TAKE') is None:
            self.as_rule = True
        if any(t.kind == 'word' and t.text == 'always' for t in sent) and index_of(content, 'COLON') is None and \
                index_of(content, 'TAKE') is None and \
                not any(c.kind in ('INSORDER', 'NOORDER', 'UNIQUE', 'DUP') for c in content):
            # "The level is always 3 if the score is at least 50, otherwise 1."
            # "Whenever a player's score passes 100, their level becomes 2.": not a command, a standing rule
            self.as_rule = True
        if self.trigger:
            self.as_rule = False
        content = [CT('WHERE', None, c.toks) if c.kind == 'RULE' else c for c in content]
        ci = index_of(content, 'COLON')
        if ci is not None:
            pre, post = content[:ci], content[ci + 1:]
            if pre and pre[0].kind in ('COLL', 'QUANT', 'GEN') and any(c.kind == 'WHERE' for c in pre):
                content = post + pre        # "Customers whose age is under 18: remove them."
            elif pre and all(c.kind in ('COLL', 'QUANT', 'GEN') or (c.kind == 'VERB' and c.val == 'generic')
                             for c in pre):
                content = [c for c in pre if c.kind in ('COLL', 'GEN')] + post
            else:
                colon = content[ci].toks[0]
                label = sent[:next(i for i, t in enumerate(sent) if t is colon)]
                words = [t for t in label if not (t.kind == 'sym' and t.text == '-')]
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
        content = self.relate(content)
        if any(c.kind == 'VALUE' for c in content) and not any(c.kind in ('COLL', 'FIELD', 'PFIELD') for c in content):
            # only single values are mentioned: the sentence is about them
            content = [CT('FIELD', c.val, c.toks) if c.kind == 'VALUE' else c for c in content]
            coll = self.state
        else:
            coll = self.scope(content)
        if coll.name in coll.fields:        # several-valued property: "phones whose phone starts with ..."
            mine = [i for i, c in enumerate(content) if c.kind == 'COLL' and c.val == coll.name]
            for i in mine:
                c = content[i]
                prev = content[i - 1] if i else None
                nxt = content[i + 1] if i + 1 < len(content) else None
                if (prev and prev.kind in ('WHERE', 'AND', 'OR', 'BY', 'SORTBY')) or \
                        (nxt and nxt.kind in ('IS', 'CMP', 'EQSYM', 'NOT')) or \
                        (len(mine) > 1 and c.toks[0].text == coll.name and
                         any(content[j].toks[0].text != coll.name for j in mine)):
                    content[i] = CT('FIELD', coll.name, c.toks)
        everyone = any((c.kind == 'QUANT' and c.toks[0].text in ('all', 'every')) or
                       (c.kind == 'GEN' and c.toks[0].text in ('everyone', 'everybody')) for c in content)
        kept = []
        for c in content:
            if c.kind in ('COLL', 'QUANT', 'GEN'):
                continue
            if c.kind == 'HAS':
                text_test = c.toks[0].text in ('contains', 'contain', 'includes', 'include') and kept and \
                    kept[-1].kind in ('FIELD', 'PFIELD', 'NOT')
                c = CT('CMP', 'has', c.toks) if text_test else CT('WHERE', None, c.toks)
            kept.append(c)
        content = kept
        for c in content:
            if c.kind == 'FIELD' and c.val not in coll.fields:
                raise self.p('error', c, f'{coll.label} has no property "{c.val}"', self.could_be(coll))
        content = self.resolve_pronouns(content, coll)
        content = self.between(content)
        order, content = self.take_order(content, coll)
        order, limit, content = self.take_limit(content, coll, order)
        for i, c in enumerate(content):     # "the orders of a given customer": the owner picks the records
            if c.kind == 'PARAM' and c.val in coll.fields and coll.fields[c.val].ref and \
                    (i == 0 or content[i - 1].kind not in ('WHERE', 'AND', 'OR', 'IS', 'CMP', 'EQSYM', 'NOT', 'OP',
                                                           'TO', 'BY', 'BECOMES', 'MODAL', 'FROM', 'VERB')):
                content = content[:i] + content[i + 1:]
                if not content or content[-1].kind != 'WHERE':
                    content.append(CT('WHERE', None, c.toks))
                content.append(c)
                break
        o = index_of(content, 'OTHERWISE')
        other = None
        if o is not None:               # "... set the level to 2 if the score is over 100, otherwise 1"
            other, content = content[o:], rstrip(content[:o])
        main, cond_t = self.split_where(content)
        main = rstrip(lstrip(main))
        if cond_t and main and index_of(main, 'BY') is None and \
                any(c.kind == 'VERB' and c.val in ('multiply', 'divide', 'increase', 'decrease') for c in main):
            b = index_of(cond_t, 'BY')      # "increase the points of the player with a given name by 5"
            if b:
                main, cond_t = main + cond_t[b:], cond_t[:b]
        if cond_t:                      # "... with the highest salary": a ranking, not a filter
            for i, c in enumerate(cond_t[:-1]):
                joiner = ('WHERE', 'AND', 'COMMA')
                if c.kind == 'AGG' and c.val in ('max', 'min') and cond_t[i + 1].kind == 'FIELD' and \
                        (i == 0 or cond_t[i - 1].kind in joiner) and \
                        (i + 2 == len(cond_t) or cond_t[i + 2].kind in joiner):
                    if order:
                        raise self.p('question', [c, cond_t[i + 1]], 'ranked by this, or by the sort order?',
                                     'two orderings in one sentence')
                    order = (cond_t[i + 1].val, c.val == 'max')
                    lo = i - 1 if i else i
                    cond_t = cond_t[:lo] + cond_t[i + 2:]
                    while cond_t and cond_t[0].kind in joiner:
                        cond_t = cond_t[1:]
                    cond_t = cond_t or None
                    nums = [m for m in main if m.kind == 'NUM']
                    if limit is None and len(nums) == 1:
                        limit = nums[0].val
                        main = [m for m in main if m.kind != 'NUM']
                    if limit is None:
                        limit = 1
                    break
        if len(main) > 2 and main[0].kind == 'FIELD' and main[1].kind == 'COMMA' and \
                any(c.kind == 'FIELD' and c.val == main[0].val for c in main[2:]):
            main = main[2:]             # "The age of every customer, double it."

        def is_verb(c, *vals):
            return c.kind == 'VERB' and c.val in vals

        if any(is_verb(c, 'addv', 'insert') for c in main) and not any(c.kind in ('FIELD', 'NUM') for c in main):
            owner = lambda c: c.kind == 'PARAM' and c.val in coll.fields and coll.fields[c.val].ref    # noqa: E731
            if any(owner(c) for c in main):         # "Add a phone to a given customer."
                main = [c for c in main if not owner(c) and c.kind not in ('TO', 'FROM')]
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
            if k is None:               # "show the orders price is 10": a bare trailing condition
                k = next((j for j in range(2, len(main) - 1)
                          if main[j].kind == 'IS' and main[j - 1].kind == 'FIELD'), None)
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
        if limit is not None:
            if act == 'find':
                act = 'show'
            if upd or act in ('remove', 'keep') or any(c.kind == 'AGG' for c in rest) or limit < 1:
                raise self.p('error', sent, 'a limit only works when showing records in this version',
                             hint='e.g. "Show the top 3 customers by salary."')

        if other is not None and not upd:
            raise self.p('error', other[0], '"otherwise" only goes with a change or a calculation in this version',
                         hint='e.g. "Set the level to 2 if the score is over 100, otherwise 1."')
        if upd:
            T.kind, T.assigns = 'update', self.parse_updates(main, coll)
            if order:
                raise self.p('error', sent, 'a change cannot be sorted')
            if other is not None:
                if where is None or len(T.assigns) != 1:
                    raise self.p('error', other[0], '"otherwise" needs one change and one "if" before it',
                                 hint='e.g. "Set the level to 2 if the score is over 100, otherwise 1."')
                f, e = T.assigns[0]
                T.assigns, T.where = [(f, ('if', where, e, self.either(other[1:], coll, f)))], None
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
            rest = [c for c in rest if c.kind != 'COMMA']
            if rest:
                raise self.leftover(rest)
            if key is None and where is not None and where[0] == 'cmp' and where[1] == 'eq' and \
                    where[2][0] == 'field' and where[3] == ('param', where[2][1]):
                key, T.where = where[2][1], None
            if key:
                T.kind, T.key = ('find' if act == 'find' else 'remove_key'), key
            elif where is not None:
                T.kind = 'list' if act == 'find' else 'remove_where'
            elif act == 'remove' and everyone:
                T.kind = 'remove_where'     # "Remove all customers.": said outright, so nothing to ask
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
            elif c.kind == 'PFIELD':
                fs.append('.'.join(c.val))
            elif c.kind not in ('COMMA', 'AND'):
                raise self.leftover([c])
        if not acts and not fs and where is None and not order:
            raise self.p('error', sent, f'I see this is about {coll.label}, but not what to do with them')
        T.kind, T.fields, T.order, T.limit = 'list', (fs or None), order, limit
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
            b = index_of(content, 'BY')
            if order is None and b is not None and b + 1 < len(content) and content[b + 1].kind == 'FIELD':
                order = content[b + 1].val          # "alphabetically by name"
                content = content[:b] + content[b + 2:]
                d = index_of(content, 'DIR')
            if order is None:
                raise self.p('question', content[d], f'"{content[d].text}" by which property?', self.could_be(coll))
            desc = content[d].val == 'desc'
            content = content[:d] + content[d + 1:]
        return ((order, desc) if order else None), content

    def between(self, content):
        """'between 18 and 30' -> 'at least 18 and at most 30' (the property carries over)."""
        b = index_of(content, 'BETWEEN')
        if b is None:
            return content
        a = index_of(content, 'AND', start=b)
        if a is None:
            raise self.p('error', content[b], 'between what and what?', hint='e.g. "between 18 and 30"')
        if b and content[b - 1].kind == 'NOT':      # outside the range: below the low end OR above the high end
            return (content[:b - 1] + [CT('CMP', 'lt', content[b].toks)] + content[b + 1:a] +
                    [CT('OR', None, content[a].toks), CT('CMP', 'gt', content[a].toks)] +
                    self.between(content[a + 1:]))
        return (content[:b] + [CT('CMP', 'ge', content[b].toks)] + content[b + 1:a + 1] +
                [CT('CMP', 'le', content[a].toks)] + self.between(content[a + 1:]))

    def take_limit(self, content, coll, order):
        limit = None
        i = index_of(content, 'TOP')
        if i is not None:
            desc, j, limit = content[i].val == 'desc', i + 1, 1
            if j < len(content) and content[j].kind == 'NUM':
                limit, j = content[j].val, j + 1
            head, tail = content[:i], content[j:]
            if order:
                order = (order[0], desc)
            else:
                b = index_of(tail, 'BY')
                if b is None or b + 1 >= len(tail) or tail[b + 1].kind != 'FIELD':
                    raise self.p('question', content[i:j], f'{content[i].text} by which property?',
                                 self.could_be(coll), f'e.g. "the top 3 {coll.label} by {next(iter(coll.fields), "score")}"')
                order = (tail[b + 1].val, desc)
                tail = tail[:b] + tail[b + 2:]
            content = head + tail
        i = index_of(content, 'FIRST')
        if i is not None:
            j, limit = i + 1, 1
            if j < len(content) and content[j].kind == 'NUM':
                limit, j = content[j].val, j + 1
            if not order and not coll.ordered:
                raise self.p('question', content[i:j], 'first in what order?',
                             f'{coll.label} are not kept in any particular order',
                             f'say "sorted by ...", or declare "Keep {coll.label} in the order they were added."')
            content = content[:i] + content[j:]
        return order, limit, content

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
            elif c.kind == 'NUM' and j + 1 < len(content) and content[j + 1].kind == 'TYPE':
                pass                    # "take two numbers a and b"
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
        held = [c for c in rest if c.kind == 'VALUE']
        if held and rest and (rest[0].kind in ('VERB', 'SCALE', 'HALVE') or any(c.kind == 'BECOMES' for c in rest)):
            raise self.p('question', held, f'should "{held[0].text}" change, or do you just want the result?',
                         'this could be read either way',
                         f'to change it, say e.g. "increase the {held[0].text} by a given {params[0]}"')
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
            T.expr = self.either(rest, Collection('input', 'inputs'))
        return P(T)

    # ------------------------------------------------------------------ finishing
    def emit(self, T, coll=None):
        seen = []
        if coll is self.state:
            if T.kind not in ('update', 'list') or T.order or T.limit is not None:
                raise self.p('error', self.cur, 'a single value can be shown or changed, nothing else',
                             hint='e.g. "Show the score." or "Increase the score by a given amount."')
            if T.kind == 'list' and not T.fields:
                T.fields = list(coll.fields)
        if T.kind == 'calc':
            pass
        elif T.kind == 'add':
            T.params = list(coll.fields)
        elif T.kind in ('find', 'remove_key'):
            T.params = [T.key]
        else:
            for e in task_exprs(T):
                if e[0] == 'param' and e[1] not in seen:
                    seen.append(e[1])
            T.params = seen
        if self.trigger:
            on, self.trigger = self.trigger, None
            if T.params:
                raise self.p('error', self.cur, f'there is nobody to give the {T.params[0]} here',
                             'this is not a command, so nothing can be handed to it')
            plain = T.kind == 'list' and not T.order and T.limit is None
            if on[0] == 'end':
                if not plain or T.where is None:
                    raise self.p('error', self.cur, 'when is the game over?',
                                 hint='e.g. "The game is over when the lives are 0."')
                T.kind, T.name, T.named, T.fields = 'end', f'end {len(self.prog.ends) + 1}', True, None
                self.prog.ends.append(T)
                return 'the game is over when ' + fmt_cond(T.where) + \
                    ('' if T.coll == STATE else f', for any {T.coll}')
            if on[0] == 'draw':
                if not plain:
                    raise self.p('error', self.cur, 'I can\'t tell what should be drawn',
                                 hint='e.g. Draw each rock at its x and y as "#".')
                for e in (x for side in on[1] for x in walk_expr(side)):
                    if e[0] == 'field' and e[1] not in coll.fields:
                        raise self.p('error', self.cur, f'{coll.label} has no property "{e[1]}"', self.could_be(coll))
                T.kind, T.name, T.named, T.fields = 'draw', f'draw {len(self.prog.draws) + 1}', True, None
                T.at, T.glyph = on[1], on[2]
                self.prog.draws.append(T)
                w = f' where {fmt_cond(T.where)}' if T.where else ''
                return f'draw "{T.glyph}" at ({fmt_expr(T.at[0])}, {fmt_expr(T.at[1])})' + \
                    ('' if T.coll == STATE else f' for each {T.coll}') + w
            if T.kind not in ('update', 'remove_where'):
                raise self.p('error', self.cur, 'what should change?',
                             'something that happens by itself has to change or remove something',
                             'e.g. "Every second, the score increases by 1."')
            T.on, T.named = on, True
            T.name = f'{"timer" if on[0] == "every" else "key"} {len(self.prog.events) + 1}'
            self.prog.events.append(T)
            return fmt_event(T)
        if self.as_rule:
            self.as_rule = False
            if T.params and T.kind != 'add':
                raise self.p('error', self.cur, f'a rule applies by itself, so it cannot wait for a given {T.params[0]}',
                             hint='name it to make it a capability instead: "Promote: ..."')
            if T.kind not in ('update', 'remove_where') or (T.where is None and
                                                            not any(e[0] == 'if' for e in task_exprs(T))):
                raise self.p('error', self.cur, 'a rule says what changes when something becomes true',
                             'this one changes nothing, or has no condition',
                             'e.g. "When a player\'s score is over 100, their level becomes 2."')
            T.name, T.named = f'rule {len(self.prog.rules) + 1}', True
            self.prog.rules.append(T)
            return 'rule: ' + canon(T)
        self.prog.tasks.append(T)
        return canon(T)

    def derived_name(self, t):
        def first_field(c):
            if c[0] != 'cmp':
                return first_field(c[1])
            return next((e[-1] for side in (c[2], c[3]) for e in walk_expr(side) if e[0] in ('field', 'pfield')),
                        'value')
        if t.kind == 'update':
            f, e = t.assigns[0]
            verb = 'set'
            if e[0] == 'bin' and e[2] == ('field', f):
                verb = {'mul': 'multiply', 'add': 'increase', 'sub': 'decrease', 'div': 'divide', 'rem': 'mod'}[e[1]]
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
            n = f'{"keep" if t.fn == "keep" else "remove"}-where-{first_field(t.where)}' if t.where else 'remove-all'
        elif t.kind == 'list':
            n = 'list' + ''.join(f'-{f}' for f in t.fields or [])
            if t.where:
                n += f'-where-{first_field(t.where)}'
            if t.order:
                n += f'-by-{t.order[0]}'
            if t.limit is not None:
                n = f'top-{t.limit}' + n[4:]
        elif t.kind == 'agg':
            n = {'avg': 'average', 'sum': 'total', 'count': 'count', 'max': 'largest', 'min': 'smallest'}[t.fn]
            if t.field:
                n += f'-{t.field}'
        else:
            n = 'calc'
        if t.coll == STATE:
            return '-'.join(t.fields) if t.kind == 'list' else n
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
        if self.state.fields:
            self.prog.collections[STATE] = self.state


def parse(text, filename='<intent>'):
    p = Parser(text, filename)
    prog = p.parse()
    return prog, p.diags, p
