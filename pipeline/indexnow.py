"""Tell IndexNow search engines (Bing, Yandex, Seznam, Naver; Bing feeds
DuckDuckGo and ChatGPT search) about every URL in the live sitemap.

Usage: python3 -I pipeline/indexnow.py https://nowacceptingpatients.com
"""
import json
import re
import sys
import urllib.parse
import urllib.request

KEY = "45f44ddf0396434f20b673af40391760"  # also served at /<KEY>.txt (static/)


def main():
    site = sys.argv[1].rstrip("/")
    with urllib.request.urlopen(f"{site}/sitemap.xml", timeout=60) as r:
        urls = re.findall(r"<loc>(.*?)</loc>", r.read().decode())
    host = urllib.parse.urlparse(site).netloc
    for i in range(0, len(urls), 10000):
        body = json.dumps({"host": host, "key": KEY, "keyLocation": f"{site}/{KEY}.txt", "urlList": urls[i:i + 10000]}).encode()
        req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body,
                                     headers={"Content-Type": "application/json; charset=utf-8"})
        with urllib.request.urlopen(req, timeout=60) as r:
            print(f"IndexNow: submitted {len(urls[i:i + 10000])} URLs, HTTP {r.status}")


if __name__ == "__main__":
    main()
