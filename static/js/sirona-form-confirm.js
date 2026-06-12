(function () {
  document.addEventListener(
    "submit",
    function (ev) {
      const form = ev.target;
      if (!(form instanceof HTMLFormElement)) return;
      const msg = (form.getAttribute("data-sirona-confirm") || "").trim();
      if (!msg) return;
      if (form.dataset.sironaConfirmOk === "1") {
        delete form.dataset.sironaConfirmOk;
        return;
      }
      const submitter = ev.submitter || null;
      ev.preventDefault();
      if (window.confirm(msg)) {
        form.dataset.sironaConfirmOk = "1";
        try {
          if (submitter && typeof form.requestSubmit === "function") {
            form.requestSubmit(submitter);
          } else if (typeof form.requestSubmit === "function") {
            form.requestSubmit();
          } else {
            form.submit();
          }
        } catch (e) {
          form.submit();
        }
      }
    },
    true
  );
})();
