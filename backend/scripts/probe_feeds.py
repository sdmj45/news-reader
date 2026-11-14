"""Probes candidate feed URLs and reports what actually responded.

Run before adding anything to the registry. Prints one line per URL: status, bytes, entry
count, and the number of entries that carried a description. Nothing is written anywhere -
the registry is edited by hand from this output, so every entry has a measurement behind it.

    python -I scripts/probe_feeds.py [url ...]
"""

from __future__ import annotations

import asyncio
import sys

import feedparser
import httpx

CANDIDATES = [
    # France
    "https://www.lemonde.fr/rss/une.xml",
    "https://www.lemonde.fr/international/rss_full.xml",
    "https://www.francetvinfo.fr/titres.rss",
    "https://www.franceinfo.fr/titres.rss",
    "https://www.lefigaro.fr/rss/figaro_actualites.xml",
    "https://www.liberation.fr/arc/outboundfeeds/collection/accueil-une/?outputType=xml",
    "https://www.france24.com/fr/rss",
    "https://www.rfi.fr/fr/france/rss",
    "https://theconversation.com/fr/articles.atom",
    # Europe / institutions
    "https://ec.europa.eu/commission/presscorner/api/rss?language=en",
    "https://www.europarl.europa.eu/rss/doc/top-stories/en.xml",
    "https://www.consilium.europa.eu/en/press/press-releases/rss.xml",
    # International, English
    "https://feeds.bbci.co.uk/news/rss.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://rss.dw.com/rdf/rss-en-all",
    "https://rss.dw.com/xml/rss-fr-all",
    "https://www.theguardian.com/world/rss",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://apnews.com/apf-topnews",
    "https://feeds.npr.org/1001/rss.xml",
    "https://www.reutersagency.com/feed/",
    # Chinese
    "https://www.france24.com/zh/rss",
    "https://rss.dw.com/rdf/rss-chi-all",
    "https://www.rfi.fr/cn/rss",
    "https://cn.nytimes.com/rss/",
    # Science / tech, openly licensed
    "https://theconversation.com/articles.atom",
    "https://arstechnica.com/feed/",
    "https://www.nature.com/nature.rss",
    # GDELT
    "https://data.gdeltproject.org/gdeltv3/gal/feed.rss",
]

UA = "NewsReaderBot/0.1 (+personal news aggregator; probe)"


async def probe(client: httpx.AsyncClient, url: str) -> str:
    try:
        r = await client.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=15.0)
    except Exception as exc:
        return f"{url:<70} ERR   {type(exc).__name__}: {str(exc)[:60]}"
    if not r.is_success:
        return f"{url:<70} {r.status_code:<5} {len(r.content)}B  final={r.url}"
    feed = feedparser.parse(r.content)
    n = len(feed.entries)
    with_desc = sum(1 for e in feed.entries if (e.get("summary") or e.get("description")))
    title = str(getattr(feed.feed, "title", ""))[:28]
    return (
        f"{url:<70} {r.status_code:<5} {len(r.content):>7}B entries={n:<4} "
        f"desc={with_desc:<4} bozo={int(getattr(feed, 'bozo', 0))} title={title!r}"
    )


async def main() -> None:
    urls = sys.argv[1:] or CANDIDATES
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*(probe(client, u) for u in urls))
    for line in results:
        print(line)


if __name__ == "__main__":
    asyncio.run(main())
