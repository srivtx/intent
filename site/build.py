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


def page(path, title, desc, body, kind='WebPage', extra_ld=None, wide=False):
    url = SITE + path
    ld = [{
        '@context': 'https://schema.org', '@type': kind, 'name': title, 'url': url, 'description': desc,
        'inLanguage': 'en', 'isPartOf': {'@type': 'WebSite', 'name': NAME, 'url': SITE},
    }] + (extra_ld or [])
    full = title if title.startswith(NAME) else f'{title} · {NAME}'
    nav = ''.join(f'<a href="{SITE}{p}"{" aria-current=page" if p == path else ""}>{n}</a>' for p, n in NAV)
    links = ''.join(f'<li><a href="{SITE}{p}">{n}</a></li>' for p, n in NAV[1:])
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
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#0c0e13" media="(prefers-color-scheme: dark)">
<meta name="theme-color" content="#fbfaf7" media="(prefers-color-scheme: light)">
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
<header class="top"><div class="wrap bar">
<a class="brand" href="{SITE}" aria-label="Intent, home">intent<span>.</span></a>
<nav aria-label="Site">{nav}<a class="gh" href="{REPO}">GitHub <span aria-hidden="true">↗</span></a></nav>
</div></header>
<main id="main" class="wrap{' wide' if wide else ''}">
{body}
</main>
<footer class="foot"><div class="wrap cols">
<div><a class="brand" href="{SITE}">intent<span>.</span></a>
<p>Plain English in, native code out. A deterministic compiler: no AI inside, and it asks instead of guessing.</p>
<p class="meta">Version {__version__} · experimental research prototype</p></div>
<div><h2>Read</h2><ul>{links}</ul></div>
<div><h2>Elsewhere</h2><ul><li><a href="{REPO}">Source on GitHub</a></li><li><a href="{REPO}/releases">Releases</a></li>
<li><a href="{SITE}llms.txt">llms.txt</a></li><li><a href="{SITE}sitemap.xml">Sitemap</a></li></ul></div>
</div></footer>
<script>{JS}</script>
</body>
</html>
'''


CSS = '''
:root{
  --bg:#fbfaf7;--surface:#ffffff;--sunk:#f4f2ec;--fg:#16181d;--dim:#565c68;--faint:#8b909a;--line:#e7e3d9;
  --accent:#b45309;--amber:#f59e0b;--soft:#fdf3e1;--ok:#047857;--shadow:0 1px 2px rgba(22,24,29,.05),0 8px 28px rgba(22,24,29,.07);
  --c-com:#8b909a;--c-str:#0f766e;--c-num:#9a3412;--c-key:#6d28d9;--c-lab:#b45309;
  --serif:"Iowan Old Style","Charter","Palatino Linotype","Book Antiqua",Georgia,serif;
  --sans:ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0c0e13;--surface:#13161d;--sunk:#0f1218;--fg:#eceef2;--dim:#a3a9b5;--faint:#6f7683;--line:#242934;
  --accent:#fbbf24;--soft:#2a2112;--ok:#34d399;--shadow:0 1px 2px rgba(0,0,0,.4),0 10px 30px rgba(0,0,0,.35);
  --c-com:#6f7683;--c-str:#5eead4;--c-num:#fdba74;--c-key:#c4b5fd;--c-lab:#fbbf24;
}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-padding-top:76px}
body{margin:0;overflow-x:clip;background:var(--bg);color:var(--fg);font:17px/1.65 var(--sans);text-rendering:optimizeLegibility}
.wrap{max-width:1120px;margin:0 auto;padding:0 20px}
@media (max-width:600px){.wrap{padding:0 16px}}
a{color:var(--accent);text-underline-offset:3px;text-decoration-thickness:1px}
a:hover{text-decoration-thickness:2px}
:focus-visible{outline:2px solid var(--amber);outline-offset:2px;border-radius:4px}
img,svg{max-width:100%}
img{height:auto}
.skip{position:absolute;left:-999px;top:8px;background:var(--fg);color:var(--bg);padding:8px 12px;border-radius:8px;z-index:9}
.skip:focus{left:8px}

/* header */
.top{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--bg) 82%,transparent);
  -webkit-backdrop-filter:saturate(1.4) blur(12px);backdrop-filter:saturate(1.4) blur(12px);border-bottom:1px solid var(--line)}
.bar{display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:60px}
.brand{font:800 25px/1 var(--sans);letter-spacing:-1.2px;color:var(--fg);text-decoration:none}
.brand span{color:var(--amber)}
nav{display:flex;align-items:center;gap:2px;overflow-x:auto;scrollbar-width:none}
nav::-webkit-scrollbar{display:none}
nav a{color:var(--dim);text-decoration:none;font-size:15px;padding:6px 11px;border-radius:999px;white-space:nowrap}
nav a:hover{color:var(--fg);background:var(--sunk)}
nav a[aria-current]{color:var(--fg);background:var(--sunk);font-weight:600}
nav .gh{margin-left:6px;border:1px solid var(--line)}
@media (max-width:640px){.bar{flex-direction:column;align-items:flex-start;gap:4px;padding-top:10px;padding-bottom:8px}
  nav{width:100%;max-width:100%}nav a{padding:6px 9px}nav .gh{margin-left:auto}}

/* type */
h1,h2,h3{color:var(--fg);text-wrap:balance}
h1{font:600 clamp(38px,6.4vw,64px)/1.04 var(--serif);letter-spacing:-1.6px;margin:56px 0 16px}
h2{font:600 clamp(26px,3.4vw,34px)/1.15 var(--serif);letter-spacing:-.6px;margin:72px 0 12px}
h3{font:650 18px/1.3 var(--sans);letter-spacing:-.2px;margin:28px 0 6px}
p,li{text-wrap:pretty}
.lede{font-size:clamp(18px,2vw,21px);line-height:1.55;color:var(--dim);max-width:640px;margin:0 0 8px}
.eyebrow{font:600 12.5px/1 var(--sans);letter-spacing:.12em;text-transform:uppercase;color:var(--accent);margin:0 0 12px}
.dim{color:var(--dim)}

/* code */
pre,code,kbd{font-family:var(--mono)}
pre{font-size:14px;line-height:1.6;background:var(--sunk);border:1px solid var(--line);border-radius:12px;padding:16px 18px;
  overflow-x:auto;margin:16px 0;tab-size:2}
:not(pre)>code{font-size:.86em;background:var(--sunk);border:1px solid var(--line);padding:1px 5px;border-radius:6px}
.c{color:var(--c-com);font-style:italic}.s{color:var(--c-str)}.n{color:var(--c-num)}.k{color:var(--c-key)}.l{color:var(--c-lab);font-weight:600}
.p{color:var(--faint);user-select:none}
.win{background:var(--surface);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);overflow:hidden;margin:16px 0}
.win>.title{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--line);
  font:500 13px/1 var(--mono);color:var(--dim);background:var(--sunk)}
.win>.title i{width:10px;height:10px;border-radius:50%;background:var(--line);display:inline-block}
.win>.title i:first-child{margin-left:0}
.win>.title b{font-weight:500;margin-left:6px}
.win>.title a{margin-left:auto;font-family:var(--sans);font-size:13px}
.win pre{margin:0;border:0;border-radius:0;background:transparent}
.term pre{background:#0c0e13;color:#e6e8ec}
.term{border-color:#20242d}
.term>.title{background:#151820;border-color:#20242d;color:#8b909a}
.term .c{color:#6f7683}.term .q{color:#fbbf24;font-weight:600}.term .ok{color:#34d399}.term .k{color:#c4b5fd}
.term .s{color:#5eead4}.term .n{color:#fdba74}

/* tables */
.tbl{overflow-x:auto;margin:16px 0;border:1px solid var(--line);border-radius:12px;background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:15px}
th,td{padding:9px 14px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}
tr:last-child td{border-bottom:0}
th{font-weight:600;background:var(--sunk);font-size:13px;letter-spacing:.02em;color:var(--dim)}
td code{white-space:nowrap}

/* buttons */
.cta{display:flex;gap:10px;flex-wrap:wrap;margin:28px 0 0}
.btn{display:inline-flex;align-items:center;gap:8px;padding:11px 18px;border-radius:10px;border:1px solid var(--line);
  text-decoration:none;color:var(--fg);font-weight:600;font-size:15.5px;background:var(--surface);transition:transform .15s,box-shadow .15s}
.btn:hover{transform:translateY(-1px);box-shadow:var(--shadow);text-decoration:none}
.btn.main{background:var(--fg);color:var(--bg);border-color:var(--fg)}

/* home */
.hero{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);gap:48px;align-items:center;padding:24px 0 8px}
.hero h1{margin-top:28px}
.hero h1 em{font-style:italic;color:var(--accent)}
.badges{display:flex;flex-wrap:wrap;gap:8px;margin:22px 0 0;padding:0;list-style:none;min-width:0}
.badges li{font-size:13px;color:var(--dim);border:1px solid var(--line);border-radius:999px;padding:4px 10px;background:var(--surface)}
.badges li::before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--ok);margin-right:7px;vertical-align:middle}
.chose{padding:6px 0 4px}
.chose div{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;padding:10px 16px;border-top:1px solid var(--line);font-size:14px}
.chose div:first-child{border-top:0}
.chose b{font-weight:650}
.chose span{color:var(--dim);grid-column:2}
.chose .ic{grid-column:1;grid-row:1/span 3}
.chose em{font-style:normal;font:12px/1.4 var(--mono);color:var(--faint);grid-column:2}
.chose .ic{width:30px;height:30px;border-radius:8px;background:var(--soft);color:var(--accent);
  display:grid;place-items:center;font:700 13px/1 var(--mono)}
@media (max-width:900px){.hero{grid-template-columns:minmax(0,1fr);gap:8px}}
.feats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);
  border-radius:16px;overflow:hidden;margin:28px 0}
.feats div{background:var(--surface);padding:22px 22px 24px}
.feats h3{margin:0 0 6px;font-size:16.5px}
.feats p{margin:0;color:var(--dim);font-size:15px;line-height:1.55}
.feats .num{font:600 12px/1 var(--mono);color:var(--accent);display:block;margin-bottom:12px}
@media (max-width:900px){.feats{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:560px){.feats{grid-template-columns:minmax(0,1fr)}}
.split{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:40px;align-items:center}
.split.start{align-items:start}
@media (max-width:860px){.split{grid-template-columns:minmax(0,1fr);gap:8px}}
.same{list-style:none;padding:0;margin:16px 0;display:grid;gap:8px}
.same li{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 14px;font-size:15.5px;position:relative}
.same li::after{content:"→";position:absolute;right:14px;color:var(--faint)}
.canon{background:var(--soft);border:1px solid color-mix(in srgb,var(--accent) 35%,transparent);border-radius:12px;padding:18px 20px}
.canon code{background:transparent;border:0;font-size:15px;color:var(--fg)}
.canon p{margin:0 0 6px;color:var(--dim);font-size:14px}
.shot{border-radius:14px;border:1px solid var(--line);box-shadow:var(--shadow);display:block}
.numbers{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin:20px 0}
.numbers div{border:1px solid var(--line);border-radius:14px;padding:18px 20px;background:var(--surface)}
.numbers b{display:block;font:600 34px/1.1 var(--serif);letter-spacing:-.5px}
.numbers span{color:var(--dim);font-size:14.5px}
@media (max-width:560px){.numbers{grid-template-columns:minmax(0,1fr)}}
.faq details{border-bottom:1px solid var(--line);padding:4px 0}
.faq summary{list-style:none;cursor:pointer;font-weight:600;padding:12px 32px 12px 0;position:relative}
.faq summary::-webkit-details-marker{display:none}
.faq summary::after{content:"+";position:absolute;right:4px;top:8px;font:400 22px/1 var(--sans);color:var(--faint);transition:transform .2s}
.faq details[open] summary::after{transform:rotate(45deg)}
.faq details p{margin:0 0 14px;color:var(--dim);max-width:760px}
.band{margin:72px 0 0;padding:36px;border:1px solid var(--line);border-radius:20px;background:
  radial-gradient(circle at 1px 1px,color-mix(in srgb,var(--faint) 28%,transparent) 1px,transparent 0) 0 0/14px 14px,var(--surface);
  display:flex;align-items:center;justify-content:space-between;gap:24px;flex-wrap:wrap}
.band h2{margin:0 0 4px;font-size:28px}
.band p{margin:0;color:var(--dim)}

/* pictures: every frame the same shape, filled with the picture's own paper */
.tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:22px;margin:28px 0}
@media (max-width:900px){.tiles{grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}}
@media (max-width:540px){.tiles{grid-template-columns:minmax(0,1fr)}}
.tile{margin:0;display:flex;flex-direction:column;background:var(--surface);border:1px solid var(--line);border-radius:16px;
  overflow:hidden;transition:transform .2s,box-shadow .2s}
.tile:hover{transform:translateY(-3px);box-shadow:var(--shadow)}
.tile:target{outline:2px solid var(--amber);outline-offset:3px}
.frame{position:relative;display:block;aspect-ratio:4/3;background:var(--paper,#0d0f14);padding:0;border:0;width:100%;
  overflow:hidden;cursor:pointer;color:inherit;font:inherit}
a.frame{text-decoration:none}
.frame svg{position:absolute;inset:0;display:block;width:100%;height:100%;transition:transform .35s}
.frame:hover svg{transform:scale(1.03)}
.tile figcaption{padding:14px 18px 16px;display:flex;flex-direction:column;gap:4px;flex:1}
.tile h3{margin:0;font-size:17px;text-transform:capitalize}
.tile p{margin:0;color:var(--dim);font-size:14.5px;line-height:1.5;flex:1}
.linkbtn{all:unset;cursor:pointer;color:var(--accent);font-weight:600;font-size:14.5px;margin-top:8px;align-self:flex-start}
.linkbtn:hover{text-decoration:underline}
.linkbtn:focus-visible{outline:2px solid var(--amber);outline-offset:2px;border-radius:4px}
.strip{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:20px 0}
.strip .frame{border-radius:14px;border:1px solid var(--line);overflow:hidden;transition:transform .2s,box-shadow .2s}
.strip .frame:hover{transform:translateY(-3px);box-shadow:var(--shadow)}
@media (max-width:640px){.strip{grid-template-columns:1fr 1fr}.strip .frame:nth-child(3){display:none}}
dialog.sheet{border:1px solid var(--line);border-radius:18px;padding:0;background:var(--surface);color:var(--fg);
  width:min(1040px,calc(100vw - 32px));max-height:calc(100vh - 48px);box-shadow:0 30px 80px rgba(0,0,0,.35)}
dialog.sheet::backdrop{background:rgba(12,14,19,.6);-webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px)}
.sheet .head{display:flex;align-items:center;gap:12px;padding:14px 18px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--surface);z-index:1}
.sheet .head h2{margin:0;font:600 22px/1.2 var(--serif);text-transform:capitalize}
.sheet .head .x{margin-left:auto;all:unset;cursor:pointer;width:34px;height:34px;display:grid;place-items:center;border-radius:9px;margin-left:auto;font-size:20px;color:var(--dim)}
.sheet .head .x:hover{background:var(--sunk);color:var(--fg)}
.sheet .body{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.1fr);gap:0}
.sheet .pic{background:var(--paper);display:grid;place-items:center;padding:20px}
.sheet .pic svg{width:100%;height:auto;max-height:70vh}
.sheet .code{padding:16px 18px;min-width:0}
.sheet .code pre{margin:0 0 12px;font-size:12.5px;max-height:52vh}
.sheet .tools{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:14px}
.sheet .tools code{white-space:normal}
@media (max-width:760px){.sheet .body{grid-template-columns:minmax(0,1fr)}.sheet .code pre{max-height:none}}
.copy{all:unset;cursor:pointer;font:600 13px/1 var(--sans);padding:7px 11px;border-radius:8px;border:1px solid var(--line);color:var(--fg)}
.copy:hover{background:var(--sunk)}

/* reading pages: a table of contents beside the text */
.doc{display:grid;grid-template-columns:220px minmax(0,1fr);gap:56px;align-items:start}
.doc>aside{position:sticky;top:84px;max-height:calc(100vh - 100px);overflow:auto;padding:28px 0 24px;font-size:14px;scrollbar-width:thin}
.doc>aside h2{font:600 12px/1 var(--sans);letter-spacing:.12em;text-transform:uppercase;color:var(--faint);margin:0 0 12px}
.doc>aside ol{list-style:none;margin:0;padding:0;border-left:1px solid var(--line)}
.doc>aside li a{display:block;padding:5px 0 5px 14px;margin-left:-1px;border-left:2px solid transparent;color:var(--dim);text-decoration:none;line-height:1.35}
.doc>aside li a:hover{color:var(--fg)}
.doc>aside li a.on{color:var(--fg);border-left-color:var(--amber);font-weight:600}
.doc>aside li li a{padding-left:26px;font-size:13.5px}
.mtoc{display:none;margin:12px 0 0;border:1px solid var(--line);border-radius:12px;background:var(--surface);padding:4px 16px}
.mtoc summary{cursor:pointer;font-weight:600;padding:10px 0}
.mtoc ol{margin:0 0 12px;padding-left:18px;font-size:15px}
@media (max-width:960px){.doc{grid-template-columns:minmax(0,1fr);gap:0}.doc>aside{display:none}.mtoc{display:block}}
.prose{max-width:760px;min-width:0;padding-bottom:24px}
.prose h1{margin-top:40px}
.prose h2{padding-top:28px;margin-top:56px;border-top:1px solid var(--line)}
.prose h2:first-of-type{border-top:0}
.prose h3{margin-top:32px}
.prose blockquote{margin:20px 0;padding:14px 18px;border:1px solid color-mix(in srgb,var(--accent) 30%,transparent);
  background:var(--soft);border-radius:12px;color:var(--fg)}
.prose blockquote p{margin:0}
.prose img{max-width:100%;height:auto;border-radius:12px}
.prose h2 .ver{font:600 .78em/1 var(--mono);background:var(--soft);color:var(--accent);padding:6px 10px;border-radius:9px;
  border:1px solid color-mix(in srgb,var(--accent) 30%,transparent);vertical-align:3px}
.prose h2 time{font:500 15px/1 var(--sans);color:var(--faint);margin-left:12px;letter-spacing:0;vertical-align:5px}
.prose h3+ul{margin-top:4px}
.prose li{margin:4px 0}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;margin:24px 0 8px}
.cards a{display:block;border:1px solid var(--line);border-radius:12px;padding:14px 16px;text-decoration:none;color:var(--fg);
  background:var(--surface);transition:transform .15s,box-shadow .15s}
.cards a:hover{transform:translateY(-2px);box-shadow:var(--shadow)}
.cards b{display:block;font:600 14.5px/1.3 var(--mono)}
.cards span{display:block;color:var(--dim);font-size:14px;line-height:1.45;margin-top:4px}
.cards small{display:block;color:var(--faint);font-size:12.5px;margin-top:8px}

/* footer */
.foot{margin-top:96px;border-top:1px solid var(--line);background:var(--sunk)}
.foot .cols{display:grid;grid-template-columns:2fr 1fr 1fr;gap:32px;padding-top:40px;padding-bottom:48px}
.foot p{color:var(--dim);font-size:14.5px;max-width:360px;margin:12px 0 0}
.foot .meta{font-size:13px;color:var(--faint)}
.foot h2{font:600 12px/1 var(--sans);letter-spacing:.12em;text-transform:uppercase;color:var(--faint);margin:6px 0 14px;border:0;padding:0}
.foot ul{list-style:none;margin:0;padding:0;display:grid;gap:8px;font-size:14.5px}
.foot a{color:var(--dim);text-decoration:none}.foot a:hover{color:var(--fg)}
.foot .brand{color:var(--fg)}
@media (max-width:640px){.foot .cols{grid-template-columns:1fr 1fr}.foot .cols>div:first-child{grid-column:1/-1}}
@media (prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
'''

JS = '''
document.querySelectorAll('[data-open]').forEach(function(b){b.addEventListener('click',function(){
  var d=document.getElementById(b.dataset.open);if(d&&d.showModal){d.showModal();}});});
document.querySelectorAll('dialog').forEach(function(d){
  d.addEventListener('click',function(e){if(e.target===d||e.target.closest('.x'))d.close();});});
document.querySelectorAll('.copy').forEach(function(b){b.addEventListener('click',function(){
  var t=document.getElementById(b.dataset.copy);if(!t||!navigator.clipboard)return;
  navigator.clipboard.writeText(t.innerText).then(function(){var o=b.textContent;b.textContent='Copied';
  setTimeout(function(){b.textContent=o;},1400);});});});
(function(){var links=[].slice.call(document.querySelectorAll('.doc>aside a[href^="#"]'));if(!links.length||!('IntersectionObserver' in window))return;
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
    return '\n'.join(out)


def window(title, code, lang='intent', link=None, term=False, ident=None):
    """A code block dressed as a window, with its file name (and a link) in the title bar."""
    a = f'<a href="{link[0]}">{link[1]}</a>' if link else ''
    i = f' id="{ident}"' if ident else ''
    return (f'<div class="win{" term" if term else ""}"><div class="title"><i></i><i></i><i></i><b>{html.escape(title)}</b>{a}</div>'
            f'<pre><code{i}>{highlight(code, lang)}</code></pre></div>')


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


def doc(content, tokens, depth=2, label='On this page'):
    """A reading page: the text, with a table of contents that follows along beside it (folded on a phone)."""
    toc = f'<ol>{"".join(toc_items(tokens, depth))}</ol>'
    short = f'<ol>{"".join(toc_items(tokens, 1))}</ol>'
    mobile = f'<details class="mtoc"><summary>{label}</summary>{short}</details>'
    end = content.find('</h1>')
    if end >= 0:
        content = content[:end + 5] + mobile + content[end + 5:]
    return (f'<div class="doc"><aside aria-label="{label}"><h2>{label}</h2>{toc}</aside>'
            f'<article class="prose">{content}</article></div>')


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
    """What the planner really builds for the first example, said briefly, with the line that caused it."""
    from intentc.check import check
    from intentc.parser import parse
    from intentc.plan import make_plan
    prog, diags, p = parse(first_example())
    diags += check(prog, p.src)
    plan = make_plan(prog)
    rows = []
    marks = {'storage': '[]', 'index on': '#', 'ordered index on': '⌥', 'removal': '↯'}
    names = {'storage': 'A growable array', 'removal swaps in the last row': 'Removal swaps in the last row'}
    for title, detail, why in plan.colls['customer'].decisions:
        if title.startswith('no '):
            continue
        mark = next((v for k, v in marks.items() if title.startswith(k)), '•')
        if title.startswith('ordered index on'):
            name, say = f'A balanced tree on {title.split()[-1]}', 'ranges and orderings without sorting'
        elif title.startswith('index on'):
            name, say = f'A hash index on {title.split()[-1]}', 'one probe finds a customer'
        else:
            name, say = names.get(title, title.capitalize()), detail.split(',')[0].split(';')[0]
        because = f'line {why[0][0]}: {why[0][1]}' if why else 'every program starts here'
        rows.append(f'<div><span class="ic" aria-hidden="true">{html.escape(mark)}</span><b>{html.escape(name)}</b>'
                    f'<span>{html.escape(say)}</span><em>{html.escape(because)}</em></div>')
    return ''.join(rows)


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


def home(pieces=()):
    feats = [('Deterministic', 'No AI in the compiler. The same sentences always mean the same program.'),
             ('Asks, never guesses', 'Unknown words are errors; a sentence with two readings becomes a pointed question.'),
             ('Chooses the data structures', 'Arrays, hash indexes and balanced trees, chosen from what you asked and '
                                             'how you use it, with the reasons shown.'),
             ('Native, through LLVM IR', 'Straight to LLVM IR and clang, tested against a reference interpreter on '
                                         'random commands.'),
             ('Money, exactly', 'Decimals kept as whole hundredths: 0.1 + 0.2 is 0.30, and rounding is explicit.'),
             ('Games, servers, pictures', 'Time, keys, chance and a board; HTTP and windows; sines and grids of '
                                          'records drawn as art.')]
    cards = ''.join(f'<div><span class="num">0{i + 1}</span><h3>{t}</h3><p>{d}</p></div>' for i, (t, d) in enumerate(feats))
    strip = ''.join(f'<a class="frame" style="--paper:{paper}" href="{SITE}gallery/#{n}" aria-label="{n.replace("-", " ")}, '
                    f'in the gallery">{svg}</a>' for n, _, _, _, svg, paper in pieces[:3])
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
    body = f'''
<section class="hero">
<div>
<h1>Write what you <em>mean</em>.<br>Get native code.</h1>
<p class="lede">Intent is an experimental programming language in plain English. You describe what information exists
and what should be possible with it. A deterministic compiler works out the data structures and algorithms and emits
<strong>LLVM IR</strong> for a native program.</p>
<div class="cta"><a class="btn main" href="{REPO}">Get it on GitHub</a><a class="btn" href="{SITE}guide/">Read the guide</a>
<a class="btn" href="{SITE}gallery/">See the gallery</a></div>
<ul class="badges"><li>No AI in the compiler</li><li>LLVM IR, then clang</li><li>Version {__version__}</li></ul>
</div>
<div>
{window('customers.intent', first_example())}
<div class="win"><div class="title"><i></i><i></i><i></i><b>./intent explain customers.intent</b></div>
<div class="chose">{chosen()}</div></div>
</div>
</section>

<div class="feats">{cards}</div>

<h2>Try it in a minute</h2>
<p class="dim">Needs Python 3.10+ and <code>clang</code>. Nothing to install.</p>
<div class="win term"><div class="title"><i></i><i></i><i></i><b>terminal</b></div><pre><code>{highlight(try_it, 'shell')}</code></pre></div>

<h2>It asks instead of guessing</h2>
<p class="lede">Every word is a known concept, filler, or a name your program declared. Anything else stops
compilation, pointing at the words. A sentence that could be read two ways is a question, never a coin flip.</p>
<div class="win term"><div class="title"><i></i><i></i><i></i><b>./intent check shop.intent</b></div><pre><code>{question}</code></pre></div>

<div class="split">
<div><h2>Many phrasings, one meaning</h2>
<p>All of these compile to the identical program. <code>./intent check</code> shows the reading of every sentence,
so you can see what it understood.</p>
<div class="canon"><p>Each one means</p><code>update customer: age = age * 2</code></div></div>
<ul class="same"><li>For every customer, double their age.</li><li>Take the customer collection and make everyone's age twice as large.</li>
<li>Customers: increase each person's age to two times its current value.</li><li>age = age * 2</li></ul>
</div>

<h2>It plans for how you use it</h2>
<p class="lede">Nothing in a program names a data structure. The compiler estimates what each choice costs, in steps
measured on native code, and can plan for a sample of real commands with <code>--workload</code>.</p>
<div class="numbers"><div><b>500×</b><span>faster ranges and orderings with the balanced tree it chose, at 80,000
records (0.24 s against 124 s)</span></div>
<div><b>2 plans</b><span>one program, two samples of commands: each plan wins on the workload it was made for</span></div></div>

<div class="split start">
<div><h2>A game in 26 sentences</h2>
<p>Programs can run by themselves: time passes, keys are pressed, and a coloured board is drawn in a terminal or a
browser window. Time, keys and chance are events, so every game can be replayed exactly.</p>
{window('snake.intent', """Every 120 milliseconds, remove the segments whose age is at least the length.
The game is over when any segment's x is the column and its y is the row.
Draw each segment at its x and y as a green "o".""")}</div>
<div><h2 style="visibility:hidden" aria-hidden="true">&nbsp;</h2>
<img class="shot" src="{SITE}window-shooter.jpg" width="560" height="350" alt="The shooter example written in Intent, running in a browser window" loading="lazy"></div>
</div>

<h2>Draw with sentences</h2>
<p>A picture is a grid of records, and sentences decide what each one looks like. One sentence makes the grid:</p>
{window('ripple.intent', """At the start there is a dot for every x from 1 to 60 and every y from 1 to 21, whose look is ".".
Every 50 milliseconds, set the look of each dot to "@" if the absolute value of
  (its y minus 11 minus 8 times the sine of (its x times 12 plus the phase)) is under 1, otherwise ".".""")}
<div class="strip">{strip}</div>

<section class="band"><div><h2>Every picture comes with its program</h2><p>Halftones, cross-stitch, orbits and posters,
each drawn by a few English sentences.</p></div><a class="btn main" href="{SITE}gallery/">Open the gallery</a></section>

<h2>Questions</h2>
<div class="faq">{faq}</div>
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
                'and steering how a program is built.', doc(content, tokens), 'TechArticle')


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
    tiles, sheets = [], []
    for n, what, cmd, code, svg, paper in pieces:
        title = n.replace('-', ' ')
        tiles.append(f'''<figure class="tile" id="{n}">
<button class="frame" style="--paper:{paper}" data-open="sheet-{n}" aria-label="{title}: open the picture and its program">{svg}</button>
<figcaption><h3>{title}</h3><p>{html.escape(what)}</p>
<button class="linkbtn" data-open="sheet-{n}">The program →</button></figcaption></figure>''')
        sheets.append(f'''<dialog class="sheet" id="sheet-{n}" aria-labelledby="sheet-{n}-t">
<div class="head"><h2 id="sheet-{n}-t">{title}</h2><button class="x" aria-label="Close">×</button></div>
<div class="body"><div class="pic" style="--paper:{paper}">{svg}</div>
<div class="code"><pre><code id="code-{n}">{highlight(code)}</code></pre>
<div class="tools"><button class="copy" data-copy="code-{n}">Copy the program</button>
<a href="{REPO}/blob/main/examples/art/{n}.intent">{n}.intent on GitHub ↗</a></div>
<p class="dim" style="font-size:13.5px;margin:12px 0 0">Saved with <code>{html.escape(cmd)}</code></p></div></div>
</dialog>''')
    make = '''$ ./intent run examples/art/ripple.intent      # play it in a terminal (q stops)
$ ./intent window examples/art/ripple.intent   # or in a window of its own
$ ./intent svg examples/art/ripple.intent --after "wait 500" --style dots -o ripple.svg'''
    body = f'''<p class="eyebrow" style="margin-top:48px">Gallery</p>
<h1 style="margin-top:0">Pictures drawn in plain English</h1>
<p class="lede">Each picture is a grid of records. Where every dot sits, what character it is and what colour it has
all come from a few sentences with sines, square roots and distances. The same programs animate in a terminal;
these are single frames saved with <code>./intent svg</code>. Open any of them to read the program that draws it.</p>
<div class="tiles">{''.join(tiles)}</div>
{''.join(sheets)}
<div class="split start">
<div><h2>Make your own</h2>
<p>Styles: <code>glyphs</code> (each cell as its character), <code>dots</code> (a halftone: "." is a small dot,
"@" a full one) and <code>blocks</code>. The language guide has the
<a href="{SITE}guide/#pictures">sentences that make pictures</a>: grids from ranges, colours by name or
<code>#rrggbb</code>, pictures drawn by hand, words and a background.</p></div>
<div><h2 style="visibility:hidden" aria-hidden="true">&nbsp;</h2>
<div class="win term"><div class="title"><i></i><i></i><i></i><b>terminal</b></div><pre><code>{highlight(make, 'shell')}</code></pre></div></div>
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
    cards = ''.join(f'<a href="#{n}"><b>{n}</b><span>{html.escape(EXAMPLE_TEXT.get(n, ""))}</span>'
                    f'<small>{k} lines of English</small></a>' for n, _, k in found)
    parts = [f'<h1>Example programs</h1><p class="lede">Complete Intent programs from the repository. Each one compiles '
             f'to a native executable with <code>./intent build</code>, and <code>./intent explain</code> shows what '
             f'it built.</p><div class="cards">{cards}</div>']
    for n, code, _ in found:
        parts.append(f'<h2 id="{n}">{n}</h2><p class="dim">{html.escape(EXAMPLE_TEXT.get(n, ""))}</p>' +
                     window(f'examples/{n}.intent', code, link=(f'{REPO}/blob/main/examples/{n}.intent', 'Source ↗')))
    tokens = [{'level': 2, 'id': n, 'name': n, 'children': []} for n, _, _ in found]
    return page('examples/', 'Example programs', 'Complete programs written in Intent, a plain-English language that '
                'compiles to native code: a shop with money, customers and orders, a to-do list, a leaderboard, and '
                'games such as snake and a shooter.', doc('\n'.join(parts), tokens, label='Examples'), 'CollectionPage')


def missing():
    body = f'''<section style="padding:64px 0 24px;max-width:640px">
<p class="eyebrow">404</p><h1 style="margin-top:0">I don't know that page.</h1>
<p class="lede">Like the compiler, this site doesn't guess. Try one of these instead:</p>
<div class="cta"><a class="btn main" href="{SITE}">Home</a><a class="btn" href="{SITE}guide/">The guide</a>
<a class="btn" href="{SITE}gallery/">The gallery</a></div></section>'''
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
