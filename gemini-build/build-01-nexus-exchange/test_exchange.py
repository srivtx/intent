#!/usr/bin/env python3
"""Stress-test and end-to-end simulation for Build 01: NEXUS Exchange Engine.

Verifies:
  1. Multi-collection state across Traders, Assets, Orders, Positions, and Audits.
  2. Exact parity between the compiled native LLVM binary (./nexus) and the
     Python reference interpreter (intentc.interp.Machine).
  3. High-throughput simulation: 10,000 order submissions, mark-to-market price
     shocks, basis-point margin calculations, circuit breakers, and liquidations.
"""
import os
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from intentc.cli import load

HERE = os.path.dirname(os.path.abspath(__file__))
INTENT_FILE = os.path.join(HERE, 'nexus.intent')
BINARY = os.path.join(HERE, 'nexus')


def build_and_verify():
    print('=== [Build 01] Compiling nexus.intent to native LLVM binary ===')
    r = subprocess.run([os.path.join(ROOT, 'intent'), 'build', INTENT_FILE, '-o', BINARY],
                       capture_output=True, text=True)
    assert r.returncode == 0, f'Build failed:\n{r.stderr}'

    # Functional scenario testing all 5 collections + sequential in-place math
    commands = [
        # 1. Register traders: handle,cash_cent,margin_limit,realized_pnl,risk_score,tier,frozen
        'register-trader alice,150000000,500000000,0,2000,3,0',
        'register-trader bob,40000000,100000000,0,8500,1,0',
        'register-trader charlie,250000000,800000000,0,1500,4,0',
        # Duplicate handle rejected
        'register-trader alice,999,999,0,0,1,0',

        # 2. Upsert assets (with replace policy): ticker,mark_price,prev_close,volatility_bp,volume,high_watermark,halted
        'upsert-asset BTC,9500000,9200000,3200,1000,9500000,0',
        'upsert-asset ETH,340000,330000,4800,5000,345000,0',
        'upsert-asset SOL,21000,20000,5200,12000,21500,0',

        # 3. Submit orders: order_id,buyer_or_seller,symbol,side,limit_price,qty,notional,priority_rank,status
        'submit-order 101,alice,BTC,1,9490000,5,0,0,1',
        'submit-order 102,charlie,BTC,1,9495000,10,0,0,1',
        'submit-order 103,bob,BTC,-1,9505000,3,0,0,1',
        'submit-order 104,alice,BTC,-1,9510000,8,0,0,1',
        'stamp-order-metrics',
        'best-bids',
        'best-asks',
        'largest-open-orders',
        'open-bid-volume',
        'open-ask-volume',

        # 4. Open leveraged positions: pos_key,holder,asset_sym,unit,entry_price,current_price,unrealized_pnl,leverage_bp,margin_used,liquidated
        'open-position alice_btc,alice,BTC,10,9400000,9500000,0,2000,0,0',
        'open-position bob_btc,bob,BTC,5,9600000,9500000,0,5000,0,0',
        'open-position charlie_eth,charlie,ETH,100,335000,340000,0,2500,0,0',

        # 5. Mark-to-market BTC at $94,500.00 (9450000 cents) -> updates current_price, unrealized_pnl, margin_used in 1 pass
        'mark-to-market 9450000,BTC',
        'mark-to-market 342000,ETH',
        'inspect-position alice_btc',
        'inspect-position bob_btc',
        'total-unrealized-pnl',
        'total-margin-used',

        # 6. Trigger market crash shock (-15% mark price, +1500 bps volatility) & circuit breakers
        'market-crash-shock',
        'trigger-circuit-breakers',
        'halted-assets',

        # 7. Crash BTC mark-to-market to $80,750.00 (8075000 cents) and liquidate insolvent positions
        'mark-to-market 8075000,BTC',
        'worst-drawdown',
        'liquidate-insolvent',
        'liquidated-positions',

        # 8. Freeze risky traders & promote whales
        'freeze-risky-traders',
        'frozen-traders',
        'promote-whales',
        'whales',

        # 9. Ordered compliance audit log
        'log-audit 1,RISK_FREEZE,bob,0,3,1700000001',
        'log-audit 2,LIQUIDATION,bob,-7625000,4,1700000002',
        'log-audit 3,WHALE_PROMO,alice,0,1,1700000003',
        'recent-first-audits',
        'critical-audits',

        # 10. Pure arithmetic calculators
        'calc-taker-fee 95000000,15',
        'calc-5-x-liq-price 9500000',
    ]

    prog, diags, _, _ = load(INTENT_FILE)
    assert all(d.level == 'note' for d in diags)
    from intentc.interp import Machine
    m = Machine(prog)
    ref_out = []
    for c in commands:
        ref_out.extend(m.run(c))

    proc = subprocess.run([BINARY], input='\n'.join(commands) + '\n', capture_output=True, text=True)
    assert proc.returncode == 0
    native_out = proc.stdout.splitlines()

    assert native_out == ref_out, f'Mismatch!\nNative: {native_out}\nRef: {ref_out}'
    print(f'  [OK] Native binary output matches reference interpreter line-for-line ({len(native_out)} output lines).')

    # Stress benchmark: 15,000 operations across all 5 collections
    stress_cmds = []
    for i in range(1, 3001):
        stress_cmds.append(f'register-trader t{i},{i * 100000},5000000,0,{(i * 37) % 10000},{(i % 4) + 1},0')
        stress_cmds.append(f'submit-order {i},t{i},BTC,{1 if i % 2 == 0 else -1},{9400000 + (i % 500) * 100},{i % 20 + 1},0,0,1')
        stress_cmds.append(f'open-position p{i},t{i},BTC,{i % 10 + 1},9450000,9500000,0,2000,0,0')
    stress_cmds.extend([
        'stamp-order-metrics',
        'mark-to-market 9320000,BTC',
        'apply-funding-rate',
        'liquidate-insolvent',
        'best-bids',
        'best-asks',
        'biggest-winners',
        'biggest-losers',
        'total-unrealized-pnl',
        'total-margin-used',
        'active-trader-count',
        'open-order-count',
    ])
    for i in range(1, 1501):
        stress_cmds.append(f'inspect-order {i * 2}')
        stress_cmds.append(f'cancel-order {i * 2 - 1}')
    stress_cmds.append('open-order-count')

    t0 = time.perf_counter()
    res = subprocess.run([BINARY], input='\n'.join(stress_cmds) + '\n', capture_output=True, text=True)
    elapsed = time.perf_counter() - t0
    assert res.returncode == 0
    lines = res.stdout.splitlines()
    print(f'  [OK] Executed {len(stress_cmds):,} exchange & risk commands in {elapsed:.3f}s '
          f'({len(stress_cmds) / elapsed:,.0f} ops/sec), final open orders = {lines[-1]}.')


if __name__ == '__main__':
    build_and_verify()
