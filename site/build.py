"""Build the public website into _site/ (served by GitHub Pages).

    python3 site/build.py            # needs the "markdown" package: pip install markdown

Every page is written for people first and for search engines and AI crawlers second: one clear
title and description, a canonical address, Open Graph and Twitter cards, structured data
(JSON-LD), a sitemap, robots.txt and llms.txt.
"""
import datetime
import glob
import html
import json
import os
import re
import shutil
import sys

import markdown

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from intentc import __version__  # noqa: E402

OUT = os.path.join(ROOT, '_site')
SITE = 'https://intent.srivtx.xyz/'
REPO = 'https://github.com/srivtx/intent'
NAME = 'Intent'
TAGLINE = 'Plain English in, native code out'
DESCRIPTION = ('Intent is an experimental programming language where you describe what information exists and '
               'what should be possible with it, in ordinary English sentences. A deterministic compiler, with no AI '
               'inside, chooses the data structures and algorithms and emits LLVM IR for a native program. It never '
               'guesses: unknown words and ambiguous sentences become questions.')
KEYWORDS = ('natural language programming, English programming language, intent-driven programming, '
            'declarative programming language, deterministic compiler, LLVM IR, compiler, programming language design, '
            'no-code, controlled natural language, program synthesis, data structure selection, Python, native code')
TODAY = datetime.date.today().isoformat()


def page(path, title, desc, body, kind='WebPage', extra_ld=None):
    url = SITE + path
    ld = [{
        '@context': 'https://schema.org', '@type': kind, 'name': title, 'url': url, 'description': desc,
        'inLanguage': 'en', 'isPartOf': {'@type': 'WebSite', 'name': NAME, 'url': SITE},
    }] + (extra_ld or [])
    full = title if title.startswith(NAME) else f'{title} · {NAME}'
    nav = ''.join(f'<a href="{SITE}{p}"{" aria-current=page" if p == path else ""}>{n}</a>'
                  for p, n in (('', 'Home'), ('guide/', 'Guide'), ('examples/', 'Examples'), ('changelog/', 'Changelog')))
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(full)}</title>
<meta name="description" content="{html.escape(desc)}">
<meta name="keywords" content="{html.escape(KEYWORDS)}">
<meta name="author" content="srivtx">
<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1">
<link rel="canonical" href="{url}">
<link rel="icon" href="{SITE}icon.svg" type="image/svg+xml">
<link rel="manifest" href="{SITE}site.webmanifest">
<link rel="sitemap" type="application/xml" href="{SITE}sitemap.xml">
<meta name="theme-color" content="#0b0f17" media="(prefers-color-scheme: dark)">
<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">
<meta property="og:type" content="{'website' if not path else 'article'}">
<meta property="og:site_name" content="{NAME}">
<meta property="og:title" content="{html.escape(full)}">
<meta property="og:description" content="{html.escape(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE}og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Intent: plain English sentences compiled to native code through LLVM IR">
<meta property="og:locale" content="en_US">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{html.escape(full)}">
<meta name="twitter:description" content="{html.escape(desc)}">
<meta name="twitter:image" content="{SITE}og.png">
<script type="application/ld+json">{json.dumps(ld if len(ld) > 1 else ld[0], ensure_ascii=False)}</script>
<style>{CSS}</style>
</head>
<body>
<header class="top"><div class="wrap bar">
<a class="brand" href="{SITE}">intent<span>.</span></a>
<nav>{nav}<a href="{REPO}">GitHub</a></nav>
</div></header>
<main class="wrap">
{body}
</main>
<footer class="wrap foot">
<p>Intent {__version__} · experimental research prototype · <a href="{REPO}">source on GitHub</a> ·
<a href="{SITE}llms.txt">llms.txt</a> · <a href="{SITE}sitemap.xml">sitemap</a></p>
</footer>
</body>
</html>
'''


CSS = '''
:root{--bg:#fff;--fg:#111827;--dim:#4b5563;--line:#e5e7eb;--code:#f6f7f9;--accent:#b45309;--amber:#f59e0b;--ok:#047857}
@media (prefers-color-scheme:dark){:root{--bg:#0b0f17;--fg:#f3f4f6;--dim:#9ca3af;--line:#1f2937;--code:#111827;--accent:#fbbf24;--ok:#34d399}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.65 ui-sans-serif,-apple-system,"Segoe UI",Helvetica,Arial,sans-serif}
.wrap{max-width:880px;margin:0 auto;padding:0 16px}
a{color:var(--accent)}
.top{border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg);z-index:1}
.bar{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:56px;flex-wrap:wrap}
.brand{font-weight:800;font-size:24px;letter-spacing:-1px;color:var(--fg);text-decoration:none}
.brand span{color:var(--amber)}
nav{display:flex;gap:14px;flex-wrap:wrap}
nav a{color:var(--dim);text-decoration:none;font-size:15px}
nav a[aria-current],nav a:hover{color:var(--fg)}
h1{font-size:clamp(32px,6vw,52px);line-height:1.1;letter-spacing:-1.5px;margin:48px 0 12px}
h2{font-size:26px;letter-spacing:-.5px;margin:48px 0 8px;border-top:1px solid var(--line);padding-top:24px}
h3{font-size:19px;margin:28px 0 6px}
.lede{font-size:20px;color:var(--dim);max-width:720px}
pre,code{font:14.5px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
pre{background:var(--code);border:1px solid var(--line);border-radius:10px;padding:14px 16px;overflow-x:auto}
:not(pre)>code{background:var(--code);padding:1px 5px;border-radius:5px}
table{border-collapse:collapse;width:100%;display:block;overflow-x:auto;font-size:15px}
th,td{border-bottom:1px solid var(--line);padding:6px 10px;text-align:left;vertical-align:top}
img{max-width:100%;height:auto}
.cta{display:flex;gap:12px;flex-wrap:wrap;margin:24px 0}
.btn{display:inline-block;padding:10px 18px;border-radius:9px;border:1px solid var(--line);text-decoration:none;color:var(--fg);font-weight:600}
.btn.main{background:var(--fg);color:var(--bg);border-color:var(--fg)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin:18px 0}
.card{border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card h3{margin:0 0 4px;font-size:17px}
.card p{margin:0;color:var(--dim);font-size:15.5px}
.ok{color:var(--ok)}
.foot{color:var(--dim);font-size:14px;border-top:1px solid var(--line);margin-top:64px;padding-top:12px;padding-bottom:32px}
blockquote{margin:16px 0;padding:2px 16px;border-left:3px solid var(--amber);color:var(--dim)}
details{border-bottom:1px solid var(--line);padding:10px 0}
summary{cursor:pointer;font-weight:600}
'''


def rewrite_links(text, src_dir):
    """Links between repository files point at GitHub, except the pages this site has itself."""
    local = {'docs/language.md': 'guide/', 'CHANGELOG.md': 'changelog/', 'README.md': '', 'examples': 'examples/',
             'examples/': 'examples/'}

    def fix(m):
        href = m.group(2)
        if re.match(r'^(https?:|mailto:|#)', href):
            return m.group(0)
        target, _, frag = href.partition('#')
        rel = os.path.normpath(os.path.join(src_dir, target)).replace(os.sep, '/')
        if rel in local and not (rel == 'README.md' and frag):
            return f'{m.group(1)}{SITE}{local[rel]}{"#" + frag if frag else ""}{m.group(3)}'
        kind = 'tree' if os.path.isdir(os.path.join(ROOT, rel)) else 'blob'
        return f'{m.group(1)}{REPO}/{kind}/main/{rel}{"#" + frag if frag else ""}{m.group(3)}'
    return re.sub(r'(\]\()([^)\s]+)(\))', fix, text)


def md(text, src_dir='.'):
    return markdown.markdown(rewrite_links(text, src_dir), extensions=['fenced_code', 'tables', 'toc'],
                             extension_configs={'toc': {'permalink': False}})


def first_example():
    return '''Customers is a collection.
Each customer has a name, an age and an email.
Emails are unique.
Reject duplicates.

Add a customer.
Find a customer by email.
Remove a customer by email.
For every customer, double their age.
adults: the names of customers whose age is at least 18.
What is the average age?
Show the customers sorted by age, largest first.'''


FAQ = [
    ('Is Intent an AI code generator?',
     'No. There is no AI or machine learning in the compiler. It is a deterministic compiler: a lexicon of known '
     'phrases, a parser and a checker. The same text always compiles to the same program.'),
    ('What happens when it does not understand a sentence?',
     'It stops and points at the words. An unknown word is an error, and a sentence that could mean two things '
     'becomes a question, such as "is code text or a number?". It never drops a word or picks a reading silently.'),
    ('What does it compile to?',
     'LLVM IR, which clang turns into a native executable. There is no C, Rust or JavaScript in between. A Python '
     'reference interpreter defines the meaning, and the native code is tested against it on random commands.'),
    ('What can I build with it?',
     'Small data services: customers, shops, to-do lists, leaderboards, orders with order lines. It can also build '
     'terminal and browser games with time, keys, chance and a coloured board. Compiled programs can be served over '
     'HTTP and keep a replayable journal.'),
    ('Does it handle money?',
     'Yes, from version 0.8. Decimal numbers are kept exactly as whole hundredths, so 0.1 + 0.2 is 0.30. '
     'Multiplication and division round to the nearest cent, halves away from zero.'),
    ('Is it ready for production?',
     'No. It is an experimental research prototype. The language changes between versions, and it is tested on '
     'macOS and Linux only.'),
]


def home():
    feats = [('Deterministic', 'No AI in the compiler. The same sentences always mean the same program.'),
             ('Asks, never guesses', 'Unknown words are errors; ambiguous sentences become pointed questions.'),
             ('Chooses the algorithms', 'Hash indexes, fused passes and removal strategies come from what you declared.'),
             ('Native via LLVM IR', 'Straight to LLVM IR and clang. Tested against a reference interpreter.'),
             ('Money, exactly', 'Decimals kept as hundredths: 0.1 + 0.2 is 0.30, rounding is explicit.'),
             ('Games and servers', 'Time, keys, chance and a board; serve any program over HTTP or in a window.')]
    cards = ''.join(f'<div class="card"><h3>{t}</h3><p>{d}</p></div>' for t, d in feats)
    faq = ''.join(f'<details><summary>{html.escape(q)}</summary><p>{html.escape(a)}</p></details>' for q, a in FAQ)
    body = f'''
<h1>Write what you mean.<br>Get native code.</h1>
<p class="lede">Intent is an experimental programming language in plain English. You describe what information
exists and what should be possible with it. A deterministic compiler works out the data structures, loops and
algorithms and emits <strong>LLVM IR</strong> for a native program. No AI is involved.</p>
<div class="cta"><a class="btn main" href="{REPO}">Get it on GitHub</a><a class="btn" href="{SITE}guide/">Read the guide</a>
<a class="btn" href="{SITE}examples/">See examples</a></div>
<pre><code>{html.escape(first_example())}</code></pre>
<p>Nothing above says array, hash map, loop, index or sort algorithm. The compiler picks a growable array with a hash
index on email, because emails are unique and are looked up, and <code>./intent explain</code> tells you which line
caused each choice.</p>
<div class="grid">{cards}</div>

<h2>Try it in a minute</h2>
<p>Needs Python 3.10+ and <code>clang</code>. Nothing to install.</p>
<pre><code>git clone {REPO}.git && cd intent
./intent check examples/customers.intent      # how every sentence was read
./intent explain examples/customers.intent    # the representation it chose, and why
./intent build examples/customers.intent -o build/customers
printf 'add Alice,20,alice@x.com\\nfind-by-email alice@x.com\\n' | ./build/customers</code></pre>

<h2>It asks instead of guessing</h2>
<pre><code>question: is "code" text or a number?
 --> shop.intent:1
1 | Each product has a code, a price (money) and a stock.
  | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ nothing in the program decides this
  = write "code (text)" or "code (number)"</code></pre>
<p>Every word is a known concept, filler, or a name your program declared. Anything else stops compilation. A sentence
that could be read two ways is a question, never a coin flip.</p>

<h2>Many phrasings, one meaning</h2>
<p>All of these compile to the identical program <code>update customer: age = age * 2</code>:</p>
<ul><li>For every customer, double their age.</li><li>Take the customer collection and make everyone's age twice as large.</li>
<li>Customers: increase each person's age to two times its current value.</li><li>age = age * 2</li></ul>

<h2>A game in 26 sentences</h2>
<p>Programs can run by themselves: time passes, keys are pressed, and a coloured board is drawn in a terminal or a
browser window. Time, keys and chance are events, so every game can be replayed exactly.</p>
<pre><code>Every 120 milliseconds, remove the segments whose age is at least the length.
The game is over when any segment's x is the column and its y is the row.
Draw each segment at its x and y as a green "o".</code></pre>
<p><img src="{SITE}window-shooter.jpg" width="560" height="350" alt="The shooter example written in Intent, running in a browser window" loading="lazy"></p>

<h2>Questions</h2>
{faq}
'''
    ld = [{'@context': 'https://schema.org', '@type': 'SoftwareSourceCode', 'name': NAME,
           'description': DESCRIPTION, 'codeRepository': REPO, 'programmingLanguage': ['Python', 'LLVM IR'],
           'license': f'{REPO}', 'version': __version__, 'dateModified': TODAY, 'keywords': KEYWORDS,
           'author': {'@type': 'Person', 'name': 'srivtx', 'url': 'https://github.com/srivtx'}},
          {'@context': 'https://schema.org', '@type': 'SoftwareApplication', 'name': NAME,
           'applicationCategory': 'DeveloperApplication', 'operatingSystem': 'macOS, Linux',
           'softwareVersion': __version__, 'url': SITE, 'downloadUrl': REPO, 'description': DESCRIPTION,
           'offers': {'@type': 'Offer', 'price': '0', 'priceCurrency': 'USD'}},
          {'@context': 'https://schema.org', '@type': 'FAQPage',
           'mainEntity': [{'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}}
                          for q, a in FAQ]}]
    return page('', f'{NAME}: {TAGLINE}, no AI in the compiler', DESCRIPTION, body, 'WebSite', ld)


def guide():
    with open(os.path.join(ROOT, 'docs', 'language.md')) as fh:
        text = fh.read()
    return page('guide/', 'Language guide', 'How to write Intent programs: describing information, teaching words, '
                'capabilities, decimals and money, single values, standing rules, time, keys and a board, and serving '
                'a program over the network.', md(text, 'docs'), 'TechArticle')


def changelog():
    with open(os.path.join(ROOT, 'CHANGELOG.md')) as fh:
        text = fh.read()
    return page('changelog/', 'Changelog', f'What changed in each version of Intent, up to {__version__}.',
                md(text), 'TechArticle')


EXAMPLE_TEXT = {
    'customers': 'a customer list with unique emails, lookups and summaries',
    'shop': 'shop stock with prices as money: sell, restock, sales, what is running low',
    'store': 'customers, their orders and order lines, with cascading removal',
    'leaderboard': 'a game leaderboard: join, award points, podium, champions',
    'todo': 'a to-do list: open, finished and urgent tasks, what to do next',
    'calculator': 'a calculator: nothing stored, values that depend on conditions',
    'arcade': 'the scorekeeping of a game: single values, players, standing rules',
    'dodge': 'a terminal game: time, arrow keys, a board, an ending',
    'snake': 'snake: records that appear and go, chance, a hit, colour, playing again',
    'shooter': 'a shooter: two collections meeting, counting inside a sentence',
    'questions': 'sentences the compiler refuses to guess about, and the questions it asks',
    'tour': 'every kind of sentence in the language guide, as one program',
}


def examples():
    parts = ['<h1>Examples</h1><p class="lede">Complete Intent programs from the repository. Each one compiles to a '
             'native executable with <code>./intent build</code>.</p>']
    for path in sorted(glob.glob(os.path.join(ROOT, 'examples', '*.intent'))):
        name = os.path.splitext(os.path.basename(path))[0]
        with open(path) as fh:
            code = fh.read()
        parts.append(f'<h2 id="{name}">{name}.intent</h2><p>{html.escape(EXAMPLE_TEXT.get(name, ""))} · '
                     f'<a href="{REPO}/blob/main/examples/{name}.intent">source</a></p>'
                     f'<pre><code>{html.escape(code)}</code></pre>')
    return page('examples/', 'Example programs', 'Complete programs written in Intent, a plain-English language that '
                'compiles to native code: a shop with money, customers and orders, a to-do list, a leaderboard, and '
                'games such as snake and a shooter.', '\n'.join(parts), 'CollectionPage')


def write(rel, text):
    p = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as fh:
        fh.write(text)


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    pages = {'': home(), 'guide/': guide(), 'examples/': examples(), 'changelog/': changelog()}
    for path, text in pages.items():
        write(path + 'index.html', text)
    write('404.html', page('404', 'Page not found', 'This page does not exist.',
                           f'<h1>Not here.</h1><p>Try the <a href="{SITE}">home page</a> or the '
                           f'<a href="{SITE}guide/">guide</a>.</p>').replace('index, follow', 'noindex'))
    for a in ('icon.svg', 'og.png', 'window-shooter.jpg', 'logo-light.svg', 'logo-dark.svg'):
        shutil.copy(os.path.join(ROOT, 'assets', a), os.path.join(OUT, a))
    for f in glob.glob(os.path.join(ROOT, 'site', 'static', '*')):
        shutil.copy(f, os.path.join(OUT, os.path.basename(f)))
    write('.nojekyll', '')
    write('robots.txt', f'User-agent: *\nAllow: /\n\nSitemap: {SITE}sitemap.xml\n')
    urls = ''.join(f'  <url><loc>{SITE}{p}</loc><lastmod>{TODAY}</lastmod>'
                   f'<priority>{"1.0" if not p else "0.8"}</priority></url>\n' for p in pages)
    write('sitemap.xml', f'<?xml version="1.0" encoding="UTF-8"?>\n'
                         f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n')
    write('site.webmanifest', json.dumps({'name': NAME, 'short_name': NAME, 'start_url': SITE, 'display': 'browser',
                                          'background_color': '#0b0f17', 'theme_color': '#0b0f17',
                                          'icons': [{'src': SITE + 'icon.svg', 'sizes': 'any', 'type': 'image/svg+xml'}]},
                                         indent=1))
    with open(os.path.join(ROOT, 'README.md')) as fh:
        readme = fh.read()
    with open(os.path.join(ROOT, 'docs', 'language.md')) as fh:
        lang = fh.read()
    write('llms.txt', f'''# {NAME}

> {DESCRIPTION}

Version {__version__}. Experimental research prototype; tested on macOS and Linux.

## Docs

- [Language guide]({SITE}guide/): every kind of sentence the compiler understands
- [Examples]({SITE}examples/): complete programs, from a shop with money to a snake game
- [Changelog]({SITE}changelog/): what changed in each version
- [Full text for language models]({SITE}llms-full.txt): the README and the guide in one file

## Source

- [GitHub repository]({REPO}): compiler in Python (no dependencies), emits LLVM IR
''')
    write('llms-full.txt', rewrite_links(readme, '.') + '\n\n---\n\n' + rewrite_links(lang, 'docs'))
    print(f'built {len(pages)} pages into {OUT}')


if __name__ == '__main__':
    main()
