"""Intent IR + plan -> LLVM IR text. No other programming language sits in between.

The generated module is a small command server: it reads one command per line on stdin
("<capability> <comma-separated arguments>") and writes results to stdout. It calls libc
for I/O, memory and sorting; everything else (records, hash indexes, loops, filters,
aggregates) is emitted here.
"""
from .interp import ROUNDS, UNSETTLED
import sys

from .ir import (BAD_SEED, BAD_WAIT, CHANCE_ADD, CHANCE_MUL, COLOUR_NAMES, ENTER_PLAY, INK_LETTER, KEY_CODES, LEAVE_PLAY, LONGEST_STEP,
                 LONGEST_WAIT, MUTATING, OVER, OVER_HINT, RGB, SINE, STATE, TEXT_OPS, TOO_SMALL, builtins, canon, decides_first,
                 colour_value, fmt_cond, fmt_event, inked as has_ink, fmt_expr, room, usage, uses_chance, walk_cond_exprs)
from .plan import narrow_settle
from .web import HTML, MOST, PLAIN, ROOM, page, title_of

LL = {'int': 'i64', 'text': 'ptr'}
FNV_OFFSET = -3750763034362895579      # 14695981039346656037 as a signed 64-bit value
FNV_PRIME = 1099511628211
MIX = -7046029254386353131             # 0x9E3779B97F4A7C15 as a signed 64-bit value
ICMP = {'gt': 'sgt', 'ge': 'sge', 'lt': 'slt', 'le': 'sle', 'eq': 'eq', 'ne': 'ne'}

DECLS = '''declare ptr @fdopen(i32, ptr)
declare i64 @getline(ptr, ptr, ptr)
declare i32 @printf(ptr, ...)
declare i32 @puts(ptr)
declare ptr @malloc(i64)
declare ptr @calloc(i64, i64)
declare ptr @realloc(ptr, i64)
declare void @free(ptr)
declare ptr @strdup(ptr)
declare i32 @strcmp(ptr, ptr)
declare ptr @strchr(ptr, i32)
declare ptr @strsep(ptr, ptr)
declare i64 @strtoll(ptr, ptr, i32)
declare i32 @snprintf(ptr, i64, ptr, ...)
declare ptr @memmove(ptr, ptr, i64)
declare void @qsort(ptr, i64, i64, ptr)
declare double @llvm.sqrt.f64(double)
declare ptr @strstr(ptr, ptr)
declare i32 @strncmp(ptr, ptr, i64)
declare i64 @strlen(ptr)
declare ptr @fopen(ptr, ptr)
declare i32 @fclose(ptr)
declare i32 @fflush(ptr)
declare i32 @fputs(ptr, ptr)
declare i32 @fputc(i32, ptr)
declare i32 @dup(i32)
declare i32 @dup2(i32, i32)
declare i32 @close(i32)
declare i32 @open(ptr, i32, ...)
'''
LIVE_DECLS = '''declare ptr @memset(ptr, i32, i64)
declare i32 @isatty(i32)
declare i32 @system(ptr)
declare i32 @poll(ptr, i64, i32)
declare i64 @read(i32, ptr, i64)
declare i32 @gettimeofday(ptr, ptr)
declare ptr @signal(i32, ptr)
declare void @exit(i32)
declare i32 @fprintf(ptr, ptr, ...)
declare i32 @tcgetattr(i32, ptr)
declare i32 @tcsetattr(i32, i32, ptr)
declare i32 @ioctl(i32, i64, ...)
declare i32 @putchar(i32)
'''
NET_DECLS = '''declare i32 @socket(i32, i32, i32)
declare i32 @bind(i32, ptr, i32)
declare i32 @listen(i32, i32)
declare i32 @accept(i32, ptr, ptr)
declare i32 @setsockopt(i32, i32, i32, ptr, i32)
declare ptr @strcasestr(ptr, ptr)
declare ptr @memchr(ptr, i32, i64)
'''


def g(*parts):
    return '@"' + '.'.join(parts) + '"'


class Fn:
    def __init__(self, name, ret='void', params='', comment=''):
        self.name, self.ret, self.params, self.comment = name, ret, params, comment
        self.allocas, self.lines, self.n = [], [], 0

    def t(self):
        self.n += 1
        return f'%t{self.n}'

    def lab(self, base):
        self.n += 1
        return f'{base}{self.n}'

    def e(self, s):
        self.lines.append('  ' + s)

    def r(self, s):
        v = self.t()
        self.e(f'{v} = {s}')
        return v

    def at(self, label):
        self.lines.append(f'{label}:')

    def br(self, l):
        self.e(f'br label %{l}')

    def cbr(self, c, a, b):
        self.e(f'br i1 {c}, label %{a}, label %{b}')

    def var(self, ty, init=None):
        self.n += 1
        v = f'%v{self.n}'
        self.allocas.append(f'  {v} = alloca {ty}')
        if init is not None:
            self.store(ty, init, v)
        return v

    def load(self, ty, p):
        return self.r(f'load {ty}, ptr {p}')

    def store(self, ty, v, p):
        self.e(f'store {ty} {v}, ptr {p}')

    def text(self):
        head = ''.join(f'; {l}\n' for l in self.comment.split('\n') if l)
        return (f'{head}define internal {self.ret} {self.name}({self.params}) {{\nentry:\n' +
                '\n'.join(self.allocas + self.lines) + '\n}\n')


class Gen:
    def __init__(self, prog, plan):
        self.prog, self.plan = prog, plan
        self.strs, self.globals, self.fns = {}, [], []
        self.others = {}                # conditions about another collection -> the function that answers each
        self.figures_made = set()       # the pictures drawn by hand that already have a painting function
        self.made = set()               # helper functions emitted once, when first needed
        self.outers = []                # while such a function is written: the collection it is asked from

    # ------------------------------------------------------------------ helpers
    def cstr(self, s):
        if s not in self.strs:
            b = s.encode() + b'\0'
            body = ''.join(chr(c) if 32 <= c < 127 and c not in (34, 92) else '\\%02X' % c for c in b)
            name = f'@.s{len(self.strs)}'
            self.strs[s] = name
            self.globals.append(f'{name} = private unnamed_addr constant [{len(b)} x i8] c"{body}"')
        return self.strs[s]

    def fn(self, *a, **k):
        f = Fn(*a, **k)
        self.fns.append(f)
        return f

    def puts(self, f, s):
        f.e(f'call i32 @puts(ptr {self.cstr(s)})')

    def printf(self, f, fmt, args=''):
        f.e(f'call i32 (ptr, ...) @printf(ptr {self.cstr(fmt)}{", " + args if args else ""})')

    def rec(self, f, c, row):
        data = f.load('ptr', g(c.name, 'data'))
        return f.r(f'getelementptr %"{c.name}", ptr {data}, i64 {row}')

    def fptr(self, f, c, rec, name):
        i = list(c.fields).index(name)
        return f.r(f'getelementptr %"{c.name}", ptr {rec}, i32 0, i32 {i}')

    def fload(self, f, c, rec, name):
        return f.load(LL[c.fields[name].type], self.fptr(f, c, rec, name))

    def eq(self, f, ty, a, b):
        if ty == 'int':
            return f.r(f'icmp eq i64 {a}, {b}')
        return f.r(f'icmp eq i32 {f.r(f"call i32 @strcmp(ptr {a}, ptr {b})")}, 0')

    def rows(self, f, c, body, count=None):
        i = f.var('i64', '0')
        head, bl, cont, end = f.lab('head'), f.lab('body'), f.lab('cont'), f.lab('end')
        f.br(head)
        f.at(head)
        iv = f.load('i64', i)
        n = count if count is not None else f.load('i64', g(c.name, 'len'))
        f.cbr(f.r(f'icmp slt i64 {iv}, {n}'), bl, end)
        f.at(bl)
        body(iv, cont)
        f.br(cont)
        f.at(cont)
        f.store('i64', f.r(f'add i64 {iv}, 1'), i)
        f.br(head)
        f.at(end)

    def guard(self, f, cond, cont):
        yes = f.lab('yes')
        f.cbr(cond, yes, cont)
        f.at(yes)

    # ------------------------------------------------------------------ expressions
    def expr(self, f, e, c, rec, vals):
        k = e[0]
        if k == 'num':
            return str(e[1]), 'int'
        if k == 'str':
            return self.cstr(e[1]), 'text'
        if k == 'field':
            return self.fload(f, c, rec, e[1]), c.fields[e[1]].type
        if k == 'param':
            return vals[e[1]]
        if k == 'pfield':               # follow the link: find the owner by its key, read its property
            p = self.prog.collections[c.fields[e[1]].ref]
            key = self.prog.key_of(p.name)
            row = f.r(f'call i64 {g(p.name, key.name, "find")}({LL[key.type]} {self.fload(f, c, rec, e[1])})')
            return self.fload(f, p, self.rec(f, p, row), e[2]), p.fields[e[2]].type
        if k == 'value':                # a single value lives in the one record of the hidden collection
            S = self.prog.collections[STATE]
            return self.fload(f, S, self.rec(f, S, '0'), e[1]), S.fields[e[1]].type
        if k == 'rand':
            return f.r(f'call i64 @rand(i64 {e[1]}, i64 {e[2] - e[1] + 1})'), 'int'
        if k == 'outer':                # the record this was asked from
            o = self.outers[-1]
            return self.fload(f, o, '%outer', e[1]), o.fields[e[1]].type
        if k == 'agg':
            return f.r(f'call i64 {self.other(e, c)}(ptr {rec or "null"})'), 'int'
        if k == 'dec':                  # hundredths
            return str(e[1]), 'int'
        if k == 'cents':
            return f.r(f'mul i64 {self.expr(f, e[1], c, rec, vals)[0]}, 100'), 'int'
        if k == 'fn':
            a = self.expr(f, e[2], c, rec, vals)[0]
            if e[1] == 'cos':
                return f.r(f'call i64 @sine(i64 {f.r(f"add i64 {a}, 9000")})'), 'int'
            if e[1] == 'abs':
                return f.r(f'select i1 {f.r(f"icmp slt i64 {a}, 0")}, i64 {f.r(f"sub i64 0, {a}")}, i64 {a}'), 'int'
            if e[1] == 'dround':
                return f.r(f'call i64 @rdiv(i64 {a}, i64 100)'), 'int'
            if e[1] == 'dtrunc':
                return f.r(f'sdiv i64 {a}, 100'), 'int'
            name = {'sin': '@sine', 'sqrt': '@root', 'dsqrt': '@droot'}[e[1]]
            return f.r(f'call i64 {name}(i64 {a})'), 'int'
        if k == 'if':                   # only the chosen side is worked out (the other may divide by zero)
            yes, no, done = f.lab('then'), f.lab('else'), f.lab('fi')
            f.cbr(self.cond(f, e[1], c, rec, vals), yes, no)
            f.at(yes)
            a, ty = self.expr(f, e[2], c, rec, vals)
            slot = f.var(LL[ty])
            f.store(LL[ty], a, slot)
            f.br(done)
            f.at(no)
            b, _ = self.expr(f, e[3], c, rec, vals)
            f.store(LL[ty], b, slot)
            f.br(done)
            f.at(done)
            return f.load(LL[ty], slot), ty
        a, _ = self.expr(f, e[2], c, rec, vals)
        b, _ = self.expr(f, e[3], c, rec, vals)
        if e[1] == 'dmul':              # hundredths times hundredths, back to hundredths
            return f.r(f'call i64 @rdiv(i64 {f.r(f"mul i64 {a}, {b}")}, i64 100)'), 'int'
        if e[1] == 'rdiv':
            return f.r(f'call i64 @rdiv(i64 {a}, i64 {b})'), 'int'
        if e[1] in ('div', 'rem') and e[3][0] != 'num':
            # the divisor is known not to be zero here; -1 is done by hand because the
            # most negative number divided by -1 does not fit
            neg = f.r(f'icmp eq i64 {b}, -1')
            q = f.r(f'{"sdiv" if e[1] == "div" else "srem"} i64 {a}, {f.r(f"select i1 {neg}, i64 1, i64 {b}")}')
            flipped = f.r(f'sub i64 0, {a}') if e[1] == 'div' else '0'
            return f.r(f'select i1 {neg}, i64 {flipped}, i64 {q}'), 'int'
        if e[1] == 'div':
            if e[3][1] == -1:
                return f.r(f'sub i64 0, {a}'), 'int'
            return f.r(f'sdiv i64 {a}, {b}'), 'int'
        if e[1] == 'rem':
            return ('0' if e[3][1] == -1 else f.r(f'srem i64 {a}, {b}')), 'int'
        return f.r(f'{e[1]} i64 {a}, {b}'), 'int'

    def cond(self, f, cnd, c, rec, vals):
        if cnd is None:
            return 'true'
        if cnd[0] == 'cmp':
            a, ty = self.expr(f, cnd[2], c, rec, vals)
            b, _ = self.expr(f, cnd[3], c, rec, vals)
            if cnd[1] in TEXT_OPS:
                op = cnd[1].lstrip('n') if cnd[1] != 'nhas' else 'has'
                if cnd[1] in ('has', 'nhas'):
                    hit = f.r(f'icmp ne ptr {f.r(f"call ptr @strstr(ptr {a}, ptr {b})")}, null')
                elif op == 'starts':
                    n = f.r(f'call i64 @strlen(ptr {b})')
                    hit = f.r(f'icmp eq i32 {f.r(f"call i32 @strncmp(ptr {a}, ptr {b}, i64 {n})")}, 0')
                else:
                    la, lb = f.r(f'call i64 @strlen(ptr {a})'), f.r(f'call i64 @strlen(ptr {b})')
                    fits = f.r(f'icmp sge i64 {la}, {lb}')
                    off = f.r(f'select i1 {fits}, i64 {f.r(f"sub i64 {la}, {lb}")}, i64 0')
                    tail = f.r(f'getelementptr i8, ptr {a}, i64 {off}')
                    same = f.r(f'icmp eq i32 {f.r(f"call i32 @strcmp(ptr {tail}, ptr {b})")}, 0')
                    hit = f.r(f'and i1 {fits}, {same}')
                return f.r(f'xor i1 {hit}, true') if cnd[1].startswith('n') else hit
            if ty == 'int':
                return f.r(f'icmp {ICMP[cnd[1]]} i64 {a}, {b}')
            return f.r(f'icmp {ICMP[cnd[1]]} i32 {f.r(f"call i32 @strcmp(ptr {a}, ptr {b})")}, 0')
        if cnd[0] in ('any', 'none'):
            hit = f.r(f'call i1 {self.other(cnd, c)}(ptr {rec or "null"})')
            return hit if cnd[0] == 'any' else f.r(f'xor i1 {hit}, true')
        a = self.cond(f, cnd[1], c, rec, vals)
        if any(e[0] == 'rand' for e in walk_cond_exprs(cnd[2])):
            # chance is only drawn when the first part leaves the answer open, exactly as the meaning says
            slot = f.var('i1')
            f.store('i1', a, slot)
            more, done = f.lab('more'), f.lab('known')
            f.cbr(a, *((more, done) if cnd[0] == 'and' else (done, more)))
            f.at(more)
            f.store('i1', self.cond(f, cnd[2], c, rec, vals), slot)
            f.br(done)
            f.at(done)
            return f.load('i1', slot)
        b = self.cond(f, cnd[2], c, rec, vals)
        return f.r(f'{cnd[0]} i1 {a}, {b}')

    def other(self, node, frm):
        """The function that looks into another collection for one record of this one: "is there
        any ...?" or "how many / the total / the largest ...". %outer is the record that asks."""
        key = (repr(node), frm.name if frm else None)
        if key not in self.others:
            agg = node[0] == 'agg'
            name = self.others[key] = g('count' if agg else 'any', str(len(self.others) + 1))
            c = self.prog.collections[node[2] if agg else node[1]]
            h = self.fn(name, 'i64' if agg else 'i1', 'ptr %outer',
                        comment=fmt_expr(node) if agg else f'is there a {c.name} with {fmt_cond(node[2])}?')
            self.outers.append(frm)
            if agg:
                acc, cnt = h.var('i64', '0'), h.var('i64', '0')

                def body(i, cont):
                    rec = self.rec(h, c, i)
                    self.guard(h, self.cond(h, node[4], c, rec, {}), cont)
                    cv = h.load('i64', cnt)
                    if node[1] != 'count':
                        v, a = self.fload(h, c, rec, node[3]), h.load('i64', acc)
                        if node[1] == 'sum':
                            nv = h.r(f'add i64 {a}, {v}')
                        else:
                            better = h.r(f'icmp {"sgt" if node[1] == "max" else "slt"} i64 {v}, {a}')
                            take = h.r(f'or i1 {better}, {h.r(f"icmp eq i64 {cv}, 0")}')
                            nv = h.r(f'select i1 {take}, i64 {v}, i64 {a}')
                        h.store('i64', nv, acc)
                    h.store('i64', h.r(f'add i64 {cv}, 1'), cnt)
                self.rows(h, c, body)
                h.e(f'ret i64 {h.load("i64", cnt if node[1] == "count" else acc)}')
            else:
                def body(i, cont):
                    hit = h.lab('hit')
                    h.cbr(self.cond(h, node[2], c, self.rec(h, c, i), {}), hit, cont)
                    h.at(hit)
                    h.e('ret i1 true')
                    h.at(h.lab('dead'))
                self.rows(h, c, body)
                h.e('ret i1 false')
            self.outers.pop()
        return self.others[key]

    def decided(self, f, t, c, vals):
        """One byte per record: does the condition hold for it, as things stand before anything changes?"""
        n = f.load('i64', g(c.name, 'len'))
        marks = f.r(f'call ptr @malloc(i64 {f.r(f"add i64 {n}, 1")})')

        def body(i, cont):
            hit = self.cond(f, t.where, c, self.rec(f, c, i), vals)
            f.store('i8', f.r(f'zext i1 {hit} to i8'), f.r(f'getelementptr i8, ptr {marks}, i64 {i}'))
        self.rows(f, c, body)
        return marks

    def chance(self):
        self.globals.append('@chance = internal global i64 0    ; where the run of chance stands')
        f = self.fn('@rand', 'i64', 'i64 %lo, i64 %span',
                    'a number drawn by chance from lo upward, one of span; the same seed draws the same numbers')
        n = f.r(f'add i64 {f.r(f"mul i64 {f.load("i64", "@chance")}, {CHANCE_MUL}")}, {CHANCE_ADD}')
        f.store('i64', n, '@chance')
        f.store('i32', '1', '@dirty')       # a command that drew a number has to be replayed to draw it again
        f.e(f'ret i64 {f.r(f"add i64 %lo, {f.r(f"urem i64 {f.r(f"lshr i64 {n}, 33")}, %span")}")}')

    def visit(self, f, t, c, body, vals):
        """Run body on every record the task has to look at: all of them, or the one the index finds."""
        pick = self.plan.picks.get(t.name)
        if not pick:
            return self.rows(f, c, body)
        v, ty = self.expr(f, pick[1], c, None, vals)
        row = f.r(f'call i64 {g(c.name, pick[0], "find")}({LL[ty]} {v})')
        hit, cont = f.lab('hit'), f.lab('cont')
        f.cbr(f.r(f'icmp sge i64 {row}, 0'), hit, cont)
        f.at(hit)
        f.store('i64', row, '@touched')
        body(row, cont)
        f.br(cont)
        f.at(cont)

    def update_body(self, f, t, c, vals, rule, marks=None):
        def body(i, cont):
            rec = self.rec(f, c, i)
            if marks:
                m = f.load('i8', f.r(f'getelementptr i8, ptr {marks}, i64 {i}'))
                self.guard(f, f.r(f'icmp ne i8 {m}, 0'), cont)
            else:
                self.guard(f, self.cond(f, t.where, c, rec, vals), cont)
            for name, e in t.assigns:
                v, ty = self.expr(f, e, c, rec, vals)
                p = self.fptr(f, c, rec, name)
                if rule:
                    old = f.load(LL[ty], p)
                    self.mark(f, f.r(f'icmp ne i64 {old}, {v}') if ty == 'int' else
                              f.r(f'icmp ne i32 {f.r(f"call i32 @strcmp(ptr {old}, ptr {v})")}, 0'))
                if ty == 'text':
                    v = f.r(f'call ptr @strdup(ptr {v})')
                    f.e(f'call void @free(ptr {f.load("ptr", p)})')
                f.store(LL[ty], v, p)
        return body

    # ------------------------------------------------------------------ collection runtime
    def collection(self, c, cp):
        C = c.name
        size = 8 * len(c.fields)
        self.globals.append(f'%"{C}" = type {{ ' + ', '.join(LL[f.type] for f in c.fields.values()) + ' }')
        for name, ty, init in (('data', 'ptr', 'null'), ('len', 'i64', '0'), ('cap', 'i64', '0')):
            self.globals.append(f'{g(C, name)} = internal global {ty} {init}')

        f = self.fn(g(C, 'grow'), comment=f'{C}: make room for one more record')
        n, cap = f.load('i64', g(C, 'len')), f.load('i64', g(C, 'cap'))
        full, done = f.lab('full'), f.lab('done')
        f.cbr(f.r(f'icmp eq i64 {n}, {cap}'), full, done)
        f.at(full)
        nc = f.r(f'select i1 {f.r(f"icmp eq i64 {cap}, 0")}, i64 16, i64 {f.r(f"shl i64 {cap}, 1")}')
        data = f.load('ptr', g(C, 'data'))
        nd = f.r(f'call ptr @realloc(ptr {data}, i64 {f.r(f"mul i64 {nc}, {size}")})')
        f.store('ptr', nd, g(C, 'data'))
        f.store('i64', nc, g(C, 'cap'))
        f.br(done)
        f.at(done)
        f.e('ret void')

        f = self.fn(g(C, 'free'), params='ptr %rec', comment=f'{C}: release the text a record owns')
        for fl in c.fields.values():
            if fl.type == 'text':
                f.e(f'call void @free(ptr {self.fload(f, c, "%rec", fl.name)})')
        f.e('ret void')

        f = self.fn(g(C, 'print'), params='ptr %rec', comment=f'{C}: write one record as a line')
        self.print_fields(f, c, '%rec', list(c.fields))
        f.e('ret void')

        for fl in c.unique_fields():
            if fl.name in cp.indexes:
                self.index(c, fl)
            else:
                self.scan_find(c, fl)

        for k in cp.orders:
            self.ordered(c, c.fields[k])

        f = self.fn(g(C, 'reindex'), comment=f'{C}: rebuild every index after rows moved')
        for k in cp.indexes:
            f.e(f'call void {g(C, k, "rebuild")}()')
        f.e('ret void')

        if cp.removal:
            self.remove_row(c, cp, size)

    def print_fields(self, f, c, rec, names):
        got = []
        for n in names:
            if '.' in n:
                ref, name = n.split('.')
                v, ty = self.expr(f, ('pfield', ref, name), c, rec, {})
                fl = self.prog.collections[c.fields[ref].ref].fields[name]
            else:
                v, ty = self.expr(f, ('field', n), c, rec, {})
                fl = c.fields[n]
            got.append(self.shown(f, v, ty, fl.dec))
        fmt = ','.join('%lld' if ty == 'int' else '%s' for _, ty in got) + '\n'
        self.printf(f, fmt, ', '.join(f'{LL[ty]} {v}' for v, ty in got))

    def shown(self, f, v, ty, dec):
        """A value ready for printf: a decimal number becomes its text, 12.50."""
        if not dec:
            return v, ty
        buf = f.var('[32 x i8]')
        return f.r(f'call ptr @decstr(i64 {v}, ptr {buf})'), 'text'

    def writer(self, inked):
        """@write(text, x, y, ink): every plain character of a text on the board, rightward from (x, y)."""
        if '@write' in self.figures_made:
            return '@write'
        self.figures_made.add('@write')
        w, h = self.prog.board
        f = self.fn('@write', 'void', 'ptr %s, i64 %x, i64 %y, i32 %ink', 'write a text on the board, one character a cell')
        i = f.var('i64', '0')
        head, body, nxt, done = f.lab('head'), f.lab('char'), f.lab('next'), f.lab('done')
        f.br(head)
        f.at(head)
        iv = f.load('i64', i)
        ch = f.load('i8', f.r(f'getelementptr i8, ptr %s, i64 {iv}'))
        f.cbr(f.r(f'icmp eq i8 {ch}, 0'), done, body)
        f.at(body)
        x = f.r(f'add i64 %x, {iv}')
        plain = f.r(f'icmp ult i8 {f.r(f"sub i8 {ch}, 33")}, 94')
        inx = f.r(f'and i1 {f.r(f"icmp sge i64 {x}, 1")}, {f.r(f"icmp sle i64 {x}, {w}")}')
        iny = f.r(f'and i1 {f.r("icmp sge i64 %y, 1")}, {f.r(f"icmp sle i64 %y, {h}")}')
        put = f.lab('put')
        f.cbr(f.r(f'and i1 {plain}, {f.r(f"and i1 {inx}, {iny}")}'), put, nxt)
        f.at(put)
        pos = f.r(f'add i64 {f.r(f"mul i64 {f.r("sub i64 %y, 1")}, {w}")}, {f.r(f"sub i64 {x}, 1")}')
        f.store('i8', ch, f.r(f'getelementptr i8, ptr @grid, i64 {pos}'))
        if inked:
            f.store('i32', '%ink', f.r(f'getelementptr i32, ptr @ink, i64 {pos}'))
        f.br(nxt)
        f.at(nxt)
        f.store('i64', f.r(f'add i64 {iv}, 1'), i)
        f.br(head)
        f.at(done)
        f.e('ret void')
        return '@write'

    def figure(self, name, inked):
        """@figure.<name>(x, y): paint a picture drawn by hand with its top left corner at (x, y); only the
        cells that land on the board are painted. Made once, from tables of its cells."""
        fn = g('figure', name)
        if fn in self.figures_made:
            return fn
        self.figures_made.add(fn)
        cells = self.prog.figures[name].cells()
        n, (w, h) = len(cells), self.prog.board
        for tag, ty, vals in (('dx', 'i64', [c[0] for c in cells]), ('dy', 'i64', [c[1] for c in cells]),
                              ('ch', 'i8', [ord(c[2]) for c in cells]),
                              ('ink', 'i32', [colour_value(c[3]) if c[3] else 0 for c in cells])):
            self.globals.append(f'{g("figure", name, tag)} = internal constant [{n} x {ty}] [' +
                                ', '.join(f'{ty} {v}' for v in vals) + ']')
        f = self.fn(fn, 'void', 'i64 %x, i64 %y', f'paint the picture "{name}" at (x, y)')

        def cell(k, cont):
            def at(tag, ty):
                return f.load(ty, f.r(f'getelementptr [{n} x {ty}], ptr {g("figure", name, tag)}, i64 0, i64 {k}'))
            x = f.r(f'add i64 %x, {at("dx", "i64")}')
            y = f.r(f'add i64 %y, {at("dy", "i64")}')
            inx = f.r(f'and i1 {f.r(f"icmp sge i64 {x}, 1")}, {f.r(f"icmp sle i64 {x}, {w}")}')
            iny = f.r(f'and i1 {f.r(f"icmp sge i64 {y}, 1")}, {f.r(f"icmp sle i64 {y}, {h}")}')
            self.guard(f, f.r(f'and i1 {inx}, {iny}'), cont)
            pos = f.r(f'add i64 {f.r(f"mul i64 {f.r(f"sub i64 {y}, 1")}, {w}")}, {f.r(f"sub i64 {x}, 1")}')
            f.store('i8', at('ch', 'i8'), f.r(f'getelementptr i8, ptr @grid, i64 {pos}'))
            if inked:
                f.store('i32', at('ink', 'i32'), f.r(f'getelementptr i32, ptr @ink, i64 {pos}'))
        self.rows(f, None, cell, count=str(n))
        f.e('ret void')
        return fn

    def colour_of(self):
        """@colourof: the ink a text names (see ir.colour_value): a name, found by halving the sorted list of
        names, or "#" and six hexadecimal digits; 0 if it names no colour."""
        n = len(COLOUR_NAMES)
        self.globals.append(f'@cnames = internal constant [{n} x ptr] [' +
                            ', '.join(f'ptr {self.cstr(x)}' for x in COLOUR_NAMES) + ']')
        self.globals.append(f'@cvals = internal constant [{n} x i32] [' +
                            ', '.join(f'i32 {colour_value(x)}' for x in COLOUR_NAMES) + ']')
        f = self.fn('@colourof', 'i32', 'ptr %s', 'the colour a text names, 0 if it names none')
        hexa, named = f.lab('hex'), f.lab('named')
        f.cbr(f.r(f'icmp eq i8 {f.load("i8", "%s")}, 35'), hexa, named)
        f.at(hexa)
        v = f.var('i32', str(RGB))
        none = f.lab('none')
        for k in range(1, 7):
            c = f.load('i8', f.r(f'getelementptr i8, ptr %s, i64 {k}'))
            dig = f.r(f'sub i8 {c}, 48')
            low = f.r(f'sub i8 {f.r(f"or i8 {c}, 32")}, 87')      # a-f and A-F alike
            isdig = f.r(f'icmp ult i8 {dig}, 10')
            islet = f.r(f'and i1 {f.r(f"icmp uge i8 {low}, 10")}, {f.r(f"icmp ult i8 {low}, 16")}')
            ok, bad = f.lab('digit'), f.lab('bad')
            f.cbr(f.r(f'or i1 {isdig}, {islet}'), ok, bad)
            f.at(bad)
            f.br(none)
            f.at(ok)
            d = f.r(f'zext i8 {f.r(f"select i1 {isdig}, i8 {dig}, i8 {low}")} to i32')
            f.store('i32', f.r(f'or i32 {f.r(f"shl i32 {f.load("i32", v)}, 4")}, {d}'), v)
        end, good = f.lab('end'), f.lab('good')
        f.br(end)
        f.at(end)
        f.cbr(f.r(f'icmp eq i8 {f.load("i8", f.r("getelementptr i8, ptr %s, i64 7"))}, 0'), good, none)
        f.at(good)
        f.e(f'ret i32 {f.r(f"or i32 {f.r(f"and i32 {f.load("i32", v)}, 16777215")}, {RGB}")}')
        f.at(none)
        f.e('ret i32 0')
        f.at(named)                     # without spaces, in lower case, at most 40 characters
        buf = '%cbuf'
        f.allocas.append(f'  {buf} = alloca [41 x i8]')
        src, dst = f.var('i64', '0'), f.var('i64', '0')
        scan, look, keep, skip, full, ended = (f.lab(x) for x in ('scan', 'look', 'keep', 'skip', 'full', 'ended'))
        f.br(scan)
        f.at(scan)
        sv = f.load('i64', src)
        ch = f.load('i8', f.r(f'getelementptr i8, ptr %s, i64 {sv}'))
        f.cbr(f.r(f'icmp eq i8 {ch}, 0'), ended, look)
        f.at(look)
        f.store('i64', f.r(f'add i64 {sv}, 1'), src)
        f.cbr(f.r(f'icmp eq i8 {ch}, 32'), scan, keep)
        f.at(keep)
        dv = f.load('i64', dst)
        f.cbr(f.r(f'icmp sge i64 {dv}, 40'), full, skip)
        f.at(full)
        f.e('ret i32 0')
        f.at(skip)
        upper = f.r(f'icmp ult i8 {f.r(f"sub i8 {ch}, 65")}, 26')
        low = f.r(f'select i1 {upper}, i8 {f.r(f"add i8 {ch}, 32")}, i8 {ch}')
        f.store('i8', low, f.r(f'getelementptr i8, ptr {buf}, i64 {dv}'))
        f.store('i64', f.r(f'add i64 {dv}, 1'), dst)
        f.br(scan)
        f.at(ended)
        f.store('i8', '0', f.r(f'getelementptr i8, ptr {buf}, i64 {f.load("i64", dst)}'))
        lo, hi = f.var('i64', '0'), f.var('i64', str(n))
        head, body, found, left, right, missing = (f.lab(x) for x in ('search', 'halve', 'found', 'left', 'right', 'missing'))
        f.br(head)
        f.at(head)
        a, b = f.load('i64', lo), f.load('i64', hi)
        f.cbr(f.r(f'icmp slt i64 {a}, {b}'), body, missing)
        f.at(body)
        mid = f.r(f'lshr i64 {f.r(f"add i64 {a}, {b}")}, 1')
        name = f.load('ptr', f.r(f'getelementptr [{n} x ptr], ptr @cnames, i64 0, i64 {mid}'))
        c = f.r(f'call i32 @strcmp(ptr {buf}, ptr {name})')
        less = f.lab('less')
        f.cbr(f.r(f'icmp eq i32 {c}, 0'), found, less)
        f.at(less)
        f.cbr(f.r(f'icmp slt i32 {c}, 0'), left, right)
        f.at(left)
        f.store('i64', mid, hi)
        f.br(head)
        f.at(right)
        f.store('i64', f.r(f'add i64 {mid}, 1'), lo)
        f.br(head)
        f.at(found)
        f.e(f'ret i32 {f.load("i32", f.r(f"getelementptr [{n} x i32], ptr @cvals, i64 0, i64 {mid}"))}')
        f.at(missing)
        f.e('ret i32 0')

    def maths(self):
        """Square roots and sines, in whole numbers only, so they come out the same everywhere (see ir.sine)."""
        self.globals.append(f'@sines = internal constant [91 x i64] [{", ".join(f"i64 {v}" for v in SINE)}]')
        f = self.fn('@sine', 'i64', 'i64 %a', 'the sine of a hundredths of a degree, in hundredths')
        r0 = f.r('srem i64 %a, 36000')
        r0 = f.r(f'select i1 {f.r(f"icmp slt i64 {r0}, 0")}, i64 {f.r(f"add i64 {r0}, 36000")}, i64 {r0}')
        q, r = f.r(f'udiv i64 {r0}, 9000'), f.r(f'urem i64 {r0}, 9000')
        odd = f.r(f'icmp ne i64 {f.r(f"and i64 {q}, 1")}, 0')
        r = f.r(f'select i1 {odd}, i64 {f.r(f"sub i64 9000, {r}")}, i64 {r}')
        k, fr = f.r(f'udiv i64 {r}, 100'), f.r(f'urem i64 {r}, 100')
        k1 = f.r(f'select i1 {f.r(f"icmp eq i64 {k}, 90")}, i64 90, i64 {f.r(f"add i64 {k}, 1")}')
        tk = f.load('i64', f.r(f'getelementptr [91 x i64], ptr @sines, i64 0, i64 {k}'))
        tk1 = f.load('i64', f.r(f'getelementptr [91 x i64], ptr @sines, i64 0, i64 {k1}'))
        v = f.r(f'add i64 {f.r(f"mul i64 {tk}, 100")}, {f.r(f"mul i64 {f.r(f"sub i64 {tk1}, {tk}")}, {fr}")}')
        v = f.r(f'udiv i64 {f.r(f"add i64 {v}, 500000")}, 1000000')
        f.e(f'ret i64 {f.r(f"select i1 {f.r(f"icmp uge i64 {q}, 2")}, i64 {f.r(f"sub i64 0, {v}")}, i64 {v}")}')

        f = self.fn('@isqrt', 'i64', 'i64 %a, i64 %scale',
                    'the whole square root of a * scale, rounded down: a first guess in floating point, then made exact')
        pos, zero = f.lab('pos'), f.lab('zero')
        f.cbr(f.r('icmp sgt i64 %a, 0'), pos, zero)
        f.at(zero)
        f.e('ret i64 0')
        f.at(pos)
        n = f.r(f'mul i128 {f.r("sext i64 %a to i128")}, {f.r("sext i64 %scale to i128")}')
        d = f.r(f'fmul double {f.r("sitofp i64 %a to double")}, {f.r("sitofp i64 %scale to double")}')
        s = f.var('i128', f.r(f'sext i64 {f.r(f"fptosi double {f.r(f"call double @llvm.sqrt.f64(double {d})")} to i64")} to i128'))
        down, dbody, up, ubody, done = f.lab('down'), f.lab('lower'), f.lab('up'), f.lab('raise'), f.lab('done')
        f.br(down)
        f.at(down)
        sv = f.load('i128', s)
        f.cbr(f.r(f'icmp sgt i128 {f.r(f"mul i128 {sv}, {sv}")}, {n}'), dbody, up)
        f.at(dbody)
        f.store('i128', f.r(f'sub i128 {sv}, 1'), s)
        f.br(down)
        f.at(up)
        sv = f.load('i128', s)
        nx = f.r(f'add i128 {sv}, 1')
        f.cbr(f.r(f'icmp sle i128 {f.r(f"mul i128 {nx}, {nx}")}, {n}'), ubody, done)
        f.at(ubody)
        f.store('i128', nx, s)
        f.br(up)
        f.at(done)
        f.e(f'ret i64 {f.r(f"trunc i128 {sv} to i64")}')

        f = self.fn('@root', 'i64', 'i64 %a', 'the whole square root, rounded down')
        f.e(f'ret i64 {f.r("call i64 @isqrt(i64 %a, i64 1)")}')

        f = self.fn('@droot', 'i64', 'i64 %a', 'the square root of hundredths, in hundredths, rounded to the nearest')
        sq = f.r('call i64 @isqrt(i64 %a, i64 100)')
        n = f.r(f'mul i128 {f.r("sext i64 %a to i128")}, 100')
        s2 = f.r(f'sext i64 {sq} to i128')
        over = f.r(f'icmp sgt i128 {f.r(f"sub i128 {n}, {f.r(f"mul i128 {s2}, {s2}")}")}, {s2}')
        nonpos = f.r('icmp sle i64 %a, 0')
        f.e(f'ret i64 {f.r(f"select i1 {nonpos}, i64 0, i64 {f.r(f"add i64 {sq}, {f.r(f"zext i1 {over} to i64")}")}")}')

    def decimals(self):
        f = self.fn('@rdiv', 'i64', 'i64 %a, i64 %b',
                    'a / b rounded to the nearest whole number, halves away from zero (b is not 0)')
        na, nb = f.r('icmp slt i64 %a, 0'), f.r('icmp slt i64 %b, 0')
        ua = f.r(f'select i1 {na}, i64 {f.r("sub i64 0, %a")}, i64 %a')
        ub = f.r(f'select i1 {nb}, i64 {f.r("sub i64 0, %b")}, i64 %b')
        q = f.r(f'udiv i64 {f.r(f"add i64 {ua}, {f.r(f"lshr i64 {ub}, 1")}")}, {ub}')
        f.e(f'ret i64 {f.r(f"select i1 {f.r(f"xor i1 {na}, {nb}")}, i64 {f.r(f"sub i64 0, {q}")}, i64 {q}")}')

        f = self.fn('@decstr', 'ptr', 'i64 %n, ptr %buf', 'hundredths as they are written: 1250 -> "12.50"')
        neg = f.r('icmp slt i64 %n, 0')
        u = f.r(f'select i1 {neg}, i64 {f.r("sub i64 0, %n")}, i64 %n')
        sign = f.r(f'select i1 {neg}, ptr {self.cstr("-")}, ptr {self.cstr("")}')
        f.e(f'call i32 (ptr, i64, ptr, ...) @snprintf(ptr %buf, i64 32, ptr {self.cstr("%s%llu.%02llu")}, ptr {sign}, '
            f'i64 {f.r(f"udiv i64 {u}, 100")}, i64 {f.r(f"urem i64 {u}, 100")})')
        f.e('ret ptr %buf')

        f = self.fn('@decparse', 'i64', 'ptr %s, ptr %ok',
                    '"12.5" -> 1250; *ok is 0 unless it is a number with at most two decimal places')
        f.store('i1', 'false', '%ok')
        p = f.var('ptr', '%s')
        skip, look, body = f.lab('skip'), f.lab('look'), f.lab('sign')
        f.br(look)
        f.at(look)
        ch = f.load('i8', f.load('ptr', p))
        space = f.r(f'or i1 {f.r(f"icmp eq i8 {ch}, 32")}, {f.r(f"icmp ult i8 {f.r(f"sub i8 {ch}, 9")}, 5")}')
        f.cbr(space, skip, body)
        f.at(skip)
        f.store('ptr', f.r(f'getelementptr i8, ptr {f.load("ptr", p)}, i64 1'), p)
        f.br(look)
        f.at(body)
        minus = f.r(f'icmp eq i8 {ch}, 45')
        signed = f.r(f'or i1 {minus}, {f.r(f"icmp eq i8 {ch}, 43")}')
        start = f.r(f'getelementptr i8, ptr {f.load("ptr", p)}, i64 {f.r(f"zext i1 {signed} to i64")}')

        def digit(q):
            return f.r(f'icmp ult i8 {f.r(f"sub i8 {f.load("i8", q)}, 48")}, 10')
        bad, whole = f.lab('bad'), f.lab('whole')
        f.cbr(digit(start), whole, bad)
        f.at(bad)
        f.e('ret i64 0')
        f.at(whole)
        endp = f.var('ptr')
        w = f.r(f'call i64 @strtoll(ptr {start}, ptr {endp}, i32 10)')
        frac = f.var('i64', '0')
        end = f.load('ptr', endp)
        point, last = f.lab('point'), f.lab('last')
        f.cbr(f.r(f'icmp eq i8 {f.load("i8", end)}, 46'), point, last)
        f.at(point)
        d1 = f.r(f'getelementptr i8, ptr {end}, i64 1')
        one, two, tenths = f.lab('one'), f.lab('two'), f.lab('tenths')
        f.cbr(digit(d1), one, bad)
        f.at(one)
        f.store('i64', f.r(f'mul i64 {f.r(f"zext i8 {f.r(f"sub i8 {f.load("i8", d1)}, 48")} to i64")}, 10'), frac)
        d2 = f.r(f'getelementptr i8, ptr {end}, i64 2')
        f.store('ptr', d2, endp)
        f.cbr(digit(d2), two, last)
        f.at(two)
        f.store('i64', f.r(f'add i64 {f.load("i64", frac)}, {f.r(f"zext i8 {f.r(f"sub i8 {f.load("i8", d2)}, 48")} to i64")}'), frac)
        f.store('ptr', f.r(f'getelementptr i8, ptr {end}, i64 3'), endp)
        f.br(last)
        f.at(last)
        done = f.lab('done')
        f.cbr(f.r(f'icmp eq i8 {f.load("i8", f.load("ptr", endp))}, 0'), done, bad)
        f.at(done)
        mag = f.r(f'add i128 {f.r(f"mul i128 {f.r(f"zext i64 {w} to i128")}, 100")}, {f.r(f"zext i64 {f.load("i64", frac)} to i128")}')
        v = f.r(f'select i1 {minus}, i128 {f.r(f"sub i128 0, {mag}")}, i128 {mag}')
        v = f.r(f'select i1 {f.r(f"icmp sgt i128 {v}, 9223372036854775807")}, i128 9223372036854775807, i128 {v}')
        v = f.r(f'select i1 {f.r(f"icmp slt i128 {v}, -9223372036854775808")}, i128 -9223372036854775808, i128 {v}')
        f.store('i1', 'true', '%ok')
        f.e(f'ret i64 {f.r(f"trunc i128 {v} to i64")}')

    # ------------------------------------------------------------------ relationships
    def kids(self, c, policy):
        return [(d, rf) for d, rf in self.prog.children_of(c.name) if rf.on_removed == policy]

    def relation(self, d, rf):
        p = self.prog.collections[rf.ref]
        key = self.prog.key_of(p.name)
        KT = LL[key.type]
        f = self.fn(g(d.name, rf.name, 'refers'), 'i1', f'{KT} %key',
                    f'does any {d.name} belong to the {p.name} with this {key.name}?')

        def body(i, cont):
            hit = f.lab('hit')
            f.cbr(self.eq(f, key.type, self.fload(f, d, self.rec(f, d, i), rf.name), '%key'), hit, cont)
            f.at(hit)
            f.e('ret i1 true')
            f.at(f.lab('dead'))
        self.rows(f, d, body)
        f.e('ret i1 false')

        f = self.fn(g(d.name, rf.name, 'sweep'),
                    comment=f'remove every {d.name} whose {p.name} no longer exists, then whatever belonged to those')
        before = f.load('i64', g(d.name, 'len'))

        def orphan(rec, _i=None):
            row = f.r(f'call i64 {g(p.name, key.name, "find")}({KT} {self.fload(f, d, rec, rf.name)})')
            return f.r(f'icmp slt i64 {row}, 0')
        kept = self.compact(f, d, orphan)
        if self.kids(d, 'cascade'):
            more, done = f.lab('more'), f.lab('done')
            f.cbr(f.r(f'icmp ne i64 {before}, {kept}'), more, done)
            f.at(more)
            self.swept(f, d)
            f.br(done)
            f.at(done)
        f.e('ret void')

    def blocked(self, f, c, rec):
        """Refuse (print and return) if this record, about to be removed, still owns records."""
        key = self.prog.key_of(c.name)
        for d, rf in self.kids(c, 'restrict'):
            used = f.r(f'call i1 {g(d.name, rf.name, "refers")}({LL[key.type]} {self.fload(f, c, rec, key.name)})')
            no, ok = f.lab('refuse'), f.lab('free')
            f.cbr(used, no, ok)
            f.at(no)
            self.puts(f, f'{c.name} still has {d.label.lower()}')
            f.e('ret void')
            f.at(ok)

    def swept(self, f, c):
        for d, rf in self.kids(c, 'cascade'):
            f.e(f'call void {g(d.name, rf.name, "sweep")}()')

    def scan_find(self, c, fl):
        C, K, KT = c.name, fl.name, LL[fl.type]
        f = self.fn(g(C, K, 'find'), 'i64', f'{KT} %key', f'{C}: row whose {K} equals key, or -1 (linear scan)')

        def body(i, cont):
            hit = f.lab('hit')
            f.cbr(self.eq(f, fl.type, self.fload(f, c, self.rec(f, c, i), K), '%key'), hit, cont)
            f.at(hit)
            f.e(f'ret i64 {i}')
            f.at(f.lab('dead'))
        self.rows(f, c, body)
        f.e('ret i64 -1')

    def index(self, c, fl):
        C, K, KT = c.name, fl.name, LL[fl.type]
        TAB, CAP, USED = g(C, K, 'tab'), g(C, K, 'icap'), g(C, K, 'used')
        self.globals += [f'{TAB} = internal global ptr null', f'{CAP} = internal global i64 0',
                         f'{USED} = internal global i64 0']

        f = self.fn(g(C, K, 'hash'), 'i64', f'{KT} %key', f'{C}.{K} index: hash of a key')
        if fl.type == 'int':
            m = f.r(f'mul i64 %key, {MIX}')
            f.e(f'ret i64 {f.r(f"xor i64 {m}, {f.r(f"lshr i64 {m}, 29")}")}')
        else:
            h, p = f.var('i64', FNV_OFFSET), f.var('ptr', '%key')
            head, bl, end = f.lab('head'), f.lab('body'), f.lab('end')
            f.br(head)
            f.at(head)
            pv = f.load('ptr', p)
            ch = f.load('i8', pv)
            f.cbr(f.r(f'icmp eq i8 {ch}, 0'), end, bl)
            f.at(bl)
            x = f.r(f'xor i64 {f.load("i64", h)}, {f.r(f"zext i8 {ch} to i64")}')
            f.store('i64', f.r(f'mul i64 {x}, {FNV_PRIME}'), h)
            f.store('ptr', f.r(f'getelementptr i8, ptr {pv}, i64 1'), p)
            f.br(head)
            f.at(end)
            f.e(f'ret i64 {f.load("i64", h)}')

        # slot: position in the table holding key, or -1. Slots: 0 empty, -1 deleted, else row+1.
        f = self.fn(g(C, K, 'slot'), 'i64', f'{KT} %key', f'{C}.{K} index: table position of a key, or -1')
        cap = f.load('i64', CAP)
        none, go = f.lab('none'), f.lab('go')
        f.cbr(f.r(f'icmp eq i64 {cap}, 0'), none, go)
        f.at(none)
        f.e('ret i64 -1')
        f.at(go)
        mask = f.r(f'sub i64 {cap}, 1')
        tab = f.load('ptr', TAB)
        hv = f.r(f'call i64 {g(C, K, "hash")}({KT} %key)')
        i = f.var('i64', f.r(f'and i64 {hv}, {mask}'))
        head, live, hit, nxt, miss = f.lab('head'), f.lab('live'), f.lab('hit'), f.lab('next'), f.lab('miss')
        chk = f.lab('chk')
        f.br(head)
        f.at(head)
        iv = f.load('i64', i)
        s = f.load('i64', f.r(f'getelementptr i64, ptr {tab}, i64 {iv}'))
        f.cbr(f.r(f'icmp eq i64 {s}, 0'), miss, chk)
        f.at(miss)
        f.e('ret i64 -1')
        f.at(chk)
        f.cbr(f.r(f'icmp sgt i64 {s}, 0'), live, nxt)
        f.at(live)
        rk = self.fload(f, c, self.rec(f, c, f.r(f'sub i64 {s}, 1')), K)
        f.cbr(self.eq(f, fl.type, rk, '%key'), hit, nxt)
        f.at(hit)
        f.e(f'ret i64 {iv}')
        f.at(nxt)
        f.store('i64', f.r(f'and i64 {f.r(f"add i64 {iv}, 1")}, {mask}'), i)
        f.br(head)

        f = self.fn(g(C, K, 'find'), 'i64', f'{KT} %key', f'{C}: row whose {K} equals key, or -1 (index probe)')
        pos = f.r(f'call i64 {g(C, K, "slot")}({KT} %key)')
        none, some = f.lab('none'), f.lab('some')
        f.cbr(f.r(f'icmp slt i64 {pos}, 0'), none, some)
        f.at(none)
        f.e('ret i64 -1')
        f.at(some)
        s = f.load('i64', f.r(f'getelementptr i64, ptr {f.load("ptr", TAB)}, i64 {pos}'))
        f.e(f'ret i64 {f.r(f"sub i64 {s}, 1")}')

        f = self.fn(g(C, K, 'rawput'), params='i64 %row', comment=f'{C}.{K} index: enter a row (key known absent)')
        key = self.fload(f, c, self.rec(f, c, '%row'), K)
        hv = f.r(f'call i64 {g(C, K, "hash")}({KT} {key})')
        mask = f.r(f'sub i64 {f.load("i64", CAP)}, 1')
        tab = f.load('ptr', TAB)
        i = f.var('i64', f.r(f'and i64 {hv}, {mask}'))
        head, free, fresh, put, nxt = f.lab('head'), f.lab('free'), f.lab('fresh'), f.lab('put'), f.lab('next')
        f.br(head)
        f.at(head)
        iv = f.load('i64', i)
        sp = f.r(f'getelementptr i64, ptr {tab}, i64 {iv}')
        s = f.load('i64', sp)
        f.cbr(f.r(f'icmp sle i64 {s}, 0'), free, nxt)
        f.at(free)
        f.cbr(f.r(f'icmp eq i64 {s}, 0'), fresh, put)
        f.at(fresh)
        f.store('i64', f.r(f'add i64 {f.load("i64", USED)}, 1'), USED)
        f.br(put)
        f.at(put)
        f.store('i64', f.r('add i64 %row, 1'), sp)
        f.e('ret void')
        f.at(nxt)
        f.store('i64', f.r(f'and i64 {f.r(f"add i64 {iv}, 1")}, {mask}'), i)
        f.br(head)

        f = self.fn(g(C, K, 'rebuild'), comment=f'{C}.{K} index: rebuild from the records, at most 1/4 full')
        n = f.load('i64', g(C, 'len'))
        want = f.r(f'shl i64 {n}, 2')
        nc = f.var('i64', '16')
        head, bl, end = f.lab('head'), f.lab('body'), f.lab('end')
        f.br(head)
        f.at(head)
        ncv = f.load('i64', nc)
        f.cbr(f.r(f'icmp slt i64 {ncv}, {want}'), bl, end)
        f.at(bl)
        f.store('i64', f.r(f'shl i64 {ncv}, 1'), nc)
        f.br(head)
        f.at(end)
        f.e(f'call void @free(ptr {f.load("ptr", TAB)})')
        f.store('ptr', f.r(f'call ptr @calloc(i64 {ncv}, i64 8)'), TAB)
        f.store('i64', ncv, CAP)
        f.store('i64', '0', USED)
        self.rows(f, c, lambda i, cont: f.e(f'call void {g(C, K, "rawput")}(i64 {i})'), count=n)
        f.e('ret void')

        f = self.fn(g(C, K, 'put'), params='i64 %row', comment=f'{C}.{K} index: enter a row, growing at 1/2 full')
        used, cap = f.load('i64', USED), f.load('i64', CAP)
        need = f.r(f'shl i64 {f.r(f"add i64 {used}, 1")}, 1')
        grow, fits = f.lab('grow'), f.lab('fits')
        f.cbr(f.r(f'icmp sgt i64 {need}, {cap}'), grow, fits)
        f.at(grow)
        f.e(f'call void {g(C, K, "rebuild")}()')
        f.e('ret void')
        f.at(fits)
        f.e(f'call void {g(C, K, "rawput")}(i64 %row)')
        f.e('ret void')

    def ordered(self, c, fl):
        """An ordered index on one property: a treap whose nodes are the row numbers themselves.

        Rows are sorted by the property, then by position, so the order is total and every row has
        exactly one place. Each node has a left and right child and a priority drawn from a fixed
        sequence; a parent's priority is never below its children's, which keeps the expected depth
        O(log n) whatever order the rows arrive in. While the index is fresh it is kept up to date
        one row at a time; a change that moves many rows at once leaves it stale, and the next read
        rebuilds it.
        """
        C, K, KT = c.name, fl.name, LL[fl.type]
        L, R, P = g(C, K, 'left'), g(C, K, 'right'), g(C, K, 'prio')
        ROOT, FRESH, OCAP, SEED = g(C, K, 'root'), g(C, K, 'fresh'), g(C, K, 'ocap'), g(C, K, 'seed')
        self.globals += [f'{L} = internal global ptr null', f'{R} = internal global ptr null',
                         f'{P} = internal global ptr null', f'{ROOT} = internal global i64 -1',
                         f'{FRESH} = internal global i1 true', f'{OCAP} = internal global i64 0',
                         f'{SEED} = internal global i64 0']

        def at(f, arr, i):
            return f.r(f'getelementptr i64, ptr {f.load("ptr", arr)}, i64 {i}')

        def get(f, arr, i):
            return f.load('i64', at(f, arr, i))

        def put(f, arr, i, v):
            f.store('i64', v, at(f, arr, i))

        f = self.fn(g(C, K, 'cmp'), 'i32', f'i64 %row, {KT} %v', f'{C}.{K} order: the row\'s {K} against v')
        k = self.fload(f, c, self.rec(f, c, '%row'), K)
        if fl.type == 'int':
            lt, gt = f.r(f'icmp slt i64 {k}, %v'), f.r(f'icmp sgt i64 {k}, %v')
            f.e(f'ret i32 {f.r(f"select i1 {lt}, i32 -1, i32 {f.r(f"select i1 {gt}, i32 1, i32 0")}")}')
        else:
            f.e(f'ret i32 {f.r(f"call i32 @strcmp(ptr {k}, ptr %v)")}')

        f = self.fn(g(C, K, 'less'), 'i1', 'i64 %a, i64 %b', f'{C}.{K} order: does row a come before row b?')
        s = f.r(f'call i32 {g(C, K, "cmp")}(i64 %a, {KT} {self.fload(f, c, self.rec(f, c, "%b"), K)})')
        tie = f.r('icmp slt i64 %a, %b')
        f.e(f'ret i1 {f.r(f"select i1 {f.r(f"icmp eq i32 {s}, 0")}, i1 {tie}, i1 {f.r(f"icmp slt i32 {s}, 0")}")}')

        f = self.fn(g(C, K, 'ins'), 'i64', 'i64 %t, i64 %x', f'{C}.{K} order: put row x in the subtree at t')
        leaf, inner, left, right, rot_r, rot_l, keep = (f.lab(n) for n in ('leaf', 'inner', 'left', 'right',
                                                                            'rotr', 'rotl', 'keep'))
        f.cbr(f.r('icmp eq i64 %t, -1'), leaf, inner)
        f.at(leaf)
        put(f, L, '%x', '-1')
        put(f, R, '%x', '-1')
        f.e('ret i64 %x')
        f.at(inner)
        f.cbr(f.r(f'call i1 {g(C, K, "less")}(i64 %x, i64 %t)'), left, right)
        f.at(left)
        y = f.r(f'call i64 {g(C, K, "ins")}(i64 {get(f, L, "%t")}, i64 %x)')
        put(f, L, '%t', y)
        f.cbr(f.r(f'icmp sgt i64 {get(f, P, y)}, {get(f, P, "%t")}'), rot_r, keep)
        f.at(rot_r)                     # the new child outranks t: it takes t's place, t goes right
        put(f, L, '%t', get(f, R, y))
        put(f, R, y, '%t')
        f.e(f'ret i64 {y}')
        f.at(right)
        y = f.r(f'call i64 {g(C, K, "ins")}(i64 {get(f, R, "%t")}, i64 %x)')
        put(f, R, '%t', y)
        f.cbr(f.r(f'icmp sgt i64 {get(f, P, y)}, {get(f, P, "%t")}'), rot_l, keep)
        f.at(rot_l)
        put(f, R, '%t', get(f, L, y))
        put(f, L, y, '%t')
        f.e(f'ret i64 {y}')
        f.at(keep)
        f.e('ret i64 %t')

        f = self.fn(g(C, K, 'join'), 'i64', 'i64 %a, i64 %b',
                    f'{C}.{K} order: one subtree from two, every row of a before every row of b')
        no_a, has_a, no_b, both, a_up, b_up = (f.lab(n) for n in ('noa', 'hasa', 'nob', 'both', 'aup', 'bup'))
        f.cbr(f.r('icmp eq i64 %a, -1'), no_a, has_a)
        f.at(no_a)
        f.e('ret i64 %b')
        f.at(has_a)
        f.cbr(f.r('icmp eq i64 %b, -1'), no_b, both)
        f.at(no_b)
        f.e('ret i64 %a')
        f.at(both)
        f.cbr(f.r(f'icmp sgt i64 {get(f, P, "%a")}, {get(f, P, "%b")}'), a_up, b_up)
        f.at(a_up)
        put(f, R, '%a', f.r(f'call i64 {g(C, K, "join")}(i64 {get(f, R, "%a")}, i64 %b)'))
        f.e('ret i64 %a')
        f.at(b_up)
        put(f, L, '%b', f.r(f'call i64 {g(C, K, "join")}(i64 %a, i64 {get(f, L, "%b")})'))
        f.e('ret i64 %b')

        f = self.fn(g(C, K, 'del'), 'i64', 'i64 %t, i64 %x', f'{C}.{K} order: take row x out of the subtree at t')
        none, some, hit, look, left, right = (f.lab(n) for n in ('none', 'some', 'hit', 'look', 'left', 'right'))
        f.cbr(f.r('icmp eq i64 %t, -1'), none, some)
        f.at(none)
        f.e('ret i64 -1')
        f.at(some)
        f.cbr(f.r('icmp eq i64 %t, %x'), hit, look)
        f.at(hit)
        f.e(f'ret i64 {f.r(f"call i64 {g(C, K, "join")}(i64 {get(f, L, "%t")}, i64 {get(f, R, "%t")})")}')
        f.at(look)
        f.cbr(f.r(f'call i1 {g(C, K, "less")}(i64 %x, i64 %t)'), left, right)
        f.at(left)
        put(f, L, '%t', f.r(f'call i64 {g(C, K, "del")}(i64 {get(f, L, "%t")}, i64 %x)'))
        f.e('ret i64 %t')
        f.at(right)
        put(f, R, '%t', f.r(f'call i64 {g(C, K, "del")}(i64 {get(f, R, "%t")}, i64 %x)'))
        f.e('ret i64 %t')

        f = self.fn(g(C, K, 'insert'), params='i64 %x', comment=f'{C}.{K} order: a row was added at x')
        out, go, grow, fits = f.lab('out'), f.lab('go'), f.lab('grow'), f.lab('fits')
        f.cbr(f.load('i1', FRESH), go, out)
        f.at(out)
        f.e('ret void')
        f.at(go)
        cap = f.load('i64', g(C, 'cap'))
        f.cbr(f.r(f'icmp slt i64 {f.load("i64", OCAP)}, {cap}'), grow, fits)
        f.at(grow)
        for arr in (L, R, P):
            f.store('ptr', f.r(f'call ptr @realloc(ptr {f.load("ptr", arr)}, i64 {f.r(f"shl i64 {cap}, 3")})'), arr)
        f.store('i64', cap, OCAP)
        f.br(fits)
        f.at(fits)
        z = f.r(f'add i64 {f.load("i64", SEED)}, {MIX}')      # splitmix64: a fixed, well-spread sequence
        f.store('i64', z, SEED)
        z = f.r(f'mul i64 {f.r(f"xor i64 {z}, {f.r(f"lshr i64 {z}, 30")}")}, -4658895280553007687')
        z = f.r(f'mul i64 {f.r(f"xor i64 {z}, {f.r(f"lshr i64 {z}, 27")}")}, -7723592293110705685')
        put(f, P, '%x', f.r(f'xor i64 {z}, {f.r(f"lshr i64 {z}, 31")}'))
        f.store('i64', f.r(f'call i64 {g(C, K, "ins")}(i64 {f.load("i64", ROOT)}, i64 %x)'), ROOT)
        f.e('ret void')

        f = self.fn(g(C, K, 'drop'), params='i64 %x', comment=f'{C}.{K} order: row x is about to go or move')
        out, go = f.lab('out'), f.lab('go')
        f.cbr(f.load('i1', FRESH), go, out)
        f.at(out)
        f.e('ret void')
        f.at(go)
        f.store('i64', f.r(f'call i64 {g(C, K, "del")}(i64 {f.load("i64", ROOT)}, i64 %x)'), ROOT)
        f.e('ret void')

        f = self.fn(g(C, K, 'shift'), params='i64 %gone',
                    comment=f'{C}.{K} order: every row after the one that went moved up one place')
        out, go = f.lab('out'), f.lab('go')
        f.cbr(f.load('i1', FRESH), go, out)
        f.at(out)
        f.e('ret void')
        f.at(go)
        n = f.load('i64', g(C, 'len'))
        tail = f.r(f'shl i64 {f.r(f"sub i64 {n}, %gone")}, 3')
        for arr in (L, R, P):
            f.e(f'call ptr @memmove(ptr {at(f, arr, "%gone")}, ptr {at(f, arr, f.r("add i64 %gone, 1"))}, i64 {tail})')

        def renumber(i, cont):
            for arr in (L, R):
                v = get(f, arr, i)
                put(f, arr, i, f.r(f'select i1 {f.r(f"icmp sgt i64 {v}, %gone")}, i64 {f.r(f"sub i64 {v}, 1")}, i64 {v}'))
        self.rows(f, c, renumber)
        r = f.load('i64', ROOT)
        f.store('i64', f.r(f'select i1 {f.r(f"icmp sgt i64 {r}, %gone")}, i64 {f.r(f"sub i64 {r}, 1")}, i64 {r}'), ROOT)
        f.e('ret void')

        f = self.fn(g(C, K, 'ready'), comment=f'{C}.{K} order: rebuild it if a change left it stale, O(n log n)')
        out, go = f.lab('out'), f.lab('go')
        f.cbr(f.load('i1', FRESH), out, go)
        f.at(out)
        f.e('ret void')
        f.at(go)
        f.store('i64', '-1', ROOT)
        f.store('i1', 'true', FRESH)
        self.rows(f, c, lambda i, cont: f.e(f'call void {g(C, K, "insert")}(i64 {i})'))
        f.e('ret void')

    def stale(self, f, c, props=None):
        """A change that moves many rows at once: the ordered indexes are rebuilt when next read."""
        for k in self.plan.colls[c.name].orders:
            if props is None or k in props:
                f.store('i1', 'false', g(c.name, k, 'fresh'))

    def walk(self, f, c, w, vals, back, body):
        """Visit, in order of w.prop (backwards if back), every row within w's bounds.

        body(row, cont, end): cont goes on to the next row, end stops the walk. The index is
        walked with a stack: first down to where the range starts, then in order until it ends.
        """
        C, K = c.name, w.prop
        KT = LL[c.fields[K].type]
        f.e(f'call void {g(C, K, "ready")}()')
        lo = (w.lo[0], self.expr(f, w.lo[1], c, None, vals)[0]) if w.lo else None
        hi = (w.hi[0], self.expr(f, w.hi[1], c, None, vals)[0]) if w.hi else None

        def below(x):                   # before the range starts
            s = f.r(f'call i32 {g(C, K, "cmp")}(i64 {x}, {KT} {lo[1]})')
            return f.r(f'icmp {"sle" if lo[0] else "slt"} i32 {s}, 0')

        def above(x):                   # after the range ends
            s = f.r(f'call i32 {g(C, K, "cmp")}(i64 {x}, {KT} {hi[1]})')
            return f.r(f'icmp {"sge" if hi[0] else "sgt"} i32 {s}, 0')
        near, far = (g(C, K, 'left'), g(C, K, 'right'))[::-1 if back else 1]
        before, after = (below if lo else None, above if hi else None)[::-1 if back else 1]

        def child(arr, x):
            return f.load('i64', f.r(f'getelementptr i64, ptr {f.load("ptr", arr)}, i64 {x}'))
        n = f.load('i64', g(C, 'len'))
        stack = f.r(f'call ptr @malloc(i64 {f.r(f"shl i64 {f.r(f"add i64 {n}, 1")}, 3")})')
        sp = f.var('i64', '0')

        def push(x):
            spv = f.load('i64', sp)
            f.store('i64', x, f.r(f'getelementptr i64, ptr {stack}, i64 {spv}'))
            f.store('i64', f.r(f'add i64 {spv}, 1'), sp)
        node = f.var('i64', f.load('i64', g(C, K, 'root')))
        seek, look, found, step = f.lab('seek'), f.lab('look'), f.lab('found'), f.lab('step')
        f.br(seek)
        f.at(seek)
        x = f.load('i64', node)
        f.cbr(f.r(f'icmp eq i64 {x}, -1'), found, look)
        f.at(look)
        if before:
            skip = f.lab('skip')
            f.cbr(before(x), skip, step)
            f.at(skip)
            f.store('i64', child(far, x), node)
            f.br(seek)
        else:
            f.br(step)
        f.at(step)
        push(x)
        f.store('i64', child(near, x), node)
        f.br(seek)
        f.at(found)
        loop, pop, inside, cont, down, end = (f.lab(n) for n in ('loop', 'pop', 'inside', 'cont', 'down', 'end'))
        cur = f.var('i64')
        f.br(loop)
        f.at(loop)
        spv = f.load('i64', sp)
        f.cbr(f.r(f'icmp eq i64 {spv}, 0'), end, pop)
        f.at(pop)
        top = f.r(f'sub i64 {spv}, 1')
        f.store('i64', top, sp)
        x = f.load('i64', f.r(f'getelementptr i64, ptr {stack}, i64 {top}'))
        f.store('i64', x, cur)
        if after:
            f.cbr(after(x), end, inside)
        else:
            f.br(inside)
        f.at(inside)
        body(x, cont, end)
        f.br(cont)
        f.at(cont)
        f.store('i64', child(far, f.load('i64', cur)), node)
        f.br(down)
        f.at(down)
        y = f.load('i64', node)
        more = f.lab('more')
        f.cbr(f.r(f'icmp eq i64 {y}, -1'), loop, more)
        f.at(more)
        push(y)
        f.store('i64', child(near, y), node)
        f.br(down)
        f.at(end)
        f.e(f'call void @free(ptr {stack})')

    def remove_row(self, c, cp, size):
        C = c.name
        how = 'swap the last record into the hole' if cp.removal == 'swap' else 'close the gap, keeping order'
        f = self.fn(g(C, 'remove_row'), params='i64 %row', comment=f'{C}: remove one record; {how}')
        p = self.rec(f, c, '%row')
        for k in cp.orders:             # taken out while its key can still be read
            f.e(f'call void {g(C, k, "drop")}(i64 %row)')

        def retarget(rec, value):
            for k in cp.indexes:
                kt = LL[c.fields[k].type]
                pos = f.r(f'call i64 {g(C, k, "slot")}({kt} {self.fload(f, c, rec, k)})')
                sp = f.r(f'getelementptr i64, ptr {f.load("ptr", g(C, k, "tab"))}, i64 {pos}')
                f.store('i64', value, sp)
        if cp.removal == 'swap':
            retarget(p, '-1')
        f.e(f'call void {g(C, "free")}(ptr {p})')
        last = f.r(f'sub i64 {f.load("i64", g(C, "len"))}, 1')
        if cp.removal == 'swap':
            move, done = f.lab('move'), f.lab('done')
            f.cbr(f.r(f'icmp ne i64 %row, {last}'), move, done)
            f.at(move)
            lp = self.rec(f, c, last)
            retarget(lp, f.r('add i64 %row, 1'))
            for k in cp.orders:         # the last row gets a new number: out, then back in under it
                f.e(f'call void {g(C, k, "drop")}(i64 {last})')
            f.e(f'call ptr @memmove(ptr {p}, ptr {lp}, i64 {size})')
            for k in cp.orders:
                f.e(f'call void {g(C, k, "insert")}(i64 %row)')
            f.br(done)
            f.at(done)
            f.store('i64', last, g(C, 'len'))
        else:
            nxt = f.r(f'getelementptr %"{C}", ptr {p}, i64 1')
            nbytes = f.r(f'mul i64 {f.r(f"sub i64 {last}, %row")}, {size}')
            f.e(f'call ptr @memmove(ptr {p}, ptr {nxt}, i64 {nbytes})')
            f.store('i64', last, g(C, 'len'))
            f.e(f'call void {g(C, "reindex")}()')
            for k in cp.orders:
                f.e(f'call void {g(C, k, "shift")}(i64 %row)')
        f.e('ret void')

    # ------------------------------------------------------------------ tasks
    def params(self, f, t):
        vals = {}
        if not t.params:
            return vals
        bad, ok = f.lab('missing'), f.lab('ok')
        f.cbr(f.r(f'icmp eq i8 {f.load("i8", "%arg")}, 0'), bad, ok)
        f.at(bad)
        self.puts(f, f'error: missing {t.params[0]}')
        f.e('ret void')
        f.at(ok)
        argp = f.var('ptr', '%arg')
        for p in t.params:
            tok = f.r(f'call ptr @strsep(ptr {argp}, ptr {self.cstr(",")})')
            bad, ok = f.lab('missing'), f.lab('ok')
            f.cbr(f.r(f'icmp eq ptr {tok}, null'), bad, ok)
            f.at(bad)
            self.puts(f, f'error: missing {p}')
            f.e('ret void')
            f.at(ok)
            if p in t.pdec:
                okp = f.var('i1')
                v = f.r(f'call i64 @decparse(ptr {tok}, ptr {okp})')
                bad, ok = f.lab('notnum'), f.lab('ok')
                f.cbr(f.load('i1', okp), ok, bad)
                f.at(bad)
                self.puts(f, f'error: {p} must be a number like 12.50')
                f.e('ret void')
                f.at(ok)
                vals[p] = (v, 'int')
            elif t.ptypes[p] == 'int':
                endp = f.var('ptr')
                v = f.r(f'call i64 @strtoll(ptr {tok}, ptr {endp}, i32 10)')
                end = f.load('ptr', endp)
                empty = f.r(f'icmp eq ptr {end}, {tok}')
                junk = f.r(f'icmp ne i8 {f.load("i8", end)}, 0')
                bad, ok = f.lab('notnum'), f.lab('ok')
                f.cbr(f.r(f'or i1 {empty}, {junk}'), bad, ok)
                f.at(bad)
                self.puts(f, f'error: {p} must be a number')
                f.e('ret void')
                f.at(ok)
                vals[p] = (v, 'int')
            else:
                vals[p] = (tok, 'text')
        return vals

    def store_record(self, f, c, rec, vals):
        for fl in c.fields.values():
            v = vals[fl.name][0]
            if fl.type == 'text':
                v = f.r(f'call ptr @strdup(ptr {v})')
            f.store(LL[fl.type], v, self.fptr(f, c, rec, fl.name))

    def compact(self, f, c, remove_if):
        """Keep rows for which remove_if(rec) is false. Returns the number of rows kept."""
        C, size = c.name, 8 * len(c.fields)
        j = f.var('i64', '0')

        def body(i, cont):
            rec = self.rec(f, c, i)
            drop, keep = f.lab('drop'), f.lab('keep')
            f.cbr(remove_if(rec, i), drop, keep)
            f.at(drop)
            f.e(f'call void {g(C, "free")}(ptr {rec})')
            f.br(cont)
            f.at(keep)
            jv = f.load('i64', j)
            f.e(f'call ptr @memmove(ptr {self.rec(f, c, jv)}, ptr {rec}, i64 {size})')
            f.store('i64', f.r(f'add i64 {jv}, 1'), j)
        self.rows(f, c, body)
        kept = f.load('i64', j)
        f.store('i64', kept, g(C, 'len'))
        f.e(f'call void {g(C, "reindex")}()')
        self.stale(f, c)
        return kept

    def mark(self, f, differs):
        """A rule notes that it really changed something."""
        was = f.load('i32', '@changed')
        f.store('i32', f.r(f'or i32 {was}, {f.r(f"zext i1 {differs} to i32")}'), '@changed')

    def task(self, t, rule=False):
        c = self.prog.collections.get(t.coll)
        cp = self.plan.colls.get(t.coll)
        cost, how = self.plan.tasks[t.name]
        f = self.fn(g('rule' if rule else 'task', t.name), params='ptr %arg',
                    comment=f'line {t.line}: {t.text}\nmeaning: {fmt_event(t) if t.on else canon(t)}\n'
                            f'plan: {how}; {cost}')
        vals = self.params(f, t)
        C = t.coll
        k = t.kind
        if k == 'calc':
            v, _ = self.expr(f, t.expr, None, None, vals)
            if t.dec:
                self.printf(f, '%s\n', f'ptr {self.shown(f, v, "int", True)[0]}')
            else:
                self.printf(f, '%lld\n', f'i64 {v}')
        elif k == 'add':
            for fl in c.fields.values():
                if fl.ref:
                    key = self.prog.key_of(fl.ref)
                    row = f.r(f'call i64 {g(fl.ref, key.name, "find")}({LL[key.type]} {vals[fl.name][0]})')
                    lost, ok = f.lab('lost'), f.lab('ok')
                    f.cbr(f.r(f'icmp slt i64 {row}, 0'), lost, ok)
                    f.at(lost)
                    self.puts(f, f'no such {fl.ref}')
                    f.e('ret void')
                    f.at(ok)
            for fl in c.unique_fields():
                row = f.r(f'call i64 {g(C, fl.name, "find")}({LL[fl.type]} {vals[fl.name][0]})')
                clash, ok = f.lab('clash'), f.lab('ok')
                f.cbr(f.r(f'icmp sge i64 {row}, 0'), clash, ok)
                f.at(clash)
                if c.on_dup == 'replace':
                    f.store('i32', '1', '@dirty')
                    f.store('i64', row, '@touched')
                    rec = self.rec(f, c, row)
                    for ox in cp.orders:
                        f.e(f'call void {g(C, ox, "drop")}(i64 {row})')
                    f.e(f'call void {g(C, "free")}(ptr {rec})')
                    self.store_record(f, c, rec, vals)
                    for ox in cp.orders:
                        f.e(f'call void {g(C, ox, "insert")}(i64 {row})')
                else:
                    self.puts(f, f'duplicate {fl.name}')
                f.e('ret void')
                f.at(ok)
            f.store('i32', '1', '@dirty')
            f.e(f'call void {g(C, "grow")}()')
            n = f.load('i64', g(C, 'len'))
            self.store_record(f, c, self.rec(f, c, n), vals)
            f.store('i64', f.r(f'add i64 {n}, 1'), g(C, 'len'))
            f.store('i64', n, '@touched')
            for ix in cp.indexes:
                f.e(f'call void {g(C, ix, "put")}(i64 {n})')
            for ox in cp.orders:
                f.e(f'call void {g(C, ox, "insert")}(i64 {n})')
        elif k == 'make':               # a record that appears by itself; a clash is passed over in silence
            go, out = f.lab('go'), f.lab('out')
            f.cbr(self.cond(f, t.where, c, None, vals), go, out)
            f.at(go)
            made = {name: self.expr(f, e, c, None, vals) for name, e in t.assigns}
            for fl in c.unique_fields():
                row = f.r(f'call i64 {g(C, fl.name, "find")}({LL[fl.type]} {made[fl.name][0]})')
                clash, ok = f.lab('clash'), f.lab('ok')
                f.cbr(f.r(f'icmp sge i64 {row}, 0'), clash, ok)
                f.at(clash)
                if c.on_dup == 'replace':
                    rec = self.rec(f, c, row)
                    for ox in cp.orders:
                        f.e(f'call void {g(C, ox, "drop")}(i64 {row})')
                    f.e(f'call void {g(C, "free")}(ptr {rec})')
                    self.store_record(f, c, rec, made)
                    for ox in cp.orders:
                        f.e(f'call void {g(C, ox, "insert")}(i64 {row})')
                f.br(out)
                f.at(ok)
            f.e(f'call void {g(C, "grow")}()')
            n = f.load('i64', g(C, 'len'))
            self.store_record(f, c, self.rec(f, c, n), made)
            f.store('i64', f.r(f'add i64 {n}, 1'), g(C, 'len'))
            for ix in cp.indexes:
                f.e(f'call void {g(C, ix, "put")}(i64 {n})')
            for ox in cp.orders:
                f.e(f'call void {g(C, ox, "insert")}(i64 {n})')
            f.br(out)
            f.at(out)
        elif k in ('find', 'remove_key') and c.fields[t.key].unique:
            kv, kt = vals[t.key]
            row = f.r(f'call i64 {g(C, t.key, "find")}({LL[kt]} {kv})')
            none, some = f.lab('none'), f.lab('some')
            f.cbr(f.r(f'icmp slt i64 {row}, 0'), none, some)
            f.at(none)
            self.puts(f, 'none')
            f.e('ret void')
            f.at(some)
            if k == 'find':
                f.e(f'call void {g(C, "print")}(ptr {self.rec(f, c, row)})')
            else:
                self.blocked(f, c, self.rec(f, c, row))
                f.store('i32', '1', '@dirty')
                f.e(f'call void {g(C, "remove_row")}(i64 {row})')
                self.swept(f, c)
        elif k == 'find':
            hits = f.var('i64', '0')
            kv, kt = vals[t.key]

            def body(i, cont):
                rec = self.rec(f, c, i)
                self.guard(f, self.eq(f, kt, self.fload(f, c, rec, t.key), kv), cont)
                f.e(f'call void {g(C, "print")}(ptr {rec})')
                f.store('i64', f.r(f'add i64 {f.load("i64", hits)}, 1'), hits)
            self.rows(f, c, body)
            self.none_if_zero(f, f.load('i64', hits))
        elif k in ('remove_key', 'remove_where'):
            if k == 'remove_key':
                kv, kt = vals[t.key]
                goes = lambda rec, i: self.eq(f, kt, self.fload(f, c, rec, t.key), kv)    # noqa: E731
            elif decides_first(t):      # it asks about the other records: all answers first, then the removing
                marks = self.decided(f, t, c, vals)
                goes = lambda rec, i: f.r(     # noqa: E731
                    f'icmp ne i8 {f.load("i8", f.r(f"getelementptr i8, ptr {marks}, i64 {i}"))}, 0')
            else:
                goes = lambda rec, i: self.cond(f, t.where, c, rec, vals)                 # noqa: E731
            if self.kids(c, 'restrict'):
                def check(i, cont):
                    rec = self.rec(f, c, i)
                    self.guard(f, goes(rec, i), cont)
                    self.blocked(f, c, rec)
                self.rows(f, c, check)
            if not rule:
                f.store('i32', '1', '@dirty')
            before = f.load('i64', g(C, 'len'))
            kept = self.compact(f, c, goes)
            if rule:
                self.mark(f, f.r(f'icmp ne i64 {before}, {kept}'))
            if self.kids(c, 'cascade'):
                more, done = f.lab('more'), f.lab('done')
                f.cbr(f.r(f'icmp ne i64 {before}, {kept}'), more, done)
                f.at(more)
                self.swept(f, c)
                f.br(done)
                f.at(done)
            if k == 'remove_where' and decides_first(t):
                f.e(f'call void @free(ptr {marks})')
            if k == 'remove_key':
                self.none_if_zero(f, f.r(f'sub i64 {before}, {kept}'))
        elif k == 'update':
            if not rule:
                f.store('i32', '1', '@dirty')
            moved = [k for k in cp.orders if any(name == k for name, _ in t.assigns)]
            if decides_first(t) and t.name not in self.plan.picks:
                self.stale(f, c, moved)
                marks = self.decided(f, t, c, vals)
                self.rows(f, c, self.update_body(f, t, c, vals, rule, marks))
                f.e(f'call void @free(ptr {marks})')
            elif t.name in self.plan.picks and moved:
                change = self.update_body(f, t, c, vals, rule)

                def body(i, cont):      # the one record: out of the ordered index, changed, back in
                    for k in moved:
                        f.e(f'call void {g(C, k, "drop")}(i64 {i})')
                    back = f.lab('back')
                    change(i, back)
                    f.br(back)
                    f.at(back)
                    for k in moved:
                        f.e(f'call void {g(C, k, "insert")}(i64 {i})')
                self.visit(f, t, c, body, vals)
            else:
                self.stale(f, c, moved)
                self.visit(f, t, c, self.update_body(f, t, c, vals, rule), vals)
        elif k == 'list' and t.name in self.plan.walks:
            self.walked_list(f, t, c, vals)
        elif k == 'list':
            names = t.fields or list(c.fields)
            if not t.order:
                shown = f.var('i64', '0') if t.limit is not None else None

                def body(i, cont):
                    rec = self.rec(f, c, i)
                    self.guard(f, self.cond(f, t.where, c, rec, vals), cont)
                    if shown:
                        sv = f.load('i64', shown)
                        self.guard(f, f.r(f'icmp slt i64 {sv}, {t.limit}'), cont)
                        f.store('i64', f.r(f'add i64 {sv}, 1'), shown)
                    self.print_fields(f, c, rec, names)
                self.visit(f, t, c, body, vals)
            else:
                self.comparator(t, c)
                n = f.load('i64', g(C, 'len'))
                idx = f.r(f'call ptr @malloc(i64 {f.r(f"add i64 {f.r(f"shl i64 {n}, 3")}, 8")})')
                cnt = f.var('i64', '0')

                def collect(i, cont):
                    self.guard(f, self.cond(f, t.where, c, self.rec(f, c, i), vals), cont)
                    cv = f.load('i64', cnt)
                    f.store('i64', i, f.r(f'getelementptr i64, ptr {idx}, i64 {cv}'))
                    f.store('i64', f.r(f'add i64 {cv}, 1'), cnt)
                self.visit(f, t, c, collect, vals)
                m = f.load('i64', cnt)
                f.e(f'call void @qsort(ptr {idx}, i64 {m}, i64 8, ptr {g("task", t.name, "cmp")})')
                if t.limit is not None:
                    m = f.r(f'select i1 {f.r(f"icmp slt i64 {m}, {t.limit}")}, i64 {m}, i64 {t.limit}')

                def emit(j, cont):
                    row = f.load('i64', f.r(f'getelementptr i64, ptr {idx}, i64 {j}'))
                    self.print_fields(f, c, self.rec(f, c, row), names)
                self.rows(f, c, emit, count=m)
                f.e(f'call void @free(ptr {idx})')
        elif k == 'agg':
            acc, cnt = f.var('i64', '0'), f.var('i64', '0')
            dec = t.fn != 'count' and c.fields[t.field].dec

            def body(i, cont, end=None):
                rec = self.rec(f, c, i)
                self.guard(f, self.cond(f, t.where, c, rec, vals), cont)
                cv = f.load('i64', cnt)
                if t.fn != 'count':
                    v = self.fload(f, c, rec, t.field)
                    a = f.load('i64', acc)
                    if t.fn in ('sum', 'avg'):
                        nv = f.r(f'add i64 {a}, {v}')
                    else:
                        better = f.r(f'icmp {"sgt" if t.fn == "max" else "slt"} i64 {v}, {a}')
                        take = f.r(f'or i1 {better}, {f.r(f"icmp eq i64 {cv}, 0")}')
                        nv = f.r(f'select i1 {take}, i64 {v}, i64 {a}')
                    f.store('i64', nv, acc)
                f.store('i64', f.r(f'add i64 {cv}, 1'), cnt)
            w = self.plan.walks.get(t.name)
            if w:
                self.walk(f, c, w, vals, False, body)
            else:
                self.visit(f, t, c, body, vals)
            n, a = f.load('i64', cnt), f.load('i64', acc)
            if t.fn == 'count':
                self.printf(f, '%lld\n', f'i64 {n}')
            elif t.fn == 'sum':
                v, ty = self.shown(f, a, 'int', dec)
                self.printf(f, '%s\n' if dec else '%lld\n', f'{LL[ty]} {v}')
            else:
                none, some = f.lab('none'), f.lab('some')
                f.cbr(f.r(f'icmp eq i64 {n}, 0'), none, some)
                f.at(none)
                self.puts(f, 'none')
                f.e('ret void')
                f.at(some)
                if t.fn == 'avg':
                    q = f.r(f'fdiv double {f.r(f"sitofp i64 {a} to double")}, {f.r(f"sitofp i64 {n} to double")}')
                    if dec:
                        q = f.r(f'fdiv double {q}, 100.0')
                    self.printf(f, '%.2f\n', f'double {q}')
                else:
                    v, ty = self.shown(f, a, 'int', dec)
                    self.printf(f, '%s\n' if dec else '%lld\n', f'{LL[ty]} {v}')
        f.e('ret void')

    def walked_list(self, f, t, c, vals):
        """A list read through an ordered index: in the order asked for, or (when the records keep
        the order they were added in and no other order is asked for) put back in that order."""
        w = self.plan.walks[t.name]
        names = t.fields or list(c.fields)
        mine = t.order is not None and t.order[0] == w.prop
        back = mine and t.order[1]
        if (mine and not (back and c.ordered)) or (not mine and not c.ordered):     # the walk order will do
            shown = f.var('i64', '0')

            def body(i, cont, end):
                rec = self.rec(f, c, i)
                self.guard(f, self.cond(f, t.where, c, rec, vals), cont)
                self.print_fields(f, c, rec, names)
                if t.limit is not None:
                    sv = f.r(f'add i64 {f.load("i64", shown)}, 1')
                    f.store('i64', sv, shown)
                    f.cbr(f.r(f'icmp sge i64 {sv}, {t.limit}'), end, cont)
                    f.at(f.lab('dead'))
            self.walk(f, c, w, vals, back, body)
            return
        # Gather the rows first: either to put them back in position order, or (largest first, in
        # records that keep their order) to turn each run of equal values round so ties stay first-added first.
        n = f.load('i64', g(c.name, 'len'))
        idx = f.r(f'call ptr @malloc(i64 {f.r(f"add i64 {f.r(f"shl i64 {n}, 3")}, 8")})')
        cnt = f.var('i64', '0')
        K = w.prop
        KT = LL[c.fields[K].type]

        def collect(i, cont, end):
            self.guard(f, self.cond(f, t.where, c, self.rec(f, c, i), vals), cont)
            cv = f.load('i64', cnt)
            if mine and t.limit is not None:        # enough once the limit is reached and the run of ties is over
                full, room = f.lab('full'), f.lab('room')
                f.cbr(f.r(f'icmp sge i64 {cv}, {t.limit}'), full, room)
                f.at(full)
                prev = f.load('i64', f.r(f'getelementptr i64, ptr {idx}, i64 {f.r(f"sub i64 {cv}, 1")}'))
                pk = self.fload(f, c, self.rec(f, c, prev), K)
                same = f.r(f'icmp eq i32 {f.r(f"call i32 {g(c.name, K, "cmp")}(i64 {i}, {KT} {pk})")}, 0')
                f.cbr(same, room, end)
                f.at(room)
            f.store('i64', i, f.r(f'getelementptr i64, ptr {idx}, i64 {cv}'))
            f.store('i64', f.r(f'add i64 {cv}, 1'), cnt)
        self.walk(f, c, w, vals, back, collect)
        m = f.load('i64', cnt)
        if not mine:
            if '@byrow' not in self.made:
                self.made.add('@byrow')
                b = self.fn('@byrow', 'i32', 'ptr %a, ptr %b', 'row numbers in ascending order, for qsort')
                ia, ib = b.load('i64', '%a'), b.load('i64', '%b')
                gt = b.r(f'zext i1 {b.r(f"icmp sgt i64 {ia}, {ib}")} to i32')
                b.e(f'ret i32 {b.r(f"sub i32 {gt}, {b.r(f"zext i1 {b.r(f"icmp slt i64 {ia}, {ib}")} to i32")}")}')
            f.e(f'call void @qsort(ptr {idx}, i64 {m}, i64 8, ptr @byrow)')
        else:
            self.untie(f, c, K, idx, m)
        if t.limit is not None:
            m = f.r(f'select i1 {f.r(f"icmp slt i64 {m}, {t.limit}")}, i64 {m}, i64 {t.limit}')

        def emit(j, cont):
            row = f.load('i64', f.r(f'getelementptr i64, ptr {idx}, i64 {j}'))
            self.print_fields(f, c, self.rec(f, c, row), names)
        self.rows(f, c, emit, count=m)
        f.e(f'call void @free(ptr {idx})')

    def untie(self, f, c, K, idx, m):
        """Walking backwards meets equal values last-added first: turn each such run round."""
        KT = LL[c.fields[K].type]
        start = f.var('i64', '0')
        head, scan, flip, done = f.lab('run'), f.lab('scan'), f.lab('flip'), f.lab('untied')
        end = f.var('i64')
        f.br(head)
        f.at(head)
        a = f.load('i64', start)
        f.cbr(f.r(f'icmp slt i64 {a}, {m}'), scan, done)
        f.at(scan)                      # the run is [a, e): every row with the same value as row idx[a]
        first = f.load('i64', f.r(f'getelementptr i64, ptr {idx}, i64 {a}'))
        key = self.fload(f, c, self.rec(f, c, first), K)
        f.store('i64', f.r(f'add i64 {a}, 1'), end)
        grow, more, stop = f.lab('grow'), f.lab('more'), f.lab('stop')
        f.br(grow)
        f.at(grow)
        e = f.load('i64', end)
        inside = f.r(f'icmp slt i64 {e}, {m}')
        f.cbr(inside, more, stop)
        f.at(more)
        row = f.load('i64', f.r(f'getelementptr i64, ptr {idx}, i64 {e}'))
        same = f.r(f'icmp eq i32 {f.r(f"call i32 {g(c.name, K, "cmp")}(i64 {row}, {KT} {key})")}, 0')
        ext = f.lab('ext')
        f.cbr(same, ext, stop)
        f.at(ext)
        f.store('i64', f.r(f'add i64 {e}, 1'), end)
        f.br(grow)
        f.at(stop)
        lo, hi = f.var('i64', a), f.var('i64', f.r(f'sub i64 {f.load("i64", end)}, 1'))
        swap, swapped = f.lab('swap'), f.lab('swapped')
        f.br(flip)
        f.at(flip)
        lv, hv = f.load('i64', lo), f.load('i64', hi)
        f.cbr(f.r(f'icmp slt i64 {lv}, {hv}'), swap, swapped)
        f.at(swap)
        pl = f.r(f'getelementptr i64, ptr {idx}, i64 {lv}')
        ph = f.r(f'getelementptr i64, ptr {idx}, i64 {hv}')
        x, y = f.load('i64', pl), f.load('i64', ph)
        f.store('i64', y, pl)
        f.store('i64', x, ph)
        f.store('i64', f.r(f'add i64 {lv}, 1'), lo)
        f.store('i64', f.r(f'sub i64 {hv}, 1'), hi)
        f.br(flip)
        f.at(swapped)
        f.store('i64', f.load('i64', end), start)
        f.br(head)
        f.at(done)

    def none_if_zero(self, f, n):
        none, done = f.lab('none'), f.lab('done')
        f.cbr(f.r(f'icmp eq i64 {n}, 0'), none, done)
        f.at(none)
        self.puts(f, 'none')
        f.br(done)
        f.at(done)

    def comparator(self, t, c):
        fld, desc = t.order
        ty = c.fields[fld].type
        f = self.fn(g('task', t.name, 'cmp'), 'i32', 'ptr %a, ptr %b',
                    f'order for "{t.name}": by {fld}{" descending" if desc else ""}, ties by row')
        ia, ib = f.load('i64', '%a'), f.load('i64', '%b')
        va = self.fload(f, c, self.rec(f, c, ia), fld)
        vb = self.fload(f, c, self.rec(f, c, ib), fld)
        if ty == 'int':
            lt = f.r(f'icmp slt i64 {va}, {vb}')
            gt = f.r(f'icmp sgt i64 {va}, {vb}')
        else:
            s = f.r(f'call i32 @strcmp(ptr {va}, ptr {vb})')
            lt = f.r(f'icmp slt i32 {s}, 0')
            gt = f.r(f'icmp sgt i32 {s}, 0')
        lo, hi = ('1', '-1') if desc else ('-1', '1')
        tie = f.r(f'select i1 {f.r(f"icmp slt i64 {ia}, {ib}")}, i32 -1, i32 1')
        r = f.r(f'select i1 {gt}, i32 {hi}, i32 {tie}')
        f.e(f'ret i32 {f.r(f"select i1 {lt}, i32 {lo}, i32 {r}")}')

    # ------------------------------------------------------------------ time, keys and the board
    def settled(self, f):
        if self.prog.rules:
            f.e('call void @settle()')

    def over(self):
        f = self.fn('@over', 'i1', comment='is the game over? true while any ending holds for any record')
        for e in self.prog.ends:
            c = self.prog.collections[e.coll]

            def body(i, cont, e=e, c=c):
                hit = f.lab('hit')
                f.cbr(self.cond(f, e.where, c, self.rec(f, c, i), {}), hit, cont)
                f.at(hit)
                f.e('ret i1 true')
                f.at(f.lab('dead'))
            self.rows(f, c, body)
        f.e('ret i1 false')

    def advance(self):
        """Time is a number of milliseconds handed in from outside, so the same run can be replayed exactly."""
        timers = self.prog.timers()
        for i, t in enumerate(timers):
            self.globals.append(f'{g("left", str(i))} = internal global i64 {t.on[1]}   ; ms until "{t.name}" happens')
        f = self.fn('@advance', params='i64 %ms',
                    comment='let time pass: whatever is due happens in the order written, then the rules settle')
        ms = f.var('i64', '%ms')
        loop, go, later, due, done = f.lab('loop'), f.lab('go'), f.lab('later'), f.lab('due'), f.lab('done')
        f.br(loop)
        f.at(loop)
        f.cbr(f.r('call i1 @over()'), done, go)
        f.at(go)
        left = [f.load('i64', g('left', str(i))) for i in range(len(timers))]
        d = left[0]
        for x in left[1:]:
            d = f.r(f'select i1 {f.r(f"icmp slt i64 {x}, {d}")}, i64 {x}, i64 {d}')
        m = f.load('i64', ms)
        f.cbr(f.r(f'icmp sgt i64 {d}, {m}'), later, due)
        f.at(later)
        for i, x in enumerate(left):
            f.store('i64', f.r(f'sub i64 {x}, {m}'), g('left', str(i)))
        f.br(done)
        f.at(due)
        f.store('i64', f.r(f'sub i64 {m}, {d}'), ms)
        for i, x in enumerate(left):
            f.store('i64', f.r(f'sub i64 {x}, {d}'), g('left', str(i)))
        for i, t in enumerate(timers):
            fire, nxt = f.lab('fire'), f.lab('next')
            f.cbr(f.r(f'icmp eq i64 {f.load("i64", g("left", str(i)))}, 0'), fire, nxt)
            f.at(fire)
            f.e(f'call void {g("task", t.name)}(ptr null)')
            f.store('i64', str(t.on[1]), g('left', str(i)))
            f.br(nxt)
            f.at(nxt)
        self.settled(f)
        f.br(loop)
        f.at(done)
        f.e('ret void')

    def press(self, key):
        f = self.fn(g('press', key), comment=f'the {key} key was pressed')
        for t in self.prog.events:
            if t.on == ('key', key):
                f.e(f'call void {g("task", t.name)}(ptr null)')
        self.settled(f)
        f.e('ret void')

    def screen(self):
        w, h = self.prog.board
        self.globals.append(f'@grid = internal global [{w * h} x i8] zeroinitializer')
        inked = has_ink(self.prog)
        if inked:
            self.globals.append(f'@ink = internal global [{w * h} x i32] zeroinitializer   ; the colour of each cell')
        if any(isinstance(d.colour, tuple) for d in self.prog.draws):
            self.colour_of()
        f = self.fn('@screen', params='i1 %live',
                    comment='draw the board as text: later sentences draw over earlier ones')
        home, clear, body = f.lab('home'), f.lab('clear'), f.lab('body')
        f.cbr('%live', home, body)
        f.at(home)
        self.printf(f, '\x1b[H')
        f.br(body)
        f.at(body)
        f.e(f'call ptr @memset(ptr @grid, i32 32, i64 {w * h})')
        if inked:
            f.e(f'call ptr @memset(ptr @ink, i32 0, i64 {w * h * 4})')
        for d in self.prog.draws:
            c = self.prog.collections.get(d.coll)

            def put(rec, cont, d=d, c=c):
                self.guard(f, self.cond(f, d.where, c, rec, {}), cont)
                x, _ = self.expr(f, d.at[0], c, rec, {})
                y, _ = self.expr(f, d.at[1], c, rec, {})
                if isinstance(d.glyph, tuple) and d.glyph[0] == 'figure':
                    f.e(f'call void {self.figure(d.glyph[1], inked)}(i64 {x}, i64 {y})')
                    return
                if d.spell:
                    text = self.cstr(d.glyph) if isinstance(d.glyph, str) else self.expr(f, d.glyph, c, rec, {})[0]
                    if isinstance(d.colour, tuple):
                        code = f.r(f'call i32 @colourof(ptr {self.expr(f, d.colour, c, rec, {})[0]})')
                    else:
                        code = str(colour_value(d.colour) if d.colour else 0)
                    f.e(f'call void {self.writer(inked)}(ptr {text}, i64 {x}, i64 {y}, i32 {code})')
                    return
                inx = f.r(f'and i1 {f.r(f"icmp sge i64 {x}, 1")}, {f.r(f"icmp sle i64 {x}, {w}")}')
                iny = f.r(f'and i1 {f.r(f"icmp sge i64 {y}, 1")}, {f.r(f"icmp sle i64 {y}, {h}")}')
                self.guard(f, f.r(f'and i1 {inx}, {iny}'), cont)
                cell = f.r(f'add i64 {f.r(f"mul i64 {f.r(f"sub i64 {y}, 1")}, {w}")}, {f.r(f"sub i64 {x}, 1")}')
                if isinstance(d.glyph, str):
                    ch = str(ord(d.glyph))
                else:                       # the first character of a text, if it is a plain one (! to ~)
                    text, _ = self.expr(f, d.glyph, c, rec, {})
                    ch = f.r(f'load i8, ptr {text}')
                    plain = f.r(f'icmp ult i8 {f.r(f"sub i8 {ch}, 33")}, 94')
                    self.guard(f, plain, cont)
                f.store('i8', ch, f.r(f'getelementptr i8, ptr @grid, i64 {cell}'))
                if inked and isinstance(d.colour, tuple):       # a colour named by a text: 0 if it names none
                    name, _ = self.expr(f, d.colour, c, rec, {})
                    f.store('i32', f.r(f'call i32 @colourof(ptr {name})'), f.r(f'getelementptr i32, ptr @ink, i64 {cell}'))
                elif inked:
                    f.store('i32', str(colour_value(d.colour) if d.colour else 0),
                            f.r(f'getelementptr i32, ptr @ink, i64 {cell}'))
            if c and d.order:               # drawn in this order, so the last one drawn is the one on top
                self.comparator(d, c)
                n = f.load('i64', g(c.name, 'len'))
                idx = f.r(f'call ptr @malloc(i64 {f.r(f"add i64 {f.r(f"shl i64 {n}, 3")}, 8")})')

                def collect(i, cont, idx=idx, c=c):
                    f.store('i64', i, f.r(f'getelementptr i64, ptr {idx}, i64 {i}'))
                self.rows(f, c, collect)
                f.e(f'call void @qsort(ptr {idx}, i64 {n}, i64 8, ptr {g("task", d.name, "cmp")})')

                def emit(j, cont, idx=idx, put=put, c=c):
                    put(self.rec(f, c, f.load('i64', f.r(f'getelementptr i64, ptr {idx}, i64 {j}'))), cont)
                self.rows(f, c, emit, count=n)
                f.e(f'call void @free(ptr {idx})')
            elif c:
                self.rows(f, c, lambda i, cont, put=put, c=c: put(self.rec(f, c, i), cont))
            else:
                skip = f.lab('skip')
                put(None, skip)
                f.br(skip)
                f.at(skip)

        def status(names):
            if not names:
                return
            S = self.prog.collections[STATE]
            rec = self.rec(f, S, '0')
            got = [(n,) + self.shown(f, self.fload(f, S, rec, n), S.fields[n].type, S.fields[n].dec) for n in names]
            fmt = '   '.join(f'{n.replace("_", " ").replace("%", "%%")} ' + ('%lld' if ty == 'int' else '%s')
                             for n, _, ty in got)
            which = f.r(f'select i1 %live, ptr {self.cstr(fmt + chr(27) + "[K" + chr(10))}, '
                        f'ptr {self.cstr(fmt + chr(10))}')
            f.e(f'call i32 (ptr, ...) @printf(ptr {which}, ' + ', '.join(f'{LL[ty]} {v}' for _, v, ty in got) + ')')
        edge = '+' + '-' * w + '+'
        status(self.prog.above)
        self.puts(f, edge)
        cur = f.var('i32') if inked else None

        def line(i, cont):
            base = f.r(f'mul i64 {i}, {w}')
            if inked:                   # colour is only put in while playing; as a command the board is plain
                fancy, plain = f.lab('fancy'), f.lab('plain')
                f.cbr('%live', fancy, plain)
                f.at(fancy)
                f.e('call i32 @putchar(i32 124)')
                f.store('i32', '0', cur)

                def cell(j, cont2):
                    at = f.r(f'add i64 {base}, {j}')
                    code = f.load('i32', f.r(f'getelementptr i32, ptr @ink, i64 {at}'))
                    same, change, rgb, basic, changed = (f.lab(x) for x in ('same', 'change', 'rgb', 'basic', 'changed'))
                    f.cbr(f.r(f'icmp eq i32 {code}, {f.load("i32", cur)}'), same, change)
                    f.at(change)
                    f.cbr(f.r(f'icmp sge i32 {code}, {RGB}'), rgb, basic)
                    f.at(rgb)
                    red = f.r(f'and i32 {f.r(f"lshr i32 {code}, 16")}, 255')
                    green = f.r(f'and i32 {f.r(f"lshr i32 {code}, 8")}, 255')
                    self.printf(f, '\x1b[38;2;%d;%d;%dm', f'i32 {red}, i32 {green}, i32 {f.r(f"and i32 {code}, 255")}')
                    f.br(changed)
                    f.at(basic)
                    self.printf(f, '\x1b[%dm', f'i32 {code}')
                    f.br(changed)
                    f.at(changed)
                    f.store('i32', code, cur)
                    f.br(same)
                    f.at(same)
                    ch = f.load('i8', f.r(f'getelementptr i8, ptr @grid, i64 {at}'))
                    f.e(f'call i32 @putchar(i32 {f.r(f"zext i8 {ch} to i32")})')
                self.rows(f, None, cell, count=str(w))
                reset, closed = f.lab('reset'), f.lab('closed')
                f.cbr(f.r(f'icmp ne i32 {f.load("i32", cur)}, 0'), reset, closed)
                f.at(reset)
                self.printf(f, '\x1b[0m')
                f.br(closed)
                f.at(closed)
                self.printf(f, '|\n')
                f.br(cont)
                f.at(plain)
            self.printf(f, '|%.*s|\n', f'i32 {w}, ptr {f.r(f"getelementptr i8, ptr @grid, i64 {base}")}')
        self.rows(f, None, line, count=str(h))
        self.puts(f, edge)
        status(self.prog.below)
        done = f.lab('done')
        f.cbr('%live', clear, done)
        f.at(clear)
        self.printf(f, '\x1b[J')
        f.br(done)
        f.at(done)
        f.e('ret void')

    def play(self):
        """Playing: the real clock and the real keyboard are turned into the same events a script would send."""
        P = self.prog
        f = self.fn('@now', 'i64', comment='the real time, in milliseconds')
        tv = f.var('[16 x i8]')
        f.e(f'call i32 @gettimeofday(ptr {tv}, ptr null)')
        sec = f.load('i64', tv)
        us = f.r(f'sext i32 {f.load("i32", f.r(f"getelementptr i8, ptr {tv}, i64 8"))} to i64')
        f.e(f'ret i64 {f.r(f"add i64 {f.r(f"mul i64 {sec}, 1000")}, {f.r(f"sdiv i64 {us}, 1000")}")}')

        # The terminal's settings are saved and put back as one opaque block, so nothing here
        # depends on how a particular system lays them out.
        self.globals.append('@terminal = internal global [512 x i8] zeroinitializer   ; its settings before playing')
        f = self.fn('@leave', comment='give the terminal back exactly the way it was')
        self.printf(f, LEAVE_PLAY)
        f.e('call i32 @fflush(ptr null)')
        f.e('call i32 @tcsetattr(i32 0, i32 0, ptr @terminal)')
        f.e('ret void')

        f = self.fn('@quit', params='i32 %sig', comment='Ctrl-C, or the terminal went away, while playing')
        f.e('call void @leave()')
        f.e('call void @exit(i32 0)')
        f.e('ret void')

        f = self.fn('@keys', 'i32', 'ptr %buf, i64 %n, ptr %jf',
                    'turn what was typed into key presses; returns 1 when the player wants to stop')
        iv, code = f.var('i64', '0'), f.var('i32', '0')
        head, body, esc, esc2, arrow, plain, keep, act, quit, done = (
            f.lab(x) for x in ('head', 'body', 'esc', 'bracket', 'arrow', 'plain', 'keep', 'act', 'quit', 'done'))

        def byte(i):
            return f.r(f'zext i8 {f.load("i8", f.r(f"getelementptr i8, ptr %buf, i64 {i}"))} to i32')
        f.br(head)
        f.at(head)
        i = f.load('i64', iv)
        f.cbr(f.r(f'icmp slt i64 {i}, %n'), body, done)
        f.at(body)
        b = byte(i)
        f.cbr(f.r(f'icmp eq i32 {b}, 27'), esc, plain)
        f.at(esc)                       # an arrow key arrives as ESC [ A..D; ESC alone means stop
        f.cbr(f.r(f'icmp slt i64 {f.r(f"add i64 {i}, 2")}, %n'), esc2, quit)
        f.at(esc2)
        f.cbr(f.r(f'icmp eq i32 {byte(f.r(f"add i64 {i}, 1"))}, 91'), arrow, quit)
        f.at(arrow)
        f.store('i32', f.r(f'add i32 {byte(f.r(f"add i64 {i}, 2"))}, 256'), code)
        f.store('i64', f.r(f'add i64 {i}, 3'), iv)
        f.br(act)
        f.at(plain)
        f.store('i64', f.r(f'add i64 {i}, 1'), iv)
        stop = f.r(f'or i1 {f.r(f"icmp eq i32 {b}, 3")}, {f.r(f"icmp eq i32 {b}, 4")}')
        f.cbr(stop, quit, keep)
        f.at(keep)
        upper = f.r(f'and i1 {f.r(f"icmp sge i32 {b}, 65")}, {f.r(f"icmp sle i32 {b}, 90")}')
        low = f.r(f'select i1 {upper}, i32 {f.r(f"add i32 {b}, 32")}, i32 {b}')
        f.store('i32', f.r(f'select i1 {f.r(f"icmp eq i32 {low}, 13")}, i32 10, i32 {low}'), code)
        f.br(act)
        f.at(act)
        cv = f.load('i32', code)
        for key in P.keys():
            yes, live, log, no = f.lab('key'), f.lab('live'), f.lab('log'), f.lab('else')
            f.cbr(f.r(f'icmp eq i32 {cv}, {KEY_CODES[key]}'), yes, no)
            f.at(yes)
            f.cbr(f.r('call i1 @over()'), head, live)
            f.at(live)
            f.e(f'call void {g("press", key)}()')
            f.cbr(f.r('icmp eq ptr %jf, null'), head, log)
            f.at(log)
            f.e(f'call i32 @fputs(ptr {self.cstr(f"press {key}" + chr(10))}, ptr %jf)')
            f.br(head)
            f.at(no)
        if 'q' not in P.keys():
            f.cbr(f.r(f'icmp eq i32 {cv}, {ord("q")}'), quit, head)
        else:
            f.br(head)
        f.at(quit)
        f.e('ret i32 1')
        f.at(done)
        f.e('ret i32 0')

        timers = P.timers()
        f = self.fn('@play', 'i32', 'ptr %jf',
                    comment='play: draw, wait for a key or for the next thing due, let that much time pass, repeat')
        buf, pfd = f.var('[16 x i8]'), f.var('{ i32, i16, i16 }')
        loop, wait, typed, decode, tick, adv, log, end, lost, bye = (
            f.lab(x) for x in ('loop', 'wait', 'typed', 'decode', 'tick', 'advance', 'log', 'end', 'lost', 'bye'))
        fallen, again, key, look, anew = (f.lab(x) for x in ('fallen', 'again', 'key', 'look', 'anew'))
        size = {'darwin': 0x40087468, 'linux': 0x5413}.get(sys.platform)     # "how big is this terminal?"
        if size:
            cols, rows = room(P)
            ws = f.var('[8 x i8]')
            asked, small, fits = f.lab('asked'), f.lab('small'), f.lab('fits')
            got = f.r(f'call i32 (i32, i64, ...) @ioctl(i32 1, i64 {size}, ptr {ws})')
            f.cbr(f.r(f'icmp eq i32 {got}, 0'), asked, fits)
            f.at(asked)
            r = f.r(f'zext i16 {f.load("i16", ws)} to i32')
            c = f.r(f'zext i16 {f.load("i16", f.r(f"getelementptr i8, ptr {ws}, i64 2"))} to i32')
            known = f.r(f'and i1 {f.r(f"icmp sgt i32 {r}, 0")}, {f.r(f"icmp sgt i32 {c}, 0")}')
            tight = f.r(f'or i1 {f.r(f"icmp slt i32 {r}, {rows}")}, {f.r(f"icmp slt i32 {c}, {cols}")}')
            f.cbr(f.r(f'and i1 {known}, {tight}'), small, fits)
            f.at(small)
            self.printf(f, TOO_SMALL + '\n', f'i32 {cols}, i32 {rows}, i32 {c}, i32 {r}')
            f.e('ret i32 1')
            f.at(fits)
        f.e('call i32 @tcgetattr(i32 0, ptr @terminal)')
        for sig in (1, 2, 15):          # hang-up, Ctrl-C, asked to stop: always give the terminal back
            f.e(f'call ptr @signal(i32 {sig}, ptr @quit)')
        f.e(f'call i32 @system(ptr {self.cstr("stty -icanon -echo min 0 time 0")})')
        self.printf(f, ENTER_PLAY)
        last = f.var('i64', f.r('call i64 @now()'))
        if uses_chance(P):              # each time it is played, chance starts somewhere else; the journal says where
            first = f.load('i64', last)
            f.store('i64', first, '@chance')
            seeded, unseeded = f.lab('seeded'), f.lab('unseeded')
            f.cbr(f.r('icmp eq ptr %jf, null'), unseeded, seeded)
            f.at(seeded)
            f.e(f'call i32 (ptr, ptr, ...) @fprintf(ptr %jf, ptr {self.cstr("seed %lld" + chr(10))}, i64 {first})')
            f.br(unseeded)
            f.at(unseeded)
        f.br(loop)
        f.at(loop)
        f.e('call void @screen(i1 true)')
        f.e('call i32 @fflush(ptr null)')
        f.cbr(f.r('call i1 @over()'), fallen, wait)
        f.at(fallen)                    # the game is over: it stays on show until the player says what next
        self.printf(f, OVER_HINT + '\x1b[K\n')
        f.e('call i32 @fflush(ptr null)')
        f.br(again)
        f.at(again)
        f.store('i32', '0', pfd)
        f.store('i16', '1', f.r(f'getelementptr {{ i32, i16, i16 }}, ptr {pfd}, i32 0, i32 1'))
        f.store('i16', '0', f.r(f'getelementptr {{ i32, i16, i16 }}, ptr {pfd}, i32 0, i32 2'))
        f.cbr(f.r(f'icmp sgt i32 {f.r(f"call i32 @poll(ptr {pfd}, i64 1, i32 1000)")}, 0'), key, again)
        f.at(key)
        got = f.r(f'call i64 @read(i32 0, ptr {buf}, i64 16)')
        f.cbr(f.r(f'icmp sgt i64 {got}, 0'), look, end)
        f.at(look)
        b0 = f.r(f'zext i8 {f.load("i8", buf)} to i32')
        enter = f.r(f'or i1 {f.r(f"icmp eq i32 {b0}, 10")}, {f.r(f"icmp eq i32 {b0}, 13")}')
        stop = f.r(f'and i1 {f.r(f"icmp eq i32 {b0}, 27")}, {f.r(f"icmp eq i64 {got}, 1")}')
        for code in (3, 4, ord('q'), ord('Q')):
            stop = f.r(f'or i1 {stop}, {f.r(f"icmp eq i32 {b0}, {code}")}')
        other = f.lab('other')
        f.cbr(enter, anew, other)
        f.at(other)
        f.cbr(stop, end, again)
        f.at(anew)
        f.e('call void @reset()')
        told, quiet = f.lab('told'), f.lab('quiet')
        f.cbr(f.r('icmp eq ptr %jf, null'), quiet, told)
        f.at(told)
        f.e(f'call i32 @fputs(ptr {self.cstr("restart" + chr(10))}, ptr %jf)')
        f.br(quiet)
        f.at(quiet)
        f.store('i64', f.r('call i64 @now()'), last)
        f.br(loop)
        f.at(wait)
        d = '1000'
        for i in range(len(timers)):
            x = f.load('i64', g('left', str(i)))
            d = f.r(f'select i1 {f.r(f"icmp slt i64 {x}, {d}")}, i64 {x}, i64 {d}')
        if timers:
            d = f.r(f'select i1 {f.r(f"icmp slt i64 {d}, 1")}, i64 1, i64 {d}')
        f.store('i32', '0', pfd)
        f.store('i16', '1', f.r(f'getelementptr {{ i32, i16, i16 }}, ptr {pfd}, i32 0, i32 1'))
        f.store('i16', '0', f.r(f'getelementptr {{ i32, i16, i16 }}, ptr {pfd}, i32 0, i32 2'))
        ready = f.r(f'call i32 @poll(ptr {pfd}, i64 1, i32 {f.r(f"trunc i64 {d} to i32")})')
        f.cbr(f.r(f'icmp sgt i32 {ready}, 0'), typed, tick)
        f.at(typed)
        nv = f.var('i64', f.r(f'call i64 @read(i32 0, ptr {buf}, i64 16)'))
        some, lone, more, rest = f.lab('some'), f.lab('lone'), f.lab('more'), f.lab('rest')
        f.cbr(f.r(f'icmp sgt i64 {f.load("i64", nv)}, 0'), some, end)
        f.at(some)                      # an arrow key is three bytes; if only the first came, give the rest a moment
        only = f.r(f'and i1 {f.r(f"icmp eq i64 {f.load("i64", nv)}, 1")}, '
                   f'{f.r(f"icmp eq i8 {f.load("i8", buf)}, 27")}')
        f.cbr(only, lone, decode)
        f.at(lone)
        f.store('i16', '0', f.r(f'getelementptr {{ i32, i16, i16 }}, ptr {pfd}, i32 0, i32 2'))
        f.cbr(f.r(f'icmp sgt i32 {f.r(f"call i32 @poll(ptr {pfd}, i64 1, i32 50)")}, 0'), more, decode)
        f.at(more)
        extra = f.r(f'call i64 @read(i32 0, ptr {f.r(f"getelementptr i8, ptr {buf}, i64 1")}, i64 15)')
        f.cbr(f.r(f'icmp sgt i64 {extra}, 0'), rest, decode)
        f.at(rest)
        f.store('i64', f.r(f'add i64 {extra}, 1'), nv)
        f.br(decode)
        f.at(decode)
        n = f.load('i64', nv)
        f.cbr(f.r(f'icmp ne i32 {f.r(f"call i32 @keys(ptr {buf}, i64 {n}, ptr %jf)")}, 0'), end, tick)
        f.at(tick)
        now = f.r('call i64 @now()')
        el = f.r(f'sub i64 {now}, {f.load("i64", last)}')
        el = f.r(f'select i1 {f.r(f"icmp sgt i64 {el}, {LONGEST_STEP}")}, i64 {LONGEST_STEP}, i64 {el}')
        f.cbr(f.r(f'icmp sgt i64 {el}, 0'), adv, loop)
        f.at(adv)
        f.store('i64', now, last)
        if timers:
            f.e(f'call void @advance(i64 {el})')
            f.cbr(f.r('icmp eq ptr %jf, null'), loop, log)
            f.at(log)
            f.e(f'call i32 (ptr, ptr, ...) @fprintf(ptr %jf, ptr {self.cstr("wait %lld" + chr(10))}, i64 {el})')
        f.br(loop)
        f.at(end)
        f.e('call void @leave()')
        f.e('call void @screen(i1 false)')      # what it looked like when it stopped stays on the terminal
        f.cbr(f.r('call i1 @over()'), lost, bye)
        f.at(lost)
        self.puts(f, OVER)
        f.br(bye)
        f.at(bye)
        f.e('call i32 @fflush(ptr null)')
        f.e('ret i32 0')

    def live(self):
        P = self.prog
        if not (P.events or P.board):
            return
        for t in P.events:
            self.task(t)
        self.over()
        if P.timers():
            self.advance()
        for k in P.keys():
            self.press(k)
        if P.board:
            self.screen()
            self.play()

    def builtin(self, f, name, line, arg):
        """wait, press and screen: commands the program answers without anyone having named them."""
        P = self.prog
        yes, no = f.lab(name), f.lab('else')
        f.cbr(self.eq(f, 'text', line, self.cstr(name)), yes, no)
        f.at(yes)
        if name == 'screen':
            f.e('call void @screen(i1 false)')
            f.e('ret i32 0')
        elif name == 'picture':         # the board for a page to paint: the screen, "~", a letter per cell for its colour
            w, h = P.board
            f.e('call void @screen(i1 false)')
            self.puts(f, '~')
            inked = has_ink(P)

            def ink_line(i, cont):
                def ink_cell(j, cont2):
                    code = '0'
                    if inked:
                        at = f.r(f'add i64 {f.r(f"mul i64 {i}, {w}")}, {j}')
                        code = f.load('i32', f.r(f'getelementptr i32, ptr @ink, i64 {at}'))
                        rgb, basic = f.lab('rgb'), f.lab('basic')
                        f.cbr(f.r(f'icmp sge i32 {code}, {RGB}'), rgb, basic)
                        f.at(rgb)               # any other colour is written out: #rrggbb
                        self.printf(f, '#%06x', f'i32 {f.r(f"and i32 {code}, 16777215")}')
                        f.br(cont2)
                        f.at(basic)
                    ch = '46'
                    for k, letter in INK_LETTER.items():
                        if k:
                            ch = f.r(f'select i1 {f.r(f"icmp eq i32 {code}, {k}")}, i32 {ord(letter)}, i32 {ch}')
                    f.e(f'call i32 @putchar(i32 {ch})')
                self.rows(f, None, ink_cell, count=str(w))
                f.e('call i32 @putchar(i32 10)')
            self.rows(f, None, ink_line, count=str(h))
            ended, alive = f.lab('ended'), f.lab('alive')
            f.cbr(f.r('call i1 @over()'), ended, alive)
            f.at(ended)
            self.puts(f, OVER)
            f.br(alive)
            f.at(alive)
            f.e('ret i32 0')
        elif name == 'restart':
            f.e('call void @reset()')
            f.e('ret i32 1')
        elif name == 'seed':
            endp = f.var('ptr')
            v = f.r(f'call i64 @strtoll(ptr {arg}, ptr {endp}, i32 10)')
            end = f.load('ptr', endp)
            bad = f.r(f'or i1 {f.r(f"icmp eq ptr {end}, {arg}")}, {f.r(f"icmp ne i8 {f.load("i8", end)}, 0")}')
            wrong, ok = f.lab('wrong'), f.lab('ok')
            f.cbr(bad, wrong, ok)
            f.at(wrong)
            self.puts(f, BAD_SEED)
            f.e('ret i32 0')
            f.at(ok)
            f.store('i64', v, '@chance')
            f.e('ret i32 1')
        elif name == 'wait':
            endp = f.var('ptr')
            v = f.r(f'call i64 @strtoll(ptr {arg}, ptr {endp}, i32 10)')
            end = f.load('ptr', endp)
            bad = f.r(f'or i1 {f.r(f"icmp eq ptr {end}, {arg}")}, {f.r(f"icmp ne i8 {f.load("i8", end)}, 0")}')
            bad = f.r(f'or i1 {bad}, {f.r(f"icmp slt i64 {v}, 0")}')
            bad = f.r(f'or i1 {bad}, {f.r(f"icmp sgt i64 {v}, {LONGEST_WAIT}")}')
            wrong, ok, over, go = f.lab('wrong'), f.lab('ok'), f.lab('over'), f.lab('go')
            f.cbr(bad, wrong, ok)
            f.at(wrong)
            self.puts(f, BAD_WAIT)
            f.e('ret i32 0')
            f.at(ok)
            f.cbr(f.r('call i1 @over()'), over, go)
            f.at(over)
            self.puts(f, OVER)
            f.e('ret i32 0')
            f.at(go)
            f.e(f'call void @advance(i64 {v})')
            f.e('ret i32 1')
        else:
            for key in P.keys():
                hit, over, go, nxt = f.lab('hit'), f.lab('over'), f.lab('go'), f.lab('next')
                f.cbr(self.eq(f, 'text', arg, self.cstr(key)), hit, nxt)
                f.at(hit)
                f.cbr(f.r('call i1 @over()'), over, go)
                f.at(over)
                self.puts(f, OVER)
                f.e('ret i32 0')
                f.at(go)
                f.e(f'call void {g("press", key)}()')
                f.e('ret i32 1')
                f.at(nxt)
            self.printf(f, 'error: no key called %s is used here\n', f'ptr {arg}')
            f.e('ret i32 0')
        f.at(no)

    # ------------------------------------------------------------------ the network
    def net(self, source_name):
        """Serving: the same commands, from many connections, one at a time in the order they arrive.

        While a command runs, what it prints goes to the connection that sent it: the program's
        output is pointed at that connection and pointed back afterwards. See web.py for the
        protocol; the interpreter serves in exactly the same way.
        """
        P = self.prog
        live = bool(P.board and P.timers())
        N = MOST + 1
        PF = '{ i32, i16, i16 }'
        self.globals += [f'@pfds = internal global [{N} x {PF}] zeroinitializer    ; who is connected (0 is the door)',
                         f'@fill = internal global [{N} x i64] zeroinitializer    ; how much each has sent so far',
                         f'@bufs = internal global [{N} x [{ROOM} x i8]] zeroinitializer',
                         '@out = internal global i32 1       ; where output goes when nobody is being answered']

        def pf(f, i, k):
            return f.r(f'getelementptr [{N} x {PF}], ptr @pfds, i64 0, i64 {i}, i32 {k}')

        def buf_of(f, i):
            return f.r(f'getelementptr [{N} x [{ROOM} x i8]], ptr @bufs, i64 0, i64 {i}, i64 0')

        def fill_of(f, i):
            return f.r(f'getelementptr [{N} x i64], ptr @fill, i64 0, i64 {i}')

        def answer_to(f, fd):
            f.e('call i32 @fflush(ptr null)')
            f.e(f'call i32 @dup2(i32 {fd}, i32 1)')

        def answered(f):
            f.e('call i32 @fflush(ptr null)')
            f.e(f'call i32 @dup2(i32 {f.load("i32", "@out")}, i32 1)')

        def diff(f, a, b):
            return f.r(f'sub i64 {f.r(f"ptrtoint ptr {a} to i64")}, {f.r(f"ptrtoint ptr {b} to i64")}')

        f = self.fn('@run_line', params='ptr %src, i64 %n, ptr %jf',
                    comment='run one command that arrived over the network; remember it if it changed anything')
        a = f.r(f'call ptr @malloc(i64 {f.r("add i64 %n, 2")})')
        f.e(f'call ptr @memmove(ptr {a}, ptr %src, i64 %n)')
        f.store('i8', '0', f.r(f'getelementptr i8, ptr {a}, i64 %n'))
        b = f.r(f'call ptr @strdup(ptr {a})')
        changed = f.r(f'call i32 @dispatch(ptr {a}, i64 %n)')
        keep, write, nl, flush, done = (f.lab(x) for x in ('keep', 'write', 'newline', 'flush', 'done'))
        f.cbr(f.r(f'icmp ne i32 {changed}, 0'), keep, done)
        f.at(keep)
        f.cbr(f.r('icmp eq ptr %jf, null'), done, write)
        f.at(write)
        f.e(f'call i32 @fputs(ptr {b}, ptr %jf)')
        lastc = f.load('i8', f.r(f'getelementptr i8, ptr {b}, i64 {f.r("sub i64 %n, 1")}'))
        f.cbr(f.r(f'icmp eq i8 {lastc}, 10'), flush, nl)
        f.at(nl)
        f.e('call i32 @fputc(i32 10, ptr %jf)')
        f.br(flush)
        f.at(flush)
        f.e('call i32 @fflush(ptr %jf)')
        f.br(done)
        f.at(done)
        f.e(f'call void @free(ptr {a})')
        f.e(f'call void @free(ptr {b})')
        f.e('ret void')

        f = self.fn('@http', 'i32', 'i64 %i, ptr %jf',
                    'a browser or another program asked over HTTP; returns 1 once it has been answered')
        buf, n = buf_of(f, '%i'), f.load('i64', fill_of(f, '%i'))
        fd = f.load('i32', pf(f, '%i', 0))
        full = f.r(f'zext i1 {f.r(f"icmp sge i64 {n}, {ROOM - 1}")} to i32')
        end = f.r(f'call ptr @strstr(ptr {buf}, ptr {self.cstr(chr(13) + chr(10) + chr(13) + chr(10))})')
        more, whole, get, post = (f.lab(x) for x in ('more', 'whole', 'get', 'post'))
        f.cbr(f.r(f'icmp eq ptr {end}, null'), more, whole)
        f.at(more)
        f.e(f'ret i32 {full}')
        f.at(whole)
        body = f.r(f'getelementptr i8, ptr {end}, i64 4')
        f.cbr(f.r(f'icmp eq i32 {f.r(f"call i32 @strncmp(ptr {buf}, ptr {self.cstr("GET ")}, i64 4)")}, 0'), get, post)
        f.at(post)                      # every line of the body is a command
        size = f.var('i64', '0')
        cl = f.r(f'call ptr @strcasestr(ptr {buf}, ptr {self.cstr("content-length:")})')
        sized, count, ready = f.lab('sized'), f.lab('count'), f.lab('ready')
        f.cbr(f.r(f'icmp eq ptr {cl}, null'), ready, sized)
        f.at(sized)
        f.cbr(f.r(f'icmp slt i64 {diff(f, cl, body)}, 0'), count, ready)
        f.at(count)
        f.store('i64', f.r(f'call i64 @strtoll(ptr {f.r(f"getelementptr i8, ptr {cl}, i64 15")}, ptr null, i32 10)'), size)
        f.br(ready)
        f.at(ready)
        want = f.load('i64', size)
        have = f.r(f'sub i64 {n}, {diff(f, body, buf)}')
        short, go = f.lab('short'), f.lab('go')
        f.cbr(f.r(f'icmp slt i64 {have}, {want}'), short, go)
        f.at(short)
        f.e(f'ret i32 {full}')
        f.at(go)
        answer_to(f, fd)
        self.printf(f, PLAIN)
        pos = f.var('i64', '0')
        head, line, cut, rest, run, fin = (f.lab(x) for x in ('head', 'line', 'cut', 'rest', 'run', 'fin'))
        length = f.var('i64')
        f.br(head)
        f.at(head)
        pv = f.load('i64', pos)
        f.cbr(f.r(f'icmp slt i64 {pv}, {want}'), line, fin)
        f.at(line)
        at = f.r(f'getelementptr i8, ptr {body}, i64 {pv}')
        left = f.r(f'sub i64 {want}, {pv}')
        nlp = f.r(f'call ptr @memchr(ptr {at}, i32 10, i64 {left})')
        f.cbr(f.r(f'icmp eq ptr {nlp}, null'), rest, cut)
        f.at(cut)
        f.store('i64', f.r(f'add i64 {diff(f, nlp, at)}, 1'), length)
        f.br(run)
        f.at(rest)
        f.store('i64', left, length)
        f.br(run)
        f.at(run)
        L = f.load('i64', length)
        f.e(f'call void @run_line(ptr {at}, i64 {L}, ptr %jf)')
        f.store('i64', f.r(f'add i64 {pv}, {L}'), pos)
        f.br(head)
        f.at(fin)
        answered(f)
        f.e('ret i32 1')
        f.at(get)                       # "/" is the page; anything else names a command: /find-by-name/ann
        path = f.r(f'getelementptr i8, ptr {buf}, i64 4')
        sp = f.r(f'call ptr @strchr(ptr {path}, i32 32)')
        bad, named, home, cmd = (f.lab(x) for x in ('bad', 'named', 'home', 'command'))
        f.cbr(f.r(f'icmp eq ptr {sp}, null'), bad, named)
        f.at(bad)
        f.e('ret i32 1')
        f.at(named)
        f.store('i8', '0', sp)
        answer_to(f, fd)
        f.cbr(f.r(f'icmp eq i32 {f.r(f"call i32 @strcmp(ptr {path}, ptr {self.cstr("/")})")}, 0'), home, cmd)
        f.at(home)
        self.printf(f, HTML)
        f.e(f'call i32 @puts(ptr {self.cstr(page(P, title_of(source_name)))})')
        answered(f)
        f.e('ret i32 1')
        f.at(cmd)
        self.printf(f, PLAIN)
        start = f.r(f'getelementptr i8, ptr {path}, i64 1')
        rp, wp, first = f.var('ptr', start), f.var('ptr', start), f.var('i1', 'true')
        hexs = f.var('[3 x i8]')
        loop, look, slash, notslash, pct, pct2, pct3, plain, put, stop = (
            f.lab(x) for x in ('loop', 'look', 'slash', 'notslash', 'pct', 'pct2', 'pct3', 'plain', 'put', 'stop'))
        ch = f.var('i8')
        f.br(loop)
        f.at(loop)
        r = f.load('ptr', rp)
        c = f.load('i8', r)
        ends = f.r(f'or i1 {f.r(f"icmp eq i8 {c}, 0")}, {f.r(f"icmp eq i8 {c}, 63")}')
        f.cbr(ends, stop, look)
        f.at(look)
        f.store('i8', c, ch)
        f.store('ptr', f.r(f'getelementptr i8, ptr {r}, i64 1'), rp)
        f.cbr(f.r(f'and i1 {f.r(f"icmp eq i8 {c}, 47")}, {f.load("i1", first)}'), slash, notslash)
        f.at(slash)                     # the first "/" parts the command from what it is given
        f.store('i8', '32', ch)
        f.store('i1', 'false', first)
        f.br(put)
        f.at(notslash)
        f.cbr(f.r(f'icmp eq i8 {c}, 37'), pct, put)
        f.at(pct)                       # %41 is the character with that number
        h1 = f.load('i8', f.r(f'getelementptr i8, ptr {r}, i64 1'))
        f.cbr(f.r(f'icmp eq i8 {h1}, 0'), put, pct2)
        f.at(pct2)
        h2 = f.load('i8', f.r(f'getelementptr i8, ptr {r}, i64 2'))
        f.cbr(f.r(f'icmp eq i8 {h2}, 0'), put, pct3)
        f.at(pct3)
        f.store('i8', h1, hexs)
        f.store('i8', h2, f.r(f'getelementptr i8, ptr {hexs}, i64 1'))
        f.store('i8', '0', f.r(f'getelementptr i8, ptr {hexs}, i64 2'))
        f.store('i8', f.r(f'trunc i64 {f.r(f"call i64 @strtoll(ptr {hexs}, ptr null, i32 16)")} to i8'), ch)
        f.store('ptr', f.r(f'getelementptr i8, ptr {r}, i64 3'), rp)
        f.br(put)
        f.at(put)
        w = f.load('ptr', wp)
        f.store('i8', f.load('i8', ch), w)
        f.store('ptr', f.r(f'getelementptr i8, ptr {w}, i64 1'), wp)
        f.br(loop)
        f.at(stop)
        w = f.load('ptr', wp)
        f.store('i8', '0', w)
        f.e(f'call void @run_line(ptr {start}, i64 {diff(f, w, start)}, ptr %jf)')
        answered(f)
        f.e('ret i32 1')

        f = self.fn('@feed', 'i32', 'i64 %i, ptr %jf',
                    'something arrived on a connection: run every whole command in it; returns 1 to hang up')
        buf, n = buf_of(f, '%i'), f.load('i64', fill_of(f, '%i'))
        fd = f.load('i32', pf(f, '%i', 0))
        isget = f.r(f'icmp eq i32 {f.r(f"call i32 @strncmp(ptr {buf}, ptr {self.cstr("GET ")}, i64 4)")}, 0')
        ispost = f.r(f'icmp eq i32 {f.r(f"call i32 @strncmp(ptr {buf}, ptr {self.cstr("POST ")}, i64 5)")}, 0')
        web, raw = f.lab('web'), f.lab('raw')
        f.cbr(f.r(f'or i1 {isget}, {ispost}'), web, raw)
        f.at(web)
        f.e(f'ret i32 {f.r("call i32 @http(i64 %i, ptr %jf)")}')
        f.at(raw)
        answer_to(f, fd)
        start = f.var('i64', '0')
        head, line, tail = f.lab('head'), f.lab('line'), f.lab('tail')
        f.br(head)
        f.at(head)
        sv = f.load('i64', start)
        at = f.r(f'getelementptr i8, ptr {buf}, i64 {sv}')
        nlp = f.r(f'call ptr @memchr(ptr {at}, i32 10, i64 {f.r(f"sub i64 {n}, {sv}")})')
        f.cbr(f.r(f'icmp eq ptr {nlp}, null'), tail, line)
        f.at(line)
        L = f.r(f'add i64 {diff(f, nlp, at)}, 1')
        f.e(f'call void @run_line(ptr {at}, i64 {L}, ptr %jf)')
        f.store('i64', f.r(f'add i64 {sv}, {L}'), start)
        f.br(head)
        f.at(tail)
        answered(f)
        left = f.r(f'sub i64 {n}, {sv}')
        f.e(f'call ptr @memmove(ptr {buf}, ptr {at}, i64 {left})')
        f.store('i64', left, fill_of(f, '%i'))
        f.e(f'ret i32 {f.r(f"zext i1 {f.r(f"icmp sge i64 {left}, {ROOM - 1}")} to i32")}')

        f = self.fn('@serve', 'i32', 'i64 %port, i32 %public, ptr %jf',
                    'listen on a port and answer whoever connects' +
                    ('; real time passes meanwhile, as when it is played' if live else ''))
        f.e('call ptr @signal(i32 13, ptr inttoptr (i64 1 to ptr))')       # a caller that hangs up is not an error
        f.store('i32', f.r('call i32 @dup(i32 1)'), '@out')
        sock = f.r('call i32 @socket(i32 2, i32 1, i32 0)')
        one = f.var('i32', '1')
        level, reuse = (65535, 4) if sys.platform == 'darwin' else (1, 2)
        f.e(f'call i32 @setsockopt(i32 {sock}, i32 {level}, i32 {reuse}, ptr {one}, i32 4)')
        addr = f.var('[16 x i8]')
        f.e(f'call ptr @memset(ptr {addr}, i32 0, i64 16)')
        if sys.platform == 'darwin':    # the address of a listener is laid out a little differently on each system
            f.store('i8', '16', addr)
            f.store('i8', '2', f.r(f'getelementptr i8, ptr {addr}, i64 1'))
        else:
            f.store('i8', '2', addr)
        f.store('i8', f.r(f'trunc i64 {f.r("lshr i64 %port, 8")} to i8'), f.r(f'getelementptr i8, ptr {addr}, i64 2'))
        f.store('i8', f.r('trunc i64 %port to i8'), f.r(f'getelementptr i8, ptr {addr}, i64 3'))
        local, bound = f.lab('local'), f.lab('bound')
        f.cbr(f.r('icmp eq i32 %public, 0'), local, bound)
        f.at(local)                     # only this machine can connect, unless it was started with serve-public
        f.store('i8', '127', f.r(f'getelementptr i8, ptr {addr}, i64 4'))
        f.store('i8', '1', f.r(f'getelementptr i8, ptr {addr}, i64 7'))
        f.br(bound)
        f.at(bound)
        failed, open_ = f.lab('failed'), f.lab('open')
        got = f.r(f'call i32 @bind(i32 {sock}, ptr {addr}, i32 16)')
        f.cbr(f.r(f'icmp ne i32 {got}, 0'), failed, open_)
        f.at(failed)
        self.printf(f, 'error: cannot listen on port %lld\n', 'i64 %port')
        f.e('ret i32 1')
        f.at(open_)
        f.e(f'call i32 @listen(i32 {sock}, i32 64)')
        self.printf(f, 'serving on port %lld\n', 'i64 %port')
        f.e('call i32 @fflush(ptr null)')
        self.rows(f, None, lambda i, cont: f.store('i32', '-1', pf(f, i, 0)), count=str(N))
        f.store('i32', sock, pf(f, '0', 0))
        f.store('i16', '1', pf(f, '0', 1))
        if live:
            last = f.var('i64', f.r('call i64 @now()'))
            if uses_chance(P):
                first = f.load('i64', last)
                f.store('i64', first, '@chance')
                seeded, unseeded = f.lab('seeded'), f.lab('unseeded')
                f.cbr(f.r('icmp eq ptr %jf, null'), unseeded, seeded)
                f.at(seeded)
                f.e(f'call i32 (ptr, ptr, ...) @fprintf(ptr %jf, ptr {self.cstr("seed %lld" + chr(10))}, i64 {first})')
                f.br(unseeded)
                f.at(unseeded)
        loop = f.lab('loop')
        f.br(loop)
        f.at(loop)
        wait = '-1'
        if live:
            d = '1000'
            for i in range(len(P.timers())):
                x = f.load('i64', g('left', str(i)))
                d = f.r(f'select i1 {f.r(f"icmp slt i64 {x}, {d}")}, i64 {x}, i64 {d}')
            d = f.r(f'select i1 {f.r(f"icmp slt i64 {d}, 1")}, i64 1, i64 {d}')
            wait = f.r(f'trunc i64 {d} to i32')
        f.e(f'call i32 @poll(ptr @pfds, i64 {N}, i32 {wait})')
        if live:                        # real time becomes "wait", the same thing a script would send
            tick, adv, log, ticked = f.lab('tick'), f.lab('advance'), f.lab('log'), f.lab('ticked')
            now = f.r('call i64 @now()')
            el = f.r(f'sub i64 {now}, {f.load("i64", last)}')
            el = f.r(f'select i1 {f.r(f"icmp sgt i64 {el}, {LONGEST_STEP}")}, i64 {LONGEST_STEP}, i64 {el}')
            f.cbr(f.r(f'icmp sgt i64 {el}, 0'), tick, ticked)
            f.at(tick)
            f.store('i64', now, last)
            f.cbr(f.r('call i1 @over()'), ticked, adv)
            f.at(adv)
            f.e(f'call void @advance(i64 {el})')
            f.cbr(f.r('icmp eq ptr %jf, null'), ticked, log)
            f.at(log)
            f.e(f'call i32 (ptr, ptr, ...) @fprintf(ptr %jf, ptr {self.cstr("wait %lld" + chr(10))}, i64 {el})')
            f.br(ticked)
            f.at(ticked)
        knock, seat, none_free, heard = f.lab('knock'), f.lab('seat'), f.lab('nofree'), f.lab('heard')
        door = f.load('i16', pf(f, '0', 2))
        f.cbr(f.r(f'icmp ne i16 {f.r(f"and i16 {door}, 1")}, 0'), knock, heard)
        f.at(knock)
        conn = f.r(f'call i32 @accept(i32 {sock}, ptr null, ptr null)')
        slot = f.var('i64', '0')
        f.store('i64', '0', slot)

        def find(i, cont):
            free = f.r(f'icmp slt i32 {f.load("i32", pf(f, i, 0))}, 0')
            unset = f.r(f'icmp eq i64 {f.load("i64", slot)}, 0')
            self.guard(f, f.r(f'and i1 {free}, {unset}'), cont)
            f.store('i64', i, slot)
        self.rows(f, None, find, count=str(N))
        sv = f.load('i64', slot)
        usable = f.r(f'and i1 {f.r(f"icmp sgt i64 {sv}, 0")}, {f.r(f"icmp sge i32 {conn}, 0")}')
        f.cbr(usable, seat, none_free)
        f.at(seat)
        f.store('i32', conn, pf(f, sv, 0))
        f.store('i16', '1', pf(f, sv, 1))
        f.store('i16', '0', pf(f, sv, 2))
        f.store('i64', '0', fill_of(f, sv))
        f.br(heard)
        f.at(none_free)
        f.e(f'call i32 @close(i32 {conn})')
        f.br(heard)
        f.at(heard)

        def hear(i, cont):
            self.guard(f, f.r(f'icmp sgt i64 {i}, 0'), cont)
            fd = f.load('i32', pf(f, i, 0))
            self.guard(f, f.r(f'icmp sge i32 {fd}, 0'), cont)
            self.guard(f, f.r(f'icmp ne i16 {f.load("i16", pf(f, i, 2))}, 0'), cont)
            f.store('i16', '0', pf(f, i, 2))
            n = f.load('i64', fill_of(f, i))
            buf = buf_of(f, i)
            got = f.r(f'call i64 @read(i32 {fd}, ptr {f.r(f"getelementptr i8, ptr {buf}, i64 {n}")}, '
                      f'i64 {f.r(f"sub i64 {ROOM - 1}, {n}")})')
            some, gone = f.lab('some'), f.lab('gone')
            f.cbr(f.r(f'icmp sgt i64 {got}, 0'), some, gone)
            f.at(some)
            total = f.r(f'add i64 {n}, {got}')
            f.store('i64', total, fill_of(f, i))
            f.store('i8', '0', f.r(f'getelementptr i8, ptr {buf}, i64 {total}'))
            f.cbr(f.r(f'icmp ne i32 {f.r(f"call i32 @feed(i64 {i}, ptr %jf)")}, 0'), gone, cont)
            f.at(gone)
            f.e(f'call i32 @close(i32 {fd})')
            f.store('i32', '-1', pf(f, i, 0))
        self.rows(f, None, hear, count=str(N))
        f.br(loop)
        f.at(f.lab('never'))
        f.e('ret i32 0')

    # ------------------------------------------------------------------ main
    def dispatch(self):
        self.globals.append('@dirty = internal global i32 0     ; set when a command really changed data')
        self.globals.append('@touched = internal global i64 -1  ; the one record a command added or changed, if any')
        f = self.fn('@dispatch', 'i32', 'ptr %line, i64 %len',
                    'run one command line; returns 1 if it may have changed the data')
        line = '%line'
        nv = f.var('i64', '%len')
        for ch in (10, 13):
            n = f.load('i64', nv)
            some, strip, skip = f.lab('some'), f.lab('strip'), f.lab('skip')
            f.cbr(f.r(f'icmp sgt i64 {n}, 0'), some, skip)
            f.at(some)
            lastp = f.r(f'getelementptr i8, ptr {line}, i64 {f.r(f"sub i64 {n}, 1")}')
            f.cbr(f.r(f'icmp eq i8 {f.load("i8", lastp)}, {ch}'), strip, skip)
            f.at(strip)
            f.store('i8', '0', lastp)
            f.store('i64', f.r(f'sub i64 {n}, 1'), nv)
            f.br(skip)
            f.at(skip)
        n = f.load('i64', nv)
        work, empty = f.lab('work'), f.lab('empty')
        f.cbr(f.r(f'icmp eq i64 {n}, 0'), empty, work)
        f.at(empty)
        f.e('ret i32 0')
        f.at(work)
        argv = f.var('ptr', f.r(f'getelementptr i8, ptr {line}, i64 {n}'))
        sp = f.r(f'call ptr @strchr(ptr {line}, i32 32)')
        cut, disp = f.lab('cut'), f.lab('dispatch')
        f.cbr(f.r(f'icmp eq ptr {sp}, null'), disp, cut)
        f.at(cut)
        f.store('i8', '0', sp)
        f.store('ptr', f.r(f'getelementptr i8, ptr {sp}, i64 1'), argv)
        f.br(disp)
        f.at(disp)
        arg = f.load('ptr', argv)
        for t in self.prog.tasks:
            yes, no = f.lab('run'), f.lab('else')
            f.cbr(self.eq(f, 'text', line, self.cstr(t.name)), yes, no)
            f.at(yes)
            f.store('i32', '0', '@dirty')
            f.store('i64', '-1', '@touched')
            f.e(f'call void {g("task", t.name)}(ptr {arg})')
            if t.kind in MUTATING and self.prog.rules:
                narrow = narrow_settle(self.prog, self.plan, t)
                if narrow == 'all':
                    f.e('call void @settle()')
                else:                   # untouched records are still as the rules left them: look only where needed
                    full, quick, after = f.lab('full'), f.lab('quick'), f.lab('after')
                    f.cbr(f.r(f'icmp ne i32 {f.load("i32", "@unsettled")}, 0'), full, quick)
                    f.at(full)
                    f.e('call void @settle()')
                    f.br(after)
                    f.at(quick)
                    if narrow == 'row' and any(r.coll == t.coll for r in self.prog.rules):
                        row = f.load('i64', '@touched')
                        one = f.lab('one')
                        f.cbr(f.r(f'icmp sge i64 {row}, 0'), one, after)
                        f.at(one)
                        f.e(f'call void {g("settle", t.coll)}(i64 {row})')
                    f.br(after)
                    f.at(after)
            f.e(f'ret i32 {f.load("i32", "@dirty")}')
            f.at(no)
        for name, _ in builtins(self.prog):
            self.builtin(f, name, line, arg)
        if all(t.name != 'help' for t in self.prog.tasks):
            yes, no = f.lab('help'), f.lab('else')
            f.cbr(self.eq(f, 'text', line, self.cstr('help')), yes, no)
            f.at(yes)
            self.puts(f, '\n'.join(usage(self.prog)))
            f.e('ret i32 0')
            f.at(no)
        self.printf(f, 'error: unknown command %s\n', f'ptr {line}')
        f.e('ret i32 0')

    def reset(self):
        f = self.fn('@reset', comment='everything as it was at the start (chance is not wound back)')
        for c in self.prog.collections.values():
            self.rows(f, c, lambda i, cont, c=c: f.e(f'call void {g(c.name, "free")}(ptr {self.rec(f, c, i)})'))
            f.store('i64', '0', g(c.name, 'len'))
            f.e(f'call void {g(c.name, "reindex")}()')
            self.stale(f, c)
        for i, t in enumerate(self.prog.timers()):
            f.store('i64', str(t.on[1]), g('left', str(i)))
        f.e('call void @start()')
        f.e('ret void')

    def start(self):
        """The single values take their starting values, and the standing rules get their first look."""
        f = self.fn('@start', comment='before the first command: starting values, then the rules')
        S = self.prog.collections.get(STATE)
        if S:
            f.e(f'call void {g(STATE, "grow")}()')
            rec = self.rec(f, S, '0')
            for fl in S.fields.values():
                v = str(fl.init) if fl.type == 'int' else f.r(f'call ptr @strdup(ptr {self.cstr(fl.init)})')
                f.store(LL[fl.type], v, self.fptr(f, S, rec, fl.name))
            f.store('i64', '1', g(STATE, 'len'))
        for s in self.prog.seeds:       # what is there from the start
            c, cp = self.prog.collections[s.coll], self.plan.colls[s.coll]

            def one(counted, s=s, c=c, cp=cp):
                f.e(f'call void {g(c.name, "grow")}()')
                n = f.load('i64', g(c.name, 'len'))
                vals = {name: self.expr(f, e, c, None, {}) for name, e in s.assigns}
                vals.update(counted)
                self.store_record(f, c, self.rec(f, c, n), vals)
                f.store('i64', f.r(f'add i64 {n}, 1'), g(c.name, 'len'))
                for ix in cp.indexes:
                    f.e(f'call void {g(c.name, ix, "put")}(i64 {n})')
                for ox in cp.orders:
                    f.e(f'call void {g(c.name, ox, "insert")}(i64 {n})')

            def count(k, counted, s=s, c=c, one=one):
                if k == len(s.ranges):      # every combination, the first range outermost
                    return one(counted)
                name, lo, hi = s.ranges[k]
                v = f.var('i64', str(lo))
                head, body, done = f.lab('count'), f.lab('each'), f.lab('counted')
                f.br(head)
                f.at(head)
                cur = f.load('i64', v)
                f.cbr(f.r(f'icmp sle i64 {cur}, {hi}'), body, done)
                f.at(body)
                val = f.r(f'mul i64 {cur}, 100') if c.fields[name].dec else cur
                count(k + 1, dict(counted, **{name: (val, 'int')}))
                f.store('i64', f.r(f'add i64 {cur}, 1'), v)
                f.br(head)
                f.at(done)
            count(0, {})
        if self.prog.rules:
            f.e('call void @settle()')
        f.e('ret void')

    def settle(self):
        self.globals.append('@changed = internal global i32 0   ; set when a rule really changed something')
        self.globals.append('@unsettled = internal global i32 0 ; set while the rules have not come to rest')

        def rounds(f, calls):
            n_ = f.var('i64', '0')
            loop, more, stuck, rest, done = (f.lab(x) for x in ('round', 'more', 'stuck', 'rest', 'done'))
            f.br(loop)
            f.at(loop)
            f.store('i32', '0', '@changed')
            for call in calls:
                f.e(call)
            f.cbr(f.r(f'icmp ne i32 {f.load("i32", "@changed")}, 0'), more, rest)
            f.at(more)
            n = f.r(f'add i64 {f.load("i64", n_)}, 1')
            f.store('i64', n, n_)
            f.cbr(f.r(f'icmp slt i64 {n}, {ROUNDS}'), loop, stuck)
            f.at(stuck)
            self.puts(f, UNSETTLED)
            f.store('i32', '1', '@unsettled')
            f.br(done)
            f.at(rest)
            f.store('i32', '0', '@unsettled')
            f.br(done)
            f.at(done)
            f.e('ret void')
        f = self.fn('@settle', comment='apply every rule, in the order written, until a whole round changes nothing')
        rounds(f, [f'call void {g("rule", r.name)}(ptr null)' for r in self.prog.rules])
        if not self.plan.local_rules:
            return
        # Every rule reads and changes one record only. So a record no command touched is still
        # exactly as the rules left it, and after a command that touched one record it is enough
        # to let the rules look at that record again.
        for r in self.prog.rules:
            c = self.prog.collections[r.coll]
            f = self.fn(g('rule1', r.name), params='i64 %row', comment=f'the rule on line {r.line}, for one {c.name}')
            cont = f.lab('cont')
            self.update_body(f, r, c, {}, True)('%row', cont)
            f.br(cont)
            f.at(cont)
            f.e('ret void')
        for name in dict.fromkeys(r.coll for r in self.prog.rules):
            f = self.fn(g('settle', name), params='i64 %row',
                        comment=f'apply the rules about one {name} to that record until nothing changes')
            rounds(f, [f'call void {g("rule1", r.name)}(i64 %row)' for r in self.prog.rules if r.coll == name])

    def main(self):
        """Commands come from stdin. Given a file name, the program also remembers:

        every command that can change data is appended to that file, and on start the file is
        replayed with output switched off. The language is deterministic, so replaying the
        commands rebuilds exactly the same data.
        """
        self.dispatch()
        self.net(self.source_name)
        f = Fn('@main', 'i32', 'i32 %argc, ptr %argv',
               'read one command per line and run it; with a file argument, remember across runs')
        f.text = lambda: Fn.text(f).replace('define internal', 'define', 1)
        self.fns.append(f)
        linep, capp, nv = f.var('ptr', 'null'), f.var('i64', '0'), f.var('i64')
        journal = f.var('ptr', 'null')
        f.e('call void @start()')
        # "serve 8080 [file]" answers over the network; "serve-public" lets other machines connect too
        mode, jarg = f.var('i32', '0'), f.var('i64', '1')
        asked, plainly, chosen, noport, withport = (f.lab(x) for x in ('asked', 'plainly', 'chosen', 'noport', 'withport'))
        f.cbr(f.r('icmp sgt i32 %argc, 1'), asked, chosen)
        f.at(asked)
        word = f.load('ptr', f.r('getelementptr ptr, ptr %argv, i64 1'))
        loc = f.r(f'icmp eq i32 {f.r(f"call i32 @strcmp(ptr {word}, ptr {self.cstr("serve")})")}, 0')
        pub = f.r(f'icmp eq i32 {f.r(f"call i32 @strcmp(ptr {word}, ptr {self.cstr("serve-public")})")}, 0')
        f.cbr(f.r(f'or i1 {loc}, {pub}'), plainly, chosen)
        f.at(plainly)
        f.cbr(f.r('icmp sgt i32 %argc, 2'), withport, noport)
        f.at(noport)
        self.puts(f, 'error: serve needs a port, e.g. "serve 8080"')
        f.e('ret i32 1')
        f.at(withport)
        f.store('i32', f.r(f'select i1 {pub}, i32 2, i32 1'), mode)
        f.store('i64', '3', jarg)
        f.br(chosen)
        f.at(chosen)
        named, serve = f.lab('named'), f.lab('serve')
        jat = f.load('i64', jarg)
        f.cbr(f.r(f'icmp sgt i64 {f.r("sext i32 %argc to i64")}, {jat}'), named, serve)
        f.at(named)
        path = f.load('ptr', f.r(f'getelementptr ptr, ptr %argv, i64 {jat}'))
        old = f.r(f'call ptr @fopen(ptr {path}, ptr {self.cstr("r")})')
        replay, opened = f.lab('replay'), f.lab('open')
        f.cbr(f.r(f'icmp eq ptr {old}, null'), opened, replay)
        f.at(replay)
        f.e('call i32 @fflush(ptr null)')
        saved = f.r('call i32 @dup(i32 1)')
        nul = f.r(f'call i32 (ptr, i32, ...) @open(ptr {self.cstr("/dev/null")}, i32 1)')
        f.e(f'call i32 @dup2(i32 {nul}, i32 1)')
        f.e(f'call i32 @close(i32 {nul})')
        rl, rgot, rdone = f.lab('rloop'), f.lab('rgot'), f.lab('rdone')
        f.br(rl)
        f.at(rl)
        f.store('i64', f.r(f'call i64 @getline(ptr {linep}, ptr {capp}, ptr {old})'), nv)
        f.cbr(f.r(f'icmp sle i64 {f.load("i64", nv)}, 0'), rdone, rgot)
        f.at(rgot)
        f.e(f'call i32 @dispatch(ptr {f.load("ptr", linep)}, i64 {f.load("i64", nv)})')
        f.br(rl)
        f.at(rdone)
        f.e('call i32 @fflush(ptr null)')
        f.e(f'call i32 @dup2(i32 {saved}, i32 1)')
        f.e(f'call i32 @close(i32 {saved})')
        f.e(f'call i32 @fclose(ptr {old})')
        f.br(opened)
        f.at(opened)
        out = f.r(f'call ptr @fopen(ptr {path}, ptr {self.cstr("a")})')
        f.store('ptr', out, journal)
        bad = f.lab('bad')
        f.cbr(f.r(f'icmp eq ptr {out}, null'), bad, serve)
        f.at(bad)
        self.printf(f, 'error: cannot write to %s\n', f'ptr {path}')
        f.e('ret i32 1')
        f.at(serve)
        jf = f.load('ptr', journal)
        net, local = f.lab('net'), f.lab('local')
        f.cbr(f.r(f'icmp ne i32 {f.load("i32", mode)}, 0'), net, local)
        f.at(net)
        port = f.r(f'call i64 @strtoll(ptr {f.load("ptr", f.r("getelementptr ptr, ptr %argv, i64 2"))}, ptr null, i32 10)')
        public = f.r(f'zext i1 {f.r(f"icmp eq i32 {f.load("i32", mode)}, 2")} to i32')
        f.e(f'ret i32 {f.r(f"call i32 @serve(i64 {port}, i32 {public}, ptr {jf})")}')
        f.at(local)
        if self.prog.board:             # at a terminal the program is played; over a pipe it takes commands
            both = f.r(f'and i32 {f.r("call i32 @isatty(i32 0)")}, {f.r("call i32 @isatty(i32 1)")}')
            play, commands = f.lab('play'), f.lab('commands')
            f.cbr(f.r(f'icmp ne i32 {both}, 0'), play, commands)
            f.at(play)
            f.e(f'ret i32 {f.r(f"call i32 @play(ptr {jf})")}')
            f.at(commands)
        fp = f.r(f'call ptr @fdopen(i32 0, ptr {self.cstr("r")})')
        loop, got, done = f.lab('loop'), f.lab('got'), f.lab('done')
        f.br(loop)
        f.at(loop)
        f.store('i64', f.r(f'call i64 @getline(ptr {linep}, ptr {capp}, ptr {fp})'), nv)
        f.cbr(f.r(f'icmp sle i64 {f.load("i64", nv)}, 0'), done, got)
        f.at(got)
        line, n = f.load('ptr', linep), f.load('i64', nv)
        plain, logged = f.lab('plain'), f.lab('logged')
        f.cbr(f.r(f'icmp eq ptr {jf}, null'), plain, logged)
        f.at(plain)
        f.e(f'call i32 @dispatch(ptr {line}, i64 {n})')
        f.e('call i32 @fflush(ptr null)')        # answer now, so the program can be driven over a pipe
        f.br(loop)
        f.at(logged)
        copy = f.r(f'call ptr @strdup(ptr {line})')
        changed = f.r(f'call i32 @dispatch(ptr {line}, i64 {n})')
        write, release = f.lab('write'), f.lab('release')
        f.cbr(f.r(f'icmp ne i32 {changed}, 0'), write, release)
        f.at(write)
        f.e(f'call i32 @fputs(ptr {copy}, ptr {jf})')
        lastc = f.load('i8', f.r(f'getelementptr i8, ptr {copy}, i64 {f.r(f"sub i64 {n}, 1")}'))
        nl, flush = f.lab('newline'), f.lab('flush')
        f.cbr(f.r(f'icmp eq i8 {lastc}, 10'), flush, nl)
        f.at(nl)
        f.e(f'call i32 @fputc(i32 10, ptr {jf})')
        f.br(flush)
        f.at(flush)
        f.e(f'call i32 @fflush(ptr {jf})')
        f.br(release)
        f.at(release)
        f.e('call i32 @fflush(ptr null)')
        f.e(f'call void @free(ptr {copy})')
        f.br(loop)
        f.at(done)
        f.e('ret i32 0')

    def module(self, source_name):
        self.source_name = source_name
        for c in self.prog.collections.values():
            self.collection(c, self.plan.colls[c.name])
        for d in self.prog.collections.values():
            for rf in d.fields.values():
                if rf.ref:
                    self.relation(d, rf)
        self.decimals()
        self.maths()
        for t in self.prog.tasks:
            self.task(t)
        for r in self.prog.rules:
            self.task(r, rule=True)
        if self.prog.rules:
            self.settle()
        self.live()
        if uses_chance(self.prog):
            self.chance()
        if self.prog.ends or self.prog.board:
            self.reset()
        self.start()
        self.main()
        return (f'; Generated by the Intent compiler from {source_name}.\n'
                f'; There is no intermediate program in any other language: Intent IR is lowered straight to this.\n\n'
                + DECLS + LIVE_DECLS + NET_DECLS + '\n' + '\n'.join(self.globals) + '\n\n' + '\n'.join(f.text() for f in self.fns))


def emit(prog, plan, source_name='<intent>'):
    return Gen(prog, plan).module(source_name)
