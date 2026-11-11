"""Draw the intent. wordmark as outlines, so the README, the favicon and the social card show the same letters as
the site's header without needing its web font. The letters are Source Serif 4 Bold at its display size, the
same face the pages are set in; the full stop is the orange used for emphasis on the site.

    python3 site/wordmark.py FONTS_DIR

FONTS_DIR holds the Source Serif 4 display Bold TTF from Google Fonts (SIL Open Font License), named
serif700.ttf. Writes assets/logo-light.svg, assets/logo-dark.svg and assets/icon.svg. Needs fontTools."""
import os
import sys

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

INK = {'light': '#1b1c1f', 'dark': '#e8e5dc'}
DOT = {'light': '#dd5a2b', 'dark': '#f0875a'}
TRACK = -0.02          # the header's letter-spacing, in ems


def outline(font, text, size, x0, baseline):
    """Path data for each character of text, set at size from x0 on baseline, with the font's own spacing."""
    glyphs, cmap = font.getGlyphSet(), font.getBestCmap()
    scale = size / font['head'].unitsPerEm
    paths, x = [], x0
    for ch in text:
        name = cmap[ord(ch)]
        pen = SVGPathPen(glyphs, ntos=lambda v: f'{v:.2f}'.rstrip('0').rstrip('.'))
        glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, x, baseline)))
        paths.append(pen.getCommands())
        x += glyphs[name].width * scale + TRACK * size
    return paths, x - TRACK * size


def bounds(font, text, size):
    from fontTools.pens.boundsPen import BoundsPen
    glyphs, cmap = font.getGlyphSet(), font.getBestCmap()
    scale, x, box = size / font['head'].unitsPerEm, 0, None
    for ch in text:
        pen = BoundsPen(glyphs)
        glyphs[cmap[ord(ch)]].draw(TransformPen(pen, (scale, 0, 0, -scale, x, 0)))
        if pen.bounds:
            b = pen.bounds
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
        x += glyphs[cmap[ord(ch)]].width * scale + TRACK * size
    return box


def logo(font, mode):
    size, pad = 96, 8
    left, top, right, bottom = bounds(font, 'intent.', size)
    w, h = right - left + 2 * pad, bottom - top + 2 * pad
    paths, _ = outline(font, 'intent.', size, pad - left, pad - top)
    word, dot = ''.join(paths[:-1]), paths[-1]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" width="{w:.0f}" height="{h:.0f}" '
            f'role="img" aria-label="intent.">\n  <title>intent.</title>\n'
            f'  <path fill="{INK[mode]}" d="{word}"/>\n  <path fill="{DOT[mode]}" d="{dot}"/>\n</svg>\n')


def icon(font):
    """The favicon: a lowercase i and the orange full stop, on the site's ink."""
    size = 92
    left, top, right, bottom = bounds(font, 'i.', size)
    x0, base = 64 - (right - left) / 2 - left, 64 - (top + bottom) / 2
    (i, dot), _ = outline(font, 'i.', size, x0, base)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128" role="img" '
            'aria-label="intent.">\n  <title>intent.</title>\n'
            '  <rect width="128" height="128" rx="22" fill="#1b1c1f"/>\n'
            f'  <path fill="#f6f4ee" d="{i}"/>\n  <path fill="{DOT["dark"]}" d="{dot}"/>\n</svg>\n')


def main(fonts):
    font = TTFont(os.path.join(fonts, 'serif700.ttf'))
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'assets')
    for mode in ('light', 'dark'):
        with open(os.path.join(out, f'logo-{mode}.svg'), 'w') as fh:
            fh.write(logo(font, mode))
    with open(os.path.join(out, 'icon.svg'), 'w') as fh:
        fh.write(icon(font))


if __name__ == '__main__':
    main(sys.argv[1])
