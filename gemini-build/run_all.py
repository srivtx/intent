#!/usr/bin/env python3
"""Master runner for all 8 builds, graphics/server experiments & stress tests in `gemini-build/`."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

SUITES = [
    ('build-01-nexus-exchange', 'test_exchange.py'),
    ('build-02-collatz-and-physics-alu', 'test_physics_alu.py'),
    ('build-03-relational-join-and-transactions', 'test_ledger.py'),
    ('build-04-compiler-bug-hunt', 'test_compiler_bugs.py'),
    ('build-05-performance-cliff-stress-test', 'test_stress.py'),
    ('build-06-observability-timeseries-db', 'test_tsdb.py'),
    ('build-07-graphics-mandelbrot-and-raytracer', 'test_graphics.py'),
    ('build-08-server-pipe-deadlock-and-rpc', 'test_server.py'),
]


def main():
    for folder, script in SUITES:
        path = os.path.join(HERE, folder, script)
        r = subprocess.run([sys.executable, path], check=False)
        if r.returncode != 0:
            print(f'FAILED: {folder}/{script}', file=sys.stderr)
            sys.exit(r.returncode)
        print()
    print('All 8 builds, native LLVM binaries, graphics/server experiments, and stress tests passed!')


if __name__ == '__main__':
    main()
