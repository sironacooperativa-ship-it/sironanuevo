/**
 * Coordina varias pestañas abiertas del sistema.
 *
 * Solo marca la sesión como "pendiente de cierre" cuando se cierra la última pestaña.
 * Si una pestaña se recarga o se vuelve a abrir enseguida, cancela ese cierre pendiente.
 */
(function () {
  try {
    var body = document.body;
    var url = body && body.getAttribute("data-sirona-sesion-cerrar-ventana-url");
    if (!url) return;

    var STORAGE_TS = "sirona_internal_nav_ts";
    var TABS_KEY = "sirona_open_tabs_v1";
    var TAB_ID = String(Date.now()) + "-" + Math.random().toString(36).slice(2);
    var HEARTBEAT_MS = 4000;
    var STALE_MS = 120000;

    function getCookie(name) {
      var parts = ("; " + document.cookie).split("; " + name + "=");
      if (parts.length === 2) {
        return parts.pop().split(";").shift() || "";
      }
      return "";
    }

    function postSessionAction(action) {
      var token = getCookie("csrftoken");
      if (!token) return;
      var payload = "csrfmiddlewaretoken=" + encodeURIComponent(token) + "&action=" + encodeURIComponent(action);
      var blob = new Blob([payload], { type: "application/x-www-form-urlencoded" });

      if (typeof navigator.sendBeacon === "function") {
        try {
          if (navigator.sendBeacon(url, blob)) return;
        } catch (e1) {}
      }

      try {
        fetch(url, {
          method: "POST",
          credentials: "same-origin",
          keepalive: true,
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: payload,
        });
      } catch (e2) {}
    }

    function readTabs() {
      try {
        return JSON.parse(localStorage.getItem(TABS_KEY) || "{}") || {};
      } catch (e) {
        return {};
      }
    }

    function writeTabs(tabs) {
      try {
        localStorage.setItem(TABS_KEY, JSON.stringify(tabs || {}));
      } catch (e) {}
    }

    function pruneTabs(tabs, now) {
      var out = {};
      Object.keys(tabs || {}).forEach(function (id) {
        var ts = parseInt(tabs[id], 10);
        if (Number.isFinite(ts) && now - ts <= STALE_MS) out[id] = ts;
      });
      return out;
    }

    function registerTab() {
      var now = Date.now();
      var tabs = pruneTabs(readTabs(), now);
      tabs[TAB_ID] = now;
      writeTabs(tabs);
    }

    function unregisterTab() {
      var now = Date.now();
      var tabs = pruneTabs(readTabs(), now);
      delete tabs[TAB_ID];
      writeTabs(tabs);
      return Object.keys(tabs).length;
    }

    function markInternalNavigation() {
      try {
        sessionStorage.setItem(STORAGE_TS, String(Date.now()));
      } catch (e) {}
    }

    function formActionIsSameOrigin(form) {
      if (!form || !form.getAttribute) return false;
      var act = form.getAttribute("action");
      if (!act || act.charAt(0) === "#") return true;
      try {
        return new URL(form.action, location.href).origin === location.origin;
      } catch (err) {
        return false;
      }
    }

    document.addEventListener(
      "click",
      function (e) {
        var t = e.target;
        if (!t || !t.closest) return;
        var a = t.closest("a[href]");
        if (a) {
          if (a.getAttribute("target") === "_blank" || a.hasAttribute("download")) return;
          var href = a.getAttribute("href") || "";
          if (!href || href.charAt(0) === "#" || href.indexOf("javascript:") === 0) return;
          try {
            var u = new URL(a.href, location.href);
            if (u.origin === location.origin) markInternalNavigation();
          } catch (err) {}
          return;
        }

        var sub = t.closest(
          'button[type="submit"],input[type="submit"],input[type="image"],button:not([type])'
        );
        if (sub && sub.form && formActionIsSameOrigin(sub.form)) {
          markInternalNavigation();
        }
      },
      true
    );

    document.addEventListener(
      "keydown",
      function (e) {
        if (e.key === "F5" || ((e.ctrlKey || e.metaKey) && String(e.key || "").toLowerCase() === "r")) {
          markInternalNavigation();
        }
      },
      true
    );

    document.addEventListener(
      "submit",
      function (e) {
        var form = e.target;
        if (!form || form.tagName !== "FORM") return;
        if (formActionIsSameOrigin(form)) markInternalNavigation();
      },
      true
    );

    registerTab();
    postSessionAction("cancel");
    var heartbeat = window.setInterval(registerTab, HEARTBEAT_MS);

    window.addEventListener("pageshow", function () {
      try {
        sessionStorage.removeItem(STORAGE_TS);
      } catch (e) {}
      registerTab();
      postSessionAction("cancel");
    });

    window.addEventListener("pagehide", function (ev) {
      if (ev.persisted) return;
      var ts = null;
      try {
        ts = sessionStorage.getItem(STORAGE_TS);
      } catch (e3) {
        ts = null;
      }
      try {
        window.clearInterval(heartbeat);
      } catch (e4) {}

      var activeAfterClose = unregisterTab();
      if (ts && Date.now() - parseInt(ts, 10) < 20000) return;
      if (activeAfterClose <= 0) postSessionAction("pending");
    });
  } catch (e) {}
})();
