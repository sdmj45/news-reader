# Phase 1 verification report

Date: **2026-11-14**
Scope: specification Phase 0 (environment inspection) and Phase 1 (core news collection).

Everything below was produced by running the code in this repository. Commands are given so
each claim can be re-run.

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

## 5. Acceptance criteria (specification section 18)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Collects real news from ≥1 verified external source | **PASS** | 30 sources, 4,468 articles |
| 2 | Processes GDELT data when reachable | **PASS** | Schema measured from `20261114183100.gal.json.gz`; 3,128 articles collected live |
| 3 | RSS collection works independently | **PASS** | 29 RSS/Atom sources, independent of GDELT |
| 4 | Articles stored in the database | **PASS** | 4,426 rows in SQLite |
| 5 | Duplicates handled | **PASS** | Canonical-URL collapse (0.9–6% per run) + 131 event clusters, 78 cross-publisher |
| 6 | Source permissions recorded | **PASS** | `license_type` + `license_evidence` on all 31; 2 CC BY-ND, 1 CC BY, 28 UNKNOWN |
| 7 | Backend exposes REST APIs | **NOT STARTED** | Phase 2 |
| 8 | Frontend displays real news | **NOT STARTED** | Phase 3 |
| 9 | Works on mobile and desktop | **NOT STARTED** | Phase 3 |
| 10 | fr / en / zh interfaces | **NOT STARTED** | Phase 3. Content in all three is collected. |
| 11 | Search and category filtering | **PARTIAL** | Implemented and tested in the repository layer; no API to reach it |
| 12 | Original links work | **PASS** | Canonical URLs stored; 0 invalid URLs in the GAL sample |
| 13 | Scheduled collection jobs | **NOT STARTED** | Phase 5. `scripts/ingest.py` is the job body. |
| 14 | Automated tests pass | **PASS** | 182 offline + 32 live |
| 15 | Cloud deployment instructions complete | **NOT STARTED** | Phase 6 |
| 16 | No paid service activated without approval | **PASS** | No cloud resource created. Defaults: SQLite, `SUMMARISER=null`, budget 0. |
| 17 | No unsupported copyright assumptions | **PASS** | §7 below |

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

## 10. Next

Phase 2: FastAPI over the existing repository. `ArticleQuery` and `Page` already match what the
endpoints need, so this is mostly serialisation, CORS and rate limiting.
