# Multistream Conference View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/multistream` a Discord screenshare style view (focused stream plus bottom strip, or a 16:9 grid), keeping the current split tree viewer as advanced mode at `?advanced=1`.

**Architecture:** The existing template is renamed to `multistream_advanced.html` and gains a "Simple mode" menu link. A new self contained `multistream.html` (inline CSS and JS, like every other template here) holds a flat list of streams plus a focused id. Three containers (focus pane, strip, grid) hold cached tile elements; a tile is only reattached when its container changes, so only tiles that move reload. The Flask routes pick the template from the `advanced` query arg.

**Tech Stack:** Flask/Jinja2 templates, vanilla JS, CSS (container query units for the focus tile), pytest.

**Spec:** `docs/superpowers/specs/2026-10-13-multistream-conference-view-design.md`

## Global Constraints

- All user facing strings, code comments, commit messages: terse, no em dashes, no en dashes, no hyphen as punctuation.
- Palette: Catppuccin Macchiato tokens, same `:root` block as the current multistream page.
- No new dependencies. No JS test harness.
- Tiles are `/live/<name>` iframes: `LIVE_BASE_URL + encodeURIComponent(name)`, with `LIVE_BASE_URL = '{{ lite_prefix }}/live/'`.
- No full tile overlays over iframes. Tile chrome is only a pin button and a close button.
- New view localStorage key: `rakuspace-multistream-v1`. Advanced keeps `irc-embed-stream-layout-v1`.
- Stream names trimmed and lowercased on submit.
- Run tests with `cd /home/glizzy/Projects/rakuspace/frontend && python_modules/bin/python -m pytest tests/ -q`. Use the explicit `cd` in every command; repo root is `/home/glizzy/Projects/rakuspace`.
- Implementers do NOT commit. Leave changes in the working tree; the controller reviews and makes a signed commit per task (`sign-commits` skill).

## File Structure

- `frontend/templates/multistream_advanced.html`: renamed from `multistream.html`. Only change: "Simple mode" link in its menu, plus menu CSS so links look like the menu buttons.
- `frontend/templates/multistream.html`: new conference view. Whole page in one file.
- `frontend/RakuSpace.py`: `/multistream` and `/lite/multistream` choose the template.
- `frontend/tests/test_rakuspace.py`: route tests.
- `CLAUDE.md`, `frontend/README.md`: describe the two modes.

---

### Task 1: Routing, advanced rename, and menu cross links

**Files:**
- Rename: `frontend/templates/multistream.html` to `frontend/templates/multistream_advanced.html`
- Modify: `frontend/templates/multistream_advanced.html` (menu CSS and markup)
- Create: `frontend/templates/multistream.html` (temporary minimal page, fully replaced in Task 2)
- Modify: `frontend/RakuSpace.py:771-777`
- Test: `frontend/tests/test_rakuspace.py`

**Interfaces:**
- Produces: `/multistream`, `/lite/multistream` render `multistream.html`; with `?advanced=1` they render `multistream_advanced.html`. Both get `lite_prefix`.
- Produces: markers the tests rely on, which Task 2 must keep in the new template:
  - `id="menu-toggle-view"` (only in the new view)
  - `href="{{ lite_prefix }}/multistream?advanced=1"` (new view's Advanced mode link)
  - `const LIVE_BASE_URL = '{{ lite_prefix }}/live/';`
- Advanced view keeps `id="menu-toggle-edit"` and gains `href="{{ lite_prefix }}/multistream"`.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/tests/test_rakuspace.py`:

```python
# --- multistream routes ---

@pytest.mark.parametrize("prefix", ["", "/lite"])
def test_multistream_renders_conference_view(client, prefix):
    resp = client.get(prefix + "/multistream")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'id="menu-toggle-view"' in body
    assert 'id="menu-toggle-edit"' not in body
    assert f"const LIVE_BASE_URL = '{prefix}/live/';" in body
    assert f'href="{prefix}/multistream?advanced=1"' in body


@pytest.mark.parametrize("prefix", ["", "/lite"])
def test_multistream_advanced_renders_split_view(client, prefix):
    resp = client.get(prefix + "/multistream?advanced=1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'id="menu-toggle-edit"' in body
    assert 'id="menu-toggle-view"' not in body
    assert f"const LIVE_BASE_URL = '{prefix}/live/';" in body
    assert f'href="{prefix}/multistream"' in body


def test_multistream_advanced_other_values_ignored(client):
    resp = client.get("/multistream?advanced=0")
    assert resp.status_code == 200
    assert 'id="menu-toggle-view"' in resp.get_data(as_text=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/glizzy/Projects/rakuspace/frontend && python_modules/bin/python -m pytest tests/test_rakuspace.py -q -k multistream`
Expected: FAIL. `menu-toggle-view` not found, advanced link not found.

- [ ] **Step 3: Rename the template**

```bash
cd /home/glizzy/Projects/rakuspace && git mv frontend/templates/multistream.html frontend/templates/multistream_advanced.html
```

- [ ] **Step 4: Add the Simple mode link to the advanced menu**

In `frontend/templates/multistream_advanced.html`, replace the menu markup:

```html
  <div class="global-menu" id="global-menu">
    <button id="menu-add-stream" type="button">Add stream</button>
    <button id="menu-toggle-edit" type="button">Edit layout</button>
    <button id="menu-reset-layout" type="button">Reset layout</button>
  </div>
```

with:

```html
  <div class="global-menu" id="global-menu">
    <button id="menu-add-stream" type="button">Add stream</button>
    <button id="menu-toggle-edit" type="button">Edit layout</button>
    <a id="menu-simple-mode" href="{{ lite_prefix }}/multistream">Simple mode</a>
    <button id="menu-reset-layout" type="button">Reset layout</button>
  </div>
```

Then make links in the menu look like its buttons. Replace:

```css
  .global-menu button {
    display: block;
    width: 100%;
    text-align: left;
    padding: 10px 14px;
    background: none;
    border: none;
    color: var(--ctp-subtext1);
    font-family: inherit;
    font-size: 14px;
    cursor: pointer;
  }
  .global-menu button:hover { background: var(--ctp-surface0); color: var(--ctp-text); }
```

with:

```css
  .global-menu button,
  .global-menu a {
    display: block;
    width: 100%;
    text-align: left;
    padding: 10px 14px;
    background: none;
    border: none;
    color: var(--ctp-subtext1);
    font-family: inherit;
    font-size: 14px;
    text-decoration: none;
    cursor: pointer;
  }
  .global-menu button:hover,
  .global-menu a:hover { background: var(--ctp-surface0); color: var(--ctp-text); }
```

And in the focus ring rule, replace `.global-menu button:focus-visible,` with:

```css
  .global-menu button:focus-visible,
  .global-menu a:focus-visible,
```

- [ ] **Step 5: Create the temporary new template**

Create `frontend/templates/multistream.html` (Task 2 replaces this file entirely):

```html
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Multi-stream viewer - RakuSpace</title>
</head>
<body>
<div class="global-menu" id="global-menu">
  <button id="menu-toggle-view" type="button">Grid view</button>
  <a id="menu-advanced-mode" href="{{ lite_prefix }}/multistream?advanced=1">Advanced mode</a>
</div>
<script>
  const LIVE_BASE_URL = '{{ lite_prefix }}/live/';
</script>
</body>
</html>
```

- [ ] **Step 6: Route on the advanced query arg**

In `frontend/RakuSpace.py`, replace:

```python
@app.route("/multistream")
def multistream():
    return render_template("multistream.html", lite_prefix="")

@app.route("/lite/multistream")
def multistream_lite():
    return render_template("multistream.html", lite_prefix="/lite")
```

with:

```python
def _render_multistream(lite_prefix):
    # ?advanced=1 keeps the old free form split layout around.
    template = "multistream_advanced.html" if request.args.get("advanced") == "1" else "multistream.html"
    return render_template(template, lite_prefix=lite_prefix)

@app.route("/multistream")
def multistream():
    return _render_multistream("")

@app.route("/lite/multistream")
def multistream_lite():
    return _render_multistream("/lite")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd /home/glizzy/Projects/rakuspace/frontend && python_modules/bin/python -m pytest tests/ -q`
Expected: all pass, including the 5 new multistream cases.

- [ ] **Step 8: Hand off for commit**

Do not commit. Report done; the controller commits as "Move split multistream viewer to advanced mode".

---

### Task 2: Conference view page

**Files:**
- Replace: `frontend/templates/multistream.html` (whole file)

**Interfaces:**
- Consumes: Task 1 routes and the test markers listed there (`id="menu-toggle-view"`, the Advanced mode `href`, the `LIVE_BASE_URL` line). They are all present in the file below.
- Produces: nothing other tasks call.

Behavior summary (from the spec), all implemented by the file below:
- State `{ version: 1, streams: [{id, name}], focusedId, lastFocusedId }` in localStorage `rakuspace-multistream-v1`. `focusedId === null` means grid view.
- First stream added gets focus. Later adds go to strip (focus view) or grid.
- Pin on unfocused tile focuses it; pin on focused tile goes to grid.
- Menu toggle: focus view to grid clears focus; grid to focus restores `lastFocusedId` or the first stream.
- Closing the focused stream promotes the next in add order, else the previous.
- Duplicate name: no new tile, existing tile flashes.
- Focus tile: largest 16:9 that fits, via container query units. Strip: fixed 16:9 tiles, height `clamp(90px, 16vh, 200px)`, centered, scrolls on overflow without clipping the first tile. Strip hidden with one stream.
- Grid: `bestGrid()` picks the column count giving the largest 16:9 tile; an inner wrapper is sized to exactly that many columns so flex wrap matches; partial last row centered; recomputed by a ResizeObserver.
- `render()` uses `insertBefore` only when a tile is not already in the right container right after the right sibling, so unmoved tiles never reload.
- Add stream: floating centered name form. Shown automatically with zero streams (Cancel hidden then).

- [ ] **Step 1: Write the page**

Replace `frontend/templates/multistream.html` with:

```html
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Multi-stream viewer - RakuSpace</title>
<link rel="icon" href="{{ url_for('static', filename='logo.png') }}">
<link rel="manifest" href="{{ url_for('static', filename='manifest.webmanifest') }}">
<script src="{{ url_for('static', filename='pwa.js') }}" defer></script>
<style>
  :root {
    /* Catppuccin Macchiato, mirroring static/app.css. This page is a
       fullscreen video layout and doesn't load app.css, so it redeclares
       the tokens its chrome needs. */
    --ctp-crust: #181926;
    --ctp-mantle: #1e2030;
    --ctp-base: #24273a;
    --ctp-surface0: #363a4f;
    --ctp-surface1: #494d64;
    --ctp-surface2: #5b6078;
    --ctp-overlay1: #8087a2;
    --ctp-subtext0: #a5adcb;
    --ctp-subtext1: #b8c0e0;
    --ctp-text: #cad3f5;
    --ctp-green: #a6da95;
    --ctp-red: #ed8796;
    --ctp-pink: #f5bde6;
    --ctp-lavender: #b7bdf8;
    /* See static/app.css for what these two roles mean. */
    --accent: var(--ctp-pink);
    --focus-ring: var(--ctp-lavender);
  }

  * {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
  }

  html, body {
    width: 100%;
    height: 100%;
    overflow: hidden;
    background: #000;
    font-family: sans-serif;
  }

  /* --- stage: focus pane over strip, or grid --- */

  .stage {
    display: flex;
    flex-direction: column;
    width: 100vw;
    height: 100vh;
  }

  .focus-pane {
    flex: 1 1 0;
    min-height: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    container-type: size;
  }
  .focus-pane > .tile {
    width: min(100cqw, calc(100cqh * 16 / 9));
    aspect-ratio: 16 / 9;
  }

  .strip {
    flex: 0 0 auto;
    overflow-x: auto;
    overflow-y: hidden;
    padding: 8px 0;
  }
  /* max-content plus auto margins centers the row while it fits and lets
     it scroll from the first tile once it doesn't. */
  .strip-inner {
    display: flex;
    gap: 8px;
    width: max-content;
    margin: 0 auto;
    padding: 0 8px;
  }
  .strip-inner > .tile {
    flex: 0 0 auto;
    height: clamp(90px, 16vh, 200px);
    aspect-ratio: 16 / 9;
  }

  .grid-pane {
    flex: 1 1 0;
    min-height: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 8px;
  }
  .grid-inner {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 8px;
    width: var(--grid-w, 100%);
  }
  .grid-inner > .tile {
    flex: 0 0 auto;
    width: var(--tile-w, 0);
    height: var(--tile-h, 0);
  }

  .stage.mode-grid .focus-pane,
  .stage.mode-grid .strip,
  .stage.mode-focus .grid-pane,
  .stage.single .strip {
    display: none;
  }

  /* --- tiles --- */

  .tile {
    position: relative;
    overflow: hidden;
    background: var(--ctp-crust);
  }
  .tile iframe {
    display: block;
    width: 100%;
    height: 100%;
    border: 0;
  }
  .tile.flash {
    outline: 2px solid var(--focus-ring);
    outline-offset: -2px;
  }

  .tile-bar {
    position: absolute;
    top: 6px;
    left: 6px;
    z-index: 20;
    display: flex;
    gap: 4px;
    opacity: 0;
    transition: opacity 0.25s ease;
  }
  .tile:hover .tile-bar,
  .tile.just-added .tile-bar,
  .tile-bar:focus-within {
    opacity: 1;
  }
  .tile-btn {
    width: 26px;
    height: 26px;
    display: flex;
    align-items: center;
    justify-content: center;
    border: none;
    border-radius: 4px;
    background: rgba(24, 25, 38, 0.85);
    color: var(--ctp-subtext0);
    font-size: 16px;
    line-height: 1;
    cursor: pointer;
  }
  .tile-btn svg {
    width: 14px;
    height: 14px;
  }
  .tile-pin:hover { background: var(--ctp-surface1); color: var(--ctp-text); }
  .tile-pin[aria-pressed="true"] { color: var(--accent); }
  .tile-close:hover { background: var(--ctp-red); color: var(--ctp-crust); }

  /* --- add stream panel --- */

  .add-panel {
    position: fixed;
    inset: 0;
    z-index: 90;
    display: flex;
    align-items: center;
    justify-content: center;
    pointer-events: none;
  }
  .add-panel[hidden] { display: none; }

  .name-form {
    pointer-events: auto;
    display: flex;
    gap: 8px;
    align-items: center;
    max-width: calc(100vw - 32px);
    background: var(--ctp-base);
    border: 1px solid var(--ctp-surface1);
    padding: 14px;
    border-radius: 8px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  }
  .name-form input {
    font-size: 14px;
    padding: 8px 10px;
    border-radius: 4px;
    border: 1px solid var(--ctp-surface2);
    background: var(--ctp-mantle);
    color: var(--ctp-text);
    outline: none;
    width: 180px;
    min-width: 0;
    font-family: inherit;
  }
  .name-form input:focus { border-color: var(--focus-ring); }
  .name-form button {
    font-size: 13px;
    padding: 8px 12px;
    border-radius: 4px;
    border: 1px solid transparent;
    cursor: pointer;
    font-family: inherit;
    color: var(--ctp-text);
  }
  .name-form button[hidden] { display: none; }
  .name-form .load-btn {
    font-weight: 600;
    color: var(--ctp-crust);
    background: var(--ctp-green);
    border-color: var(--ctp-green);
  }
  .name-form .load-btn:hover { filter: brightness(1.08); }
  .name-form .cancel-btn { background: var(--ctp-surface1); border-color: var(--ctp-surface2); }
  .name-form .cancel-btn:hover { background: var(--ctp-surface2); }

  /* --- global menu --- */

  .menu-wrap {
    position: fixed;
    top: 10px;
    right: 10px;
    z-index: 100;
  }
  .global-menu-btn {
    width: 36px;
    height: 36px;
    border: 1px solid var(--ctp-surface1);
    border-radius: 4px;
    background: rgba(24, 25, 38, 0.85);
    cursor: pointer;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 4px;
    opacity: 0;
    transition: opacity 0.25s ease;
  }
  .global-menu-btn:hover { border-color: var(--ctp-surface2); }
  .global-menu-btn span {
    display: block;
    width: 18px;
    height: 2px;
    background: var(--ctp-subtext0);
  }
  .global-menu-btn:hover span { background: var(--ctp-text); }
  .menu-wrap:hover .global-menu-btn,
  .menu-wrap.just-added .global-menu-btn,
  .menu-wrap.open .global-menu-btn,
  .menu-wrap:focus-within .global-menu-btn {
    opacity: 1;
  }

  .global-menu {
    display: none;
    position: absolute;
    top: 42px;
    right: 0;
    background: var(--ctp-crust);
    border: 1px solid var(--ctp-surface1);
    border-radius: 8px;
    overflow: hidden;
    min-width: 190px;
    max-width: calc(100vw - 20px);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  }
  .menu-wrap.open .global-menu { display: block; }
  .global-menu button,
  .global-menu a {
    display: block;
    width: 100%;
    text-align: left;
    padding: 10px 14px;
    background: none;
    border: none;
    color: var(--ctp-subtext1);
    font-family: inherit;
    font-size: 14px;
    text-decoration: none;
    cursor: pointer;
  }
  .global-menu button:hover,
  .global-menu a:hover { background: var(--ctp-surface0); color: var(--ctp-text); }
  .global-menu button:disabled {
    color: var(--ctp-overlay1);
    background: none;
    cursor: default;
  }

  .global-menu-btn:focus-visible,
  .global-menu button:focus-visible,
  .global-menu a:focus-visible,
  .tile-btn:focus-visible,
  .name-form button:focus-visible {
    outline: 2px solid var(--focus-ring);
    outline-offset: -2px;
  }

  @media (prefers-reduced-motion: reduce) {
    .global-menu-btn, .tile-bar { transition: none; }
  }
</style>
</head>
<body>
<div class="stage mode-grid single" id="stage">
  <div class="focus-pane" id="focus-pane"></div>
  <div class="strip" id="strip"><div class="strip-inner" id="strip-inner"></div></div>
  <div class="grid-pane" id="grid-pane"><div class="grid-inner" id="grid-inner"></div></div>
</div>

<div class="add-panel" id="add-panel" hidden>
  <form class="name-form" id="add-form">
    <input id="add-input" type="text" placeholder="Stream name" autocomplete="off" aria-label="Stream name">
    <button type="submit" class="load-btn">Load</button>
    <button type="button" class="cancel-btn" id="add-cancel">Cancel</button>
  </form>
</div>

<div class="menu-wrap" id="menu-wrap">
  <button class="global-menu-btn" id="global-menu-btn" type="button" title="Menu" aria-label="Menu">
    <span></span><span></span><span></span>
  </button>
  <div class="global-menu" id="global-menu">
    <button id="menu-add-stream" type="button">Add stream</button>
    <button id="menu-toggle-view" type="button">Grid view</button>
    <a id="menu-advanced-mode" href="{{ lite_prefix }}/multistream?advanced=1">Advanced mode</a>
    <button id="menu-reset-layout" type="button">Reset layout</button>
  </div>
</div>

<script>
(function () {
  const LIVE_BASE_URL = '{{ lite_prefix }}/live/';
  const STORAGE_KEY = 'rakuspace-multistream-v1';
  const GRID_GAP = 8;
  // Lucide "pin" icon (ISC license).
  const PIN_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="12" x2="12" y1="17" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"/></svg>';

  const stage = document.getElementById('stage');
  const focusPane = document.getElementById('focus-pane');
  const stripInner = document.getElementById('strip-inner');
  const gridPane = document.getElementById('grid-pane');
  const gridInner = document.getElementById('grid-inner');
  const addPanel = document.getElementById('add-panel');
  const addForm = document.getElementById('add-form');
  const addInput = document.getElementById('add-input');
  const addCancel = document.getElementById('add-cancel');
  const viewBtn = document.getElementById('menu-toggle-view');

  // streams is in add order, which is also strip and grid order.
  // focusedId null means grid view.
  const state = { streams: [], focusedId: null, lastFocusedId: null };
  let nextId = 1;

  // Tile elements by stream id. Reused across renders so a tile is only
  // reattached (and its iframe reloaded) when it changes container.
  const tileCache = new Map();

  function findStream(id) {
    return state.streams.find((s) => s.id === id) || null;
  }

  // ---- persistence ----

  function saveState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        version: 1,
        streams: state.streams,
        focusedId: state.focusedId,
        lastFocusedId: state.lastFocusedId,
      }));
    } catch (err) {
      console.warn('[multistream] failed to save layout', err);
    }
  }

  function loadState() {
    let data;
    try {
      data = JSON.parse(localStorage.getItem(STORAGE_KEY));
    } catch (err) {
      console.warn('[multistream] failed to load saved layout, starting fresh', err);
      return;
    }
    if (!data || data.version !== 1 || !Array.isArray(data.streams)) return;

    const seenIds = new Set();
    const seenNames = new Set();
    for (const s of data.streams) {
      if (!s || !Number.isInteger(s.id) || typeof s.name !== 'string') continue;
      const name = s.name.trim().toLowerCase();
      if (!name || seenIds.has(s.id) || seenNames.has(name)) continue;
      seenIds.add(s.id);
      seenNames.add(name);
      state.streams.push({ id: s.id, name });
    }

    if (data.focusedId === null) {
      state.focusedId = null;
    } else if (findStream(data.focusedId)) {
      state.focusedId = data.focusedId;
    } else {
      state.focusedId = state.streams.length ? state.streams[0].id : null;
    }
    state.lastFocusedId = findStream(data.lastFocusedId) ? data.lastFocusedId : null;
    nextId = state.streams.reduce((m, s) => Math.max(m, s.id), 0) + 1;
  }

  // ---- actions ----

  function setFocus(id) {
    state.focusedId = id;
    if (id !== null) state.lastFocusedId = id;
  }

  // Returns true when the name was usable (added, or already present).
  function addStream(rawName) {
    // Stream names are case insensitive and always lowercase server side.
    const name = rawName.trim().toLowerCase();
    if (!name) return false;
    const existing = state.streams.find((s) => s.name === name);
    if (existing) {
      flashTile(existing.id);
      return true;
    }
    const stream = { id: nextId++, name };
    const wasEmpty = state.streams.length === 0;
    state.streams.push(stream);
    if (wasEmpty) setFocus(stream.id);
    render();
    markJustAdded(stream.id);
    return true;
  }

  function removeStream(id) {
    const idx = state.streams.findIndex((s) => s.id === id);
    if (idx === -1) return;
    state.streams.splice(idx, 1);
    if (state.lastFocusedId === id) state.lastFocusedId = null;
    if (state.focusedId === id) {
      const next = state.streams[idx] || state.streams[idx - 1] || null;
      setFocus(next ? next.id : null);
    }
    const entry = tileCache.get(id);
    if (entry) {
      entry.el.remove();
      tileCache.delete(id);
    }
    render();
    if (state.streams.length === 0) openAddPanel();
  }

  function togglePin(id) {
    setFocus(state.focusedId === id ? null : id);
    render();
  }

  function toggleView() {
    if (state.streams.length === 0) return;
    if (state.focusedId !== null) {
      setFocus(null);
    } else {
      setFocus(findStream(state.lastFocusedId) ? state.lastFocusedId : state.streams[0].id);
    }
    render();
  }

  function resetLayout() {
    if (!confirm('Reset the stream layout? This removes all added streams.')) return;
    for (const entry of tileCache.values()) entry.el.remove();
    tileCache.clear();
    state.streams = [];
    state.focusedId = null;
    state.lastFocusedId = null;
    nextId = 1;
    render();
    openAddPanel();
  }

  // ---- tiles ----

  function getTile(stream) {
    let entry = tileCache.get(stream.id);
    if (entry) return entry;

    const el = document.createElement('div');
    el.className = 'tile';
    el.dataset.streamId = stream.id;

    const iframe = document.createElement('iframe');
    iframe.allow = 'autoplay; encrypted-media; picture-in-picture; fullscreen';
    iframe.allowFullscreen = true;
    iframe.src = LIVE_BASE_URL + encodeURIComponent(stream.name);

    const bar = document.createElement('div');
    bar.className = 'tile-bar';

    const pinBtn = document.createElement('button');
    pinBtn.type = 'button';
    pinBtn.className = 'tile-btn tile-pin';
    pinBtn.innerHTML = PIN_SVG;
    pinBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      togglePin(stream.id);
    });

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'tile-btn tile-close';
    closeBtn.textContent = '×';
    closeBtn.title = 'Close';
    closeBtn.setAttribute('aria-label', 'Close stream');
    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      removeStream(stream.id);
    });

    bar.append(pinBtn, closeBtn);
    el.append(iframe, bar);

    entry = { el, pinBtn };
    tileCache.set(stream.id, entry);
    return entry;
  }

  function markJustAdded(id) {
    const entry = tileCache.get(id);
    if (!entry) return;
    entry.el.classList.add('just-added');
    setTimeout(() => entry.el.classList.remove('just-added'), 2500);
  }

  function flashTile(id) {
    const entry = tileCache.get(id);
    if (!entry) return;
    entry.el.classList.add('flash');
    setTimeout(() => entry.el.classList.remove('flash'), 1200);
  }

  // ---- layout ----

  // Column count that gives the largest 16:9 tile for n tiles in W x H.
  function bestGrid(n, W, H, gap) {
    let best = { cols: 1, w: 0, h: 0 };
    for (let cols = 1; cols <= n; cols++) {
      const rows = Math.ceil(n / cols);
      const maxW = (W - gap * (cols - 1)) / cols;
      const maxH = (H - gap * (rows - 1)) / rows;
      const w = Math.floor(Math.max(0, Math.min(maxW, maxH * 16 / 9)));
      if (w > best.w) best = { cols, w, h: Math.floor(w * 9 / 16) };
    }
    return best;
  }

  function layoutGrid() {
    const n = state.streams.length;
    if (state.focusedId !== null || n === 0) return;
    const cs = getComputedStyle(gridPane);
    const W = gridPane.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    const H = gridPane.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    const { cols, w, h } = bestGrid(n, W, H, GRID_GAP);
    // Pin the inner width to exactly cols tiles so wrapping matches.
    gridInner.style.setProperty('--grid-w', (cols * w + (cols - 1) * GRID_GAP) + 'px');
    gridInner.style.setProperty('--tile-w', w + 'px');
    gridInner.style.setProperty('--tile-h', h + 'px');
  }

  function render() {
    const focusMode = state.focusedId !== null;
    stage.classList.toggle('mode-focus', focusMode);
    stage.classList.toggle('mode-grid', !focusMode);
    stage.classList.toggle('single', state.streams.length <= 1);

    // Walk streams in add order, tracking the last tile placed in each
    // container. A tile is only moved when it isn't already right after
    // that one, so tiles that stay put never reload.
    const lastIn = new Map();
    for (const stream of state.streams) {
      const entry = getTile(stream);
      const focused = stream.id === state.focusedId;
      const target = !focusMode ? gridInner : (focused ? focusPane : stripInner);
      const prev = lastIn.get(target) || null;
      if (entry.el.parentNode !== target || entry.el.previousElementSibling !== prev) {
        target.insertBefore(entry.el, prev ? prev.nextSibling : target.firstChild);
      }
      lastIn.set(target, entry.el);

      entry.pinBtn.setAttribute('aria-pressed', String(focused));
      entry.pinBtn.title = focused ? 'Unpin' : 'Pin';
      entry.pinBtn.setAttribute('aria-label', focused ? 'Unpin stream' : 'Pin stream');
    }

    layoutGrid();
    viewBtn.textContent = focusMode ? 'Grid view' : 'Focus view';
    viewBtn.disabled = state.streams.length === 0;
    saveState();
  }

  new ResizeObserver(layoutGrid).observe(gridPane);

  // ---- add stream panel ----

  function openAddPanel() {
    addCancel.hidden = state.streams.length === 0;
    addInput.value = '';
    addPanel.hidden = false;
    setTimeout(() => addInput.focus(), 0);
  }

  function closeAddPanel() {
    // With nothing loaded the form is the whole page, so it stays.
    if (state.streams.length === 0) return;
    addPanel.hidden = true;
  }

  addForm.addEventListener('submit', (e) => {
    e.preventDefault();
    if (addStream(addInput.value)) addPanel.hidden = true;
  });
  addCancel.addEventListener('click', closeAddPanel);
  addInput.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeAddPanel();
  });

  // ---- global menu ----

  const menuWrap = document.getElementById('menu-wrap');
  document.getElementById('global-menu-btn').addEventListener('click', (e) => {
    e.stopPropagation();
    menuWrap.classList.toggle('open');
  });
  document.addEventListener('click', (e) => {
    if (menuWrap.classList.contains('open') && !menuWrap.contains(e.target)) {
      menuWrap.classList.remove('open');
    }
  });
  document.getElementById('menu-add-stream').addEventListener('click', () => {
    menuWrap.classList.remove('open');
    openAddPanel();
  });
  viewBtn.addEventListener('click', () => {
    menuWrap.classList.remove('open');
    toggleView();
  });
  document.getElementById('menu-reset-layout').addEventListener('click', () => {
    menuWrap.classList.remove('open');
    resetLayout();
  });

  menuWrap.classList.add('just-added');
  setTimeout(() => menuWrap.classList.remove('just-added'), 3000);

  loadState();
  render();
  if (state.streams.length === 0) openAddPanel();
})();
</script>
</body>
</html>
```

- [ ] **Step 2: Syntax check the script**

Run:

```bash
cd /home/glizzy/Projects/rakuspace/frontend && python_modules/bin/python - <<'EOF'
import re, pathlib
src = pathlib.Path("templates/multistream.html").read_text()
scripts = re.findall(r"<script>(.*?)</script>", src, re.S)
assert len(scripts) == 1, len(scripts)
pathlib.Path("/tmp/claude-1000/-home-glizzy-Projects-rakuspace/e2ffc1f2-34c6-42f7-ac8f-af28810b410a/scratchpad/ms_check.js").write_text(scripts[0])
EOF
node --check /tmp/claude-1000/-home-glizzy-Projects-rakuspace/e2ffc1f2-34c6-42f7-ac8f-af28810b410a/scratchpad/ms_check.js && echo OK
```

Expected: `OK`. (The `{{ lite_prefix }}` inside a string literal is valid JS as is.)

- [ ] **Step 3: Check bestGrid math in node**

Run:

```bash
node -e '
function bestGrid(n, W, H, gap) {
  let best = { cols: 1, w: 0, h: 0 };
  for (let cols = 1; cols <= n; cols++) {
    const rows = Math.ceil(n / cols);
    const maxW = (W - gap * (cols - 1)) / cols;
    const maxH = (H - gap * (rows - 1)) / rows;
    const w = Math.floor(Math.max(0, Math.min(maxW, maxH * 16 / 9)));
    if (w > best.w) best = { cols, w, h: Math.floor(w * 9 / 16) };
  }
  return best;
}
console.log(JSON.stringify([bestGrid(1,1904,1064,8), bestGrid(2,1904,1064,8), bestGrid(4,1904,1064,8), bestGrid(5,1904,1064,8), bestGrid(10,1904,1064,8)]));
'
```

Expected: cols of `1, 2, 2, 3, 4` for n of `1, 2, 4, 5, 10`, every `w` positive, and for each result `cols * w + (cols - 1) * 8 <= 1904`. If the function body here differs from the template, fix the template so they match.

- [ ] **Step 4: Run the test suite**

Run: `cd /home/glizzy/Projects/rakuspace/frontend && python_modules/bin/python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Hand off for commit**

Do not commit. Report done; the controller commits as "Add conference style multistream view".

---

### Task 3: Docs and manual check

**Files:**
- Modify: `CLAUDE.md` (Pages list, `/multistream` bullet)
- Modify: `frontend/README.md` (`/multistream` bullet)

**Interfaces:**
- Consumes: Tasks 1 and 2.

- [ ] **Step 1: Update CLAUDE.md**

Replace:

```markdown
  - `/multistream` — multi-tile stream multiplexer (`multistream.html`).
```

with:

```markdown
  - `/multistream` — multi-tile stream viewer. Default is a conference style view (`multistream.html`): first stream focused at 16:9 with the rest in a scrolling bottom strip, or a 16:9 grid when nothing is pinned; state in localStorage `rakuspace-multistream-v1`. `?advanced=1` serves the old free form split layout (`multistream_advanced.html`), and each links to the other from its burger menu. Only tiles that change container reload, since moving an iframe reloads it.
```

- [ ] **Step 2: Update frontend/README.md**

Replace:

```markdown
 - `/multistream`
  - Multi-tile stream multiplexer.
```

with:

```markdown
 - `/multistream`
  - Multi-tile stream viewer. One stream focused with the rest in a strip along the bottom, or a grid. Pin a tile to focus it. `?advanced=1` gives the older free form split layout.
```

- [ ] **Step 3: Run tests**

Run: `cd /home/glizzy/Projects/rakuspace/frontend && python_modules/bin/python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 4: Hand off for commit**

Do not commit. Report done; the controller commits as "Document multistream simple and advanced modes".

- [ ] **Step 5: Manual browser check (controller and user)**

Start the dev server (`cd /home/glizzy/Projects/rakuspace/frontend && python_modules/bin/python RakuSpace.py`) and open `/multistream`:

- Fresh visit: name form centered, no Cancel button.
- Add 1 stream: fills the page at 16:9, no strip.
- Add 2, 5, ~10: first stays focused, others in strip; strip centered, then scrolls with the first tile not clipped.
- Pin a strip tile: it moves to focus, old focus returns to its add order slot; other strip tiles do not reload.
- Pin the focused tile: grid view, sensible column count, last row centered.
- Menu "Focus view" restores the last pinned stream. Label flips correctly.
- Close the focused stream: next stream takes focus.
- Duplicate name: existing tile flashes, no new tile.
- Resize window in both views.
- Reload: streams, focus and view persist.
- Menu "Advanced mode" opens the old viewer; its "Simple mode" link comes back. Same under `/lite/multistream`.
