#!/usr/bin/env python3
"""Does the ordered index pay for itself? The workload from the critique, built two ways.

  planner   - what the planner chooses, given a small sample of the same kind of commands
              (--workload): a hash index on email and a balanced tree on age
  no tree   - built with --no-order: the hash index stays, every range or ordered read scans and sorts
  no index  - built with --no-index: finds and removals scan too

Commands: n adds, then n/10 rounds of (a narrow range query, a count, the 5 oldest, a removal).
Both builds must print the same lines (in any order: nothing says the order matters).
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
Each customer has a name, an email and an age.
Emails are unique. Reject duplicates.

Add a customer.
Find a customer by email.
Remove a customer by email.
in-range: show the customers whose age is between a given low and a given high.
How many customers are aged at least a given age?
oldest: show the top 5 customers by age.
'''


def workload(n, rng):
    emails = [f'user{i}@example.com' for i in range(n)]
    span = n * 10                      # ages spread thin, so a narrow range holds a handful
    cmds = [f'add name{i},{e},{rng.randrange(span)}' for i, e in enumerate(emails)]
    gone = rng.sample(emails, n // 10)
    for e in gone:
        lo = rng.randrange(span)
        cmds += [f'in-range {lo},{lo + 20}', f'count {span - 50}', 'oldest', f'find-by-email {e}',
                 f'remove-by-email {e}']
    return cmds


def main():
    d = tempfile.mkdtemp(prefix='intent-bench-')
    exes = {}
    for name, no_index in (('planner', False), ('no tree', 'order'), ('no index', True)):
        src = os.path.join(d, name.replace(' ', '_') + '.intent')
        with open(src, 'w') as fh:
            fh.write(PROGRAM)
        exes[name] = src[:-7]
        assert build(src, exes[name], no_index=no_index, quiet=True, workload=workload(2000, random.Random(0)))
        subprocess.run([exes[name]], input='count 0\n', capture_output=True, text=True)    # warm up
    print(f'{"records":>8}  ' + '  '.join(f'{k:>10}' for k in exes) + '   (seconds; n adds, n/10 rounds of '
          'range + count + top 5 + find + remove)')
    for n in (10000, 20000, 40000, 80000):
        data = '\n'.join(workload(n, random.Random(n))) + '\n'
        row, outs = [], set()
        for exe in exes.values():
            t0 = time.perf_counter()
            out = subprocess.run([exe], input=data, capture_output=True, text=True).stdout
            row.append(time.perf_counter() - t0)
            outs.add(tuple(sorted(out.split('\n'))))      # order is not part of these customers' meaning
        assert len(outs) == 1, 'the two builds printed different things'
        print(f'{n:>8}  ' + '  '.join(f'{t:>10.3f}' for t in row))


if __name__ == '__main__':
    main()
