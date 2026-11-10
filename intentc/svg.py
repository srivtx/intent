"""A board as a picture: an SVG of what the program draws, after whatever events it is given.

The picture comes from the reference interpreter, so it is exactly what the compiled program would
show on its screen; only the look is chosen here: each drawn cell as its character, as a dot, or as
a filled square, in the colour the program gave it.
"""

from xml.sax.saxutils import escape

from .ir import COLOURS

# The terminal colours, as they are painted in a picture (0: drawn without a colour).
PAINT = {0: '#ece8dc', 31: '#ff5a4e', 32: '#5ee07a', 33: '#ffd23f', 34: '#4c7dff', 35: '#ff6ad5',
         36: '#3fe0e8', 37: '#ffffff', 90: '#7d8290'}
PAPER = {'dark': ('#0d0f14', '#1b1f29'), 'light': ('#f6f3ea', '#e4dfd2')}
STYLES = ('glyphs', 'dots', 'blocks')
# How much ink a character carries, lightest first: a shading ramp drawn in dots becomes a halftone.
RAMP = '.,`\'-_:;~"^=+!<>?/|\\icl1*ovxzsea%&$#8BWM@'


def weight(c):
    """From a little over 0 (a full stop) to 1 (an @); letters and anything else not in the ramp count as full."""
    i = RAMP.find(c)
    return 1.0 if i < 0 else (i + 1) / len(RAMP)


def picture(m, style='glyphs', paper='dark', cell=18, title=''):
    """The board of machine m as SVG text."""
    if style not in STYLES:
        raise ValueError(f'style must be one of {", ".join(STYLES)}')
    w, h = m.prog.board
    grid, ink = m.paint()
    bg, faint = PAPER[paper]
    plain = PAINT[0] if paper == 'dark' else '#22252d'
    cw, ch = (cell * 3 // 5, cell) if style == 'glyphs' else (cell, cell)
    pad = cell
    W, H = w * cw + 2 * pad, h * ch + 2 * pad
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
           f'role="img" aria-label="{escape(title or "a picture drawn by an Intent program")}">',
           f'<rect width="{W}" height="{H}" fill="{bg}"/>']
    if title:
        out.append(f'<title>{escape(title)}</title>')
    if style == 'dots':                     # the empty cells show faintly, like an unlit dot-matrix
        out.append(f'<g fill="{faint}">' + ''.join(
            f'<circle cx="{pad + x * cw + cw / 2:g}" cy="{pad + y * ch + ch / 2:g}" r="{cell * 0.12:g}"/>'
            for y in range(h) for x in range(w) if grid[y][x] == ' ') + '</g>')
    if style == 'glyphs':
        out.append(f'<g font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" '
                   f'font-size="{cell * 0.9:g}" text-anchor="middle" dominant-baseline="central">')
    for y in range(h):
        for x in range(w):
            c = grid[y][x]
            if c == ' ':
                continue
            colour = PAINT.get(ink[y][x], plain) if ink[y][x] else plain
            cx, cy = pad + x * cw + cw / 2, pad + y * ch + ch / 2
            if style == 'glyphs':
                out.append(f'<text x="{cx:g}" y="{cy:g}" fill="{colour}">{escape(c)}</text>')
            elif style == 'dots':
                r = cell * 0.44 * max(0.3, weight(c)) ** 0.5     # the area of the dot follows the ink
                out.append(f'<circle cx="{cx:g}" cy="{cy:g}" r="{r:.2f}" fill="{colour}"/>')
            else:
                o = max(0.25, weight(c))
                out.append(f'<rect x="{pad + x * cw:g}" y="{pad + y * ch:g}" width="{cw:g}" height="{ch:g}" '
                           f'fill="{colour}"' + (f' fill-opacity="{o:.2f}"' if o < 1 else '') + '/>')
    if style == 'glyphs':
        out.append('</g>')
    out.append('</svg>')
    return '\n'.join(out) + '\n'


assert set(PAINT) >= set(COLOURS.values()) | {0}
