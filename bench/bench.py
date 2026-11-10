#!/usr/bin/env python3
"""Does the representation the planner picks matter? Same intent, three builds, same commands.

  indexed   - what the planner chooses by itself
  no index  - the same program built with --no-index (every keyed operation scans)
  ordered   - the same program plus one sentence: "Keep customers in the order they were added."
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
Each customer has a name, an age and an email.
Emails are unique. Reject duplicates.
Add a customer.
Find a customer by email.
Remove a customer by email.
How many customers are there?
What is the average age?
'''


def workload(n, rng):
    emails = [f'user{i}@example.com' for i in range(n)]
    cmds = [f'add name{i},{rng.randint(1, 90)},{e}' for i, e in enumerate(emails)]
    cmds += [f'find-by-email {rng.choice(emails)}' for _ in range(n)]
    cmds += [f'remove-by-email {e}' for e in rng.sample(emails, n // 2)]
    cmds += ['count', 'average-age']
    return '\n'.join(cmds) + '\n'


def main():
    d = tempfile.mkdtemp(prefix='intent-bench-')
    variants = {'indexed': (PROGRAM, False), 'no index': (PROGRAM, True),
                'ordered': (PROGRAM + 'Keep customers in the order they were added.\n', False)}
    exes = {}
    for name, (text, no_index) in variants.items():
        src = os.path.join(d, name.replace(' ', '_') + '.intent')
        with open(src, 'w') as fh:
            fh.write(text)
        exes[name] = src[:-7]
        assert build(src, exes[name], no_index=no_index, quiet=True)
        subprocess.run([exes[name]], input='count\n', capture_output=True, text=True)   # warm up
    print(f'{"records":>8}  ' + '  '.join(f'{k:>10}' for k in exes) + '   (seconds; n adds, n finds, n/2 removes)')
    for n in (5000, 10000, 20000, 40000):
        data = workload(n, random.Random(n))
        row, tails = [], set()
        for name, exe in exes.items():
            t0 = time.perf_counter()
            out = subprocess.run([exe], input=data, capture_output=True, text=True).stdout
            row.append(time.perf_counter() - t0)
            tails.add(tuple(out.split('\n')[-3:-1]))
        assert len(tails) == 1, 'variants disagree on the final count/average'
        print(f'{n:>8}  ' + '  '.join(f'{t:>10.3f}' for t in row))


if __name__ == '__main__':
    main()
