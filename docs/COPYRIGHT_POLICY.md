# Copyright and reuse policy

**Technical accessibility is not permission.** A feed being public, a page loading without a
login, and GDELT indexing a URL are all facts about plumbing. None of them is a licence.

This document describes how that principle is implemented, so that it can be audited rather
than taken on trust.

---

## 1. The default is metadata only

A source whose reuse terms have not been researched is `LicenseType.UNKNOWN`. For such a
source the application stores and displays:

* the headline
* the publisher's name
* the publication timestamp
* the original URL
* an attribution line

and nothing else. The publisher's own description **is measured and discarded**:
`offered_description_chars` records how long it was so that coverage statistics remain
possible, while `original_description` stays null.

27 of the 30 registered sources are `UNKNOWN` today, including GDELT.

## 2. Two independent axes

Real licences separate "how much may be shown" from "may it be altered", so the model does too.
Collapsing them would be wrong in both directions: CC BY-ND permits republishing an entire
article verbatim while forbidding translation.

| Licence | Description | Full text | Derivatives (summary, translation) |
|---|---|---|---|
| `UNKNOWN` | no | no | no |
| `METADATA_ONLY` | no | no | no |
| `FEED_EXCERPT` | yes | no | no |
| `CC_BY_ND` | yes | yes | **no** |
| `CC_BY` / `CC_BY_SA` | yes | yes | yes |
| `PUBLIC_DOMAIN` | yes | yes | yes |
| `EXPLICIT_AGREEMENT` | yes | yes | yes |

Implemented in [`app/models/licensing.py`](../backend/app/models/licensing.py) and tested in
`tests/unit/test_licensing.py`.

## 3. The two sources with researched permissions

### The Conversation (France and UK) — CC BY-ND

> "licence Creative Commons Attribution/Pas de modification"
> — <https://theconversation.com/fr/republishing-guidelines>, read 2026-11-14

Their Atom feed carries full article bodies (836 kB per fetch). Under ND the application may
republish those verbatim with attribution, and **may not** summarise or translate them. Their
English guidelines add two carve-outs the registry records: the licence **prohibits use as AI
training data**, and embedded images are licensed separately by their creators.

### European Commission press releases — CC BY 4.0

> "Unless otherwise indicated (e.g. in individual copyright notices), content owned by the EU
> on this website is licensed under the Creative Commons Attribution 4.0 International
> (CC BY 4.0) licence."
> — <https://commission.europa.eu/legal-notice_en>, read 2026-11-14, implementing Commission
> Decision 2011/833/EU

This is currently the **only** source from which the application may publish a generated
summary or a translation. The carve-out is recorded too: material the EU does not own, and
content depicting identifiable individuals, needs separate clearance, so full-text reuse of an
individual release is not automatic.

## 4. How the rule is enforced in code

Three mechanisms, deliberately redundant:

1. **At parse time.** `RSSCollector` and `GDELTGALCollector` consult the source's licence
   before populating `original_description`.
2. **At persistence time.** `ingestion._enforce_license` checks again, against the registry
   rather than against whatever the article object claims, and clears the field if the two
   disagree. Two independent checks must agree before text survives.
3. **At registry construction.** `NewsSource.__post_init__` raises if a source claims a licence
   above `UNKNOWN` with an empty `license_evidence`, and raises if
   `summary_republication_allowed` is set without `modification_allowed` — a summary is a
   derivative work and the two flags cannot disagree.

Articles whose licence forbids a summary are stored with
`processing_status = SUMMARY_SKIPPED_LICENSE`, so "we chose not to" is distinguishable from
"we failed to" and from "nothing to summarise".

## 5. What the application never does

* Scrape full articles from publishers who have not licensed them.
* Treat a feed carrying a description as permission to republish it.
* Treat GDELT's index as a licence over the 545 domains it indexes.
* Generate a summary from text it had no right to process.
* Re-host images. Image URLs are stored and hotlinked, keeping the request and the copyright
  question with the publisher.
* Store full article bodies for any source below `CC_BY_ND`.

## 6. Provenance is recorded, not implied

Generated content never shares a field with publisher metadata:

| Field | Origin |
|---|---|
| `original_description` | the publisher |
| `generated_summary` | a model — with `provenance.summary_model` and `summary_prompt_version` |
| `translated_summary` | a model — with `provenance.translation_model` |
| `body_paragraphs` | the publisher, only under a full-text licence |

A reader can always tell which is which, and so can a later audit.

## 7. Before any public deployment

This policy is adequate for a private family instance. Public release additionally requires:

* Re-reading the terms of every `UNKNOWN` source and recording the outcome.
* A visible attribution and source-policy page.
* A takedown contact and procedure.
* GDPR work: privacy notice, retention policy, deletion path.
* A decision on whether to display the EU CC BY summaries at all, given that one licensed
  source among twenty-nine makes the feature look broken rather than careful.

Public deployment requires the project owner's explicit approval. Nothing in this repository
deploys anything.
