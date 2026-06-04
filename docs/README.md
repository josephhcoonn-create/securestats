# docs/

Static assets referenced by the project root [`README.md`](../README.md).

## Dashboard hero

`dashboard-screenshot.png` is the live PNG referenced from the root README's
hero `<img>`. To regenerate it (after a frontend tweak, slate refresh, etc.):

```bash
# from repo root, with the stack running on http://localhost:8080
npm install
npx playwright install chromium    # one-time
npm run capture-dashboard
```

The capture script (`scripts/capture-dashboard.mjs`) logs in as
`josephhcoonn / ChangeMe123!`, drops the JWT into `localStorage`, navigates
to `/picks`, waits for the radial-bar charts to render, and writes a
1440×900 PNG to `docs/dashboard-screenshot.png`.

Set `CLICK_HISTORY=1` to capture the History sub-tab instead, or override
`TARGET_PATH` (e.g. `TARGET_PATH=/odds`) to capture a different page.

`dashboard-screenshot.svg` is the old vector placeholder, kept around as
a fallback in case the PNG ever gets deleted.
