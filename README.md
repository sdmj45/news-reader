# News Reader

A multilingual news aggregator for personal and family use, designed to grow into a public
platform without an architectural rewrite.

**Status: Phase 1 complete and verified. Phases 2–8 not started.**

The collection engine works against real sources: a single run on 2026-11-14 collected
**4,468 articles from 30 live sources in 30.7 seconds**, 30/30 succeeding. There is no API and
no frontend yet — read [What does not work](#what-does-not-work) before forming an impression.

## What works today

| | |
|---|---|
| RSS/Atom collection | 29 sources — French, English, Chinese — all fetch-verified on 2026-11-14 |
| GDELT GAL collection | JSON-NL, schema **measured** from live data, ~1,800 articles per file |
| Normalisation | URL canonicalisation, title cleaning, 40+ date formats, language tags |
| Deduplication | Canonical-URL collapse; measured duplicate rate 0.9–6% per run |
| Event clustering | Cross-publisher, multilingual (word tokens and CJK bigrams), links without merging |
| Classification | 16 categories, source section → keyword count → abstain. No AI, no cost. |
| Licence enforcement | Conservative by default, checked twice, 28 of 31 sources metadata-only |
| Persistence | SQLite with cursor pagination and the indexes Firestore will need |
| Per-source health | Isolation, exponential backoff, ETag/cursor incremental collection |
| Automated tests | **182 passing** (unit + integration), plus 33 live-data tests run on demand |

## What does not work

* **No REST API.** Phase 2.
* **No frontend.** Phase 3. Nothing is viewable in a browser.
* **No summaries or translations.** Phase 4. Of 31 registered sources, exactly **one**
  (European Commission, CC BY 4.0) licenses derivative works, so this feature will cover ~10
  articles per run until more permissions are researched.
* **Nothing is deployed.** No GCP project, no Firestore, no Cloud Run, no scheduler. The
  Firestore repository is declared in the factory and not yet written.
* **Chinese coverage is thin** — three sources (DW, RFI, NYT), all foreign outlets' Chinese
  services. Every other candidate refused the client or returned an unparsable body. See
  [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md).
* **61% of GDELT articles classify as `OTHER`.** The keyword tables cover French, English and
  Chinese; GAL carries 40+ languages.

## Quick start

No credentials, no cloud project, no cost.

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp ../.env.example .env

.venv/bin/python -m scripts.ingest              # collect real news into data/news.db
.venv/bin/python -m scripts.ingest --dry-run    # collect and report, write nothing
.venv/bin/python -m scripts.ingest --sources lemonde-une,bbc-news

.venv/bin/python -m pytest                      # 182 tests, offline
.venv/bin/python -m pytest -m realdata          # live checks against real providers
.venv/bin/ruff check .
```

### Investigating sources

```bash
.venv/bin/python -I scripts/probe_feeds.py              # probe every candidate feed
.venv/bin/python -I scripts/probe_feeds.py <url>        # probe one
.venv/bin/python -m scripts.probe_gdelt                 # measure the live GAL schema
```

## The copyright rule

Technical accessibility is not permission. A source whose terms have not been researched is
`UNKNOWN`, which means headline, publisher, timestamp and link — and nothing else. The
publisher's description is *measured and discarded*, so coverage statistics stay possible
without storing text the project has no right to store.

GDELT is `UNKNOWN` and always will be: it indexes other publishers' pages across 545 domains
per file; it cannot license them.

Full policy: [`docs/COPYRIGHT_POLICY.md`](docs/COPYRIGHT_POLICY.md).

## Documentation

| | |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How it is built and why |
| [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) | Every source, measured; the GAL schema; rejected candidates |
| [`docs/COPYRIGHT_POLICY.md`](docs/COPYRIGHT_POLICY.md) | The licence model and its enforcement |
| [`docs/PHASE1_VERIFICATION.md`](docs/PHASE1_VERIFICATION.md) | Acceptance criteria, with evidence |
| [`PROJECT_SPECIFICATION.md`](PROJECT_SPECIFICATION.md) | The original brief |

## Layout

```
backend/
  app/
    collectors/   base, rss, gdelt, manager
    processors/   normalization, dedup, classifier
    models/       licensing, source, article
    repositories/ protocol, sqlite, factory
    services/     source_registry, ingestion
  scripts/        ingest, probe_feeds, probe_gdelt
  tests/          unit, integration, realdata, fixtures (real captured feeds)
docs/
infrastructure/   gcp, cloudflare, deployment  (empty until Phase 6)
```
