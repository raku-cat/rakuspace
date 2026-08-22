/* Shared sizing behaviour for the IRC chat pane on the player pages
   (player.html and multistream.html).

   Those pages own *whether* chat is shown -- they have different persistence
   models for that (a per-stream localStorage flag vs. a field in the saved
   multistream layout) -- and they own loading/unloading the iframe. This
   module owns everything about how wide the pane is:

     - a sensible default width computed from the viewport, rather than the
       fixed 4:1 flex ratio these pages used to share, which squeezed chat
       into an unusable sliver on small windows and let it sprawl on large
       ones;
     - a draggable divider on the pane's inner edge, with the chosen width
       remembered across reloads;
     - a narrow-viewport mode where side-by-side stops making sense at all,
       so chat auto-hides and, if the viewer explicitly opens it, covers the
       video instead of splitting with it.

   Usage:

     const sizer = RakuChatPane.create({ layout, pane, storageKey, onNarrowChange });
     sizer.update(shown);   // whenever the page's own visibility state changes
     sizer.isNarrow();      // to decide the page's default visibility
*/
(function () {
  "use strict";

  // Below this viewport width a side-by-side video/chat split leaves both
  // panes too small to use, so chat becomes an overlay instead.
  var NARROW_WIDTH = 700;

  // The video pane never gets squeezed below this, however wide chat is.
  var MIN_VIDEO_PX = 320;
  var MIN_CHAT_PX = 220;

  function defaultWidth() {
    // Roughly a quarter of the window, bounded to a comfortable reading
    // width for chat -- wide windows get a proportionally narrower pane.
    return Math.round(Math.min(Math.max(window.innerWidth * 0.24, 280), 420));
  }

  function create(opts) {
    var layout = opts.layout;
    var pane = opts.pane;
    var storageKey = opts.storageKey;
    var onNarrowChange = opts.onNarrowChange || function () {};

    var narrow = window.innerWidth < NARROW_WIDTH;
    var width = null; // null means "still following the computed default"

    try {
      var saved = parseInt(window.localStorage.getItem(storageKey), 10);
      if (!isNaN(saved) && saved > 0) width = saved;
    } catch (err) {
      // localStorage unavailable (private browsing etc.) -- use the default.
    }

    function saveWidth() {
      try {
        window.localStorage.setItem(storageKey, String(Math.round(width)));
      } catch (err) {
        // ignore -- the width just won't survive a reload
      }
    }

    // Clamped at read time rather than at write time so that a width saved on
    // a wide monitor doesn't crush the video when the same layout is later
    // opened in a small window.
    function effectiveWidth() {
      var max = Math.max(window.innerWidth - MIN_VIDEO_PX, MIN_CHAT_PX);
      return Math.min(Math.max(width === null ? defaultWidth() : width, MIN_CHAT_PX), max);
    }

    var resizer = document.createElement("div");
    resizer.id = "chat-resizer";
    resizer.className = "chat-resizer hidden";
    resizer.setAttribute("role", "separator");
    resizer.setAttribute("aria-orientation", "vertical");
    resizer.setAttribute("aria-label", "Resize chat");
    resizer.tabIndex = 0;
    layout.insertBefore(resizer, pane);

    var drag = null;

    resizer.addEventListener("mousedown", function (e) {
      e.preventDefault();
      drag = { startX: e.clientX, startWidth: effectiveWidth() };
      document.body.classList.add("chat-resizing");
    });

    document.addEventListener("mousemove", function (e) {
      if (!drag) return;
      // The pane is on the right, so dragging left widens it.
      width = drag.startWidth - (e.clientX - drag.startX);
      pane.style.width = effectiveWidth() + "px";
    });

    document.addEventListener("mouseup", function () {
      if (!drag) return;
      drag = null;
      document.body.classList.remove("chat-resizing");
      width = effectiveWidth();
      saveWidth();
    });

    resizer.addEventListener("keydown", function (e) {
      var step = e.shiftKey ? 50 : 10;
      if (e.key === "ArrowLeft") width = effectiveWidth() + step;
      else if (e.key === "ArrowRight") width = effectiveWidth() - step;
      else return;
      e.preventDefault();
      width = effectiveWidth();
      pane.style.width = width + "px";
      saveWidth();
    });

    function update(shown) {
      pane.classList.toggle("overlay", narrow && shown);
      if (narrow || !shown) {
        pane.style.width = "";
        resizer.classList.add("hidden");
      } else {
        pane.style.width = effectiveWidth() + "px";
        resizer.classList.remove("hidden");
      }
    }

    window.addEventListener("resize", function () {
      var nowNarrow = window.innerWidth < NARROW_WIDTH;
      if (nowNarrow !== narrow) {
        narrow = nowNarrow;
        // Let the page recompute visibility for the new mode; it calls back
        // into update() with the result.
        onNarrowChange(narrow);
        return;
      }
      if (!narrow && !pane.classList.contains("hidden")) {
        pane.style.width = effectiveWidth() + "px";
      }
    });

    return {
      update: update,
      isNarrow: function () { return narrow; },
    };
  }

  window.RakuChatPane = { create: create, NARROW_WIDTH: NARROW_WIDTH };
})();
