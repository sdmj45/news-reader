# Verification report

Date: **2026-11-14**
Scope: specification Phases 0–4 — environment inspection, collection, REST API, reading
interface, and translation.

Everything below was produced by running the code in this repository. Commands are given so
each claim can be re-run.

## 0. Current totals

```
$ cd backend && .venv/bin/python -m pytest -q
229 passed, 33 deselected in 4.90s

$ .venv/bin/ruff check .
All checks passed!

$ cd frontend && npm run build && npm run lint
built in 444ms — 242 kB JS (77 kB gzip), 16 kB CSS (4 kB gzip); lint clean

$ npm run e2e        # real browser, real backend, real news
23 passed, 0 failed
```

A full pipeline run on 2026-11-14:

```
collection   29/29 sources, 1,336 articles, 31.5s, duplicate rate 3.1%, 21 events
translation  25 of 25 headlines into Chinese, 0 failed, 7,019 characters
```

---

## 1. Environment inspection (Phase 0)

| Check | Result |
|---|---|
| Working directory | Empty. No existing files were overwritten. |
| Python | 3.12.3 |
| Node.js | 24.13.0 (unused in Phase 1) |
| Docker, gcloud, firebase, uv, poetry | present |
| Git | not a repository → initialised |
| **Existing GDELT prototype** | **None found** anywhere under `~/dev` |
| Existing related work | `../actuFrancaisAI` — a French/Chinese news reader with a verified source registry, rights model and dedup. See §6. |
| gcloud account | A corporate EDF account whose token needs reauthentication. **No personal GCP project exists.** Cloud deployment is blocked on the owner creating one. |

## 2. What was built

| Component | File | Tests |
|---|---|---|
| Licence model | `app/models/licensing.py` | 20 |
| Source model + invariants | `app/models/source.py` | ↑ |
| Article model | `app/models/article.py` | — |
| Normalisation | `app/processors/normalization.py` | 35 |
| Deduplication + event clustering | `app/processors/dedup.py` | 20 |
| Classification | `app/processors/classifier.py` | 22 |
| Collector base (retry, backoff, rate limit, stats) | `app/collectors/base.py` | — |
| RSS/Atom collector | `app/collectors/rss_collector.py` | 17 |
| GDELT GAL collector + schema probe | `app/collectors/gdelt_collector.py` | 23 |
| Collector manager | `app/collectors/collector_manager.py` | ↓ |
| Source registry (31 sources) | `app/services/source_registry.py` | ↑ |
| Ingestion pipeline | `app/services/ingestion.py` | 24 integration |
| Repository protocol + SQLite | `app/repositories/` | 24 |

## 3. Test results

```
$ cd backend && .venv/bin/python -m pytest -q
182 passed, 33 deselected in 3.63s

$ .venv/bin/python -m pytest -m realdata -q
31 passed, 1 skipped, 182 deselected in 101.24s

$ .venv/bin/ruff check .
All checks passed!
```

The one skip is deliberate: a live check that reports when a previously rejected endpoint
starts working. It skipped because NYT Chinese had recovered — which is how
`nytimes-zh` came to be added to the registry. Re-run after that change: 2 passed, 0 skipped.

The 33 real-data tests are deselected by default (`pytest.ini`) because they make live
requests and can fail for reasons outside this codebase. That separation is specification
section 15's requirement.

## 4. Live collection — measured, not simulated

```
$ .venv/bin/python -m scripts.ingest

run 0a2ca397725d4359  30.7s

  sources          30/30 succeeded  (0 skipped, 100% success rate)
  collected        4468
  after dedup      4426  (duplicate rate 0.9%)
  written          4426 new, 0 updated, 0 unchanged
  events           131 (78 across publishers)
  descriptions     4250 withheld by licence

  categories  OTHER=2677, SCIENCE=660, INTERNATIONAL=490, FRANCE=128,
              EUROPE=75, TECHNOLOGY=71, POLITICS=69, CULTURE=64
  languages   en=1313, fr=907, es=341, it=247, de=180, zh=175, pt=138, ru=131
```

Second run immediately afterwards — **0 new, 600 unchanged**, confirming idempotency.

Largest contributors: GDELT GAL 3,128; Sciencepost 400; DW English 128; Nature 75.
644 distinct publishers appear in the database.

## 4b. Translation — measured, not simulated

MyMemory, free and key-less, on real French headlines:

| French | Chinese |
|---|---|
| Victime d'une cyberattaque, Maileva, une filiale de La Poste, annonce un vol de données concernant 22 millions de personnes | 法国邮政旗下子公司 Maileva 遭遇网络攻击，宣布 2200 万人的数据被盗 |
| Manifestations du 14 novembre : une équipe de BFMTV agressée en marge de la mobilisation à Lyon | 11月14日示威活动：BFMTV记者团队在里昂示威活动期间遭到袭击 |
| Volodymyr Zelensky affirme que Washington a proposé des concessions territoriales… | 弗拉基米尔·泽连斯基声称，华盛顿提议以乌克兰加入北约为条件，换取领土让步 |
| Grève à la SNCF : trafic perturbé lundi dans toute la France | 法国国家铁路公司罢工：周一法国全境交通受阻 |

Proper nouns survive transliteration and "SNCF" is expanded rather than dropped. 50 of 50
headlines translated across two passes, 0 failures.

**The quota is the binding constraint, not the quality.** MyMemory allows roughly 5,000
characters a day anonymously — about 60 headlines — rising to ~50,000 with a contact address
in `TRANSLATE_CONTACT_EMAIL`. Hence: a separate pass, a budget checked before each call, and
permanent storage so a headline is paid for once.

## 5. Acceptance criteria (specification section 18)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Collects real news from ≥1 verified external source | **PASS** | 30 sources, 4,468 articles |
| 2 | Processes GDELT data when reachable | **PASS** | Schema measured from `20261114183100.gal.json.gz`; 3,128 articles collected live |
| 3 | RSS collection works independently | **PASS** | 29 RSS/Atom sources, independent of GDELT |
| 4 | Articles stored in the database | **PASS** | 4,426 rows in SQLite |
| 5 | Duplicates handled | **PASS** | Canonical-URL collapse (0.9–6% per run) + 131 event clusters, 78 cross-publisher |
| 6 | Source permissions recorded | **PASS** | `license_type` + `license_evidence` on all 31; 2 CC BY-ND, 1 CC BY, 28 UNKNOWN |
| 7 | Backend exposes REST APIs | **PASS** | FastAPI; `/health`, `/api/v1/articles`, `/articles/{id}`, `/articles/categories`, `/sources`, `/stats`. 24 API tests. |
| 8 | Frontend displays real news | **PASS** | Verified in a real browser against the real backend; screenshots in the commit for Phase 3 |
| 9 | Works on mobile and desktop | **PASS** | Checked at 390×844 and 1280×900, light and dark |
| 10 | fr / en / zh interfaces | **PASS** | All three, independent of the news language. Verified end to end. |
| 11 | Search and category filtering | **PASS** | API + UI, covered by API tests and browser tests |
| 12 | Original links work | **PASS** | Canonical URLs stored; 0 invalid URLs in the GAL sample; browser test checks `target`/`rel` |
| 13 | Scheduled collection jobs | **NOT STARTED** | Phase 5. `scripts/ingest.py` and `scripts/translate.py` are the job bodies. |
| 14 | Automated tests pass | **PASS** | 229 backend offline, 23 browser E2E, 33 live-data |
| 15 | Cloud deployment instructions complete | **NOT STARTED** | Phase 6 |
| 16 | No paid service activated without approval | **PASS** | No cloud resource created. Defaults: SQLite, `SUMMARISER=null`, budget 0. |
| 17 | No unsupported copyright assumptions | **PASS** | §7 below. Translation is gated on an explicit operator assertion, not assumed. |

Additionally, from the brief's other sections:

| Requirement | Status |
|---|---|
| §1.2.6 AI summaries where permitted | **NOT IMPLEMENTED** — would apply to one source; headline translation was built first |
| §1.2.7 Automatic translation into Chinese | **PASS** |
| §1.2.7 Automatic translation into French | **NOT IMPLEMENTED** — the sources are already French |
| §1.2.11 Bookmarks | **PASS** — browser-local, stored whole |
| §10.5 PWA | **PASS** — manifest, icons, service worker, installable |
| §11 User accounts | **NOT STARTED** — data structures exist, no auth |

## 6. Prior work: `../actuFrancaisAI`

The specification asked whether an earlier prototype exists. There is no GDELT prototype, but
there is a closely related project by the same owner: an Android + Python French/Chinese news
reader with 31 verified feeds, a four-level content-rights model, event clustering and 163
passing tests.

**No code was copied.** Three design ideas were reused because they are sound and were already
validated against real French news:

* splitting "how much may be shown" from "may it be altered", so CC BY-ND is representable;
* refusing to enable a source that has not actually been fetched, enforced in `__post_init__`;
* conservative-by-default licensing with a cited evidence field.

They are reimplemented here against this project's data model. **Whether `news-reader`
supersedes `actuFrancaisAI`, or they stay separate, is the owner's decision — it was not
assumed either way.**

## 7. Copyright behaviour, verified at the database level

```
  [midilibre.fr] "Nous sommes le Samu de la mer" ...
     licence=UNKNOWN  desc_stored=False  offered=175ch
  [Le Monde] Présidentielle 2027 : Gérard Larcher invite ...
     licence=UNKNOWN  desc_stored=False  offered=199ch
```

4,250 descriptions were withheld in a single run. Coverage is still measurable
(`offered_description_chars`) without the text being stored. GDELT's 97% description coverage
produced zero stored descriptions.

## 8. Defects found and fixed during this phase

Each was found by running the code, not by inspection, and each has a regression test.

1. **An HTML error page looked like a healthy empty feed.** `feedparser` reports a 200 HTML
   maintenance page as zero entries with no error, which the pipeline recorded as a successful
   collection. Now detected via `feed.version` and reported as a source failure.
   *Tests:* `test_html_error_page_raises_rather_than_looking_like_an_empty_feed`,
   `test_an_html_error_page_is_a_failure_not_an_empty_success`.

2. **Description coverage reported 103% for the BBC.** Descriptions were counted per feed
   entry while items were counted per kept article, so a feed listing one article twice pushed
   the ratio above 1. Both counters now run over the same population.
   *Tests:* `TestStatisticsAreConsistent` (3 tests).

3. **A single 503 backed a source off for 5 minutes.** Publishers blip constantly and the
   fetch interval already spaces runs; one blip cost several scheduled runs. The first failure
   is now forgiven. *Test:* `test_a_single_failure_is_forgiven`.

4. **GDELT quiet periods were recorded as failures.** Between quarter-hour publications every
   candidate filename 404s. With a cursor that means "nothing new"; without one it means
   GDELT is unreachable. Conflating them would have backed GDELT off for six hours over a
   working feed. *Tests:* `TestGDELTQuietPeriods` (3 tests).

5. **The "has a rejected endpoint recovered?" check measured bytes, not feeds.** It flagged
   Al Jazeera Chinese (352 kB, unparsable) and a third-party mirror. Now requires parsable
   entries and ignores provenance-based rejections — which is what surfaced the genuine
   recovery of NYT Chinese.

6. **Registry data defect**: one rejected candidate recorded no probe date. Caught by
   `test_rejected_candidates_each_record_a_reason`.

## 9. Known limitations

* **61% of articles classify as `OTHER`**, almost all from GDELT. The keyword tables cover
  French, English and Chinese; GAL carries 40+ languages. Fixing this properly means either
  per-language tables or accepting that the firehose is mostly uncategorised.
* **Chinese coverage is thin** — three sources, all foreign broadcasters' Chinese services.
* **Event clustering is conservative.** 131 clusters from 4,426 articles. Under-merging is the
  intended bias, but the real rate of cross-publisher overlap has not been measured against a
  hand-labelled sample, so the thresholds are reasoned, not tuned.
* **GDELT was intermittently unreachable** from this host (see `docs/DATA_SOURCES.md` §1.4).
  Cause not established.
* **Only one source licenses derivative works.** Phase 4's summary feature will apply to ~10
  articles per run until more permissions are researched. That is a product problem, not a
  technical one.
* **No Firestore implementation yet.** The factory declares it; the class is not written.
* **`ruff format` is not enforced** — 21 files would be reformatted. The hand-laid-out registry
  and keyword tables read better as written. `ruff check` passes.

## 10. Defects found in Phases 2–4

Each found by running the code, each with a regression test.

7. **SQLite connections cannot cross threads.** The repository held one connection; uvicorn
   serves from a different thread, so *every* endpoint returned HTTP 500. No unit test caught
   it because the tests call the repository directly. Fixed with per-thread connections and a
   shared-cache URI for in-memory databases, plus
   `test_the_api_serves_from_a_worker_thread`.

8. **Headlines carried the publisher's own name as a suffix** — "… - La Dépêche de Kabylie" —
   which repeats on every card next to a publisher label that already says it, and is paid
   for twice when translated. Stripped only when the tail actually matches the outlet.

9. **GDELT flooded the reading list with one paper's 2020 archive.** GAL dates articles by
   first-seen, so a site republishing old content looks like the freshest news on the
   service. Found by reading the first translated batch and noticing all six were from the
   same Algerian regional paper. Fixed with a per-domain cap, and GDELT was disabled by
   default on editorial grounds.

10. **The Chinese interface rendered as tofu boxes** while Chinese *article* text rendered
    fine: the base font stack had no CJK fallback, so every translated button and chip fell
    through Inter to nothing. Invisible until the app was opened in a browser with no system
    Chinese font — which is any bare Linux desktop.

11. **The tagline truncated to "Les titres français, avec le c…"** at phone width.

## 11. Next

**Phase 5 — scheduled collection.** `scripts/ingest.py` and `scripts/translate.py` are
already the job bodies; this is a Dockerfile, two Cloud Run Jobs and two Cloud Scheduler
triggers.

**Phase 6 — deployment.** Blocked on the owner creating a personal GCP project; the
`gcloud` account on this host is a corporate one needing reauthentication. Needs the
Firestore repository written, which is one class behind an existing protocol.

Before any public deployment, two things in this report must change: the per-process rate
limiter, and `PERSONAL_USE_MODE`, which the application refuses to run with
`APP_ENV=production` for exactly that reason.
