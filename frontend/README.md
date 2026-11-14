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
