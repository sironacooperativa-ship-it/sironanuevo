(function () {
  // Preserva posición de scroll después de un POST (ediciones en tablas, etc.).
  // Se guarda al submit y se restaura una sola vez al recargar.
  const KEY = "sirona_scroll_restore:" + window.location.pathname + window.location.search;
  // Preserva posición al volver desde pantallas de edición/creación (GET -> GET).
  const RETURN_KEY = "sirona_scroll_return";
  const MODAL_SCROLL_KEY = "sirona_modal_scroll_y";
  const DISABLE_ATTR = "data-sirona-no-scroll-restore";

  function getScrollY() {
    return window.scrollY || document.documentElement.scrollTop || 0;
  }

  function fullUrl() {
    return window.location.pathname + (window.location.search || "");
  }

  function restoreTo(y) {
    const top = Math.max(0, parseInt(String(y || "0"), 10) || 0);
    window.setTimeout(function () {
      try {
        window.scrollTo({ top: top, left: 0, behavior: "instant" });
      } catch (e) {
        window.scrollTo(0, top);
      }
    }, 0);
  }

  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (raw) {
      window.sessionStorage.removeItem(KEY);
      restoreTo(raw);
    }
  } catch (e) {}

  // Restore when returning from edit/create pages.
  function tryRestoreReturn() {
    try {
      const raw = window.sessionStorage.getItem(RETURN_KEY);
      if (!raw) return;
      const obj = JSON.parse(raw);
      if (!obj || obj.url !== fullUrl()) return;
      window.sessionStorage.removeItem(RETURN_KEY);
      restoreTo(obj.y);
    } catch (e) {}
  }

  tryRestoreReturn();
  window.addEventListener("pageshow", tryRestoreReturn);

  // When opening edit/create (modal or full page), remember current scroll to restore later.
  function looksLikeEditOrCreateUrl(u) {
    const p = (u && u.pathname) ? u.pathname : "";
    return (
      /\/(nuevo|editar)\//i.test(p) ||
      /\/(create|update)\b/i.test(p) ||
      (u && u.searchParams && u.searchParams.get("modal") === "1")
    );
  }

  document.addEventListener(
    "click",
    function (ev) {
      const a = ev.target && ev.target.closest ? ev.target.closest("a[href], [data-sirona-modal-url]") : null;
      if (!a) return;
      const hrefRaw = (a.getAttribute("data-sirona-modal-url") || a.getAttribute("href") || "").trim();
      if (!hrefRaw || hrefRaw === "#") return;
      let u;
      try {
        u = new URL(hrefRaw, window.location.origin);
      } catch (e) {
        return;
      }
      if (u.origin !== window.location.origin) return;
      if (!looksLikeEditOrCreateUrl(u)) return;
      try {
        window.sessionStorage.setItem(RETURN_KEY, JSON.stringify({ url: fullUrl(), y: getScrollY() }));
      } catch (e) {}
    },
    true
  );

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

  // Modal: al cerrar, volver al scroll anterior (evita saltos por focus).
  try {
    const modalEl = document.getElementById("sironaModal");
    if (modalEl) {
      modalEl.addEventListener("show.bs.modal", function () {
        try {
          window.sessionStorage.setItem(MODAL_SCROLL_KEY, String(getScrollY()));
        } catch (e) {}
      });
      modalEl.addEventListener("hidden.bs.modal", function () {
        try {
          const y = window.sessionStorage.getItem(MODAL_SCROLL_KEY);
          window.sessionStorage.removeItem(MODAL_SCROLL_KEY);
          if (y) restoreTo(y);
        } catch (e) {}
      });
    }
  } catch (e) {}
})();

