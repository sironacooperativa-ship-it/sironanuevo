/**
 * Confirmación antes de enviar formularios con data-sirona-confirm.
 * Tras confirmar, quita el atributo y reenvía: así el segundo envío no vuelve a interceptarse.
 */
(function () {
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
      try {
        if (typeof form.requestSubmit === "function") {
          form.requestSubmit();
        } else {
          form.submit();
        }
      } catch (e) {
        form.submit();
      }
    },
    true
  );
})();
