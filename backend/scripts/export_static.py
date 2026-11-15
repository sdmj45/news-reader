"""Exports the database as static JSON, so the site needs no server at all.

This is what makes a genuinely free deployment possible. The API is read-only and the data
changes a few times an hour, which means a server is not answering questions a file could
answer. Removing it removes the only component that needs a cloud account with a payment
method on file.

    python -m scripts.export_static [--out ../frontend/public/data] [--limit 800]

Produces, in ``--out``:

* ``articles.json`` - the newest articles, already filtered and ordered.
* ``meta.json``     - counts, categories, publishers, and when this was generated.

Both are small enough to load once and filter in the browser: 800 articles is about 400 kB,
roughly 90 kB over the wire after gzip, which is less than one of the images a news site
would have loaded. Searching and filtering 800 records in JavaScript is instant, so the
client-side version is not a degraded one - it is faster than the API it replaces, because
there is no round trip.

The export is deliberately **bounded and ordered here**, not in the browser: a snapshot that
grows without limit would eventually become a slow first paint, and that failure arrives
gradually enough that nobody notices it happening.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import get_settings
from app.models.article import Article
from app.repositories.base import ArticleQuery
from app.repositories.factory import build_repository

#: Articles in the snapshot. Enough for several days of reading, small enough to stay fast.
#:
#: Measured on real data: 800 articles came to 680 kB, 231 kB gzipped, which is a slow first
#: paint on mobile for a reader who wanted today's headlines. 400 is 352 kB, 121 kB gzipped,
#: and still covers several days.
DEFAULT_LIMIT = 400

#: Characters of the publisher's description kept, cut on a word boundary.
#:
#: This is a **bound against outliers, not a size optimisation** - and measuring said so.
#: The average description is 260 characters, so capping at 320 saved 2% on a real snapshot.
#: What it prevents is one publisher's 1,979-character standfirst (The Guardian, measured)
#: dominating a card in a reader built for reading the news briefly.
DEFAULT_MAX_DESCRIPTION = 320

#: Articles older than this are dropped even if the limit has not been reached. A news
#: reader showing last month's headlines because nothing newer arrived is worse than one
#: showing a short list.
MAX_AGE_DAYS = 10


def _truncate(text: str, limit: int) -> str:
    """Cuts at the last word boundary before ``limit`` and marks the cut with an ellipsis."""
    if limit <= 0 or len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-\u2013\u2014")
    return f"{cut}\u2026"


def article_json(article: Article, max_description: int = DEFAULT_MAX_DESCRIPTION) -> dict:
    """The same shape the REST API serves, minus what the interface never reads.

    Kept deliberately parallel to :class:`app.api.schemas.ArticleOut` so the frontend can use
    one set of types for both modes. Null and empty fields are omitted: across 800 articles
    the absent keys are a third of the payload.
    """
    data: dict = {
        "id": article.id,
        "title": article.title,
        "url": article.url or article.canonical_url,
        "publisher": article.publisher,
        "domain": article.domain,
        "language": article.language,
        "category": article.category.value,
        "published_at": article.published_at.astimezone(UTC).isoformat(),
        "license": article.license_status.value,
        "attribution": article.attribution_text,
    }
    if article.country:
        data["country"] = article.country
    if article.secondary_categories:
        data["secondary_categories"] = [c.value for c in article.secondary_categories]
    if article.author:
        data["author"] = article.author
    if article.image_url:
        data["image_url"] = article.image_url
    if article.original_description:
        data["description"] = _truncate(article.original_description, max_description)
    if article.description_withheld_reason:
        data["description_withheld_reason"] = article.description_withheld_reason
    if article.event_id:
        data["event_id"] = article.event_id

    translation: dict = {}
    if article.translated_title:
        translation["title"] = article.translated_title
    if article.translated_summary:
        translation["summary"] = {
            # CJK packs far more into a character, so the same cap would cut a Chinese
            # summary much further into its content than the French one it mirrors.
            language: _truncate(text, max_description // 2 if language == "zh" else max_description)
            for language, text in article.translated_summary.items()
        }
    if article.provenance.translation_model:
        translation["provider"] = article.provenance.translation_model
    if article.provenance.translation_generated_at:
        translation["generated_at"] = (
            article.provenance.translation_generated_at.astimezone(UTC).isoformat()
        )
    if translation:
        data["translation"] = translation
    return data


def collect(repository, limit: int, languages: tuple[str, ...]) -> list[Article]:
    """The newest articles within the age window, newest first.

    Paged rather than fetched in one query because the repository caps a page at 200 - the
    same cap the API enforces, and going around it here would make the export the one caller
    that reads unbounded.
    """
    cutoff = datetime.now(UTC) - timedelta(days=MAX_AGE_DAYS)
    out: list[Article] = []
    cursor: str | None = None
    while len(out) < limit:
        page = repository.list_articles(
            ArticleQuery(
                languages=languages,
                published_after=cutoff,
                limit=min(200, limit - len(out)),
                cursor=cursor,
            )
        )
        out.extend(page.articles)
        cursor = page.next_cursor
        if not cursor:
            break
    return out[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="../frontend/public/data",
                        help="Directory to write into. Created if absent.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--language", action="append", default=[],
                        help="Repeatable. Default: every language in the database.")
    parser.add_argument("--max-description", type=int, default=DEFAULT_MAX_DESCRIPTION,
                        help="Characters of publisher description to keep. 0 keeps all.")
    args = parser.parse_args()

    settings = get_settings()
    repository = build_repository(settings)
    articles = collect(repository, args.limit, tuple(args.language))

    if not articles:
        # Writing an empty snapshot would replace a working site with a blank one. Refusing
        # leaves the previous deployment in place, which is the better failure.
        print(
            "No articles within the last "
            f"{MAX_AGE_DAYS} days. Nothing was written, so any existing snapshot is kept. "
            "Run `python -m scripts.ingest` first.",
            file=sys.stderr,
        )
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = [article_json(a, args.max_description) for a in articles]
    (out_dir / "articles.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    translated = sum(1 for a in articles if a.translated_title)
    meta = {
        "generated_at": datetime.now(UTC).isoformat(),
        "articles": len(articles),
        "translated": {
            language: sum(1 for a in articles if language in a.translated_title)
            for language in settings.target_languages
        },
        "languages": dict(Counter(a.language for a in articles).most_common()),
        # Counted over primary *and* secondary categories, because that is what the
        # browser filters on. A chip whose number disagreed with the list behind it would
        # be worse than a chip with no number.
        "categories": [
            {"category": category, "count": count}
            for category, count in Counter(
                tag
                for article in articles
                for tag in {
                    article.category.value,
                    *(c.value for c in article.secondary_categories),
                }
            ).most_common()
        ],
        "publishers": sorted({a.publisher for a in articles}),
        "oldest": articles[-1].published_at.astimezone(UTC).isoformat(),
        "newest": articles[0].published_at.astimezone(UTC).isoformat(),
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    size = (out_dir / "articles.json").stat().st_size
    print(f"wrote {len(articles)} articles ({size / 1024:.0f} kB) to {out_dir}")
    print(f"  translated  {translated} ({translated / len(articles):.0%})")
    print(f"  languages   {', '.join(f'{k}={v}' for k, v in list(meta['languages'].items())[:6])}")
    print(f"  newest      {meta['newest']}")
    print(f"  oldest      {meta['oldest']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
