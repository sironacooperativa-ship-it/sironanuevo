/**
 * Confirmación antes de borrar/enviar acciones sensibles.
 * Usa form.submit() nativo (no dispara listeners submit) para evitar bucles.
 */
(function () {
  function enviarFormulario(form) {
    if (!form) return;
    HTMLFormElement.prototype.submit.call(form);
  }

  document.addEventListener(
    "click",
    function (ev) {
      const btn = ev.target && ev.target.closest ? ev.target.closest("[data-sirona-confirm-submit]") : null;
      if (!btn) return;
      const form = btn.form || (btn.closest ? btn.closest("form") : null);
      if (!form) return;
      ev.preventDefault();
      ev.stopPropagation();
      const msg = (btn.getAttribute("data-sirona-confirm-submit") || "").trim();
      if (!msg || !window.confirm(msg)) return;
      enviarFormulario(form);
    },
    true
  );

  document.addEventListener(
    "submit",
    function (ev) {
      const form = ev.target;
      if (!(form instanceof HTMLFormElement)) return;
      const msg = (form.getAttribute("data-sirona-confirm") || "").trim();
      if (!msg) return;
      ev.preventDefault();
      if (!window.confirm(msg)) return;
      form.removeAttribute("data-sirona-confirm");
      enviarFormulario(form);
    },
    true
  );
})();
