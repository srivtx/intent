"""Tell IndexNow search engines (Bing, Yandex, Seznam, Naver) that the site's pages changed.

    python3 site/indexnow.py        # after a deploy; reads the URLs from _site/sitemap.xml
"""
import glob
import json
import os
import re
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
HOST = 'intent.srivtx.xyz'


def main():
    key = os.path.splitext(os.path.basename(glob.glob(os.path.join(HERE, 'static', '*.txt'))[0]))[0]
    with open(os.path.join(HERE, '..', '_site', 'sitemap.xml')) as fh:
        urls = re.findall(r'<loc>([^<]+)</loc>', fh.read())
    body = json.dumps({'host': HOST, 'key': key, 'keyLocation': f'https://{HOST}/{key}.txt', 'urlList': urls}).encode()
    req = urllib.request.Request('https://api.indexnow.org/indexnow', body,
                                 {'Content-Type': 'application/json; charset=utf-8'})
    with urllib.request.urlopen(req, timeout=30) as r:
        print(r.status, 'submitted', len(urls), 'urls')


if __name__ == '__main__':
    main()
