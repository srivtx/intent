"""Command line: check, explain, ir, build, run."""
import argparse
import os
import subprocess
import sys

from .check import check
from .interp import Machine
from .ir import STATE, builtins, fmt_event
from .llvm import emit
from .parser import parse
from .plan import make_plan

COLORS = {'error': '31', 'question': '33', 'note': '36'}


def paint(s, code, on):
    return f'\033[{code}m{s}\033[0m' if on else s


def render(d, src, color=False):
    text = src.line_text(d.line)
    num = str(d.line)
    pad = ' ' * len(num)
    out = [paint(f'{d.level}: ', COLORS[d.level] + ';1', color) + paint(d.msg, '1', color),
           f'{pad}--> {src.filename}:{d.line}',
           f'{pad} |',
           f'{num} | {text}',
           f'{pad} | ' + ' ' * d.start + paint('^' * max(1, d.end - d.start), COLORS[d.level], color) +
           (f' {d.label}' if d.label else '')]
    if d.hint:
        out.append(f'{pad} = {d.hint}')
    return '\n'.join(out)


def load(path, no_index=False):
    with open(path) as fh:
        text = fh.read()
    prog, diags, p = parse(text, path)
    diags += check(prog, p.src)
    diags.sort(key=lambda d: (d.line, d.start))
    blocking = [d for d in diags if d.level != 'note']
    plan = None if blocking else make_plan(prog, no_index)
    return prog, diags, p, plan


def report(diags, p, quiet_notes=False):
    color = sys.stderr.isatty()
    for d in diags:
        if quiet_notes and d.level == 'note':
            continue
        print(render(d, p.src, color) + '\n', file=sys.stderr)
    q = sum(d.level == 'question' for d in diags)
    e = sum(d.level == 'error' for d in diags)
    if q or e:
        parts = ([f'{q} question{"s" if q != 1 else ""} to answer'] if q else []) + \
                ([f'{e} thing{"s" if e != 1 else ""} I could not read'] if e else [])
        print('not compiled: ' + ', '.join(parts), file=sys.stderr)
    return not (q or e)


def usage(prog, t):
    args = ','.join(f'<{p}>' for p in t.params)
    return t.name + (' ' + args if args else '')


def cmd_check(a):
    prog, diags, p, plan = load(a.file)
    print('How I read this program:\n')
    w = max((len(s) for _, s, _ in p.readings), default=0)
    for line, s, r in p.readings:
        print(f'{line:>4}  {s:<{min(w, 60)}}  ->  {r}')
    print()
    return 0 if report(diags, p) else 1


def cmd_explain(a):
    prog, diags, p, plan = load(a.file, a.no_index)
    if not report(diags, p, quiet_notes=True):
        return 1
    for c in prog.collections.values():
        cp = plan.colls[c.name]
        props = ', '.join(f'{f.name}: {"number" if f.type == "int" else "text"}' +
                          (' (unique)' if f.unique else '') +
                          ('' if f.how == 'declared' else f' [{f.how}]') for f in c.fields.values())
        print(f'{c.label}  —  {props}')
        if c.name != STATE:
            print(f'  order: {"insertion order is kept" if c.ordered else "not part of the meaning"}')
        print()
        for title, detail, why in cp.decisions:
            print(f'  {title}: {detail}')
            for line, reason in why:
                print(f'      because line {line}: {reason}')
        print()
    print('Commands the compiled program accepts (one per line on stdin):\n')
    w = max((len(usage(prog, t)) for t in prog.tasks), default=0)
    for t in prog.tasks:
        cost, how = plan.tasks[t.name]
        print(f'  {usage(prog, t):<{w}}   {cost:<14} {how}')
        print(f'  {"":<{w}}   line {t.line}: {t.text}')
    for _, u in builtins(prog):
        print(f'  {u}')
    if prog.events:
        print('\nWhat happens by itself:\n')
        for t in prog.events:
            cost, how = plan.tasks[t.name]
            print(f'  {fmt_event(t)}')
            print(f'      {cost}, {how}; line {t.line}')
    if prog.board:
        w, h = prog.board
        print(f'\nThe board: {w} wide, {h} high, {w * h} bytes, redrawn whole after every event.')
        print('Run the program in a terminal to play it; q, Esc or Ctrl-C stops.')
    return 0


def cmd_ir(a):
    prog, diags, p, plan = load(a.file, a.no_index)
    if not report(diags, p, quiet_notes=True):
        return 1
    print(emit(prog, plan, a.file))
    return 0


def build(path, out, no_index=False, quiet=False):
    prog, diags, p, plan = load(path, no_index)
    if not report(diags, p, quiet_notes=quiet):
        return None
    ll = out + '.ll'
    with open(ll, 'w') as fh:
        fh.write(emit(prog, plan, path))
    r = subprocess.run(['clang', '-O2', '-Wno-override-module', ll, '-o', out], capture_output=True, text=True)
    if r.returncode:
        print(r.stderr, file=sys.stderr)
        print('internal error: clang rejected the generated LLVM IR (this is a compiler bug, not your program)',
              file=sys.stderr)
        return None
    return prog


def cmd_build(a):
    out = a.output or os.path.splitext(a.file)[0]
    prog = build(a.file, out, a.no_index)
    if prog is None:
        return 1
    print(f'built {out}  (LLVM IR in {out}.ll)')
    print('commands: ' + ' | '.join([usage(prog, t) for t in prog.tasks] + [u for _, u in builtins(prog)]))
    if prog.board:
        print(f'play it: run {out} in a terminal (q, Esc or Ctrl-C stops)')
    return 0


def cmd_run(a):
    prog, diags, p, plan = load(a.file)
    if not report(diags, p, quiet_notes=True):
        return 1
    m = Machine(prog)
    if prog.board and sys.stdin.isatty() and sys.stdout.isatty():
        from .play import play          # at a terminal the program is played; over a pipe it takes commands
        play(m)
        return 0
    for line in sys.stdin:
        for o in m.run(line):
            print(o)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='intent', description='Intent: describe behaviour, get native code.')
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name, fn, help_ in (('check', cmd_check, 'show how the program was understood, and every open question'),
                            ('explain', cmd_explain, 'show the chosen representation and why'),
                            ('ir', cmd_ir, 'print the generated LLVM IR'),
                            ('build', cmd_build, 'compile to a native executable'),
                            ('run', cmd_run, 'run in the reference interpreter (commands on stdin)')):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument('file')
        sp.set_defaults(fn=fn)
        if name in ('explain', 'ir', 'build'):
            sp.add_argument('--no-index', action='store_true', help='experiment: forbid hash indexes')
        if name == 'build':
            sp.add_argument('-o', '--output')
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == '__main__':
    sys.exit(main())
