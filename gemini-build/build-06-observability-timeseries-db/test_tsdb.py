#!/usr/bin/env python3
"""Verification & Sliding-Window Benchmark for Build 06: IntentTSDB."""
import os
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from intentc.cli import load
from intentc.interp import Machine

HERE = os.path.dirname(os.path.abspath(__file__))
INTENT_FILE = os.path.join(HERE, 'tsdb.intent')
BINARY = os.path.join(HERE, 'tsdb')


def run_test():
    print('=== [Build 06] Compiling tsdb.intent to native LLVM binary ===')
    r = subprocess.run([os.path.join(ROOT, 'intent'), 'build', INTENT_FILE, '-o', BINARY],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    subprocess.run([BINARY], input='', capture_output=True, text=True, check=True)

    cmds = [
        'register-host web-01,us-east,100,0',
        'register-host web-02,us-west,100,0',
        'register-host db-01,us-east,200,0',
        # sample_id,host_name,service_tag,ts_epoch,cpu_pct,mem_mb,latency_ms,error_count,compute_load,anomaly_score
        'ingest-sample 1,web-01,api,1000,45,2048,120,0,0,0',
        'ingest-sample 2,web-01,api,1010,92,4096,650,4,0,0',
        'ingest-sample 3,web-02,auth,1020,30,1024,80,0,0,0',
        'ingest-sample 4,db-01,storage,1030,98,16384,1200,12,0,0',
        'ingest-sample 5,web-02,api,1040,55,2048,210,1,0,0',
        'score-samples',
        'total-compute-load',
        'fleet-avg-latency',
        'host-avg-latency web-01',
        'host-max-latency web-01',
        'host-total-errors db-01',
        'service-avg-cpu api',
        'top-anomalies',
        'slowest-samples',
        'severe-sample-count',
        # Evict samples older than ts_epoch=1020 (drops samples 1 and 2)
        'evict-old-samples 1020',
        'sample-count',
        'fleet-avg-latency',
        # Quarantine db-01 and open an incident
        'quarantine-host db-01',
        'quarantined-hosts',
        'open-incident 501,db-01,1200,5,0',
        'active-incidents',
        'resolve-incident 501',
        'active-incidents',
    ]

    prog, diags, _, _ = load(INTENT_FILE)
    assert all(d.level == 'note' for d in diags)
    m = Machine(prog)
    ref_out = []
    for c in cmds:
        ref_out.extend(m.run(c))

    proc = subprocess.run([BINARY], input='\n'.join(cmds) + '\n', capture_output=True, text=True, check=True)
    nat_out = proc.stdout.splitlines()
    assert nat_out == ref_out, f'Mismatch!\nNative: {nat_out}\nRef: {ref_out}'
    print(f'  [OK] IntentTSDB native output matches reference interpreter ({len(nat_out)} lines).')

    # High-rate ingestion + sliding window eviction benchmark (20,000 samples)
    bench = []
    for i in range(1, 20001):
        bench.append(f'ingest-sample {i},host-{i % 10},svc-{i % 3},{1000 + i},{20 + (i % 80)},{1024 + (i % 4) * 1024},{50 + (i % 900)},{i % 5},0,0')
    bench.extend([
        'score-samples',
        'total-compute-load',
        'top-anomalies',
        'host-avg-latency host-1',
        'evict-old-samples 15000',
        'sample-count',
    ])
    t0 = time.perf_counter()
    res = subprocess.run([BINARY], input='\n'.join(bench) + '\n', capture_output=True, text=True, check=True)
    dt = time.perf_counter() - t0
    out_lines = res.stdout.splitlines()
    assert out_lines[-1] == '6001', f'Expected 6001 samples remaining after cutoff 15000, got {out_lines[-1]}'
    print(f'  [OK] Ingested, scored & windowed 20,000 telemetry samples in {dt:.3f}s ({len(bench)/dt:,.0f} ops/sec).')


if __name__ == '__main__':
    run_test()
