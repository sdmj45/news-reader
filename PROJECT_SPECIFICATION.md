# News Reader — project specification

The authoritative brief for this project, as provided by the owner on 2026-11-14.

Implementation status against it is tracked in
[`docs/VERIFICATION.md`](docs/VERIFICATION.md), which maps each of the
seventeen acceptance criteria in section 18 to evidence or to the phase that will deliver it.

Where this implementation knowingly departs from the brief, the departure and its reason are
recorded here:

| Brief | Implementation | Reason |
|---|---|---|
| §2.1 "Primary database: Firestore" | SQLite today, Firestore behind `DatabaseBackend.FIRESTORE` | No GCP project exists, and creating cloud resources needs the owner's approval (§14.6). The repository layer is a protocol so the swap costs one class. |
| §4.1 GAL fields `date, url, domain, outletName, title, desc, lang, author, image` | Also `outletLogo`, `outletTwitter`, which the brief does not list; neither is stored | Measured from live data. The application displays neither outlet logos nor social handles. |
| §4.1 GAL "produced each minute" | Files cluster after each quarter hour | Measured: a 33-minute sweep found 9 files. See `docs/DATA_SOURCES.md` §1.2. |
| §9 "Initial categories" list | Implemented as given, plus `OTHER` | Classification must be able to abstain; a wrong category is worse than none. |
| §16 project structure | No `collector/` package; the job body is `backend/scripts/ingest.py` | §16 permits a simpler organisation where justified. A separate top-level package for one entry point that imports the whole backend would be a directory, not a module. |

---

## The brief

> **Not yet inlined.** The full specification text has not been pasted into this file. It is
> the only item from specification §16 that this repository does not yet contain, and it is a
> copy-paste rather than a piece of work: everything derived from the brief — the deviation
> table above, the acceptance-criteria mapping in `docs/VERIFICATION.md`, the licence
> policy, the source registry — is already here.
>
> Paste the brief below this line to complete the file.
