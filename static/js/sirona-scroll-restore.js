(function () {
  // Preserva posición de scroll después de un POST (ediciones en tablas, etc.).
  // Se guarda al submit y se restaura una sola vez al recargar.
  const KEY = "sirona_scroll_restore:" + window.location.pathname + window.location.search;
  const DISABLE_ATTR = "data-sirona-no-scroll-restore";

  function getScrollY() {
    return window.scrollY || document.documentElement.scrollTop || 0;
  }

  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (raw) {
      window.sessionStorage.removeItem(KEY);
      const y = Math.max(0, parseInt(raw, 10) || 0);
      window.setTimeout(function () {
        window.scrollTo({ top: y, left: 0, behavior: "instant" });
      }, 0);
    }
  } catch (e) {}

  document.addEventListener(
    "submit",
    function (ev) {
      const form = ev.target;
      if (!form || form.nodeName !== "FORM") return;
      if (form.hasAttribute(DISABLE_ATTR)) return;
      try {
        window.sessionStorage.setItem(KEY, String(getScrollY()));
      } catch (e) {}
    },
    true
  );
})();

