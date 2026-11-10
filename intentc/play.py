"""Playing a program in the terminal with the reference interpreter.

Nothing here decides what the program means. The real clock and the real keyboard are turned
into the same two events a script can send ("wait <milliseconds>", "press <key>"), and the
board is whatever "screen" prints. The compiled program does exactly the same.
"""
import os
import select
import shutil
import signal
import sys
import termios
import time

from .ir import ENTER_PLAY, KEY_CODES, LEAVE_PLAY, LONGEST_STEP, OVER, TOO_SMALL, room


def decode(data):
    """Bytes from the keyboard -> key codes; None means the player wants to stop."""
    i = 0
    while i < len(data):
        b = data[i]
        if b == 27:                     # an arrow key arrives as ESC [ A..D; ESC alone means stop
            if i + 2 < len(data) and data[i + 1] == 91:
                yield 256 + data[i + 2]
                i += 3
                continue
            yield None
            return
        i += 1
        if b in (3, 4):
            yield None
            return
        if 65 <= b <= 90:
            b += 32
        yield 10 if b == 13 else b


def play(m, out=sys.stdout):
    """Returns the exit status: 0, or 1 when the terminal is too small to show the board."""
    names = {KEY_CODES[k]: k for k in m.prog.keys()}
    need, have = room(m.prog), shutil.get_terminal_size()
    if have.columns < need[0] or have.lines < need[1]:
        print(TOO_SMALL % (need + (have.columns, have.lines)))
        return 1
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    raw = termios.tcgetattr(fd)
    raw[3] &= ~(termios.ICANON | termios.ECHO)
    raw[6][termios.VMIN], raw[6][termios.VTIME] = 0, 0

    def stop(*_):
        raise KeyboardInterrupt
    handlers = {s: signal.signal(s, stop) for s in (signal.SIGTERM, signal.SIGHUP)}
    try:
        termios.tcsetattr(fd, termios.TCSADRAIN, raw)
        out.write(ENTER_PLAY)
        last = time.monotonic()
        going = True
        while going:
            out.write('\x1b[H' + ''.join(line + '\x1b[K\n' for line in m.screen()) + '\x1b[J')
            out.flush()
            if m.over():
                break
            due = min(m.left + [1000])
            if select.select([fd], [], [], max(due, 1) / 1000)[0]:
                data = os.read(fd, 16)
                if not data:
                    break
                if data == b'\x1b' and select.select([fd], [], [], 0.025)[0]:
                    data += os.read(fd, 15)         # an arrow key whose bytes arrived apart
                for code in decode(data):
                    if code is None or (code == ord('q') and code not in names):
                        going = False
                        break
                    if code in names and not m.over():
                        m.press(names[code])
            now = time.monotonic()
            passed = min(int((now - last) * 1000), LONGEST_STEP)
            if passed > 0:
                last = now
                m.advance(passed)
    except KeyboardInterrupt:
        pass
    finally:
        out.write(LEAVE_PLAY)
        out.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        for s, h in handlers.items():
            signal.signal(s, h)
    print('\n'.join(m.screen()))                   # what it looked like when it stopped stays on the terminal
    if m.over():
        print(OVER)
    return 0
