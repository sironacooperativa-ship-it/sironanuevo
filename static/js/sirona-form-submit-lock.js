/**
 * Evita doble envío de formularios: bloquea re-clics mientras el POST está en curso.
 * Los botones primarios (azules) pasan a gris mientras están deshabilitados.
 */
(function (w) {
  "use strict";

  var LOCKED = "data-sirona-submit-locked";
  var PROCESSING = "sirona-btn-processing";

  function isPrimaryLike(btn) {
    if (!btn || !btn.classList) return false;
    if (btn.classList.contains("btn-primary") || btn.classList.contains("btn-outline-primary")) {
      return true;
    }
    return btn.classList.contains("action-button") && btn.classList.contains("primary");
  }

  function submitControls(form) {
    var list = [];
    if (!form) return list;

    form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach(function (el) {
      list.push(el);
    });

    var fid = form.getAttribute("id");
    if (fid) {
      document.querySelectorAll('[form="' + fid + '"]').forEach(function (el) {
        if (el.tagName === "INPUT" && el.type === "submit") list.push(el);
        if (el.tagName === "BUTTON" && (!el.type || el.type === "submit")) list.push(el);
      });
    }
    return list;
  }

  function lock(form, submitter) {
    if (!form || form.getAttribute(LOCKED) === "1") return;
    form.setAttribute(LOCKED, "1");
    form.setAttribute("aria-busy", "true");

    submitControls(form).forEach(function (btn) {
      btn.disabled = true;
      if (isPrimaryLike(btn)) btn.classList.add(PROCESSING);
    });

    if (submitter && submitter !== form && !submitter.disabled) {
      submitter.disabled = true;
      if (isPrimaryLike(submitter)) submitter.classList.add(PROCESSING);
    }
  }

  function shouldSkip(form) {
    return !form || form.hasAttribute("data-sirona-no-submit-lock");
  }

  document.addEventListener(
    "submit",
    function (ev) {
      var form = ev.target;
      if (!(form instanceof HTMLFormElement)) return;
      if (shouldSkip(form)) return;
      if (form.getAttribute(LOCKED) === "1") {
        ev.preventDefault();
        ev.stopImmediatePropagation();
      }
    },
    true
  );

  document.addEventListener(
    "submit",
    function (ev) {
      if (ev.defaultPrevented) return;
      var form = ev.target;
      if (!(form instanceof HTMLFormElement)) return;
      if (shouldSkip(form)) return;
      lock(form, ev.submitter || null);
    },
    false
  );

  w.SironaFormSubmitLock = { lock: lock };
})(typeof window !== "undefined" ? window : this);
