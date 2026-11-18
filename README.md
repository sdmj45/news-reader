# News Reader

A multilingual news aggregator for personal and family use, designed to grow into a public
platform without an architectural rewrite.

**Status: Phases 1–4 complete and verified. Phases 5–8 (scheduling, cloud deployment,
stabilisation, public release) not started.**

It works end to end on a laptop: collect real French news, translate the headlines into
Chinese, read them in a browser. Nothing is deployed anywhere — read
[What does not work](#what-does-not-work) before forming an impression.

## What works today

| | |
|---|---|
| **Reading interface** | React + Vite + Tailwind. French headline with the Chinese underneath, categories, search, saved articles, light/dark, PWA |
| **Chinese translation** | MyMemory, free and key-less. Measured good on real headlines; 100% success over a live pass |
| **REST API** | FastAPI, read-only, cursor-paginated, CORS-restricted, rate-limited |
| RSS/Atom collection | 62 active sources — French, English, Chinese — each fetch-verified before being added |
| GDELT GAL collection | JSON-NL, schema **measured** from live data, ~1,800 articles per file |
| Normalisation | URL canonicalisation, title cleaning, 40+ date formats, language tags |
| Deduplication | Canonical-URL collapse; measured duplicate rate 0.9–6% per run |
| Event clustering | Cross-publisher, multilingual (word tokens and CJK bigrams), links without merging |
| Classification | 18 categories including a China desk and a French-policy tag (visas, tax, pensions, benefits); source section → keyword count → abstain. Sport, culture, environment and health are excluded (`EXCLUDED_CATEGORIES`). No AI, no cost. |
| Licence enforcement | Conservative by default, checked twice, 61 of 62 active sources metadata-only; The Conversation is disabled because CC BY-ND forbids translation |
| Persistence | SQLite with cursor pagination and the indexes Firestore will need; keeps the last `RETENTION_DAYS` (2) days and deletes the rest |
| Per-source health | Isolation, exponential backoff, ETag/cursor incremental collection |
| Automated tests | **335 backend** (unit + integration + API), **23 browser end-to-end**, plus 45 live-data tests on demand |

## What does not work

* **It is not deployed yet** — but the pipeline to do it for free is written and tested.
  Push to a public GitHub repo, enable Pages, and `.github/workflows/publish.yml` collects,
  translates, exports and publishes every three hours at no cost. See
  [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).
* **No Google Cloud.** Its free tier requires a billing account with a payment method, and
  this application does not need a server at all — the site reads a static JSON snapshot and
  filters it in the browser. The FastAPI backend still exists and still works; it is a
  development convenience now, not a deployment.
* **Translation needs `PERSONAL_USE_MODE=true`.** A translation is a derivative work, and 28
  of 31 publishers have granted no such permission. With the flag off — the default — exactly
  one source (European Commission, CC BY 4.0) can be translated, which is about ten articles
  a day. See [the copyright policy](docs/COPYRIGHT_POLICY.md); the flag is an assertion about
  how *you* operate the instance, not a licence.
* **The free translation quota is small.** MyMemory allows roughly 5,000 characters a day
  anonymously, about 60 headlines, rising to ~50,000 with a contact address in
  `TRANSLATE_CONTACT_EMAIL`. Translations are permanent once made, so the cost is paid once
  per article.
* **No generated summaries.** The brief asks for them; the licence situation means they would
  apply to one source, so the headline translation was built first. The interface is honest
  about it rather than showing an empty field.
* **The API rate limiter is per-process**, so it does not hold across Cloud Run instances.
  Fine for a household; must be replaced before public launch.
* **China coverage is all foreign desks** — BBC中文, 自由亚洲, SCMP, Le Monde's China desk, DW
  and RFI's Chinese services. No mainland publisher is included: every candidate probed
  either refused the client, returned an unparsable body, or was a third-party mirror whose
  completeness could not be established. See [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md).
* **GDELT is disabled by default.** It works — the schema was measured, the collector is
  tested — but filtering it to French yields the *francophone world*, not French news: a
  Tunisian daily, an Algerian paper republishing its 2020 archive, a Senegalese site. It
  buried Le Monde under 184 long-tail articles. Enable it with `COLLECTOR_ONLY_SOURCES` if
  you want breadth over focus.

## Quick start

No credentials, no cloud project, no cost.

```bash
# 1. Backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp ../.env.example .env
echo "PERSONAL_USE_MODE=true" >> .env     # see "What does not work" before setting this

.venv/bin/python -m scripts.ingest        # collect real news into data/news.db  (~20s)
.venv/bin/python -m scripts.translate     # translate headlines into Chinese
.venv/bin/python -m uvicorn app.main:app --port 8000

# 2. Frontend, in another terminal
cd frontend
npm install
npm run dev                               # http://127.0.0.1:5173
```

Other backend commands:

```bash
.venv/bin/python -m scripts.ingest --dry-run             # collect and report, write nothing
.venv/bin/python -m scripts.ingest --sources lemonde-une
.venv/bin/python -m scripts.translate --limit 20 --language zh

.venv/bin/python -m pytest                # 229 tests, offline
.venv/bin/python -m pytest -m realdata    # live checks against real providers
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
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Deploying for €0, with the free-tier numbers checked |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How it is built and why |
| [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) | Every source, measured; the GAL schema; rejected candidates |
| [`docs/COPYRIGHT_POLICY.md`](docs/COPYRIGHT_POLICY.md) | The licence model and its enforcement |
| [`docs/VERIFICATION.md`](docs/VERIFICATION.md) | Acceptance criteria and defects found, with evidence |
| [`PROJECT_SPECIFICATION.md`](PROJECT_SPECIFICATION.md) | The original brief |

## Layout

```
backend/
  app/
    api/          schemas, deps, v1/{articles,meta}
    collectors/   base, rss, gdelt, manager
    processors/   normalization, dedup, classifier
    models/       licensing, rights, source, article
    repositories/ protocol, sqlite, factory
    services/     source_registry, ingestion, translation/
    main.py       the FastAPI app
  scripts/        ingest, translate, probe_feeds, probe_gdelt
  tests/          unit, integration, realdata, fixtures (real captured feeds)
frontend/
  src/            components, hooks, services, i18n, types
  e2e/            browser tests against a real backend
docs/
```
