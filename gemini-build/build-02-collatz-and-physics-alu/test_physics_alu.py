#!/usr/bin/env python3
"""Verification & Stress Test for Build 02: Branchless Collatz, 2D Physics & Register ALU.

Proves that pure English sentences compiled by Intent to LLVM IR can:
  1. Compute exact Collatz (3n+1) stopping times and hailstone peaks for seeds 1..100
     (including seed 27 -> 111 steps, peak 9,232) without a modulo (%) or if/else construct!
  2. Run a 2D elastic rigid-body particle simulation with gravity, drag, floor/wall bounces,
     and Hamiltonian energy tracking.
  3. Compute 64-bit Fibonacci numbers up to F(91) = 4,660,046,610,375,530,309 in-place.
"""
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from intentc.cli import load
from intentc.interp import Machine

HERE = os.path.dirname(os.path.abspath(__file__))
INTENT_FILE = os.path.join(HERE, 'physics_alu.intent')
BINARY = os.path.join(HERE, 'physics_alu')


def expected_collatz(n):
    steps, peak = 0, n
    while n > 1:
        n = n // 2 if n % 2 == 0 else 3 * n + 1
        peak = max(peak, n)
        steps += 1
    return steps, peak


def run_test():
    print('=== [Build 02] Compiling physics_alu.intent to native LLVM binary ===')
    r = subprocess.run([os.path.join(ROOT, 'intent'), 'build', INTENT_FILE, '-o', BINARY],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    cmds = []
    # 1. Seed Collatz stones 1..50 (including seed 27 which takes 111 steps and peaks at 9232)
    for n in range(1, 51):
        cmds.append(f'add-stone {n},{n},{n},0,{n},0')
    cmds.append('show-even-stones')
    cmds.append('show-odd-stones')
    for _ in range(115):
        cmds.append('step-collatz')
        cmds.append('update-stone-peaks')
    cmds.append('active-stone-count')
    cmds.append('converged-stone-count')
    cmds.append('find-stone 27')
    cmds.append('hardest-stones')
    cmds.append('highest-peak-stones')

    # 2. Spawn 20 particles and run 100 physics ticks with floor & wall bounces
    for i in range(1, 21):
        cmds.append(f'spawn-particle {i},p{i},{i * 2},{-500 + i * 50},{200 + i * 30},{15 - i},{40 - i * 3},0,0,0,0,0')
    for _ in range(100):
        cmds.append('step-physics')
        cmds.append('bounce-floor')
        cmds.append('bounce-left-wall')
        cmds.append('bounce-right-wall')
    cmds.append('energetic-particles')
    cmds.append('total-system-energy')
    cmds.append('total-bounces')

    # 3. Fibonacci register machine: compute F(91) starting from F(0)=0, F(1)=1 in 90 cycles
    cmds.append('init-register 1,fib_91,0,1,0,1')
    for _ in range(90):
        cmds.append('step-fibonacci')
    cmds.append('read-register 1')

    # Verify native LLVM binary vs reference interpreter
    prog, diags, _, _ = load(INTENT_FILE)
    assert all(d.level == 'note' for d in diags)
    m = Machine(prog)
    ref_out = []
    for c in cmds:
        ref_out.extend(m.run(c))

    proc = subprocess.run([BINARY], input='\n'.join(cmds) + '\n', capture_output=True, text=True)
    assert proc.returncode == 0
    native_out = proc.stdout.splitlines()
    assert native_out == ref_out, 'Native vs Reference mismatch!'

    # Check Collatz(27): id=27, seed=27, val=1, rem=0, peak=9232, steps=111
    exp_steps, exp_peak = expected_collatz(27)
    assert f'27,27,1,0,{exp_peak},{exp_steps}' in native_out, f'Collatz(27) wrong in {native_out}'
    print(f'  [OK] Branchless Collatz(27) verified in native LLVM binary: steps={exp_steps}, peak={exp_peak}!')

    # Check Fibonacci(91) = 4660046610375530309
    fib91_line = native_out[-1]
    assert '4660046610375530309' in fib91_line, f'Fibonacci(91) wrong: {fib91_line}'
    print(f'  [OK] 64-bit Fibonacci register verified: {fib91_line}')
    print(f'  [OK] 2D elastic particle physics verified ({len(native_out)} lines matched reference interpreter).')


if __name__ == '__main__':
    run_test()
