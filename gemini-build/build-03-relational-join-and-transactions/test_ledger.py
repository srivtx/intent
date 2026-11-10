#!/usr/bin/env python3
"""Test & Failure Demonstration for Build 03: Two-Phase Ledger & Inventory Service.

Demonstrates:
  1. Guarded WHERE predicates ('whose balance is at least a given amount') prevent
     negative balances/stock within a single collection.
  2. WHY multi-collection transactions are still missing: because `hold-funds` and
     `allocate-stock` produce NO output when a guard condition fails (0 rows matched),
     a naive caller cannot tell if `allocate-stock` succeeded without issuing a
     follow-up `find-product` query and manually rolling back `release-funds`!
"""
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from intentc.cli import load
from intentc.interp import Machine

HERE = os.path.dirname(os.path.abspath(__file__))
INTENT_FILE = os.path.join(HERE, 'ledger_service.intent')
BINARY = os.path.join(HERE, 'ledger_service')


def run_test():
    print('=== [Build 03] Compiling ledger_service.intent to native LLVM binary ===')
    r = subprocess.run([os.path.join(ROOT, 'intent'), 'build', INTENT_FILE, '-o', BINARY],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    cmds = [
        # Seed wallets & products
        'create-wallet w_alice,1000,0,0',
        'create-wallet w_bob,200,0,0',
        'add-product GPU_H100,300,2,0',

        # TX 1: Alice buys 2 GPUs for 600 (succeeds: balance 1000 >= 600, stock 2 >= 2)
        'stage-transfer 1,w_alice,GPU_H100,2,600,0',
        'hold-funds 600,w_alice',
        'allocate-stock 2,GPU_H100',
        'capture-funds 600,w_alice',
        'commit-transfer 1',

        # TX 2: Alice tries to buy 1 more GPU for 300 (funds hold succeeds: 400 >= 300,
        #       but GPU stock is now 0 < 1 so allocate-stock silently matches 0 rows!)
        'stage-transfer 2,w_alice,GPU_H100,1,300,0',
        'hold-funds 300,w_alice',
        'allocate-stock 1,GPU_H100',
        # Compensating rollback required by external orchestrator:
        'release-funds 300,w_alice',
        'abort-transfer 2',

        # TX 3: Bob tries to hold 500 when balance is only 200 -> guarded WHERE prevents negative balance!
        'hold-funds 500,w_bob',

        'find-wallet w_alice',
        'find-wallet w_bob',
        'find-product GPU_H100',
        'committed-transfers',
        'aborted-transfers',
        'committed-revenue',
    ]

    prog, diags, _, _ = load(INTENT_FILE)
    assert all(d.level == 'note' for d in diags)
    m = Machine(prog)
    ref_out = []
    for c in cmds:
        ref_out.extend(m.run(c))

    proc = subprocess.run([BINARY], input='\n'.join(cmds) + '\n', capture_output=True, text=True)
    assert proc.returncode == 0
    native_out = proc.stdout.splitlines()
    assert native_out == ref_out, f'Mismatch:\n{native_out}\nvs\n{ref_out}'

    # Verify Alice's final wallet: balance=400, reserved=0, tx_count=1
    assert 'w_alice,400,0,1' in native_out
    # Verify Bob's wallet was protected by the guard: balance=200, reserved=0, tx_count=0
    assert 'w_bob,200,0,0' in native_out
    # Verify GPU stock=0, sold=2
    assert 'GPU_H100,300,0,2' in native_out
    print('  [OK] Two-phase ledger & guarded inventory verified in native LLVM binary.')
    print('  [OK] Confirmed silent 0-row update hazard: `allocate-stock` emits 0 lines when out-of-stock.')


if __name__ == '__main__':
    run_test()
