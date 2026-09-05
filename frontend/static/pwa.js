// Registers the install-only service worker on every page that includes
// this script. Safe to include on pages with no manifest link too - a
// service worker with no manifest just does nothing installable.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // Best-effort. Install just won't be offered if this fails.
    });
  });
}
