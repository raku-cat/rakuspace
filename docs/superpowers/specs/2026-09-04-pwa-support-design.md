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
- No changes to `RakuSpace.py`, the database, or auth. This is static
  assets plus `<link>`/`<script>` tags in existing templates.
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

A single site-wide service worker, `static/sw.js`, handles only `install`/
`activate` — no `fetch` handler, no caching. Registered via a small shared
script (`static/pwa.js`) included on every page that links a manifest.

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

Just get the manifest `<link>` tag and the `pwa.js` include added to
`<head>`/before `</body>`. No visual or behavioral changes otherwise.

## Testing

No pytest coverage needed — nothing server-side changes. Manual
verification:
1. Install the main app from `index.html` (or any non-golive page) via the
   browser's install UI; confirm it opens standalone at `/`.
2. On `golive.html`, click "Install as app (PWA)"; confirm it installs as a
   separately-named, separately-windowed app with `start_url: /go_live`.
3. Open the installed Go Live app; confirm only the chromeless retro-window
   is visible, filling the window, with no header/back/install button.
4. Open `/go_live` in an ordinary browser tab; confirm it looks and behaves
   exactly as it does today.
