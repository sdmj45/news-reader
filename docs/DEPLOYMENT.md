# Deployment

**Total cost: €0. No credit card anywhere, no cloud account, no server.**

Free-tier figures below were checked on 2026-11-14 against the providers' own
documentation; links are at the bottom. They change, so re-check before relying on them.

---

## 1. Why there is no Google Cloud project

The original plan was Cloud Run + Firestore. That was dropped, for one blunt reason:

> **Google Cloud's free tier requires a billing account, and a billing account requires a
> valid payment method.** A project without one cannot use Google Cloud services *even
> inside the free limits*.

Cloud Run's free allowance (2M requests/month) is real and this application would fit inside
it. But "free with a card on file" is not the same as free, and a misconfiguration — a
runaway collection loop, a Firestore read storm — bills a real card.

The second reason is better: **this application does not need a server.** The API is
read-only and the data changes a few times an hour, so a server would be answering questions
a file can answer. Once collection runs on a schedule and writes a JSON snapshot, the whole
product is static files.

```
GitHub Actions  ──runs──▶  collect → translate → export JSON → build site
       │                                                            │
       │ every 3 hours, free                                        ▼
       └──────────────────────────────────────────────▶  GitHub Pages (static, free)
                                                                    │
                                                          reader's browser filters
                                                          and searches the snapshot
```

No database to host, no container to keep warm, no cold starts, nothing to pay for, and
nothing that can run up a bill because there is no meter.

## 2. What each piece costs

| Component | Provider | Free allowance (checked 2026-11-14) | This project uses |
|---|---|---|---|
| Scheduled jobs | GitHub Actions | **Unlimited** on public repos; 2,000 Linux min/month on private | ~3 min × 8 runs/day ≈ 720 min/month |
| Hosting | GitHub Pages | Free on public repos. 1 GB site, 100 GB/month bandwidth (soft), 10 builds/hour (soft) | ~1 MB site, ~400 kB of data |
| Translation | MyMemory | No key. ~5,000 characters/day anonymous, ~50,000 with a contact address | ~80 headlines/run |
| News sources | RSS + GDELT | Free and public | 29 feeds |

**No payment method is required for any of them.**

### The trade-off you are accepting

A **public repository**. Unlimited Actions minutes and free Pages both depend on it. Nothing
in this repository is secret — no keys, no credentials, and `.gitignore` excludes `.env` and
the database. If you want it private: Actions still works inside 2,000 minutes/month (drop
to 4 runs/day), but GitHub Pages on a private repo needs a paid plan, so host the `dist/`
output on Cloudflare Pages instead (§5).

## 3. Setting it up

```bash
# 1. Create a GitHub repository and push
gh repo create news-reader --public --source=. --push
# or: git remote add origin git@github.com:<you>/news-reader.git && git push -u origin main

# 2. Enable Pages: Settings → Pages → Source: "GitHub Actions"

# 3. Optional but recommended — raise the free translation quota 10×.
#    This is a contact address, not a credential; MyMemory documents it as the way to lift
#    the anonymous limit, and it needs no registration.
#    Settings → Secrets and variables → Actions → Variables → New variable
#      Name:  TRANSLATE_CONTACT_EMAIL
#      Value: your@email

# 4. Run it once by hand: Actions → "collect and publish" → Run workflow
```

The site appears at `https://<you>.github.io/news-reader/` a few minutes later.

### Before you make it public, read this

`.github/workflows/publish.yml` sets `PERSONAL_USE_MODE: "true"`, which is what allows the
headlines to be translated at all. That flag is an assertion that **this instance serves one
private household and republishes nothing**. Publishing the site at a public URL and telling
people about it contradicts that assertion.

For a family instance the honest reading is: a URL that only your household knows is still a
private reader. Announcing it, submitting it to search engines or putting ads on it is not.
See [`COPYRIGHT_POLICY.md`](COPYRIGHT_POLICY.md) §7 for what a genuinely public release would
require. If you would rather not make the assertion, delete that line: the site still works,
and about ten articles a day (the CC BY-licensed ones) still get translated.

## 4. The two scheduling caveats

Both are GitHub's behaviour, not this project's, and both are easy to be bitten by:

1. **Scheduled workflows are disabled after 60 days without repository activity** on public
   repos. The workflow deploys an artifact rather than committing, so it may not count as
   activity. If the site goes stale, press "Run workflow" — that resets the clock. A commit
   does too.
2. **Scheduled runs are delayed under load, and queued jobs can be dropped at peak.** The
   cron is set to `:17` rather than `:00` for exactly this reason. A missed run costs
   nothing: the next one collects everything since.

## 5. Cloudflare Pages instead

Also free, no card, and it serves from the root rather than `/<repo>/`.

- Free plan: 500 builds/month, 20,000 files per site, 25 MiB per file, 100 custom domains.
- Works with a private repository, which GitHub Pages does not.

Change two things in `publish.yml`: drop the `VITE_BASE` line (Cloudflare serves from `/`),
and replace the three `actions/*-pages` steps with `cloudflare/wrangler-action`, which needs
a `CLOUDFLARE_API_TOKEN` secret. The build itself is identical.

## 6. Keeping the server option

`backend/app/main.py` is still a working FastAPI application and the tests still cover it.
It is the right answer if the snapshot ever outgrows a single file — tens of thousands of
articles, or per-user state — and `VITE_DATA_MODE=api` switches the frontend back to it with
no other change. Until then it is a development convenience, not a deployment.

If you do deploy it one day, the Firestore repository is the one missing class: the protocol
is in `app/repositories/base.py` and SQLite shows the shape.

## 7. Running the whole pipeline locally

Exactly what the workflow does, in the same order:

```bash
cd backend
export PERSONAL_USE_MODE=true
python -m scripts.ingest                                   # ~20s, 29 sources
python -m scripts.translate                                # headline → Chinese
python -m scripts.export_static --out ../frontend/public/data

cd ../frontend
VITE_DATA_MODE=static npm run build
npx vite preview                                           # static site, no backend running
```

## Sources

- [GitHub Actions billing](https://docs.github.com/en/actions/concepts/billing-and-usage)
- [GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)
- [GitHub Actions `schedule` event](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
- [Cloudflare Pages limits](https://developers.cloudflare.com/pages/platform/limits/)
- [Google Cloud free tier](https://docs.cloud.google.com/free/docs/free-cloud-features)
- [MyMemory usage limits](https://mymemory.translated.net/doc/usagelimits.php)
