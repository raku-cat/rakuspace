# PWA support, with a separate Go Live app

## Goal

Make RakuSpace installable as a PWA. Additionally, let the Go Live broadcaster
page (`/go_live`) install as its own separate app, distinct from the main
site app, so a user can keep "browse/manage RakuSpace" and "go live" as two
separate home-screen/dock apps while both still work fine from a normal
browser tab too.

## Non-goals

- No offline caching of app data or assets. The service worker exists only
  to satisfy Chrome/Android's install requirements (a controlling SW is
  mandatory for the install prompt).
- No changes to the database or auth. `RakuSpace.py` gets one small addition
  (see Service worker scope below), not touching either.
- No custom install button on the main site pages; installing the main app
  relies on the browser's native install UI.

## Architecture

Two independent Web App Manifests on one origin. Browsers evaluate
installability against whichever manifest is linked from the page currently
open, so two manifests can coexist without any server-side routing changes:

- **Main app** — `static/manifest.webmanifest`
  - `name: "RakuSpace"`, `start_url: "/"`, `scope: "/"`, `display: "standalone"`
  - Icons: `static/icon-192.png`, `static/icon-512.png`
  - Linked from every page except `golive.html`: `index.html`, `player.html`,
    `player_lite.html`, `multistream.html`, `stream.html`, `notifications.html`
- **Go Live app** — `static/manifest-golive.webmanifest`
  - `name: "RakuSpace — Go Live"`, `start_url: "/go_live"`, `scope: "/go_live"`,
    `display: "standalone"`
  - Same icons as the main app (same branding, distinct name only)
  - Linked only from `golive.html`, in place of the main manifest

A single site-wide service worker, `static/sw.js`, handles `install`/
`activate` plus a no-op `fetch` listener (some browsers' install criteria
check for a registered fetch handler even though this one does no caching
or interception). Registered via a small shared script (`static/pwa.js`)
included on every page that links a manifest.

### Service worker scope

A service worker's default scope is the directory it's served from. Serving
it at `static/sw.js` would scope it to `/static/`, which controls no actual
page — the install prompt would never fire. `RakuSpace.py` gets one new
route, `/sw.js`, serving that same file from the site root so its scope
covers `/` and `/go_live`:

```python
@app.route("/sw.js")
def service_worker():
    return send_from_directory(app.static_folder, "sw.js")
```

### Scope collision between the two manifests

The main app's `scope: "/"` also covers `/go_live` — manifest scope has no
exclusion mechanism. So `(display-mode: standalone)` alone can't tell
"installed Go Live app" apart from "installed main app, currently showing
`/go_live`" — both are standalone. Visiting Go Live from inside the
installed main app must keep its normal header/back link; only launching
the dedicated Go Live app should go chromeless.

Fix: the Go Live manifest's `start_url` carries a marker query param
(`/go_live?app=1`, `scope` stays `/go_live`). `golive.html` adds a
`golive-app` class to `<body>` only when that param is present, and the
chromeless CSS is gated on `body.golive-app` *inside* the
`(display-mode: standalone)` media query, not on the media query alone.

Both manifests also get an explicit `"id"` (`"/"` and `"/go_live"`) so a
future `start_url` change doesn't orphan existing installs (identity
otherwise keys off `start_url`).

## Icons

`static/logo.png` is 32x32, too small for a home-screen icon (Chrome wants
192px+/512px). Stopgap: generate `static/icon-192.png` and
`static/icon-512.png` by upscaling `logo.png`. Expected to look soft up
close; swappable later without any manifest/template changes once better
source art exists.

## golive.html changes

### Install button

A new button, styled like the existing `.golive-link`/`.new-badge` pair on
`index.html`, reading "Install as app (PWA)" with a "New!" badge, placed to
the left of the existing "← Back to Home" link in the header.

Behavior:
- JS listens for `beforeinstallprompt`, calls `preventDefault()`, and stores
  the event.
- Clicking the button calls `.prompt()` on the stored event.
- If `beforeinstallprompt` never fires (browser doesn't support it, e.g.
  Firefox/iOS, or the app is already installed), the button stays hidden.

### Standalone (installed) view

When `golive.html` is opened from the installed Go Live app, it should show
*only* the purple "retro-win" broadcaster panel — no header, no page
background — filling the window edge-to-edge.

Implementation: pure CSS under `@media (display-mode: standalone)`:
- `<header>` is hidden entirely (back link and install button both live
  there, and neither has a purpose inside the installed app window).
- `main.golive.centered` drops its centering/padding.
- `.retro-win` drops `max-width: 660px` and its margin, drop shadow, and
  border-radius, and instead fills the viewport (`width/height: 100vw/100vh`
  or equivalent), flush to the window edges.
- Internal layout becomes a flex column so the titlebar and statusbar stay
  pinned to the top/bottom and the preview/controls area absorbs the extra
  vertical space instead of clipping or leaving dead space.

No JS is required to detect standalone mode for this layout change — modern
Chrome/Edge/Android and current iOS Safari all support the
`(display-mode: standalone)` media query directly. The regular
browser-tab view of `golive.html` is completely unaffected, since all of
this is gated behind that media query.

## Other pages

`index.html`, `player.html`, `multistream.html`, `stream.html`, and
`notifications.html` get the manifest `<link>` tag and the `pwa.js` include
added to `<head>`. `player_lite.html` is deliberately minimal (no
`app.css`, just `hls.js`) for lightweight embedding, so it's left out.

## Testing

No pytest coverage needed for the manifests/service worker/CSS themselves;
`RakuSpace.py`'s new `/sw.js` route has no auth or state, so no new test
was added for it either — existing tests keep passing.

Service workers and install prompts require a secure context (HTTPS, or
`localhost`/`127.0.0.1`) — testing against a LAN IP will silently no-op
both. Manual verification, over `http://localhost:5000` or the real
deployment:
1. Install the main app from `index.html` (or any non-golive page) via the
   browser's install UI; confirm it opens standalone at `/`.
2. On `golive.html`, click "Install as app (PWA)"; confirm it installs as a
   separately-named, separately-windowed app with `start_url: /go_live?app=1`.
3. Open the installed Go Live app; confirm only the chromeless retro-window
   is visible, filling the window, with no header/back/install button.
4. Open `/go_live` in an ordinary browser tab; confirm it looks and behaves
   exactly as it does today.
5. From inside the installed *main* app, navigate to `/go_live`; confirm it
   still shows the normal header and back link (not chromeless) — this is
   the scope-collision case above.
6. DevTools can override `display-mode` without installing, useful for
   checking the standalone CSS directly.
