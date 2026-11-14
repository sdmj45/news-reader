# Data sources

Every claim in this document was produced by running code in this repository against live
endpoints. Where something could not be measured, it says so.

Measurement date: **2026-11-14**. Host: a WSL2 development machine behind a corporate network.
Reproduce with:

```bash
cd backend
.venv/bin/python -I scripts/probe_feeds.py     # every candidate feed, status and entry count
.venv/bin/python -m scripts.probe_gdelt        # GDELT GAL schema, measured from a real file
.venv/bin/python -m pytest -m realdata         # the registry's claims, re-checked
```

---

## 1. GDELT Article List (GAL)

### 1.1 What was measured

`scripts/probe_gdelt.py` downloaded `20261114183100.gal.json.gz` and measured 1,791 records.

| Field | Present | Note |
|---|---|---|
| `date` | 100.0% | ISO 8601 with `Z`. GDELT states ~30% are the true publication time; the rest are first-seen. |
| `url` | 100.0% | 0 invalid, 0 duplicates within the file. |
| `domain` | 100.0% | |
| `outletName` | 100.0% | Repeats the domain when the outlet has no human-readable name. |
| `title` | 100.0% | |
| `lang` | 100.0% | en 26%, es 13%, de 10%, fr 6%, then 40+ others. |
| `desc` | 97.2% | **Median 150 characters** — a standfirst, not an article. |
| `outletLogo` | 96.2% | Not stored: the application does not display outlet logos. |
| `image` | 95.5% | |
| `outletTwitter` | 63.5% | Not stored. |
| `author` | 37.2% | |

Other measurements from the same file: **545 distinct domains**, 1.4 MB decompressed,
1,791 lines, 0 malformed.

### 1.2 File layout — corrected against the documentation

The announcement post says a file is produced "each minute". That is not what the data shows.

* Pattern: `https://data.gdeltproject.org/gdeltv3/gal/YYYYMMDDHHMM00.gal.json.gz`
* gzip, UTF-8, one JSON object per line, no enclosing array.
* **Files cluster in the minutes after each quarter hour.** A sweep of 33 consecutive
  minute-stamps found 9 files. `GDELTGALCollector.candidate_urls` searches a six-minute window
  after each quarter mark rather than guessing a single URL.
* There is **no index**: `/gdeltv3/gal/`, `lastupdate.txt` and `MASTERFILELIST.TXT` all return
  404. Filenames must be derived from the clock.

### 1.3 The RSS variant is worse, and is disabled

`https://data.gdeltproject.org/gdeltv3/gal/feed.rss` returned HTTP 200, 1,054,163 bytes,
3,600 entries — and **0 of 3,600 entries carried a description**. Each entry has `title`,
`link` and `pubDate` only: no language, no outlet name, no image.

It is therefore registered (`gdelt-gal-rss`) but **disabled**: strictly less metadata than the
JSON-NL files for a 1 MB download every fetch.

### 1.4 Reachability caveat

GDELT was **initially unreachable from this host**. `curl` to `data.gdeltproject.org`,
`api.gdeltproject.org`, `blog.gdeltproject.org` and `www.gdeltproject.org` all timed out, over
both IPv4 and IPv6, while Le Monde, BBC, DW and the Guardian answered normally. The same hosts
responded a few minutes later through `httpx`, and have responded since.

The cause was not established. The environment sits behind a corporate proxy
(`gcloud` is configured with a custom CA bundle), and an intermittent block is the most likely
explanation. The consequence for the code: **GAL collection must treat total unreachability as
a normal operating condition**, which `GDELTGALCollector.collect` does — it reports the failure
and leaves the other 28 sources untouched.

### 1.5 Licensing

GDELT **indexes** other publishers' pages. It does not license their content, and it cannot:
a single file carried 545 distinct domains. The 150-character `desc` belongs to each underlying
publisher.

The registry therefore records `gdelt-gal` as `UNKNOWN`, and the pipeline **measures the
description and discards it**. GAL's 97% description coverage produces zero displayed
descriptions. That is the intended behaviour, not a defect.

---

## 2. RSS and Atom sources

30 enabled sources, all fetch-verified on 2026-11-14. Full table with licence evidence:
[`backend/app/services/source_registry.py`](../backend/app/services/source_registry.py).

| Language | Sources | Examples |
|---|---|---|
| French | 15 | Le Monde (6 sections), franceinfo (3), Le Figaro, France 24, RFI, Futura, Sciencepost, The Conversation France |
| English | 11 | BBC (2), DW, Guardian, Al Jazeera, NPR, Ars Technica, Nature, Euronews, European Commission, The Conversation |
| Chinese | 3 | 德国之声 (DW), 法广 (RFI), 纽约时报中文网 |
| Multilingual | 1 | GDELT GAL |

### 2.1 Measured per-source behaviour

From a full live run on 2026-11-14 (`python -m scripts.ingest`): **30/30 sources succeeded,
4,468 articles collected in 30.7 seconds**. Description coverage was 100% for every RSS source
except RFI French (90%) and Le Figaro (94% at probe time).

### 2.2 Candidates that were probed and rejected

Recorded in `REJECTED_CANDIDATES` so that the absence of a well-known outlet is a decision,
not an oversight.

| Endpoint | Reason |
|---|---|
| European Parliament top-stories (en, fr) | HTTP 403 |
| Council of the EU press releases | HTTP 403 |
| AP `apnews.com/apf-topnews` | HTTP 403 |
| Reuters Agency feed | HTTP 404 |
| France 24 Chinese (`/zh/rss`, `/zh-hans/rss`) | HTTP 404 — no Chinese France 24 feed located |
| Libération outbound feed | HTTP 200, 0 parsable entries |
| DW French (`rss-fr-all`) | HTTP 200, 28-byte empty body |
| Al Jazeera Chinese | HTTP 200, 352 kB, 0 parsable entries |
| VOA Chinese API | HTTP 200, 11-byte body |
| `feedx.net/rss/zaobao.xml` | **Works**, but rejected on provenance: a third-party mirror of Lianhe Zaobao, not the publisher's feed |

A 403 is a publisher refusing automated access. None of them is worked around.

### 2.3 Chinese coverage is thin, and that is a known gap

Three Chinese sources: DW, RFI and NYT Chinese — all foreign outlets' Chinese services. NYT
Chinese timed out on the first probe and was initially rejected; a re-probe the same day
returned 20 entries, which is why the live suite re-checks rejected endpoints. Every mainland
and Singapore candidate probed either refused the client, returned an unparsable body, or was
a third-party mirror. GDELT supplies Chinese-language articles (`lang: zh`) and partly fills the
gap, at `UNKNOWN` licence. Listed as an open item, not solved.

---

## 3. How to add a source

1. Probe it: `python -I scripts/probe_feeds.py <url>`. Record status, entry count, description
   count.
2. Read the publisher's terms. If no explicit reuse permission exists, the entry is `UNKNOWN`
   and nothing but title, publisher, time and link will ever be shown.
3. Add it to `SOURCES` with `verification=FETCH_VERIFIED`, `verified_on`, and
   `verified_item_count` from step 1. `NewsSource.__post_init__` refuses an enabled source that
   is not fetch-verified, and refuses an elevated licence with no evidence.
4. Run `pytest tests/unit/test_licensing.py` — the registry invariants are tested.
5. Run `pytest -m realdata -k <source_id>`.
