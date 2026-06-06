(function () {
  "use strict";

  var guarded = [];

  var MESSAGES = {
    presupuesto:
      "Hay un presupuesto sin guardar.\n\n¿Salir de esta página?\n\n" +
      "• Cancelar: seguir cargando\n" +
      "• Aceptar: salir y descartar lo cargado",
    pedido:
      "Hay un pedido sin guardar.\n\n¿Salir de esta página?\n\n" +
      "• Cancelar: seguir cargando\n" +
      "• Aceptar: salir y descartar lo cargado",
  };

  function resolveMessage(form) {
    var key = (form.getAttribute("data-sirona-leave-guard") || "").trim();
    if (MESSAGES[key]) return MESSAGES[key];
    if (key) return key;
    return (
      "Hay datos sin guardar.\n\n¿Salir de esta página?\n\n" +
      "• Cancelar: seguir cargando\n" +
      "• Aceptar: salir y descartar lo cargado"
    );
  }

  function isNavigationLink(a) {
    if (!a || a.tagName !== "A") return false;
    if (a.hasAttribute("data-sirona-modal-url")) return false;
    if (a.hasAttribute("data-sirona-no-leave-guard")) return false;
    if ((a.getAttribute("target") || "").toLowerCase() === "_blank") return false;
    if (a.hasAttribute("download")) return false;
    var href = (a.getAttribute("href") || "").trim();
    if (!href || href === "#" || href.indexOf("javascript:") === 0) return false;
    var url;
    try {
      url = new URL(a.href, window.location.href);
    } catch (e) {
      return false;
    }
    if (url.origin !== window.location.origin) return false;
    var cur = new URL(window.location.href);
    if (url.pathname === cur.pathname && url.search === cur.search) return false;
    return true;
  }

  function initFormGuard(form) {
    if (!form || form.dataset.sironaLeaveGuardInit === "1") return;
    form.dataset.sironaLeaveGuardInit = "1";

    var dirty = false;
    var submitting = false;
    var message = resolveMessage(form);

    function setDirty() {
      dirty = true;
    }

    function shouldGuard() {
      return dirty && !submitting;
    }

    function allowLeave() {
      dirty = false;
    }

    form.addEventListener(
      "input",
      function () {
        setDirty();
      },
      true
    );
    form.addEventListener(
      "change",
      function () {
        setDirty();
      },
      true
    );
    form.addEventListener(
      "click",
      function (ev) {
        if (ev.target.closest(".js-remove, #btnAddLinea")) setDirty();
      },
      true
    );
    form.addEventListener(
      "submit",
      function () {
        submitting = true;
        dirty = false;
      },
      true
    );

    guarded.push({ shouldGuard: shouldGuard, allowLeave: allowLeave, message: message });
  }

  document.addEventListener(
    "click",
    function (ev) {
      var active = null;
      for (var i = 0; i < guarded.length; i++) {
        if (guarded[i].shouldGuard()) {
          active = guarded[i];
          break;
        }
      }
      if (!active) return;

      var a = ev.target.closest("a[href]");
      if (!isNavigationLink(a)) return;

      if (!window.confirm(active.message)) {
        ev.preventDefault();
        ev.stopImmediatePropagation();
        return;
      }
      active.allowLeave();
    },
    true
  );

  window.addEventListener("beforeunload", function (ev) {
    for (var i = 0; i < guarded.length; i++) {
      if (guarded[i].shouldGuard()) {
        ev.preventDefault();
        ev.returnValue = "";
        return;
      }
    }
  });

  function boot() {
    document.querySelectorAll("[data-sirona-leave-guard]").forEach(initFormGuard);
  }

  window.SironaFormGuard = { init: initFormGuard, boot: boot };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
