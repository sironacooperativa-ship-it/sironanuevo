/**
 * Cierra la sesión en el servidor al cerrar la pestaña o ventana del navegador.
 * No interrumpe: navegación interna (clic/enlace), envío de formularios (GET/POST),
 * recargas (F5), historial atrás/adelante ni restauración desde caché (bfcache).
 * La caducidad deslizante sigue en SESSION_COOKIE_AGE + SESSION_SAVE_EVERY_REQUEST.
 */
(function () {
  try {
    var body = document.body;
    var url = body && body.getAttribute("data-sirona-sesion-cerrar-ventana-url");
    if (!url) return;

    var STORAGE_TS = "sirona_internal_nav_ts";

    function getCookie(name) {
      var parts = ("; " + document.cookie).split("; " + name + "=");
      if (parts.length === 2) {
        return parts.pop().split(";").shift() || "";
      }
      return "";
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

    function isReloadNavigation() {
      try {
        var nav = performance.getEntriesByType("navigation")[0];
        if (nav && nav.type === "reload") return true;
      } catch (e1) {}
      try {
        if (performance.navigation && performance.navigation.type === 1) return true;
      } catch (e2) {}
      return false;
    }

    function isBackForwardNavigation() {
      try {
        var nav = performance.getEntriesByType("navigation")[0];
        if (nav && nav.type === "back_forward") return true;
      } catch (e3) {}
      try {
        if (performance.navigation && performance.navigation.type === 2) return true;
      } catch (e4) {}
      return false;
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
      "submit",
      function (e) {
        var form = e.target;
        if (!form || form.tagName !== "FORM") return;
        if (formActionIsSameOrigin(form)) markInternalNavigation();
      },
      true
    );

    window.addEventListener("pageshow", function () {
      try {
        sessionStorage.removeItem(STORAGE_TS);
      } catch (e) {}
    });

    window.addEventListener("pagehide", function (ev) {
      if (ev.persisted) return;
      if (isReloadNavigation()) return;
      if (isBackForwardNavigation()) return;
      var ts = null;
      try {
        ts = sessionStorage.getItem(STORAGE_TS);
      } catch (e3) {
        ts = null;
      }
      if (ts && Date.now() - parseInt(ts, 10) < 20000) return;

      var token = getCookie("csrftoken");
      if (!token) return;

      var payload = "csrfmiddlewaretoken=" + encodeURIComponent(token);
      var blob = new Blob([payload], { type: "application/x-www-form-urlencoded" });

      if (typeof navigator.sendBeacon === "function") {
        try {
          if (navigator.sendBeacon(url, blob)) return;
        } catch (e4) {}
      }

      try {
        fetch(url, {
          method: "POST",
          credentials: "same-origin",
          keepalive: true,
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: payload,
        });
      } catch (e5) {}
    });
  } catch (e) {}
})();
