# Architecture

## Current state

Phases 1–4 are implemented and verified: collection, a read-only REST API, a reading
interface, and Chinese translation. Phases 5–8 (scheduled jobs, cloud deployment,
stabilisation, public release) are not.

Three processes, deliberately separate:

```
  scripts/ingest.py      collection      fast, free, every 20-30 min
  scripts/translate.py   translation     slow, rationed, budget-capped
  app/main.py            the API         read-only, serves what the other two wrote
```

They are separate because their failure modes are: a translation quota running out must
never cost an article, and a collection run must never block a reader. Phase 5 schedules the
first two as Cloud Run Jobs without changing either.

```
                    ┌──────────────────────────────────────────┐
                    │  scripts/ingest.py  (Phase 5: Cloud Run Job) │
                    └───────────────────┬──────────────────────┘
                                        │
                              CollectorManager
                        (bounded concurrency, per-host rate limit,
                         per-source isolation and backoff)
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              │                         │                         │
        RSSCollector            GDELTRSSCollector         GDELTGALCollector
     (RSS 0.9x/1.0/2.0,          (disabled: no              (JSON-NL, gzip,
      Atom; 28 sources)           descriptions)              clock-derived
              │                         │                     file discovery)
              └─────────────────────────┼─────────────────────────┘
                                        │
                               normalization
                   (URL canonicalisation, title cleaning, dates, language)
                                        │
                                  deduplicate
                          (same canonical URL → one record)
                                        │
                                   classify
                   (source section → keyword count → abstain)
                                        │
                                cluster_events
               (time + content tokens + named entity; links, never merges)
                                        │
                              _enforce_license
                      (second, independent check against the registry)
                                        │
                              ArticleRepository
                      ┌─────────────────┴─────────────────┐
                 SQLite (now)                    Firestore (Phase 6)
                              │
                 ┌────────────┴─────────────┐
                 │                          │
       scripts/translate.py            app/main.py  (FastAPI, read-only)
       MyMemory, budget-capped,              │
       permanent, licence-gated         frontend/  (React, Cloudflare Pages)
```

## Why it is shaped this way

### The repository is a protocol, not a base class

Specification section 2.1 requires the database to be replaceable. That is only true if
nothing above the storage layer knows which one is in use, so `ArticleRepository` is expressed
in application terms ("the newest articles in this category") and never in SQL or Firestore
query syntax.

Two Firestore constraints are baked into the contract even though SQLite would not need them,
so that behaviour measured locally transfers to production:

* **Cursor pagination, not offset.** Firestore charges per document read and has no efficient
  `OFFSET`; an offset API would quietly cost a full scan per page.
* **Upsert by article id.** Collection re-reads the same articles constantly.

The cursor is `(published_at, id)` rather than `published_at` alone, because articles
routinely share a timestamp and a single-column cursor silently skips rows.

### Deduplication and event clustering are different operations

`deduplicate` decides two records are *the same article* and keeps one. Its only evidence is
the canonical URL — the only signal that cannot be wrong. Two publishers writing the same
headline is routine (wire copy guarantees it), and deleting one would discard a publisher's
work.

`cluster_events` decides two *different* articles cover the same event and links them with a
shared `event_id`, deleting nothing. It requires agreement on time, on content words, **and**
on a named entity, because the cheap version — token overlap alone — merges "La France
enregistre une baisse du chômage" with "La France accueille un sommet sur le climat".

Clustering is near-linear, not quadratic: candidate pairs come from an inverted index on
content tokens. GDELT alone supplies thousands of articles per run.

### Multilingual tokenisation branches

The registry carries French, English and Chinese; GDELT carries 40+ languages. Whitespace
languages are tokenised on words with a 232-entry stopword list; CJK uses character bigrams,
the standard cheap substitute for a segmenter, needing no model or dictionary. Cross-script
grouping is declined rather than guessed — it would need translation, which is a later phase
and a licence question.

### Failure is data

Every collector returns a `CollectionResult` and never raises into the manager. A failed
source contributes zero articles and one recorded error; there is no cache fallback, no sample
data, no placeholder article. `CollectionStats` is produced on every run whether or not anyone
is watching, because a metric computed only when something looks wrong has no baseline.

Two failure modes get specific handling, both discovered by running the code:

* **An HTTP 200 HTML error page** is not an empty feed. `feedparser` reports it as zero
  entries with no error, which would be recorded as a healthy source that published nothing.
  The collector checks `feed.version` and raises.
* **A GDELT quiet period** is not a GDELT outage. Between quarter-hour publications every
  candidate filename 404s; with a cursor that is "nothing new", without one it is a real
  failure.

### Backoff forgives the first failure

Publishers return a 503 for a few seconds all the time, and a source's own fetch interval
already spaces runs out. Backing off after one blip would turn a momentary outage into a gap
of several scheduled runs. The schedule is `(0, 0, 15, 60, 180, 360)` minutes, capped at six
hours — beyond that a source needs a human, not a longer timer.

## Module map

| Path | Responsibility |
|---|---|
| `app/models/licensing.py` | What may be stored, shown, and altered. The conservative default. |
| `app/models/source.py` | Source record + invariants (no unverified source may be enabled). |
| `app/models/article.py` | Normalised article. Publisher metadata and generated content never share a field. |
| `app/processors/normalization.py` | URLs, titles, dates, language tags. |
| `app/processors/dedup.py` | Same-article collapse and cross-publisher event clustering. |
| `app/processors/classifier.py` | Category assignment: section → keyword count → abstain. |
| `app/collectors/base.py` | Collector interface, retry/backoff, rate limiting, statistics. |
| `app/collectors/rss_collector.py` | RSS and Atom. |
| `app/collectors/gdelt_collector.py` | GAL JSON-NL, file discovery, gzip, schema probe. |
| `app/collectors/collector_manager.py` | Concurrency, isolation, per-source backoff. |
| `app/services/source_registry.py` | The 30 verified sources and their licence evidence. |
| `app/services/ingestion.py` | One run, end to end, with its measured report. |
| `app/repositories/` | Storage protocol, SQLite implementation, factory. |

## Cost posture

Nothing in this repository costs money to run. SQLite on disk, no cloud project, no AI
provider, no paid API. `SUMMARISER=null` and `SUMMARY_DAILY_BUDGET_CALLS=0` are the defaults,
and `DATABASE_BACKEND=firestore` must be set deliberately. Specification section 12 forbids
silently activating a paid service; a permissive default is how that happens.

## What Phase 2 onward will add

* **Phase 2** — FastAPI over the existing repository. The query model (`ArticleQuery`, `Page`)
  already matches what the endpoints need, so this is mostly serialisation and CORS.
* **Phase 3** — React/Vite frontend.
* **Phase 4** — summarisation behind a pluggable interface, gated on
  `allows_summary_publication`. Today that is one source out of thirty.
* **Phase 5–6** — Cloud Run Job + Scheduler; Firestore repository; Cloudflare Pages.
