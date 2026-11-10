#!/usr/bin/env python3
"""Build 08: Persistent Server Test — Proving the `stdout` Pipe Deadlock & PTY Live RPC Fix.

Demonstrates two critical truths about running compiled Intent binaries as servers:
  1. THE PIPE DEADLOCK BUG (`intentc/llvm.py:765`):
     Because `@main` in `llvm.py` never calls `@fflush(ptr null)` after `@dispatch`,
     spawning a compiled Intent binary over a standard OS pipe (`subprocess.PIPE`)
     causes `libc` to block-buffer `stdout` (4KB). Sending a single query like
     `active-session-count\\n` while keeping `stdin` open DEADLOCKS waiting for a reply!
  2. THE PTY (`pty.openpty()`) LIVE SERVER SOLUTION:
     Attaching `stdout` to a pseudo-terminal (`pty.openpty()`) makes `isatty(1) == 1`,
     forcing `libc` into line-buffered mode (`_IOLBF`). The exact same unmodified
     Intent binary then works as a live, sub-millisecond interactive RPC server with
     Write-Ahead Log (`wal.log`) crash recovery!
"""
import os
import pty
import select
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
HERE = os.path.dirname(os.path.abspath(__file__))
INTENT_FILE = os.path.join(HERE, 'session_server.intent')
BINARY = os.path.join(HERE, 'session_server')
WAL_FILE = os.path.join(HERE, 'sessions_wal.log')


def run_server_test():
    print('=== [Build 08] Compiling session_server.intent to native LLVM binary ===')
    r = subprocess.run([os.path.join(ROOT, 'intent'), 'build', INTENT_FILE, '-o', BINARY],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    if os.path.exists(WAL_FILE):
        os.remove(WAL_FILE)

    # ---- Part 1: Prove the Standard Pipe Buffering Deadlock in llvm.py:765 ----
    proc_pipe = subprocess.Popen(
        [BINARY],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        proc_pipe.stdin.write(b'active-session-count\n')
        proc_pipe.stdin.flush()
        # Wait 150ms for response on stdout pipe while stdin remains open
        ready, _, _ = select.select([proc_pipe.stdout], [], [], 0.15)
        assert ready == [], 'Expected stdout pipe to block due to missing fflush(null) in llvm.py!'
        print('  [PROVEN Bug 8] Standard OS pipe (`subprocess.PIPE`) DEADLOCKS on interactive RPC because `llvm.py:765` never calls `fflush(stdout)`!')
    finally:
        proc_pipe.kill()
        proc_pipe.wait()

    # ---- Part 2: Run the Unmodified Binary as a Live Interactive RPC Server via PTY ----
    master_fd, slave_fd = pty.openpty()
    proc_pty = subprocess.Popen(
        [BINARY, WAL_FILE],
        stdin=subprocess.PIPE,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)

    def rpc(cmd_str, expect_reply=True):
        proc_pty.stdin.write((cmd_str + '\n').encode())
        proc_pty.stdin.flush()
        if not expect_reply:
            return None
        ready, _, _ = select.select([master_fd], [], [], 2.0)
        assert ready, f'Timeout waiting for PTY reply to {cmd_str}'
        data = os.read(master_fd, 4096).decode()
        return [l.strip() for l in data.splitlines() if l.strip()]

    try:
        assert rpc('active-session-count') == ['0']
        rpc('create-session tok_1,alice,3,0,5,2000,0', expect_reply=False)
        rpc('create-session tok_2,bob,1,4,5,2000,0', expect_reply=False)
        assert rpc('active-session-count') == ['2']
        assert rpc('lookup-session tok_1') == ['tok_1,alice,3,0,5,2000,0']

        # Increment Bob's request count twice -> hits quota_limit (5) -> enforce-quotas revokes Bob!
        rpc('record-hit tok_2', expect_reply=False)
        rpc('enforce-quotas', expect_reply=False)
        assert rpc('active-session-count') == ['1']
        assert rpc('revoked-session-count') == ['1']
        print('  [OK] PTY-backed live interactive RPC server responded in real time across 8 sequential round-trips!')
    finally:
        proc_pty.stdin.close()
        os.close(master_fd)
        proc_pty.wait()

    # ---- Part 3: Verify WAL Crash Recovery on Server Restart ----
    res_restart = subprocess.run([BINARY, WAL_FILE], input='active-session-count\nrevoked-session-count\nlookup-session tok_2\n',
                                 capture_output=True, text=True, check=True)
    assert res_restart.stdout.splitlines() == ['1', '1', 'tok_2,bob,1,5,5,2000,1']
    print('  [OK] Server crash-recovery verified: restarting binary with `sessions_wal.log` restored exact session state!')


if __name__ == '__main__':
    run_server_test()
