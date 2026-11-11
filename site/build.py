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
import shlex
import shutil
import sys

import markdown

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from intentc import __version__  # noqa: E402

OUT = os.path.join(ROOT, '_site')
SITE = os.environ.get('INTENT_SITE', 'https://intent.srivtx.xyz/')     # INTENT_SITE=http://localhost:8017/ to preview
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


NAV = (('', 'Home'), ('guide/', 'Guide'), ('gallery/', 'Gallery'), ('examples/', 'Examples'), ('changelog/', 'Changelog'))
FONTS = ('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600'
         '&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&display=swap')
# The mark: a lower-case i set in pixels, its dot in orange.
MARK = ('<svg class="mark" viewBox="0 0 5 8" width="14" height="22" aria-hidden="true" shape-rendering="crispEdges">'
        '<rect x="2" y="0" width="1" height="1" fill="var(--orange)"/><rect x="1" y="2" width="2" height="1" fill="currentColor"/>'
        '<rect x="2" y="3" width="1" height="4" fill="currentColor"/><rect x="1" y="7" width="3" height="1" fill="currentColor"/></svg>')


def page(path, title, desc, body, kind='WebPage', extra_ld=None, wide=False):
    url = SITE + path
    ld = [{
        '@context': 'https://schema.org', '@type': kind, 'name': title, 'url': url, 'description': desc,
        'inLanguage': 'en', 'isPartOf': {'@type': 'WebSite', 'name': NAME, 'url': SITE},
    }] + (extra_ld or [])
    full = title if title.startswith(NAME) else f'{title} · {NAME}'
    nav = ''.join(f'<a href="{SITE}{p}"{" aria-current=page" if p == path else ""}>{n.lower()}</a>'
                  for p, n in NAV[1:])
    links = ' · '.join(f'<a href="{SITE}{p}">{n.lower()}</a>' for p, n in NAV[1:])
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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#10141c" media="(prefers-color-scheme: dark)">
<meta name="theme-color" content="#f6f4ee" media="(prefers-color-scheme: light)">
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
<a class="skip" href="#main">Skip to the content</a>
<header class="masthead"><div class="wrap bar">
<a class="brand" href="{SITE}" aria-label="Intent, home">{MARK}<span>intent</span></a>
<nav aria-label="Site">{nav}<a href="{REPO}">github&#8599;</a></nav>
</div></header>
<main id="main" class="wrap{' wide' if wide else ''}">
{body}
</main>
<footer class="colophon"><div class="wrap">
<p><a class="brand" href="{SITE}">{MARK}<span>intent</span></a> {__version__}, an experimental research prototype.
A deterministic compiler from plain English to native code, with no AI inside.</p>
<p>{links} · <a href="{REPO}">source</a> · <a href="{REPO}/releases">releases</a> · <a href="{SITE}llms.txt">llms.txt</a></p>
<p class="set">Set in Source Serif and IBM Plex Mono. Built from the repository by <code>site/build.py</code>; the
pictures are drawn at build time by the programs beside them.</p>
</div></footer>
<script>{JS}</script>
</body>
</html>
'''


CSS = '''
:root{
  --paper:#f6f4ee;--sheet:#fbfaf6;--ink:#1b1c1f;--ink2:#4b4e56;--ink3:#80838b;--rule:#d6d0c2;--rule2:#e6e1d5;
  --blue:#2a5fc4;--green:#2c8248;--orange:#dd5a2b;--yellow:#e9b92c;--mark:#efe9da;
  --grid:rgba(42,95,196,.11);--grid2:rgba(42,95,196,.24);
  --serif:"Source Serif 4","Source Serif Pro","Iowan Old Style",Charter,Georgia,serif;
  --mono:"IBM Plex Mono",ui-monospace,"SF Mono",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root{
  --paper:#10141c;--sheet:#151a24;--ink:#e8e5dc;--ink2:#b4b1a8;--ink3:#7e7c77;--rule:#2b3242;--rule2:#1f2532;
  --blue:#80a8f2;--green:#6fc58d;--orange:#f0875a;--yellow:#efcd62;--mark:#1d2330;
  --grid:rgba(128,168,242,.08);--grid2:rgba(128,168,242,.17);
}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-padding-top:72px;scroll-behavior:smooth}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}*{transition:none!important}}
body{margin:0;overflow-x:clip;background:var(--paper);color:var(--ink);font:400 18px/1.62 var(--serif);
  font-optical-sizing:auto;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
img,svg{max-width:100%}
img{height:auto}
.wrap{max-width:1080px;margin:0 auto;padding:0 24px}
@media (max-width:600px){.wrap{padding:0 16px}body{font-size:17px}}
a{color:var(--blue);text-decoration:none;background:linear-gradient(currentColor,currentColor) 0 100%/0 1px no-repeat;
  transition:background-size .25s ease}
a:hover{background-size:100% 1px}
:focus-visible{outline:2px solid var(--orange);outline-offset:2px}
.skip{position:absolute;left:-999px;top:8px;background:var(--ink);color:var(--paper);padding:8px 12px;z-index:9;font:14px var(--mono)}
.skip:focus{left:8px}
/* scrollbars stay out of sight; things still scroll */
pre,nav,.tbl,dialog,.contents,.sheet .code pre{scrollbar-width:none}
pre::-webkit-scrollbar,nav::-webkit-scrollbar,.tbl::-webkit-scrollbar,dialog::-webkit-scrollbar,.contents::-webkit-scrollbar{display:none}

/* masthead */
.masthead{position:sticky;top:0;z-index:5;background:var(--paper);border-bottom:1px solid var(--rule)}
.bar{display:flex;align-items:center;justify-content:space-between;gap:20px;min-height:56px}
.brand{display:inline-flex;align-items:center;gap:8px;color:var(--ink);background:none;font:600 17px/1 var(--mono);letter-spacing:-.02em}
.brand .mark{color:var(--blue);height:20px;width:auto}
.masthead nav{display:flex;gap:22px;overflow-x:auto;font:400 14px/1 var(--mono)}
.masthead nav a{color:var(--ink2);padding:6px 0;white-space:nowrap;background:none;border-bottom:1.5px solid transparent;transition:color .15s,border-color .15s}
.masthead nav a:hover{color:var(--ink);border-color:var(--rule)}
.masthead nav a[aria-current]{color:var(--ink);border-color:var(--blue)}
@media (max-width:640px){.bar{flex-direction:column;align-items:flex-start;gap:6px;padding-top:12px;padding-bottom:6px}
  .masthead nav{width:100%;gap:13px;font-size:13px}}

/* type */
h1,h2,h3{font-family:var(--serif);font-weight:400;color:var(--ink);text-wrap:balance}
h1{font-size:clamp(40px,6.2vw,70px);line-height:1.02;letter-spacing:-.025em;margin:56px 0 20px}
h1 em{font-style:italic;color:var(--orange)}
h2{font-size:clamp(26px,3vw,32px);line-height:1.15;letter-spacing:-.015em;margin:80px 0 14px}
h3{font-size:21px;line-height:1.3;margin:32px 0 6px;font-weight:600}
p,li{text-wrap:pretty}
.kicker{font:400 13px/1.4 var(--mono);color:var(--ink3);letter-spacing:.02em;margin:0 0 14px}
.abstract{font-size:20px;line-height:1.55;color:var(--ink2);max-width:600px;margin:0}
.abstract b{font:600 13px/1 var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--ink);margin-right:6px}
.dim{color:var(--ink2)}
.small{font-size:15.5px}
/* numbered sections, like a paper */
.numbered{counter-reset:sec}
.numbered>h2,.numbered>section>h2{counter-increment:sec}
.numbered>h2::before,.numbered>section>h2::before{content:counter(sec);display:inline-block;min-width:34px;
  font:500 14px/1 var(--mono);color:var(--blue);vertical-align:.45em}

/* code */
pre,code,kbd{font-family:var(--mono)}
code{font-size:.84em}
:not(pre)>code{background:var(--mark);padding:1px 5px;border-radius:2px;color:var(--ink)}
pre{font-size:13.5px;line-height:1.65;margin:0;padding:16px 18px;overflow-x:auto;tab-size:2;white-space:pre-wrap;overflow-wrap:anywhere}
.ln{display:block;padding-left:3ch;text-indent:-3ch}
.ln:empty::after{content:"\\200b"}
pre code{font-size:inherit}
.c{color:var(--ink3);font-style:italic}.s{color:var(--green)}.n{color:var(--orange)}.k{color:var(--blue)}.l{color:var(--orange);font-weight:600}
.p{color:var(--ink3);user-select:none}.q{color:var(--orange);font-weight:600}
figure{margin:28px 0}
.listing{border:1px solid var(--rule);background:var(--sheet);counter-increment:listing}
.listing>figcaption{display:flex;gap:14px;align-items:baseline;padding:9px 16px;border-bottom:1px solid var(--rule2);
  font:400 12.5px/1.4 var(--mono);color:var(--ink3)}
.listing>figcaption::before{content:"Listing " counter(listing);color:var(--ink);font-weight:500}
.listing>figcaption a{margin-left:auto}
.listing>.note{margin:0;padding:11px 16px 12px;border-top:1px solid var(--rule2);font-size:15.5px;line-height:1.5;color:var(--ink2)}
.listing>.note b{font-weight:600;color:var(--ink)}
main{counter-reset:listing figure table plate}
.fig{counter-increment:figure}
.fig>figcaption,.table>figcaption{font-size:15px;line-height:1.5;color:var(--ink2);margin-top:10px}
.fig>figcaption::before{content:"Fig. " counter(figure) " ";font:500 12.5px/1 var(--mono);color:var(--ink);margin-right:6px}
.fig img{display:block;border:1px solid var(--rule)}

/* graph paper, for figures and plates */
.graph{background-color:var(--sheet);background-image:
  linear-gradient(var(--grid2) 1px,transparent 1px),linear-gradient(90deg,var(--grid2) 1px,transparent 1px),
  linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px);
  background-size:80px 80px,80px 80px,16px 16px,16px 16px;background-position:-1px -1px;border:1px solid var(--rule)}

/* tables */
.tbl{overflow-x:auto;margin:20px 0}
table{border-collapse:collapse;width:100%;font-size:16px;border-top:1.5px solid var(--ink);border-bottom:1.5px solid var(--ink)}
th,td{padding:9px 14px 9px 0;text-align:left;vertical-align:top;border-bottom:1px solid var(--rule2)}
tr:last-child td{border-bottom:0}
th{font:500 12px/1.3 var(--mono);letter-spacing:.04em;text-transform:uppercase;color:var(--ink2);border-bottom:1px solid var(--ink)}
td.r,th.r{text-align:right;font-variant-numeric:tabular-nums}
td code{white-space:nowrap}
.table{counter-increment:table}
.table>figcaption::before{content:"Table " counter(table) " ";font:500 12.5px/1 var(--mono);color:var(--ink);margin-right:6px}
td b{font-weight:600}

/* buttons */
.actions{display:flex;gap:12px;flex-wrap:wrap;margin:32px 0 0}
.btn{display:inline-block;padding:12px 18px;border:1px solid var(--ink);color:var(--ink);background:transparent;
  font:500 14px/1 var(--mono);transition:background-color .15s,color .15s,border-color .15s}
.btn:hover{background:var(--ink);color:var(--paper)}
.btn.main{background:var(--ink);color:var(--paper)}
.btn.main:hover{background:var(--blue);border-color:var(--blue)}

/* home */
.hero{display:grid;grid-template-columns:minmax(0,.92fr) minmax(0,1.08fr);gap:56px;align-items:center;padding:28px 0 8px}
.hero h1{margin-top:8px}
.specimen{padding:24px}
.specimen pre{font-size:12.6px}
.specimen .listing{margin:0}
@media (max-width:920px){.hero{grid-template-columns:minmax(0,1fr);gap:28px}.specimen{padding:16px}}
.props{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:0 40px;margin:24px 0 0}
.props div{border-top:1px solid var(--ink);padding:14px 0 22px}
.props dt{font:500 13px/1.3 var(--mono);color:var(--ink);display:flex;align-items:center;gap:9px;margin:0 0 6px}
.props dt::before{content:"";width:9px;height:9px;flex:none;background:var(--c,var(--blue))}
.props dd{margin:0;color:var(--ink2);font-size:16.5px;line-height:1.5}
@media (max-width:860px){.props{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:540px){.props{grid-template-columns:minmax(0,1fr)}}
.two{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:48px;align-items:start}
@media (max-width:860px){.two{grid-template-columns:minmax(0,1fr);gap:0}}
.plates3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;padding:24px;margin:24px 0 10px}
.plates3 a{display:block;background:none}
.plates3 .frame{border:1px solid var(--ink);transition:border-color .2s}
.plates3 a:hover .frame{border-color:var(--blue)}
.plates3 span{display:block;font:400 12.5px/1.3 var(--mono);color:var(--ink2);margin-top:8px}
@media (max-width:640px){.plates3{grid-template-columns:repeat(2,minmax(0,1fr));padding:14px;gap:14px}.plates3 a:nth-child(3){display:none}}
.qa details{border-top:1px solid var(--rule)}
.qa details:last-child{border-bottom:1px solid var(--rule)}
.qa summary{list-style:none;cursor:pointer;padding:16px 36px 16px 0;position:relative;font-size:19px}
.qa summary::-webkit-details-marker{display:none}
.qa summary::after{content:"+";position:absolute;right:2px;top:14px;font:400 20px/1 var(--mono);color:var(--ink3);transition:transform .2s}
.qa details[open] summary::after{transform:rotate(45deg)}
.qa details p{margin:-4px 0 18px;color:var(--ink2);max-width:720px}

/* plates: every frame the same shape, filled with the picture's own paper */
.frame{position:relative;display:block;aspect-ratio:4/3;background:var(--paper-of,#0d0f14);padding:0;border:0;width:100%;
  overflow:hidden;cursor:pointer;color:inherit;font:inherit}
.frame svg{position:absolute;inset:0;display:block;width:100%;height:100%}
.board{padding:28px;margin:32px 0}
.plates{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:28px 24px;counter-reset:plate}
@media (max-width:900px){.plates{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:540px){.plates{grid-template-columns:minmax(0,1fr)}.board{padding:14px}}
.plate{margin:0;counter-increment:plate;display:flex;flex-direction:column}
.plate .frame{border:1px solid var(--ink);transition:border-color .2s}
.plate .frame:hover{border-color:var(--blue)}
.plate figcaption{padding:10px 0 0;display:flex;flex-direction:column;gap:2px;flex:1}
.plate .no{font:500 12px/1.3 var(--mono);color:var(--ink3);letter-spacing:.04em}
.plate .no::before{content:"Plate " counter(plate, decimal-leading-zero) " · "}
.plate h3{margin:0;font-size:20px;font-weight:400;text-transform:capitalize}
.plate p{margin:0;color:var(--ink2);font-size:15.5px;line-height:1.45;flex:1}
.plate:target .frame{outline:2px solid var(--orange);outline-offset:3px}
.read{all:unset;cursor:pointer;color:var(--blue);font:500 13px/1 var(--mono);margin-top:10px;align-self:flex-start}
.read:hover{text-decoration:underline;text-underline-offset:3px}
.read:focus-visible{outline:2px solid var(--orange);outline-offset:3px}
dialog.sheet{border:1px solid var(--ink);padding:0;background:var(--sheet);color:var(--ink);
  width:min(1040px,calc(100vw - 32px));max-height:calc(100vh - 48px)}
dialog.sheet[open]{animation:rise .22s ease-out}
dialog.sheet[open]::backdrop{animation:fade .22s ease-out}
@keyframes rise{from{opacity:0;transform:translateY(8px)}}
@keyframes fade{from{opacity:0}}
dialog.sheet::backdrop{background:rgba(16,20,28,.55)}
.sheet .head{display:flex;align-items:baseline;gap:14px;padding:12px 18px;border-bottom:1px solid var(--rule);position:sticky;top:0;background:var(--sheet);z-index:1}
.sheet .head h2{margin:0;font-size:24px;text-transform:capitalize}
.sheet .head span{font:400 12.5px/1 var(--mono);color:var(--ink3)}
.sheet .x{all:unset;cursor:pointer;margin-left:auto;font:400 13px/1 var(--mono);color:var(--ink2);padding:6px 0}
.sheet .x:hover{color:var(--ink)}
.sheet .body{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.1fr)}
.sheet .pic{background:var(--paper-of);display:grid;place-items:center;padding:20px;border-right:1px solid var(--rule)}
.sheet .pic svg{width:100%;height:auto;max-height:70vh}
.sheet .code{min-width:0;display:flex;flex-direction:column}
.sheet .code pre{max-height:58vh;font-size:12.5px;flex:1}
.sheet .tools{display:flex;gap:18px;align-items:center;flex-wrap:wrap;padding:12px 18px;border-top:1px solid var(--rule2);font:400 13px/1.5 var(--mono)}
.sheet .tools code{background:none;padding:0;color:var(--ink3);font-size:12px}
@media (max-width:760px){.sheet .body{grid-template-columns:minmax(0,1fr)}.sheet .pic{border-right:0;border-bottom:1px solid var(--rule)}.sheet .code pre{max-height:none}}
.copy{all:unset;cursor:pointer;color:var(--blue);font:500 13px/1 var(--mono)}
.copy:hover{text-decoration:underline;text-underline-offset:3px}

/* reading pages: contents beside the text */
.doc{display:grid;grid-template-columns:210px minmax(0,1fr);gap:64px;align-items:start}
.contents{position:sticky;top:76px;max-height:calc(100vh - 92px);overflow:auto;padding:36px 0 24px;font:400 13px/1.45 var(--mono)}
.contents h2{font:500 12px/1 var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--ink3);margin:0 0 14px}
.contents ol{list-style:none;margin:0;padding:0;counter-reset:item}
.contents>ol>li{counter-increment:item}
.contents li a{display:block;padding:4px 0 4px 12px;border-left:1.5px solid var(--rule2);color:var(--ink2);background:none;transition:color .15s,border-color .15s}
.contents.counted>ol>li>a::before{content:counter(item) "  ";color:var(--ink3)}
.contents li a:hover{color:var(--ink)}
.contents li a.on{color:var(--ink);border-left-color:var(--blue)}
.contents li li a{padding-left:24px;font-size:12.5px}
.mtoc{display:none;margin:16px 0 0;border:1px solid var(--rule);background:var(--sheet);padding:0 16px;font:400 14px/1.5 var(--mono)}
.mtoc summary{cursor:pointer;padding:11px 0;color:var(--ink)}
.mtoc ol{margin:0 0 12px;padding-left:22px}
@media (max-width:960px){.doc{grid-template-columns:minmax(0,1fr);gap:0}.contents{display:none}.mtoc{display:block}}
.prose{max-width:740px;min-width:0;padding-bottom:24px}
.prose h1{margin-top:44px}
.prose h2{padding-top:30px;margin-top:60px;border-top:1px solid var(--rule)}
.prose h2:first-of-type{border-top:0;padding-top:0}
.prose.numbered h2{counter-increment:sec}
.prose.numbered h2::before{content:counter(sec);display:inline-block;min-width:34px;font:500 14px/1 var(--mono);color:var(--blue);vertical-align:.45em}
.prose pre{border:1px solid var(--rule);background:var(--sheet);margin:18px 0}
.prose blockquote{margin:22px 0;padding:2px 0 2px 18px;border-left:3px solid var(--orange);color:var(--ink2)}
.prose blockquote p{margin:6px 0}
.prose img{max-width:100%;height:auto;border:1px solid var(--rule)}
.prose li{margin:4px 0}
.prose h2 .ver{font:500 .62em/1 var(--mono);color:var(--blue);border:1px solid currentColor;padding:5px 8px;vertical-align:.3em;margin-right:12px}
.prose h2 time{font:400 14px/1 var(--mono);color:var(--ink3);vertical-align:.5em}
.index{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));border-top:1px solid var(--ink);margin:28px 0 8px}
.index a{display:block;padding:12px 14px 14px 0;border-bottom:1px solid var(--rule2);color:var(--ink);background:none}
.index a:hover b{color:var(--blue)}
.index b{display:block;font:500 14px/1.3 var(--mono);transition:color .15s}
.index span{display:block;color:var(--ink2);font-size:15px;line-height:1.4;margin-top:3px}
.index small{display:block;color:var(--ink3);font:400 12px/1 var(--mono);margin-top:8px}

/* colophon */
.colophon{margin-top:110px;border-top:1px solid var(--rule);padding:28px 0 44px;font-size:15.5px;color:var(--ink2)}
.colophon p{margin:0 0 8px;max-width:760px}
.colophon .brand{font-size:15px;vertical-align:-3px}
.colophon .brand .mark{height:16px}
.colophon a{font-family:var(--mono);font-size:13.5px}
.colophon .set{color:var(--ink3);font-size:14.5px;margin-top:14px}
'''

JS = '''
document.querySelectorAll('[data-open]').forEach(function(b){b.addEventListener('click',function(){
  var d=document.getElementById(b.dataset.open);if(d&&d.showModal){d.showModal();}});});
document.querySelectorAll('dialog').forEach(function(d){
  d.addEventListener('click',function(e){if(e.target===d||e.target.closest('.x'))d.close();});});
document.querySelectorAll('.copy').forEach(function(b){b.addEventListener('click',function(){
  var t=document.getElementById(b.dataset.copy);if(!t||!navigator.clipboard)return;
  var lines=t.querySelectorAll('.ln');var text=lines.length?[].map.call(lines,function(l){return l.textContent;}).join('\\n'):t.innerText;
  navigator.clipboard.writeText(text).then(function(){var o=b.textContent;b.textContent='copied';
  setTimeout(function(){b.textContent=o;},1400);});});});
(function(){var links=[].slice.call(document.querySelectorAll('.contents a[href^="#"]'));if(!links.length||!('IntersectionObserver' in window))return;
  var by={};links.forEach(function(a){by[decodeURIComponent(a.getAttribute('href').slice(1))]=a;});
  var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){
    links.forEach(function(a){a.classList.remove('on');});var a=by[e.target.id];if(a){a.classList.add('on');}}});},
    {rootMargin:'-80px 0px -70% 0px'});
  Object.keys(by).forEach(function(id){var h=document.getElementById(id);if(h)io.observe(h);});})();
'''

INTENT_WORDS = {'collection', 'unique', 'duplicates', 'reject', 'replace', 'each', 'every', 'when', 'where', 'whose',
                'belongs', 'start', 'starts', 'always', 'otherwise', 'if', 'draw', 'write', 'show', 'add', 'remove',
                'find', 'keep', 'increase', 'decrease', 'set', 'becomes', 'expect', 'take', 'return', 'given', 'looks',
                'background', 'board', 'milliseconds', 'seconds', 'pressed'}
TOKEN = re.compile(r'("[^"\n]*")|(\b\d[\d,.]*\b)|([A-Za-z][\w-]*)')


def split_comment(line):
    quoted = False
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == '#' and not quoted and (i == 0 or line[i - 1] in ' \t'):
            return line[:i], line[i:]
    return line, ''


def highlight(code, lang='intent'):
    """Code as HTML with comments, texts, numbers, labels and the words of the language picked out."""
    out = []
    for line in code.split('\n'):
        body, comment = split_comment(line)
        parts, pos = [], 0
        label = re.match(r'^(\s*)([a-z][\w-]*)(:)(?=\s)', body) if lang == 'intent' else None
        if label:
            parts.append(html.escape(label.group(1)) + f'<span class="l">{html.escape(label.group(2))}</span>:')
            pos = label.end()
        if lang == 'shell' and re.match(r'^\s*\$ ', body):
            i = body.index('$')
            parts.append(html.escape(body[:i]) + '<span class="p">$</span>')
            pos = i + 1
        for m in TOKEN.finditer(body, pos):
            parts.append(html.escape(body[pos:m.start()]))
            s, n, w = m.groups()
            if s:
                parts.append(f'<span class="s">{html.escape(s)}</span>')
            elif n:
                parts.append(f'<span class="n">{html.escape(n)}</span>')
            elif lang == 'intent' and w.lower() in INTENT_WORDS:
                parts.append(f'<span class="k">{html.escape(w)}</span>')
            elif lang == 'shell' and w in ('intent', 'printf', 'git', 'cd', 'python3', 'clang'):
                parts.append(f'<span class="k">{html.escape(w)}</span>')
            else:
                parts.append(html.escape(w))
            pos = m.end()
        parts.append(html.escape(body[pos:]))
        if comment:
            parts.append(f'<span class="c">{html.escape(comment)}</span>')
        out.append(''.join(parts))
    # one block per line, so a long sentence wraps under itself with a hanging indent
    return ''.join(f'<span class="ln">{l}</span>' for l in out)


def listing(title, code, lang='intent', link=None, ident=None, note='', raw=False):
    """A numbered listing: its file name above, the code, and a note below if it needs one."""
    a = f'<a href="{link[0]}">{link[1]}</a>' if link else ''
    i = f' id="{ident}"' if ident else ''
    body = code if raw else highlight(code, lang)
    n = f'<p class="note">{note}</p>' if note else ''
    return (f'<figure class="listing"><figcaption>{html.escape(title)}{a}</figcaption>'
            f'<pre><code{i}>{body}</code></pre>{n}</figure>')


def rewrite_links(text, src_dir):
    """Links between repository files point at GitHub, except the pages this site has itself."""
    local = {'docs/language.md': 'guide/', 'CHANGELOG.md': 'changelog/', 'README.md': '', 'examples': 'examples/',
             'examples/': 'examples/', 'examples/art': 'gallery/', 'examples/art/': 'gallery/'}

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
    """Markdown as HTML, with its code highlighted and its tables able to scroll; and its headings."""
    conv = markdown.Markdown(extensions=['fenced_code', 'tables', 'toc'], extension_configs={'toc': {'permalink': False}})
    out = conv.convert(rewrite_links(text, src_dir))

    def code(m):
        lang = m.group(1) or ''
        raw = html.unescape(m.group(2))
        kind = 'shell' if lang in ('bash', 'sh', 'shell', 'console') else 'intent' if lang in ('', 'intent', 'text') else None
        return f'<pre><code>{highlight(raw, kind) if kind else m.group(2)}</code></pre>'
    out = re.sub(r'<pre><code(?: class="language-([\w-]+)")?>(.*?)</code></pre>', code, out, flags=re.S)
    out = out.replace('<table>', '<div class="tbl"><table>').replace('</table>', '</table></div>')
    return out, conv.toc_tokens


def toc_items(tokens, depth):
    out = []
    for t in tokens:
        if t['level'] == 1:                     # the page's own title: its sections are what the reader needs
            out += toc_items(t['children'], depth)
            continue
        kids = toc_items(t['children'], depth - 1) if depth > 1 else []
        out.append(f'<li><a href="#{t["id"]}">{t["name"]}</a>' + (f'<ol>{"".join(kids)}</ol>' if kids else '') + '</li>')
    return out


def doc(content, tokens, depth=2, label='On this page', numbered=False):
    """A reading page: the text, with its contents beside it, following along (folded on a phone)."""
    toc = f'<ol>{"".join(toc_items(tokens, depth))}</ol>'
    short = f'<ol>{"".join(toc_items(tokens, 1))}</ol>'
    mobile = f'<details class="mtoc"><summary>{label}</summary>{short}</details>'
    end = content.find('</h1>')
    if end >= 0:
        content = content[:end + 5] + mobile + content[end + 5:]
    return (f'<div class="doc"><aside class="contents{" counted" if numbered else ""}" aria-label="{label}"><h2>{label}</h2>'
            f'{toc}</aside><article class="prose{" numbered" if numbered else ""}">{content}</article></div>')


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


def chosen():
    """What the planner really builds for the first example, in a few words each; the reason is in the title."""
    from intentc.check import check
    from intentc.parser import parse
    from intentc.plan import make_plan
    prog, diags, p = parse(first_example())
    diags += check(prog, p.src)
    plan = make_plan(prog)
    parts = []
    for title, detail, why in plan.colls['customer'].decisions:
        if title == 'storage':
            name = 'an array'
        elif title.startswith('index on'):
            name = f'a hash index on {title.split()[-1]}'
        elif title.startswith('ordered index on'):
            name = f'a tree on {title.split()[-1]}'
        else:
            continue                # the finer points are for ./intent explain
        reason = f'line {why[0][0]}: {why[0][1]}' if why else detail
        parts.append(f'<b title="{html.escape(reason)}">{html.escape(name)}</b>')
    return ', '.join(parts[:-1]) + ' and ' + parts[-1] if len(parts) > 1 else ''.join(parts)


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
    ('How does it choose data structures?',
     'From what the program asks: a hash index when a unique property is looked up, a balanced tree when it asks '
     'for ranges or orderings, and a removal strategy from whether order matters. Since 0.8.1 it weighs measured '
     'costs, and can plan for a sample of real commands. ./intent explain shows every choice and the line behind it.'),
    ('What can I build with it?',
     'Small data services: customers, shops, to-do lists, leaderboards, orders with order lines. It can also build '
     'terminal and browser games with time, keys, chance and a coloured board, and pictures. Compiled programs can '
     'be served over HTTP and keep a replayable journal.'),
    ('Does it handle money?',
     'Yes. Decimal numbers are kept exactly as whole hundredths, so 0.1 + 0.2 is 0.30. Multiplication and division '
     'round to the nearest cent, halves away from zero.'),
    ('Is it ready for production?',
     'No. It is an experimental research prototype. The language changes between versions, and it is tested on '
     'macOS and Linux only.'),
]


PROPS = [('Deterministic', 'No AI in the compiler. The same sentences always mean the same program.', 'var(--blue)'),
         ('Asks, never guesses', 'An unknown word is an error; a sentence with two readings is a pointed question.',
          'var(--orange)'),
         ('Chooses the data structures', 'Arrays, hash indexes and balanced trees, from what you asked and how it is used.',
          'var(--green)'),
         ('Native, through LLVM IR', 'Straight to LLVM IR and clang, tested against a reference interpreter.',
          'var(--yellow)'),
         ('Money, exactly', 'Decimals are whole hundredths: 0.1 + 0.2 is 0.30, and rounding is explicit.', 'var(--blue)'),
         ('Games, servers, pictures', 'Time, keys and chance; HTTP and windows; grids of records drawn as pictures.',
          'var(--orange)')]

PHRASINGS = ['For every customer, double their age.',
             "Take the customer collection and make everyone's age twice as large.",
             "Customers: increase each person's age to two times its current value.",
             'age = age * 2']


def home(pieces=()):
    props = ''.join(f'<div style="--c:{c}"><dt>{t}</dt><dd>{d}</dd></div>' for t, d, c in PROPS)
    plates = ''.join(f'<a href="{SITE}gallery/#{n}"><span class="frame" style="--paper-of:{paper}">{svg}</span>'
                     f'<span>{n.replace("-", " ")}</span></a>' for n, _, _, _, svg, paper in pieces[:3])
    faq = ''.join(f'<details><summary>{html.escape(q)}</summary><p>{html.escape(a)}</p></details>' for q, a in FAQ)
    try_it = f'''$ git clone {REPO}.git && cd intent
$ ./intent check examples/customers.intent      # how every sentence was read
$ ./intent explain examples/customers.intent    # what it built, and why
$ ./intent build examples/customers.intent -o build/customers
$ printf 'add Alice,20,alice@x.com\\nfind-by-email alice@x.com\\n' | ./build/customers
Alice,20,alice@x.com'''
    question = '''<span class="q">question:</span> is "code" text or a number?
 <span class="c">--></span> shop.intent:1
<span class="c">1 |</span> Each product has a code, a price (money) and a stock.
<span class="c">  |</span> <span class="q">^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^</span> nothing in the program decides this
<span class="c">  =</span> write <span class="s">"code (text)"</span> or <span class="s">"code (number)"</span>'''
    rows = ''.join(f'<tr><td>{html.escape(p)}</td><td><code>update customer: age = age * 2</code></td></tr>'
                   for p in PHRASINGS)
    body = f'''
<section class="hero">
<div>
<p class="kicker">An experimental programming language · version {__version__}</p>
<h1>Write what you <em>mean</em>.<br>Get native code.</h1>
<p class="abstract"><b>Abstract</b>Describe what information exists and what should be possible with it, in plain
English. A deterministic compiler, with no AI inside, chooses the data structures and algorithms and emits LLVM IR
for a native program. When it is unsure, it asks.</p>
<div class="actions"><a class="btn main" href="{REPO}">Get it on GitHub</a><a class="btn" href="{SITE}guide/">Read the guide</a></div>
</div>
<div class="specimen graph">{listing('customers.intent', first_example(),
                                     note=f'The compiler built {chosen()}. Nothing above asked for them.')}</div>
</section>

<div class="numbered">
<h2>Properties</h2>
<dl class="props">{props}</dl>

<h2>Try it in a minute</h2>
<p class="dim">Needs Python 3.10 or later and <code>clang</code>. Nothing to install.</p>
{listing('terminal', try_it, 'shell')}

<h2>It asks instead of guessing</h2>
<p class="dim">Every word is a known concept, filler, or a name the program declared. Anything else stops compilation,
pointing at the words. A sentence that could be read two ways becomes a question, never a coin flip.</p>
{listing('./intent check shop.intent', question, raw=True)}

<h2>Many phrasings, one meaning</h2>
<figure class="table"><div class="tbl"><table><thead><tr><th>Sentence</th><th>Read as</th></tr></thead>
<tbody>{rows}</tbody></table></div><figcaption>Four sentences, one program. <code>./intent check</code> prints the
reading of every sentence, so you can see what it understood.</figcaption></figure>

<h2>It plans for how it is used</h2>
<p class="dim">Nothing in a program names a data structure. The compiler estimates what each choice costs, in steps
measured on native code, and can plan for a sample of real commands with <code>--workload</code>.</p>
<figure class="table"><div class="tbl"><table><thead><tr><th>Records</th><th class="r">Its choice</th>
<th class="r">Hash index only</th><th class="r">No index</th></tr></thead><tbody>
<tr><td>10,000</td><td class="r"><b>0.031</b></td><td class="r">1.566</td><td class="r">2.096</td></tr>
<tr><td>20,000</td><td class="r"><b>0.072</b></td><td class="r">6.694</td><td class="r">8.099</td></tr>
<tr><td>40,000</td><td class="r"><b>0.161</b></td><td class="r">28.275</td><td class="r">34.147</td></tr>
<tr><td>80,000</td><td class="r"><b>0.241</b></td><td class="r">123.558</td><td class="r">155.030</td></tr>
</tbody></table></div><figcaption>Seconds for n adds, then n/10 rounds of a narrow range, a count, the five oldest, a
find and a removal. Its choice is an array, a hash index on email and a balanced tree on age. All three print the
same lines (<code>bench/ordered.py</code>).</figcaption></figure>
<figure class="table"><div class="tbl"><table><thead><tr><th>Workload</th><th class="r">Planned for reads</th>
<th class="r">Planned for churn</th></tr></thead><tbody>
<tr><td>19 reads to each change of every age</td><td class="r"><b>2.82</b></td><td class="r">17.25</td></tr>
<tr><td>a change of every age before each read</td><td class="r">9.44</td><td class="r"><b>7.82</b></td></tr>
</tbody></table></div><figcaption>One program, planned from two small samples of commands, then run on the full
workload of each kind. Each plan wins on the workload it was made for (<code>bench/workload.py</code>).</figcaption></figure>

<h2>A game in 26 sentences</h2>
<div class="two">
<div><p class="dim">Programs can run by themselves: time passes, keys are pressed, and a coloured board is drawn in a
terminal or a browser window. Time, keys and chance are events, so every game can be replayed exactly.</p>
{listing('snake.intent', """Every 120 milliseconds, remove the segments
  whose age is at least the length.
The game is over when any segment's x is the column
  and its y is the row.
Draw each segment at its x and y as a green "o".""")}</div>
<figure class="fig"><img src="{SITE}window-shooter.jpg" width="560" height="350" loading="lazy"
alt="The shooter example written in Intent, running in a browser window">
<figcaption><code>examples/shooter.intent</code>, running in a window of its own.</figcaption></figure>
</div>

<h2>Pictures from sentences</h2>
<p class="dim">A picture is a grid of records, and sentences decide what each one looks like. One sentence makes the
grid; another moves a wave through it.</p>
{listing('ripple.intent', """At the start there is a dot for every x from 1 to 60
  and every y from 1 to 21, whose look is ".".
Every 50 milliseconds, set the look of each dot to "@"
  if the absolute value of (its y minus 11 minus 8 times
  the sine of (its x times 12 plus the phase)) is under 1,
  otherwise ".".""")}
<div class="plates3 graph">{plates}</div>
<p class="small"><a href="{SITE}gallery/">All the plates, each with the program that draws it &#8594;</a></p>

<h2>Questions</h2>
<div class="qa">{faq}</div>
</div>
'''
    ld = [{'@context': 'https://schema.org', '@type': 'SoftwareSourceCode', 'name': NAME,
           'description': DESCRIPTION, 'codeRepository': REPO, 'programmingLanguage': ['Python', 'LLVM IR'],
           'version': __version__, 'dateModified': TODAY, 'keywords': KEYWORDS,
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
    content, tokens = md(text, 'docs')
    return page('guide/', 'Language guide', 'How to write Intent programs: describing information, teaching words, '
                'capabilities, decimals and money, single values, standing rules, time, keys and a board, pictures, '
                'and steering how a program is built.', doc(content, tokens, numbered=True), 'TechArticle')


def changelog():
    with open(os.path.join(ROOT, 'CHANGELOG.md')) as fh:
        text = fh.read()
    content, tokens = md(text)
    # "0.8.1 — 2026-11-11": the version as a tag, the date beside it
    content = re.sub(r'(<h2 id="[^"]*">)([\d.]+) — (\d{4}-\d\d-\d\d)</h2>',
                     r'\1<span class="ver">\2</span><time datetime="\3">\3</time></h2>', content)
    return page('changelog/', 'Changelog', f'What changed in each version of Intent, up to {__version__}.',
                doc(content, tokens, depth=1, label='Versions'), 'TechArticle')


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


def art():
    """The programs in examples/art, each with the picture it draws. How to draw it (after which events, in
    which style) is read from the "./intent svg" line in the program's own header, so the two never disagree."""
    from intentc.check import check
    from intentc.interp import Machine
    from intentc.parser import parse
    from intentc.svg import picture
    out = []
    for path in sorted(glob.glob(os.path.join(ROOT, 'examples', 'art', '*.intent'))):
        name = os.path.splitext(os.path.basename(path))[0]
        with open(path) as fh:
            code = fh.read()
        lines = code.split('\n')
        what = lines[0].lstrip('# ').strip()
        cmd = next((l.lstrip('# ').strip() for l in lines if l.lstrip('# ').startswith('./intent svg')), '')
        args = shlex.split(cmd)[3:]
        opt = {k.lstrip('-'): v for k, v in zip(args[::2], args[1::2])}
        prog, diags, p = parse(code)
        diags += check(prog, p.src)
        bad = [d.msg for d in diags if d.level != 'note']
        if bad:
            raise SystemExit(f'{path}: {bad}')
        m = Machine(prog)
        for c in opt.get('after', '').split(';'):
            if c.strip():
                m.run(c.strip())
        svg = picture(m, opt.get('style', 'glyphs'), opt.get('paper', 'dark'), title=name.replace('-', ' '))
        svg = re.sub(r' width="\d+" height="\d+" role', ' role', svg, count=1)      # let the page size it
        paper = re.search(r'<rect width="[\d.]+" height="[\d.]+" fill="(#[0-9a-fA-F]{6})"', svg).group(1)
        out.append((name, what, cmd, code, svg, paper))
    return out


def gallery(pieces):
    plates, sheets = [], []
    for k, (n, what, cmd, code, svg, paper) in enumerate(pieces, 1):
        title = n.replace('-', ' ')
        plates.append(f'''<figure class="plate" id="{n}">
<button class="frame" style="--paper-of:{paper}" data-open="sheet-{n}" aria-label="{title}: the picture and its program">{svg}</button>
<figcaption><span class="no"></span><h3>{title}</h3><p>{html.escape(what)}</p>
<button class="read" data-open="sheet-{n}">Read the program &#8594;</button></figcaption></figure>''')
        sheets.append(f'''<dialog class="sheet" id="sheet-{n}" aria-labelledby="sheet-{n}-t">
<div class="head"><span>Plate {k:02d}</span><h2 id="sheet-{n}-t">{title}</h2><button class="x">close &#215;</button></div>
<div class="body"><div class="pic" style="--paper-of:{paper}">{svg}</div>
<div class="code"><pre><code id="code-{n}">{highlight(code)}</code></pre>
<div class="tools"><button class="copy" data-copy="code-{n}">copy the program</button>
<a href="{REPO}/blob/main/examples/art/{n}.intent">{n}.intent&#8599;</a><code>{html.escape(cmd)}</code></div></div></div>
</dialog>''')
    make = '''$ ./intent run examples/art/ripple.intent      # play it in a terminal (q stops)
$ ./intent window examples/art/ripple.intent   # or in a window of its own
$ ./intent svg examples/art/ripple.intent --after "wait 500" --style dots -o ripple.svg'''
    body = f'''<section style="padding-top:8px">
<h1>Plates</h1>
<p class="abstract">Pictures drawn by Intent programs. Each is a grid of records: where every dot sits, what character
it is and what colour it has all come from a few sentences with sines, square roots and distances. These are single
frames saved with <code>./intent svg</code>; the same programs animate in a terminal.</p>
</section>
<div class="board graph"><div class="plates">{''.join(plates)}</div></div>
{''.join(sheets)}
<div class="two">
<div><h2>Make your own</h2>
<p class="dim">Styles: <code>glyphs</code> (each cell as its character), <code>dots</code> (a halftone: "." is a small
dot, "@" a full one) and <code>blocks</code>. The guide has the <a href="{SITE}guide/#pictures">sentences that make
pictures</a>: grids from ranges, colours by name or <code>#rrggbb</code>, pictures drawn by hand, words and a
background.</p></div>
<div style="padding-top:80px">{listing('terminal', make, 'shell')}</div>
</div>'''
    ld = [{'@context': 'https://schema.org', '@type': 'ImageObject', 'name': n.replace('-', ' '), 'description': what,
           'contentUrl': f'{SITE}gallery/#{n}', 'creator': {'@type': 'Person', 'name': 'srivtx'}}
          for n, what, _, _, _, _ in pieces]
    return page('gallery/', 'Gallery: pictures drawn in plain English',
                'Generative art written as plain English sentences and compiled to native code: halftone suns, '
                'ripples, orbits and cross-stitch, drawn by Intent programs with sines and square roots.',
                body, 'CollectionPage', ld, wide=True)


def examples():
    found = []
    for path in sorted(glob.glob(os.path.join(ROOT, 'examples', '*.intent'))):
        name = os.path.splitext(os.path.basename(path))[0]
        with open(path) as fh:
            code = fh.read()
        sentences = sum(1 for l in code.split('\n') if l.strip() and not l.lstrip().startswith('#'))
        found.append((name, code, sentences))
    index = ''.join(f'<a href="#{n}"><b>{n}</b><span>{html.escape(EXAMPLE_TEXT.get(n, ""))}</span>'
                    f'<small>{k} lines</small></a>' for n, _, k in found)
    parts = [f'<h1>Examples</h1><p class="abstract">Complete Intent programs from the repository. Each compiles to a '
             f'native executable with <code>./intent build</code>; <code>./intent explain</code> shows what it built.</p>'
             f'<nav class="index" aria-label="Examples">{index}</nav>']
    for n, code, _ in found:
        parts.append(f'<h2 id="{n}">{n}</h2><p class="dim">{html.escape(EXAMPLE_TEXT.get(n, ""))}</p>' +
                     listing(f'examples/{n}.intent', code, link=(f'{REPO}/blob/main/examples/{n}.intent', 'source&#8599;')))
    tokens = [{'level': 2, 'id': n, 'name': n, 'children': []} for n, _, _ in found]
    return page('examples/', 'Example programs', 'Complete programs written in Intent, a plain-English language that '
                'compiles to native code: a shop with money, customers and orders, a to-do list, a leaderboard, and '
                'games such as snake and a shooter.', doc('\n'.join(parts), tokens, label='Examples'), 'CollectionPage')


def missing():
    body = f'''<section style="padding:40px 0 24px;max-width:640px">
<p class="kicker">Error 404</p><h1>No such page.</h1>
<p class="abstract">Like the compiler, this site does not guess what you meant. These pages do exist:</p>
<div class="actions"><a class="btn main" href="{SITE}">Home</a><a class="btn" href="{SITE}guide/">Guide</a>
<a class="btn" href="{SITE}gallery/">Plates</a></div></section>'''
    return page('404', 'Page not found', 'This page does not exist.', body).replace('index, follow', 'noindex')


def write(rel, text):
    p = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as fh:
        fh.write(text)


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    pieces = art()
    pages = {'': home(pieces), 'guide/': guide(), 'gallery/': gallery(pieces), 'examples/': examples(),
             'changelog/': changelog()}
    for path, text in pages.items():
        write(path + 'index.html', text)
    write('404.html', missing())
    for a in ('icon.svg', 'og.png', 'window-shooter.jpg', 'logo-light.svg', 'logo-dark.svg'):
        shutil.copy(os.path.join(ROOT, 'assets', a), os.path.join(OUT, a))
    for f in glob.glob(os.path.join(ROOT, 'site', 'static', '*')):
        shutil.copy(f, os.path.join(OUT, os.path.basename(f)))
    write('.nojekyll', '')
    # IndexNow (Bing, Yandex, Seznam, Naver): the key file proves the site is ours; see site/indexnow.py
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
- [Gallery]({SITE}gallery/): pictures drawn by Intent programs, each with its source
- [Changelog]({SITE}changelog/): what changed in each version
- [Full text for language models]({SITE}llms-full.txt): the README and the guide in one file

## Source

- [GitHub repository]({REPO}): compiler in Python (no dependencies), emits LLVM IR
''')
    write('llms-full.txt', rewrite_links(readme, '.') + '\n\n---\n\n' + rewrite_links(lang, 'docs'))
    print(f'built {len(pages)} pages into {OUT}')


if __name__ == '__main__':
    main()
