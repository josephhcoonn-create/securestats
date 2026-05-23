# docs/

Static assets referenced by the project root [`README.md`](../README.md).

## Replacing the dashboard mockup

`dashboard-screenshot.svg` is a vector mockup used as the README hero image
so the page never shows a broken-image icon. To swap in a real screenshot:

1. Boot the stack and sign in:
   ```bash
   docker compose up --build
   open http://localhost:8080
   ```
2. Capture the view you want (Players, Leaders, Streaks, or Compare) as
   a PNG.
3. Save it here as `dashboard-screenshot.png` (or `.jpg`).
4. Update the `<img src="…"/>` reference in the root README to point at
   the new file, then commit.

A 1200×700 capture sits nicely at the README width (`width="900"` on the
`<img>` tag — adjust if your image has a different aspect ratio).
