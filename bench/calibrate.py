#!/usr/bin/env python3
"""Measure the step costs the planner's cost model uses (SORT, WALK, DESCEND, REBUILD in plan.py).

Each is timed on native builds over 200,000 customers and given relative to one step of a plain
pass over the records. Command-line overhead is the same for every command, so it is taken out by
subtracting a run of the same records with no queries. Numbers vary by machine; the ratios are what
the planner uses.
"""
import math
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
How many customers are aged under a given limit?
top: show the top 1 customers by age.
birthday: increase the age of customers by 1.
'''
N = 200000


def main():
    d = tempfile.mkdtemp(prefix='intent-calibrate-')
    src = os.path.join(d, 'p.intent')
    with open(src, 'w') as fh:
        fh.write(PROGRAM)
    exe = {'plain': os.path.join(d, 'plain'), 'tree': os.path.join(d, 'tree')}
    assert build(src, exe['plain'], no_index='order', quiet=True)
    assert build(src, exe['tree'], quiet=True)
    rng = random.Random(0)
    adds = [f'add c{i},{rng.randint(1, 1000000)}' for i in range(N)]

    def time_of(kind, cmds):
        path = os.path.join(d, 'in.txt')
        with open(path, 'w') as fh:
            fh.write('\n'.join(adds + cmds) + '\n')
        best = float('inf')
        for _ in range(3):
            with open(path) as fh:
                t0 = time.perf_counter()
                subprocess.run([exe[kind]], stdin=fh, stdout=subprocess.DEVNULL)
                best = min(best, time.perf_counter() - t0)
        return best

    base = {k: time_of(k, []) for k in exe}

    def per(kind, cmds, k):
        return (time_of(kind, cmds * k) - base[kind]) / k

    lgn = math.log2(N)
    scan = per('plain', ['count 0'], 5000)
    sort = per('plain', ['top'], 300)
    birthday = per('plain', ['birthday'], 300)
    top = per('tree', ['top'], 300000)
    walk = per('tree', ['count 1000001'], 300)            # everyone is in range: a walk over all of them
    rebuild = per('tree', ['birthday', 'top'], 300)
    step = scan / N
    rows = (('pass, per record', step),
            ('SORT, per k log k', (sort - scan) / (N * lgn)),
            ('WALK, per record', walk / N),
            ('DESCEND, per level (an upper bound: includes reading and printing a command)', top / lgn),
            ('REBUILD, per n log n', (rebuild - birthday - top) / (N * lgn)))
    for name, v in rows:
        print(f'{v * 1e9:8.2f} ns  {v / step:7.1f} steps   {name}')


if __name__ == '__main__':
    main()
