"""A program on the network, and in a window.

Nothing here decides what a program means. A served program takes exactly the commands it takes
on stdin; they just arrive over connections instead, one at a time, in the order they arrive:

  a plain connection        each line is a command, the answer comes back on the same connection
  GET /                     a page that shows the program: its board as a picture, or a console
  GET /<command>/<args>     run one command (%XX is decoded), the answer is the body
  POST /                    every line of the body is a command, the answers are the body

A program with a board lives in real time while it is served, as it does in a terminal: the clock
becomes "wait" commands. The compiled program serves itself the same way ("./game serve 8080").
"""
import json
import os
import select
import socket
import time
from urllib.parse import unquote

from .ir import LONGEST_STEP, OVER, builtins, usage, uses_chance

PLAIN = 'HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n'
HTML = 'HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n'
MOST = 64               # connections held open at once
ROOM = 8192             # the longest command line, and the largest request, in bytes

PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root { --bg:#14161b; --panel:#1c1f26; --line:#2b303b; --text:#d8dee9; --dim:#7a8394; --accent:#5af78e; }
@media (prefers-color-scheme: light) { :root { --bg:#f4f5f7; --panel:#ffffff; --line:#d5d9e0; --text:#1d2330; --dim:#667085; --accent:#0a7f43; } }
* { box-sizing: border-box; }
[hidden] { display: none !important; }
html, body { height: 100%; margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
main { min-height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 10px; padding: 16px; }
h1 { font-size: 13px; font-weight: 600; letter-spacing: .12em; text-transform: uppercase; color: var(--dim); margin: 0; }
canvas { background: #0d0f13; border: 1px solid var(--line); border-radius: 10px; max-width: 100%; }
.status { min-height: 1.5em; font-variant-numeric: tabular-nums; white-space: pre; }
.hint { color: var(--dim); font-size: 12px; text-align: center; }
.over { color: var(--accent); }
#console { width: min(760px, 100%); display: flex; flex-direction: column; gap: 8px; }
#log { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 12px; height: 46vh;
  overflow: auto; white-space: pre-wrap; margin: 0; }
#log b { color: var(--accent); font-weight: 600; }
input { font: inherit; color: inherit; background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
  padding: 9px 12px; width: 100%; outline: none; }
input:focus { border-color: var(--accent); }
</style></head><body><main>
<h1>__TITLE__</h1>
<div id="above" class="status"></div>
<canvas id="board" hidden></canvas>
<div id="below" class="status"></div>
<div id="hint" class="hint"></div>
<div id="console" hidden><pre id="log"></pre><input id="cmd" placeholder="a command, then Enter" autocomplete="off" spellcheck="false">
<div class="hint">__USAGE__</div></div>
</main>
<script>
const P = __PROGRAM__;
const INK = {'.':'#d8dee9', r:'#ff5c57', g:'#5af78e', y:'#f3f99d', b:'#57c7ff', m:'#ff6ac1', c:'#9aedfe', w:'#f1f1f0', k:'#7a8394'};
const say = async text => (await fetch('/', {method: 'POST', body: text + '\n'})).text();
if (P.board) {
  const cv = document.getElementById('board'), g = cv.getContext('2d');
  const [W, H] = P.board;
  let cell = 24, over = false;
  const fit = () => {
    cell = Math.max(8, Math.floor(Math.min((innerWidth - 40) / W, (innerHeight - 190) / H, 44)));
    const r = devicePixelRatio || 1;
    cv.width = W * cell * r; cv.height = H * cell * r;
    cv.style.width = W * cell + 'px'; cv.style.height = H * cell + 'px';
    g.setTransform(r, 0, 0, r, 0, 0);
  };
  cv.hidden = false; fit(); addEventListener('resize', fit);
  const draw = text => {
    const lines = text.split('\n'), cut = lines.indexOf('~');
    const top = lines.findIndex(l => l.startsWith('+'));
    const rows = lines.slice(top + 1, top + 1 + H).map(l => l.slice(1, 1 + W));
    const inks = lines.slice(cut + 1, cut + 1 + H);
    document.getElementById('above').textContent = lines.slice(0, top).join('   ');
    document.getElementById('below').textContent = lines.slice(top + H + 2, cut).join('   ');
    over = lines[cut + 1 + H] === P.over;
    g.clearRect(0, 0, W * cell, H * cell);
    g.textAlign = 'center'; g.textBaseline = 'middle';
    g.font = '600 ' + Math.round(cell * 0.72) + 'px ui-monospace, Menlo, Consolas, monospace';
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const ch = (rows[y] || '')[x] || ' ';
      if (ch === ' ') continue;
      const colour = INK[(inks[y] || '')[x]] || INK['.'], px = x * cell, py = y * cell;
      g.fillStyle = colour;
      if (ch === '#') {                 // a filled cell: walls, bricks, blocks
        g.globalAlpha = 0.92; g.beginPath(); g.roundRect(px + 1, py + 1, cell - 2, cell - 2, cell * 0.18); g.fill();
      } else {
        g.globalAlpha = 0.16; g.beginPath(); g.roundRect(px + 1, py + 1, cell - 2, cell - 2, cell * 0.28); g.fill();
        g.globalAlpha = 1; g.fillText(ch, px + cell / 2, py + cell / 2 + 1);
      }
      g.globalAlpha = 1;
    }
    const hint = document.getElementById('hint');
    hint.textContent = over ? P.overHint : (P.keys.length ? 'keys: ' + P.keys.join('  ') : '');
    hint.className = over ? 'hint over' : 'hint';
  };
  const NAMES = {ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down', ' ': 'space', Enter: 'enter'};
  addEventListener('keydown', e => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const key = NAMES[e.key] || (e.key.length === 1 ? e.key.toLowerCase() : '');
    if (over && key === 'enter' && P.restart) { e.preventDefault(); say('restart'); return; }
    if (P.keys.includes(key)) { e.preventDefault(); say('press ' + key); }
  });
  const look = async () => {
    try { draw(await (await fetch('/picture')).text()); } catch (e) { document.getElementById('hint').textContent = 'the program has stopped'; }
    setTimeout(look, 40);
  };
  look();
} else {
  const box = document.getElementById('console'), log = document.getElementById('log'), cmd = document.getElementById('cmd');
  box.hidden = false; cmd.focus();
  const past = []; let at = 0;
  cmd.addEventListener('keydown', async e => {
    if (e.key === 'ArrowUp' && at > 0) { cmd.value = past[--at]; return; }
    if (e.key === 'ArrowDown' && at < past.length) { cmd.value = past[++at] || ''; return; }
    if (e.key !== 'Enter' || !cmd.value.trim()) return;
    const text = cmd.value.trim(); cmd.value = ''; past.push(text); at = past.length;
    const b = document.createElement('b'); b.textContent = '> ' + text + '\n'; log.append(b);
    log.append(await say(text)); log.scrollTop = log.scrollHeight;
  });
}
</script></body></html>
'''


def page(prog, title):
    """The one page a served program shows. Everything in it comes from the program."""
    info = {'board': list(prog.board) if prog.board else None, 'keys': prog.keys(), 'over': OVER,
            'overHint': 'the game is over: Enter plays again', 'restart': bool(prog.ends)}
    esc = title.replace('&', '&amp;').replace('<', '&lt;')
    use = ' &nbsp;·&nbsp; '.join(u.replace('&', '&amp;').replace('<', '&lt;') for u in usage(prog))
    return PAGE.replace('__TITLE__', esc).replace('__USAGE__', use).replace('__PROGRAM__', json.dumps(info))


def title_of(path):
    return os.path.splitext(os.path.basename(path))[0].replace('-', ' ').replace('_', ' ')


def from_path(path):
    """"/find-by-name/ann%20lee?x" -> "find-by-name ann lee": the command a GET asks for."""
    path = path.split('?', 1)[0].lstrip('/')
    return unquote(path.replace('/', ' ', 1))


class Server:
    def __init__(self, m, title, port=0, public=False):
        self.m, self.title = m, title
        self.live = bool(m.prog.board and m.prog.timers())
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('0.0.0.0' if public else '127.0.0.1', port))
        self.sock.listen(64)
        self.port = self.sock.getsockname()[1]
        self.held = {}                  # connection -> what has arrived on it and is not a whole command yet
        self.last = time.monotonic()
        if self.live and uses_chance(m.prog):
            m.chance = int(time.time() * 1000)

    def run_lines(self, text):
        out = []
        for line in text.split('\n'):
            out += self.m.run(line)
        return ''.join(o + '\n' for o in out)

    def http(self, data):
        """The answer to a whole request, or None while more of it is still to come."""
        head, sep, body = data.partition(b'\r\n\r\n')
        if not sep:
            return None
        lines = head.decode('utf-8', 'replace').split('\r\n')
        method, _, rest = lines[0].partition(' ')
        if method == 'POST':
            size = next((int(l.split(':', 1)[1]) for l in lines[1:] if l.lower().startswith('content-length:')), 0)
            if len(body) < size:
                return None
            return PLAIN + self.run_lines(body[:size].decode('utf-8', 'replace'))
        path = rest.split(' ', 1)[0]
        if path == '/':
            return HTML + page(self.m.prog, self.title)
        return PLAIN + self.run_lines(from_path(path))

    def feed(self, conn):
        try:
            got = conn.recv(ROOM)
        except OSError:
            got = b''
        if not got:
            return self.drop(conn)
        data = self.held[conn] + got
        if data.startswith((b'GET ', b'POST ')):
            answer = self.http(data)
            if answer is None and len(data) < ROOM:
                self.held[conn] = data
                return
            self.send(conn, answer or PLAIN)
            return self.drop(conn)
        *whole, rest = data.split(b'\n')
        for line in whole:
            if not self.send(conn, self.run_lines(line.decode('utf-8', 'replace'))):
                return self.drop(conn)
        if len(rest) >= ROOM:
            return self.drop(conn)
        self.held[conn] = rest

    def send(self, conn, text):
        try:
            conn.sendall(text.encode())
            return True
        except OSError:
            return False

    def drop(self, conn):
        self.held.pop(conn, None)
        conn.close()

    def tick(self):
        """Real time becomes "wait": the same thing a script would send."""
        now = time.monotonic()
        passed = min(int((now - self.last) * 1000), LONGEST_STEP)
        if passed > 0:
            self.last = now
            if not self.m.over():
                self.m.advance(passed)

    def step(self, wait=None):
        if self.live:
            due = min(self.m.left + [1000]) if not self.m.over() else 1000
            wait = max(due, 1) / 1000 if wait is None else min(wait, max(due, 1) / 1000)
        ready = select.select([self.sock] + list(self.held), [], [], wait)[0]
        if self.live:
            self.tick()
        for s in ready:
            if s is self.sock:
                conn, _ = s.accept()
                if len(self.held) >= MOST:
                    conn.close()
                else:
                    self.held[conn] = b''
            elif s in self.held:
                self.feed(s)

    def forever(self):
        try:
            while True:
                self.step()
        except KeyboardInterrupt:
            pass
        finally:
            self.close()

    def close(self):
        for conn in list(self.held):
            self.drop(conn)
        self.sock.close()


__all__ = ['Server', 'page', 'title_of', 'from_path', 'builtins']
