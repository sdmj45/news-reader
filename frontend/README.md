# Frontend

React + TypeScript + Vite + Tailwind v4. A single screen: French headlines with their
Chinese translation underneath, filters, search, and saved articles.

```bash
npm install
npm run dev        # http://127.0.0.1:5173, proxies /api to the backend on :8000
npm run build      # type-check then build to dist/
npm run lint
npm run e2e        # real browser, real backend — see e2e/reader.spec.mjs
```

## If you run `npm install` behind a corporate proxy

Your npm is configured against an internal mirror, and `npm install` rewrites every
`resolved` URL in `package-lock.json` to point at it. That lockfile installs perfectly here
and fails on every other machine, including GitHub Actions, which cannot resolve the
internal hostname — and npm reports it by printing its own usage text, which is not a clue.

```bash
npm run lockfile:fix     # rewrite the URLs back to registry.npmjs.org
npm run lockfile:check   # exits 1 if any private URL remains; part of `npm run lint`
```

The rewrite is safe: these mirrors are path-prefixed proxies of registry.npmjs.org, and the
`integrity` hashes are of the tarball contents, which are identical whichever host served
them. Installing still works locally afterwards, because npm substitutes your configured
registry for the host in the lockfile.

## Two data modes

`VITE_DATA_MODE` chooses where articles come from, behind one interface
([`src/services/api.ts`](src/services/api.ts)):

- **`static`** — reads `public/data/{articles,meta}.json` and filters in the browser. No
  server. This is what the deployed site uses and the default for a production build. On the
  measured snapshot (400 articles, 353 kB, 121 kB gzipped) it is *faster* than the API,
  because every filter after the first costs no round trip.
- **`api`** — talks to the FastAPI backend. The default during `npm run dev`.

For `api` mode the backend must be running:

```bash
cd ../backend && PERSONAL_USE_MODE=true .venv/bin/python -m uvicorn app.main:app --port 8000
```

For `static` mode, generate a snapshot first:

```bash
cd ../backend && python -m scripts.export_static --out ../frontend/public/data
cd ../frontend && VITE_DATA_MODE=static npm run build && npx vite preview
```

## Decisions worth knowing

**French and Chinese are stacked, not toggled.** A household where one reader works in
French and another in Chinese looks at the same card; hiding one behind a switch makes them
take turns. Which line comes first follows the interface language, and can be set explicitly
in settings.

**Absence of a translation is stated.** A card with no Chinese line says whether it is *not
translated yet* or *not permitted for that source* — the licence travels with the article, so
the interface can tell them apart. A card that silently shows only French is
indistinguishable from a broken one.

**Saved articles live in the browser, stored whole.** Until there are accounts, a favourites
endpoint would be either a list everyone shares or a tracking identifier. Storing the whole
article rather than its id means the saved list still works when the backend has rotated the
article out or is unreachable.

**No router.** The product is a list with filters. A URL scheme would be more machinery than
the thing it navigates.

**The service worker caches the shell, never the news.** News that is silently hours stale is
worse than news that is honestly absent.

**Both themes are first-class.** This is opened early in the morning and late at night.

**The mobile app is this site, installed as a PWA.** There is no app-store build. The
"下载手机版 / Get the mobile app" button in the header adapts to the device
([`src/services/install.ts`](src/services/install.ts)): one-tap install where the browser
offers it (Chrome, Edge, Samsung Internet), Share → Add to Home Screen steps on iOS, an
"open in browser" hint inside WeChat and other in-app browsers, and on a computer a QR code
that opens the site on the phone. The button hides itself inside the installed app. The
manifest uses relative URLs so the install works from the GitHub Pages sub-path.
