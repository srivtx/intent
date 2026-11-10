"""Draw the 1200x630 social card (og.png) shown when the site or repo is shared. Needs Pillow."""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
BG, FG, DIM, AMBER, GREEN, CODE_BG = '#0b0f17', '#f3f4f6', '#9ca3af', '#f59e0b', '#34d399', '#111827'


def font(names, size, index=0):
    for n in names:
        for d in ('/System/Library/Fonts', '/System/Library/Fonts/Supplemental', '/usr/share/fonts/truetype/dejavu'):
            p = os.path.join(d, n)
            if os.path.exists(p):
                return ImageFont.truetype(p, size, index=index if p.endswith('.ttc') else 0)
    return ImageFont.load_default(size)


SANS = ['HelveticaNeue.ttc', 'Helvetica.ttc', 'DejaVuSans-Bold.ttf']
MONO = ['Menlo.ttc', 'DejaVuSansMono.ttf']


def main(out):
    im = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(im)
    big = font(SANS, 120, index=1)
    d.text((72, 48), 'intent', font=big, fill=FG)
    d.text((72 + d.textlength('intent', font=big), 48), '.', font=big, fill=AMBER)
    d.text((76, 196), 'Plain English in. Native code out. No AI in the compiler.', font=font(SANS, 38), fill=DIM)
    d.rounded_rectangle((72, 268, W - 72, 560), 18, fill=CODE_BG)
    mono = font(MONO, 30)
    lines = [('Products have a code (text), a price (money), a stock.', FG),
             ('Codes are unique. Reject duplicates.', FG),
             ('Add a product. Find a product by code.', FG),
             ('sale: decrease the price by a given discount.', FG),
             ('-> hash index on code, O(1) find, native via LLVM IR', GREEN)]
    for i, (s, c) in enumerate(lines):
        d.text((104, 296 + i * 50), s, font=mono, fill=c)
    d.text((76, 576), 'github.com/srivtx/intent', font=font(SANS, 28), fill=AMBER)
    sm = font(SANS, 26)
    tag = 'deterministic  ·  asks, never guesses'
    d.text((W - 72 - d.textlength(tag, font=sm), 578), tag, font=sm, fill=DIM)
    im.save(out, optimize=True)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', 'assets', 'og.png'))
