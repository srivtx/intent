"""Intent IR + plan -> LLVM IR text. No other programming language sits in between.

The generated module is a small command server: it reads one command per line on stdin
("<capability> <comma-separated arguments>") and writes results to stdout. It calls libc
for I/O, memory and sorting; everything else (records, hash indexes, loops, filters,
aggregates) is emitted here.
"""
from .interp import ROUNDS, UNSETTLED
import sys

from .ir import (BAD_WAIT, ENTER_PLAY, LEAVE_PLAY, TOO_SMALL, room, KEY_CODES, LONGEST_STEP, LONGEST_WAIT, MUTATING, OVER, STATE, TEXT_OPS, builtins, canon,
                 fmt_event, usage)

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
declare ptr @memmove(ptr, ptr, i64)
declare void @qsort(ptr, i64, i64, ptr)
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
        a = self.cond(f, cnd[1], c, rec, vals)
        b = self.cond(f, cnd[2], c, rec, vals)
        return f.r(f'{cnd[0]} i1 {a}, {b}')

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

        f = self.fn(g(C, 'reindex'), comment=f'{C}: rebuild every index after rows moved')
        for k in cp.indexes:
            f.e(f'call void {g(C, k, "rebuild")}()')
        f.e('ret void')

        if cp.removal:
            self.remove_row(c, cp, size)

    def print_fields(self, f, c, rec, names):
        got = [self.expr(f, ('pfield',) + tuple(n.split('.')) if '.' in n else ('field', n), c, rec, {})
               for n in names]
        fmt = ','.join('%lld' if ty == 'int' else '%s' for _, ty in got) + '\n'
        self.printf(f, fmt, ', '.join(f'{LL[ty]} {v}' for v, ty in got))

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

        def orphan(rec):
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

    def remove_row(self, c, cp, size):
        C = c.name
        how = 'swap the last record into the hole' if cp.removal == 'swap' else 'close the gap, keeping order'
        f = self.fn(g(C, 'remove_row'), params='i64 %row', comment=f'{C}: remove one record; {how}')
        p = self.rec(f, c, '%row')

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
            f.e(f'call ptr @memmove(ptr {p}, ptr {lp}, i64 {size})')
            f.br(done)
            f.at(done)
            f.store('i64', last, g(C, 'len'))
        else:
            nxt = f.r(f'getelementptr %"{C}", ptr {p}, i64 1')
            nbytes = f.r(f'mul i64 {f.r(f"sub i64 {last}, %row")}, {size}')
            f.e(f'call ptr @memmove(ptr {p}, ptr {nxt}, i64 {nbytes})')
            f.store('i64', last, g(C, 'len'))
            f.e(f'call void {g(C, "reindex")}()')
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
            if t.ptypes[p] == 'int':
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
            f.cbr(remove_if(rec), drop, keep)
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
                    rec = self.rec(f, c, row)
                    f.e(f'call void {g(C, "free")}(ptr {rec})')
                    self.store_record(f, c, rec, vals)
                else:
                    self.puts(f, f'duplicate {fl.name}')
                f.e('ret void')
                f.at(ok)
            f.store('i32', '1', '@dirty')
            f.e(f'call void {g(C, "grow")}()')
            n = f.load('i64', g(C, 'len'))
            self.store_record(f, c, self.rec(f, c, n), vals)
            f.store('i64', f.r(f'add i64 {n}, 1'), g(C, 'len'))
            for ix in cp.indexes:
                f.e(f'call void {g(C, ix, "put")}(i64 {n})')
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
                goes = lambda rec: self.eq(f, kt, self.fload(f, c, rec, t.key), kv)       # noqa: E731
            else:
                goes = lambda rec: self.cond(f, t.where, c, rec, vals)                    # noqa: E731
            if self.kids(c, 'restrict'):
                def check(i, cont):
                    rec = self.rec(f, c, i)
                    self.guard(f, goes(rec), cont)
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
            if k == 'remove_key':
                self.none_if_zero(f, f.r(f'sub i64 {before}, {kept}'))
        elif k == 'update':
            if not rule:
                f.store('i32', '1', '@dirty')

            def body(i, cont):
                rec = self.rec(f, c, i)
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
            self.rows(f, c, body)
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
                self.rows(f, c, body)
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
                self.rows(f, c, collect)
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

            def body(i, cont):
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
            self.rows(f, c, body)
            n, a = f.load('i64', cnt), f.load('i64', acc)
            if t.fn == 'count':
                self.printf(f, '%lld\n', f'i64 {n}')
            elif t.fn == 'sum':
                self.printf(f, '%lld\n', f'i64 {a}')
            else:
                none, some = f.lab('none'), f.lab('some')
                f.cbr(f.r(f'icmp eq i64 {n}, 0'), none, some)
                f.at(none)
                self.puts(f, 'none')
                f.e('ret void')
                f.at(some)
                if t.fn == 'avg':
                    q = f.r(f'fdiv double {f.r(f"sitofp i64 {a} to double")}, {f.r(f"sitofp i64 {n} to double")}')
                    self.printf(f, '%.2f\n', f'double {q}')
                else:
                    self.printf(f, '%lld\n', f'i64 {a}')
        f.e('ret void')

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
        f = self.fn('@screen', params='i1 %live',
                    comment='draw the board as text: later sentences draw over earlier ones')
        home, clear, body = f.lab('home'), f.lab('clear'), f.lab('body')
        f.cbr('%live', home, body)
        f.at(home)
        self.printf(f, '\x1b[H')
        f.br(body)
        f.at(body)
        f.e(f'call ptr @memset(ptr @grid, i32 32, i64 {w * h})')
        for d in self.prog.draws:
            c = self.prog.collections.get(d.coll)

            def put(rec, cont, d=d, c=c):
                self.guard(f, self.cond(f, d.where, c, rec, {}), cont)
                x, _ = self.expr(f, d.at[0], c, rec, {})
                y, _ = self.expr(f, d.at[1], c, rec, {})
                inx = f.r(f'and i1 {f.r(f"icmp sge i64 {x}, 1")}, {f.r(f"icmp sle i64 {x}, {w}")}')
                iny = f.r(f'and i1 {f.r(f"icmp sge i64 {y}, 1")}, {f.r(f"icmp sle i64 {y}, {h}")}')
                self.guard(f, f.r(f'and i1 {inx}, {iny}'), cont)
                cell = f.r(f'add i64 {f.r(f"mul i64 {f.r(f"sub i64 {y}, 1")}, {w}")}, {f.r(f"sub i64 {x}, 1")}')
                f.store('i8', str(ord(d.glyph)), f.r(f'getelementptr i8, ptr @grid, i64 {cell}'))
            if c:
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
            got = [(n, self.fload(f, S, rec, n), S.fields[n].type) for n in names]
            fmt = '   '.join(f'{n.replace("_", " ").replace("%", "%%")} ' + ('%lld' if ty == 'int' else '%s')
                             for n, _, ty in got)
            which = f.r(f'select i1 %live, ptr {self.cstr(fmt + chr(27) + "[K" + chr(10))}, '
                        f'ptr {self.cstr(fmt + chr(10))}')
            f.e(f'call i32 (ptr, ...) @printf(ptr {which}, ' + ', '.join(f'{LL[ty]} {v}' for _, v, ty in got) + ')')
        edge = '+' + '-' * w + '+'
        status(self.prog.above)
        self.puts(f, edge)
        self.rows(f, None, lambda i, cont: self.printf(
            f, '|%.*s|\n', f'i32 {w}, ptr {f.r(f"getelementptr i8, ptr @grid, i64 {f.r(f"mul i64 {i}, {w}")}")}'),
            count=str(h))
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
        f.br(loop)
        f.at(loop)
        f.e('call void @screen(i1 true)')
        f.e('call i32 @fflush(ptr null)')
        f.cbr(f.r('call i1 @over()'), end, wait)
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
        f.cbr(f.r(f'icmp sgt i32 {f.r(f"call i32 @poll(ptr {pfd}, i64 1, i32 25)")}, 0'), more, decode)
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

    # ------------------------------------------------------------------ main
    def dispatch(self):
        self.globals.append('@dirty = internal global i32 0     ; set when a command really changed data')
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
            f.e(f'call void {g("task", t.name)}(ptr {arg})')
            if t.kind in MUTATING and self.prog.rules:
                f.e('call void @settle()')
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
            f.e(f'call void {g(c.name, "grow")}()')
            n = f.load('i64', g(c.name, 'len'))
            vals = {name: self.expr(f, e, c, None, {}) for name, e in s.assigns}
            self.store_record(f, c, self.rec(f, c, n), vals)
            f.store('i64', f.r(f'add i64 {n}, 1'), g(c.name, 'len'))
            for ix in cp.indexes:
                f.e(f'call void {g(c.name, ix, "put")}(i64 {n})')
        if self.prog.rules:
            f.e('call void @settle()')
        f.e('ret void')

    def settle(self):
        self.globals.append('@changed = internal global i32 0   ; set when a rule really changed something')
        f = self.fn('@settle', comment='apply every rule, in the order written, until a whole round changes nothing')
        rounds = f.var('i64', '0')
        loop, more, stuck, done = f.lab('round'), f.lab('more'), f.lab('stuck'), f.lab('done')
        f.br(loop)
        f.at(loop)
        f.store('i32', '0', '@changed')
        for r in self.prog.rules:
            f.e(f'call void {g("rule", r.name)}(ptr null)')
        f.cbr(f.r(f'icmp ne i32 {f.load("i32", "@changed")}, 0'), more, done)
        f.at(more)
        n = f.r(f'add i64 {f.load("i64", rounds)}, 1')
        f.store('i64', n, rounds)
        f.cbr(f.r(f'icmp slt i64 {n}, {ROUNDS}'), loop, stuck)
        f.at(stuck)
        self.puts(f, UNSETTLED)
        f.br(done)
        f.at(done)
        f.e('ret void')

    def main(self):
        """Commands come from stdin. Given a file name, the program also remembers:

        every command that can change data is appended to that file, and on start the file is
        replayed with output switched off. The language is deterministic, so replaying the
        commands rebuilds exactly the same data.
        """
        self.dispatch()
        f = Fn('@main', 'i32', 'i32 %argc, ptr %argv',
               'read one command per line and run it; with a file argument, remember across runs')
        f.text = lambda: Fn.text(f).replace('define internal', 'define', 1)
        self.fns.append(f)
        linep, capp, nv = f.var('ptr', 'null'), f.var('i64', '0'), f.var('i64')
        journal = f.var('ptr', 'null')
        f.e('call void @start()')
        named, serve = f.lab('named'), f.lab('serve')
        f.cbr(f.r('icmp sgt i32 %argc, 1'), named, serve)
        f.at(named)
        path = f.load('ptr', f.r('getelementptr ptr, ptr %argv, i64 1'))
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
        for c in self.prog.collections.values():
            self.collection(c, self.plan.colls[c.name])
        for d in self.prog.collections.values():
            for rf in d.fields.values():
                if rf.ref:
                    self.relation(d, rf)
        for t in self.prog.tasks:
            self.task(t)
        for r in self.prog.rules:
            self.task(r, rule=True)
        if self.prog.rules:
            self.settle()
        self.live()
        self.start()
        self.main()
        return (f'; Generated by the Intent compiler from {source_name}.\n'
                f'; There is no intermediate program in any other language: Intent IR is lowered straight to this.\n\n'
                + DECLS + (LIVE_DECLS if self.prog.events or self.prog.board else '') + '\n' + '\n'.join(self.globals) + '\n\n' + '\n'.join(f.text() for f in self.fns))


def emit(prog, plan, source_name='<intent>'):
    return Gen(prog, plan).module(source_name)
