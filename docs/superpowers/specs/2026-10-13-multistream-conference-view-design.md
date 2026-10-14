# Multistream conference view

## Goal

Replace the default `/multistream` page with a video conference style layout,
modeled on Discord screenshare: one focused stream at a proper 16:9 size, the
rest in a horizontal strip along the bottom, plus a grid view. Adding a stream
should never require rearranging the layout by hand.

The current split tree viewer stays available, unchanged, as advanced mode.

## Non-goals

- No avoiding iframe reloads on focus changes. A stream reloads when it moves
  between the focus pane and the strip. This is accepted.
- No full tile overlays and no click to focus. OvenPlayer misbehaves under
  overlays, and strip tiles must keep usable player controls (mute in
  particular).
- No stream name labels. OvenPlayer already shows one.
- No right click menus, no drag reordering, no resizing.
- No JS test harness.
- No migration of saved advanced layouts into the new view.

## Files and routes

- `frontend/templates/multistream.html` is renamed to
  `frontend/templates/multistream_advanced.html`. Its only change is a menu
  item, "Simple mode", linking to the same path without the query string.
  Its localStorage key stays as is.
- New `frontend/templates/multistream.html` holds the conference view.
- `/multistream` and `/lite/multistream` render `multistream_advanced.html`
  when `request.args.get("advanced") == "1"`, otherwise `multistream.html`.
  Both still pass `lite_prefix`.

## Menu

Same burger menu as today, top right, same styling and fade behavior. Items:

- **Add stream**
- **Grid view** / **Focus view**: one toggle, labeled with what it switches
  to
- **Advanced mode**: link to `?advanced=1` on the current path
- **Reset layout**: confirm, then clear all streams

No other new icons outside the menu, apart from the per tile pin.

## State

Persisted to localStorage under `rakuspace-multistream-v1`:

```
{ version: 1,
  streams: [{ id, name }],   // add order = strip order
  focusedId: id | null,      // null = grid view
  lastFocusedId: id | null   // target for the Focus view toggle
}
```

Rules:

- Adding the first stream focuses it. Later adds append to `streams`. They
  land in the strip in focus view, or in the grid in grid view.
- Pin on an unfocused tile sets `focusedId` to it.
- Pin on the focused tile clears `focusedId` (grid view).
- Menu toggle in focus view clears `focusedId`. In grid view it sets
  `focusedId` to `lastFocusedId` if that stream still exists, else the
  first stream. Does nothing with zero streams.
- Closing the focused stream promotes the next stream in add order (or the
  previous one if it was last). With no streams left, `focusedId` is null.
- `lastFocusedId` updates whenever `focusedId` is set to a stream.
- Names are trimmed and lowercased on submit. Adding a name already present
  does nothing except briefly highlight the existing tile.

## Layout

### Focus view

- The page is a column: focus pane (`flex: 1`) above the strip.
- The focused tile is `aspect-ratio: 16/9`, `max-width: 100%`,
  `max-height: 100%`, centered, black letterboxing around it.
- The strip is a horizontal row of fixed size 16:9 tiles, height
  `clamp(90px, 16vh, 200px)`, 8px gap. Centered when it fits, scrolls
  horizontally (`overflow-x: auto`) when it does not. Centering must not
  clip the first tile on overflow (use an inner wrapper with
  `margin: 0 auto`, not plain `justify-content: center`).
- The strip is hidden when there is only one stream.

### Grid view

- All streams in one wrapping flex container, last partial row centered.
- A small function picks the column count (1 to n) that gives the largest
  16:9 tile for the container size and stream count, and sets tile width and
  height. It reruns via a ResizeObserver on the container.

### Rendering

- Tile elements (a wrapper holding the `/live/<name>` iframe and the tile
  buttons) are cached by stream id.
- `render()` places each tile in its target container and only calls
  `appendChild` when the tile's parent actually differs, so tiles that do
  not change container never reload. Tile order within a container follows
  add order; reorder only when needed.
- Removed streams have their element removed and dropped from the cache.

### Tile chrome

- Top left, shown on hover (and on keyboard focus): a pin button and a close
  button. Same look and fade as the current `.tile-close`.
- The pin is highlighted in the accent color on the focused tile.
- Nothing else is drawn over the iframe.

## Add stream flow

- "Add stream" opens the existing name form (input, Load, Cancel, same
  styling) as a small floating panel centered on the page. Escape or Cancel
  closes it.
- With zero streams the form is shown centered by default.

## Error handling

- Saved state that fails to parse, has an unknown version, or has a malformed
  shape is discarded and the view starts empty, like advanced mode does.
- A `focusedId` pointing at a missing stream falls back to the first stream.
- localStorage unavailable or throwing: the view works, just without
  persistence. All reads and writes are wrapped in try/catch.
- Offline or unknown stream names are not validated. `player.html` shows its
  own offline state.

## Testing

pytest, in `frontend/tests/test_rakuspace.py`:

- `/multistream` renders the conference view.
- `/multistream?advanced=1` renders the advanced view.
- `/lite/multistream` and `/lite/multistream?advanced=1` do the same, with
  `/lite/live/` as the iframe base.
- Each view contains the link to the other.

Manual browser check:

- 1, 2, 5 and ~10 streams in focus view and grid view.
- Toggle between views, pin and unpin, close the focused stream.
- Strip scroll on overflow, first tile not clipped.
- Window resize in both views.
- Reload keeps streams, focus and view.
- Advanced mode still works and links back.
