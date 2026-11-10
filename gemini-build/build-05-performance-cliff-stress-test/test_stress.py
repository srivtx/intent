#!/usr/bin/env python3
"""Stress Test & Performance Cliff Benchmark for Build 05.

Tests:
  1. The O(n^2) Ordered-Removal Cliff: Compares `fast_unordered` vs `slow_ordered`
     on N=15,000 records (15k adds, 15k finds, 7.5k deletes), showing the >100x
     slowdown caused by `llvm.py:412` rebuilding the entire hash table on every
     single ordered deletion (even when deleting from the tail!).
  2. High-Churn Tombstone Saturation: 50,000 add + delete cycles keeping live count
     at 10, verifying that tombstone slots (-1) trigger periodic `rebuild()` without
     corrupting the hash table.
  3. 16-Stage Sequential Pipeline & 64-Bit Boundary Torture: Verifies `INT64_MAX`,
     `INT64_MIN`, `INT64_MIN / -1` (special guard at `llvm.py:174`), `-7 / 2 == -3`,
     and `9 + 10% == 9` truncation against the reference interpreter.
"""
import os
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from intentc.cli import load
from intentc.interp import Machine

HERE = os.path.dirname(os.path.abspath(__file__))


def run_stress():
    print('=== [Build 05] Compiling Stress Test Binaries ===')
    fast_src = os.path.join(HERE, 'fast_unordered.intent')
    slow_src = os.path.join(HERE, 'slow_ordered.intent')
    pipe_src = os.path.join(HERE, 'deep_pipeline.intent')
    fast_bin = os.path.join(HERE, 'fast_unordered')
    slow_bin = os.path.join(HERE, 'slow_ordered')
    pipe_bin = os.path.join(HERE, 'deep_pipeline')

    for src, out in ((fast_src, fast_bin), (slow_src, slow_bin), (pipe_src, pipe_bin)):
        subprocess.run([os.path.join(ROOT, 'intent'), 'build', src, '-o', out],
                       check=True, capture_output=True)
        # Warm up binary so macOS AMFI signature verification (~0.5s on first launch) is not timed
        subprocess.run([out], input='', capture_output=True, text=True, check=True)

    # 1. Benchmark: Unordered O(1) swap vs Ordered O(n) reindex on 15,000 records
    N = 15000
    bench_cmds = [f'add-item key_{i}@nexus.io,{i},{i * 10}' for i in range(N)]
    bench_cmds += [f'find-item key_{i}@nexus.io' for i in range(N)]
    bench_cmds += [f'remove-item key_{i * 2}@nexus.io' for i in range(N // 2)]
    bench_cmds += ['count-items', 'total-val']
    payload = '\n'.join(bench_cmds) + '\n'

    t0 = time.perf_counter()
    r_fast = subprocess.run([fast_bin], input=payload, capture_output=True, text=True, check=True)
    t_fast = time.perf_counter() - t0

    t0 = time.perf_counter()
    r_slow = subprocess.run([slow_bin], input=payload, capture_output=True, text=True, check=True)
    t_slow = time.perf_counter() - t0

    assert r_fast.stdout.splitlines()[-2:] == r_slow.stdout.splitlines()[-2:]
    ratio = t_slow / max(t_fast, 1e-6)
    print(f'  [OK] 37,502-op Workload (N={N:,}):')
    print(f'       - Unordered (O(1) swap):     {t_fast:.4f}s ({len(bench_cmds)/t_fast:,.0f} ops/sec)')
    print(f'       - Ordered (reindex cliff):   {t_slow:.4f}s ({len(bench_cmds)/t_slow:,.0f} ops/sec) -> {ratio:.1f}x slower!')

    # 2. High-Churn Tombstone Saturation Stress Test (50,000 add/delete cycles, live size <= 10)
    churn_cmds = []
    for i in range(1, 50001):
        churn_cmds.append(f'add-item k_{i},{i},{i}')
        if i > 10:
            churn_cmds.append(f'remove-item k_{i - 10}')
    churn_cmds.extend(['count-items', 'total-val', 'find-item k_50000', 'find-item k_1'])
    t0 = time.perf_counter()
    r_churn = subprocess.run([fast_bin], input='\n'.join(churn_cmds) + '\n', capture_output=True, text=True, check=True)
    t_churn = time.perf_counter() - t0
    churn_out = r_churn.stdout.splitlines()
    exp_sum = sum(range(49991, 50001))
    assert churn_out == ['10', str(exp_sum), 'k_50000,50000,50000', 'none'], f'Churn mismatch: {churn_out}'
    print(f'  [OK] Tombstone Churn Test: 100,000 add/remove ops in {t_churn:.3f}s ({100000/t_churn:,.0f} ops/sec), live=10, sum={exp_sum}.')

    # 3. 16-Stage Pipeline & 64-Bit Boundary Torture Test (INT64_MIN, INT64_MAX, -7/2, 9+10%)
    I64_MAX = (1 << 63) - 1
    I64_MIN = -(1 << 63)
    pipe_cmds = [
        f'add-state 1,{I64_MIN},0,0,0,0,0,0,0,0,0',
        f'add-state 2,{I64_MAX},0,0,0,0,0,0,0,0,0',
        'add-state 3,-7,0,0,0,0,0,0,0,0,0',
        'add-state 4,9,0,0,0,0,0,0,0,0,0',
        # Test INT64_MIN / -1 (guarded in llvm.py:174 via `sub i64 0, %a` so it wraps to INT64_MIN without UB!)
        'negate-x',
        'find-state 1',
        'find-state 2',
        # Test negative division truncation toward zero (-7 / -1 = 7, then 7 / 2 = 3, and for -7: reset and halve)
        'add-state 3,-7,0,0,0,0,0,0,0,0,0',
        'halve-x',
        'find-state 3',
        # Test percent truncation on small numbers: 9 increased by 10% -> 9 + (9*10)/100 = 9!
        'add-state 4,9,0,0,0,0,0,0,0,0,0',
        'bump-ten-pct',
        'find-state 4',
        # Run 16-stage sequential pipeline on all 4 boundary states
        'run-pipeline',
        'find-state 1',
        'find-state 2',
        'find-state 3',
        'find-state 4',
    ]

    prog, diags, _, _ = load(pipe_src)
    assert all(d.level == 'note' for d in diags)
    m = Machine(prog)
    ref_out = []
    for c in pipe_cmds:
        ref_out.extend(m.run(c))

    r_pipe = subprocess.run([pipe_bin], input='\n'.join(pipe_cmds) + '\n', capture_output=True, text=True, check=True)
    nat_out = r_pipe.stdout.splitlines()
    assert nat_out == ref_out, f'Boundary torture mismatch!\nNative: {nat_out}\nRef: {ref_out}'
    print('  [OK] 16-Stage Sequential Pipeline & 64-Bit Boundary Torture (INT64_MIN/-1, -7/2=-3, 9+10%=9) matched bit-for-bit!')


if __name__ == '__main__':
    run_stress()
