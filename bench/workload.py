#!/usr/bin/env python3
"""Does planning for the workload pay? One program, two samples of commands, two builds.

The program reads the 10 oldest customers and narrow bands of age, and now and then changes every
customer's age at once (which leaves a tree on age to be rebuilt, one sort of all n, at the next read).
  reads  - one change for every 19 reads: the planner keeps a tree on age, and reads walk it
  churn  - a change before every read: every read would rebuild the tree, more than a pass costs,
           so the planner keeps no tree

Each build is planned from a small sample (`--workload`), then run on the full workload of both kinds.
"""
import os
import random
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from intentc.cli import build          # noqa: E402

PROGRAM = '''Customers is a collection.
Each customer has a name and an age.
Add a customer.
oldest: show the top 10 customers by age.
band: show the customers whose age is between a given low and a given high.
older: increase the age of customers by 1.
younger: decrease the age of customers by 1.
'''


def workload(kind, n, rounds, rng):
    cmds = [f'add c{i},{rng.randint(1, 10 * n)}' for i in range(n)]
    for i in range(rounds):
        if kind == 'reads' and i % 20 or kind == 'churn' and i % 2:
            lo = rng.randint(1, 10 * n)
            cmds.append(rng.choice(['oldest', f'band {lo},{lo + 20}']))
        else:
            cmds.append('older' if i % 4 < 2 else 'younger')
    return cmds


def main():
    d = tempfile.mkdtemp(prefix='intent-bench-')
    src = os.path.join(d, 'p.intent')
    with open(src, 'w') as fh:
        fh.write(PROGRAM)
    exes = {}
    for kind in ('reads', 'churn'):
        exes[kind] = os.path.join(d, kind)
        assert build(src, exes[kind], quiet=True, workload=workload(kind, 2000, 400, random.Random(0)))
    print(f'{"workload":>9}  {"planned for reads":>18}  {"planned for churn":>18}   (seconds; 50,000 adds, '
          '4,000 rounds)')
    for kind in ('reads', 'churn'):
        data = '\n'.join(workload(kind, 50000, 4000, random.Random(1))) + '\n'
        row, outs = [], set()
        for exe in exes.values():
            t0 = time.perf_counter()
            out = subprocess.run([exe], input=data, capture_output=True, text=True).stdout
            row.append(time.perf_counter() - t0)
            outs.add(tuple(sorted(out.split('\n'))))      # order among equal ages is not part of the meaning
        assert len(outs) == 1, 'the two builds printed different things'
        print(f'{kind:>9}  {row[0]:>18.3f}  {row[1]:>18.3f}')


if __name__ == '__main__':
    main()
