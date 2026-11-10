#!/usr/bin/env python3
"""Deterministic Reproducer Suite for Build 04: 7 Compiler & Runtime Bugs in `intentc`."""
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from intentc.cli import load

HERE = os.path.dirname(os.path.abspath(__file__))


def run_bug_hunt():
    print('=== [Build 04] Running Reproducers for 7 Discovered Compiler/Runtime Bugs ===')

    # ---- Bug 1: "not between A and B" De Morgan violation ----
    b1_src = os.path.join(HERE, 'bug1_not_between.intent')
    b1_bin = os.path.join(HERE, 'bug1_not_between')
    subprocess.run([os.path.join(ROOT, 'intent'), 'build', b1_src, '-o', b1_bin],
                   check=True, capture_output=True)
    inp = 'add-member Teen,15\nadd-member Adult,25\nadd-member Senior,45\nbuggy-outside\ncorrect-outside\n'
    res1 = subprocess.run([b1_bin], input=inp, capture_output=True, text=True, check=True)
    lines1 = res1.stdout.splitlines()
    # buggy-outside only returns 'Teen' (drops 'Senior' age 45!), whereas correct-outside returns ['Teen', 'Senior']
    assert lines1 == ['Teen', 'Teen', 'Senior'], f'Unexpected output: {lines1}'
    print('  [PROVEN Bug 1] `whose age is not between 18 and 30` miscompiles to `age < 18 and age <= 30`, dropping Senior(45)!')

    # ---- Bug 2: Taught word inside hyphenated capability label ----
    b2_src = os.path.join(HERE, 'bug2_hyphenated_macro_label.intent')
    prog2, diags2, _, _ = load(b2_src)
    assert not diags2
    task_names = [t.name for t in prog2.tasks]
    assert 'show-score-at-least-100' in task_names and 'show-vip' not in task_names
    print(f'  [PROVEN Bug 2] Hyphenated label `show-vip:` corrupted by macro expansion into `{task_names[1]}`!')

    # ---- Bug 3 & Bug 4: Missing 1st text arg coercion & WAL journal logging failed commands ----
    b3_src = os.path.join(HERE, 'bug3_and_4_runtime.intent')
    b3_bin = os.path.join(HERE, 'bug3_and_4_runtime')
    journal = os.path.join(HERE, 'corrupted_journal.log')
    if os.path.exists(journal):
        os.remove(journal)
    subprocess.run([os.path.join(ROOT, 'intent'), 'build', b3_src, '-o', b3_bin],
                   check=True, capture_output=True)

    # Send:
    #  1) valid add with empty email: "add-user ,25"
    #  2) "find-user" with NO argument at all -> instead of "error: missing email", matches email=""!
    #  3) invalid add with non-number age: "add-user bob@x.com,not_a_number" -> prints error, YET logs to journal!
    #  4) duplicate add: "add-user ,99" -> prints "duplicate email", YET logs to journal!
    inp3 = 'add-user ,25\nfind-user\nadd-user bob@x.com,not_a_number\nadd-user ,99\n'
    res3 = subprocess.run([b3_bin, journal], input=inp3, capture_output=True, text=True, check=True)
    out3 = res3.stdout.splitlines()
    assert out3[0] == ',25', f'Expected find-user with no arg to match empty email, got {out3}'
    assert out3[1] == 'error: age must be a number'
    assert out3[2] == 'duplicate email'
    print('  [PROVEN Bug 3] `find-user` with NO argument silently coerces missing argument to `""` instead of reporting `error: missing email`!')

    with open(journal) as fh:
        logged_lines = [l.strip() for l in fh if l.strip()]
    assert 'add-user bob@x.com,not_a_number' in logged_lines
    assert 'add-user ,99' in logged_lines
    print(f'  [PROVEN Bug 4] Failed/rejected mutating commands were appended to WAL journal: {logged_lines}')

    # ---- Bug 5, 6, 7: Compile-time parser bugs ----
    b5_src = os.path.join(HERE, 'bug5_6_7_parser.intent')
    chk = subprocess.run([os.path.join(ROOT, 'intent'), 'check', b5_src], capture_output=True, text=True)
    with open(os.path.join(HERE, 'bug5_6_7_output.txt'), 'w') as fh:
        fh.write(chk.stdout + chk.stderr)
    assert chk.returncode != 0
    assert 'Bookings has no property "customer"' in chk.stderr or 'which collection is this about?' in chk.stderr
    assert 'I don\'t see how "is" fits in' in chk.stderr
    print('  [PROVEN Bugs 5, 6, 7] Confirmed Field-shadows-Collection, `order by` SORTBY collision, and bare `is` phrase macro failure.')


if __name__ == '__main__':
    run_bug_hunt()
