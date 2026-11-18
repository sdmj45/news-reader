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
from app.models.article import Article, Category
from app.repositories.base import ArticleQuery
from app.repositories.factory import build_repository

#: Articles in the snapshot. Enough for several days of reading, small enough to stay fast.
#:
#: Chosen by measuring the alternatives on the real registry of 52 sources, counting the
#: articles each setting surfaces from the slow, high-signal technology sources (DeepMind,
#: OpenAI, LWN, MIT Technology Review, IEEE Spectrum, InfoQ, Simon Willison, GitHub):
#:
#:   limit  cap   France  Tech  China  slow-AI  gzipped  window
#:     400   12       43   164     47       38   105 kB  2d20h
#:     550   15       53   242     65       83   142 kB  5d16h   <- chosen
#:     650   18       63   278     78       91   168 kB  9d17h
#:
#: 650 is better on every count except that 168 kB is a lot to send a phone. 550 doubles
#: the frontier-technology coverage over 400 for 37 kB more.
#:
#: Those windows were measured before RETENTION_DAYS existed. With the default two-day
#: window, the window is usually what binds, and the snapshot is everything recent.
DEFAULT_LIMIT = 550

#: Characters of the publisher's description kept, cut on a word boundary.
#:
#: This is a **bound against outliers, not a size optimisation** - and measuring said so.
#: The average description is 260 characters, so capping at 320 saved 2% on a real snapshot.
#: What it prevents is one publisher's 1,979-character standfirst (The Guardian, measured)
#: dominating a card in a reader built for reading the news briefly.
DEFAULT_MAX_DESCRIPTION = 320

#: Articles any one publisher may contribute to the snapshot.
#:
#: Without this, "newest 400" is won by whoever publishes most often. Measured across 53
#: sources: franceinfo took 54 slots and Le Monde 51, the window shrank to 21 hours, and
#: **every** low-volume source was squeezed out entirely - Google DeepMind, OpenAI, MIT
#: Technology Review, LWN, the GitHub blog and Import AI each had zero articles in it.
#: Those are precisely the sources worth reading; they publish once a week rather than
#: once an hour, and a pure recency cut is the one selection rule guaranteed to lose them.
#:
#: Capping per publisher costs a few of the fiftieth-most-recent franceinfo headlines and
#: buys the entire slow half of the registry: at this setting those eight sources
#: contribute 83 articles instead of none.
DEFAULT_MAX_PER_PUBLISHER = 15


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


def collect(
    repository,
    limit: int,
    languages: tuple[str, ...],
    max_per_publisher: int = DEFAULT_MAX_PER_PUBLISHER,
    max_age_days: int = 2,
) -> list[Article]:
    """The newest articles within the age window, newest first, balanced across publishers.

    ``max_age_days`` is the retention window (``RETENTION_DAYS``); 0 means no age limit. A
    news reader showing last month's headlines because nothing newer arrived is worse than
    one showing a short list.

    Asks each publisher for its newest ``max_per_publisher`` and merges, rather than taking
    the newest N overall and trimming. The difference matters: trimming a global list can
    only remove articles it has already read, so a publisher whose latest post is older
    than the Nth most recent article in the database is invisible no matter how large N is.
    That is exactly how every weekly source disappeared from a 400-article snapshot.

    Bounded by construction - publishers times the cap, around 500 rows for this registry -
    so it does not grow with the database the way a "read five times the limit and filter"
    pass would.
    """
    cutoff = datetime.now(UTC) - timedelta(days=max_age_days) if max_age_days > 0 else None

    def newest(
        count: int, publisher: str | None = None, categories: tuple[Category, ...] = ()
    ) -> list[Article]:
        out: list[Article] = []
        cursor: str | None = None
        while len(out) < count:
            page = repository.list_articles(
                ArticleQuery(
                    categories=categories,
                    languages=languages,
                    publishers=(publisher,) if publisher else (),
                    published_after=cutoff,
                    limit=min(200, count - len(out)),
                    cursor=cursor,
                )
            )
            out.extend(page.articles)
            cursor = page.next_cursor
            if not cursor:
                break
        return out

    if not max_per_publisher:
        return newest(limit)

    selected: list[Article] = []
    for publisher in repository.distinct_publishers():
        selected.extend(newest(max_per_publisher, publisher))

    # French policy articles are outside the cap. They are few - a handful a day - and they
    # come mostly from Le Monde's money and immigration desks, which share one cap with
    # every other Le Monde section and lost to the front page every time. Then whatever is
    # oldest and not policy makes room for them.
    chosen = {a.id for a in selected}
    policy = [a for a in newest(limit, categories=(Category.FRANCE_POLICY,))
              if a.id not in chosen]
    selected.extend(policy)

    selected.sort(key=lambda a: a.published_at, reverse=True)
    if len(selected) >= limit:
        keep = {a.id for a in policy}
        room = limit - len(keep)
        others = [a for a in selected if a.id not in keep][:max(room, 0)]
        kept = {a.id for a in others} | keep
        return [a for a in selected if a.id in kept][:limit]

    # Capping can leave the snapshot short when few publishers have posted recently.
    # Publishing a half-empty page because of an internal rule would be the wrong trade, so
    # the remainder is filled from the newest articles overall.
    chosen = {a.id for a in selected}
    for article in newest(limit):
        if article.id not in chosen:
            selected.append(article)
            chosen.add(article.id)
            if len(selected) == limit:
                break
    selected.sort(key=lambda a: a.published_at, reverse=True)
    return selected[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="../frontend/public/data",
                        help="Directory to write into. Created if absent.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--language", action="append", default=[],
                        help="Repeatable. Default: every language in the database.")
    parser.add_argument("--max-description", type=int, default=DEFAULT_MAX_DESCRIPTION,
                        help="Characters of publisher description to keep. 0 keeps all.")
    parser.add_argument("--max-per-publisher", type=int, default=DEFAULT_MAX_PER_PUBLISHER,
                        help="Articles one publisher may contribute. 0 disables the cap.")
    args = parser.parse_args()

    settings = get_settings()
    repository = build_repository(settings)
    articles = collect(repository, args.limit, tuple(args.language),
                       max_per_publisher=args.max_per_publisher,
                       max_age_days=settings.retention_days)

    if not articles:
        # Writing an empty snapshot would replace a working site with a blank one. Refusing
        # leaves the previous deployment in place, which is the better failure.
        print(
            "No articles within the last "
            f"{settings.retention_days} days. Nothing was written, so any existing snapshot is kept. "
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
    print(f"  publishers  {len(meta['publishers'])} "
          f"(max {args.max_per_publisher or 'unlimited'} articles each)")
    print(f"  newest      {meta['newest']}")
    print(f"  oldest      {meta['oldest']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
