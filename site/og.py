"""Draw the 1200x630 social card (og.png) shown when the site or repo is shared, as a page of the site: paper,
Source Serif and IBM Plex Mono, the intent. wordmark, the headline and the first listing on graph paper.

    python3 site/og.py FONTS_DIR [OUT]

FONTS_DIR holds the Google Fonts TTFs (SIL Open Font License): serif700.ttf (Source Serif 4 display Bold),
serif400d.ttf and serif400i.ttf (display Regular and Italic), mono400.ttf and mono500.ttf (IBM Plex Mono).
Needs Pillow."""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
PAPER, SHEET, INK, INK2, INK3 = '#f6f4ee', '#fbfaf6', '#1b1c1f', '#4b4e56', '#80838b'
RULE, RULE2, GRID, BLUE, GREEN, ORANGE = '#d6d0c2', '#e6e1d5', '#e4ebf3', '#2a5fc4', '#2c8248', '#dd5a2b'

LISTING = [[('Customers is a ', INK), ('collection', BLUE), ('.', INK)],
           [('Each', BLUE), (' customer has a name, an age', INK)],
           [('  and an email.', INK)],
           [('Emails are ', INK), ('unique', BLUE), ('. ', INK), ('Reject duplicates', BLUE), ('.', INK)],
           [],
           [('Add', BLUE), (' a customer.', INK)],
           [('Find', BLUE), (' a customer by email.', INK)],
           [('Show', BLUE), (' the customers sorted by age.', INK)],
           [('adults', ORANGE), (': the names of customers', INK)],
           [('  ', INK), ('whose', BLUE), (' age is at least ', INK), ('18', ORANGE), ('.', INK)]]


def main(fonts, out):
    f = lambda name, size: ImageFont.truetype(os.path.join(fonts, name), size)
    im = Image.new('RGB', (W, H), PAPER)
    d = ImageDraw.Draw(im)

    def run(x, y, parts, font):
        for text, colour in parts:
            d.text((x, y), text, font=font, fill=colour)
            x += d.textlength(text, font=font)
        return x

    # the masthead: wordmark and a rule, as on every page
    mark = f('serif700.ttf', 46)
    run(64, 40, [('intent', INK), ('.', ORANGE)], mark)
    small = f('mono400.ttf', 19)
    tag = 'guide  gallery  examples  changelog'
    d.text((W - 64 - d.textlength(tag, font=small), 56), tag, font=small, fill=INK2)
    d.line((0, 116, W, 116), fill=RULE, width=1)

    # the headline, set like the home page's
    d.text((64, 150), 'An experimental programming language', font=small, fill=INK3)
    head, it = f('serif400d.ttf', 74), f('serif400i.ttf', 74)
    run(60, 186, [('Write what', INK)], head)
    x = run(run(60, 266, [('you ', INK)], head), 266, [('mean', ORANGE)], it)
    run(x, 266, [('.', INK)], head)
    run(60, 346, [('Get native code.', INK)], head)
    body = f('serif400d.ttf', 25)
    for i, line in enumerate(['Plain English, compiled through LLVM IR,', 'with no AI in the compiler.']):
        d.text((64, 462 + i * 34), line, font=body, fill=INK2)

    # the first listing, on graph paper
    gx0, gy0, gx1, gy1 = 640, 116, W, H
    for gx in range(gx0, gx1, 24):
        d.line((gx, gy0, gx, gy1), fill=GRID)
    for gy in range(gy0, gy1, 24):
        d.line((gx0, gy, gx1, gy), fill=GRID)
    d.line((gx0, gy0, gx0, gy1), fill=RULE)
    bx0, by0, bx1, by1 = 676, 156, W - 40, 590
    d.rectangle((bx0, by0, bx1, by1), fill=SHEET, outline=RULE)
    cap, mono = f('mono500.ttf', 17), f('mono400.ttf', 19)
    x = run(bx0 + 20, by0 + 16, [('Listing 1', INK)], cap)
    d.text((x + 12, by0 + 16), 'customers.intent', font=f('mono400.ttf', 17), fill=INK3)
    d.line((bx0, by0 + 50, bx1, by0 + 50), fill=RULE2)
    for i, parts in enumerate(LISTING):
        run(bx0 + 20, by0 + 68 + i * 28, parts, mono)
    d.line((bx0, by1 - 76, bx1, by1 - 76), fill=RULE2)
    note = f('serif400d.ttf', 19)
    run(bx0 + 20, by1 - 60, [('Built: an array, a hash index on email', INK2)], note)
    run(bx0 + 20, by1 - 35, [('and a tree on age. Nothing asked for them.', INK2)], note)

    foot = f('mono400.ttf', 19)
    d.text((64, 578), 'intent.srivtx.xyz', font=foot, fill=BLUE)
    im.save(out, optimize=True)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else
         os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'assets', 'og.png'))
