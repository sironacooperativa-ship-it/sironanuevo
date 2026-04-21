(function () {
  const modalEl = document.getElementById("sironaModal");
  const contentEl = document.getElementById("sironaModalContent");
  if (!modalEl || !contentEl || typeof bootstrap === "undefined") return;

  const modal = new bootstrap.Modal(modalEl);
  document.addEventListener("click", function (ev) {
    const btn = ev.target.closest("[data-sirona-modal-url]");
    if (!btn) return;
    ev.preventDefault();
    const url = btn.getAttribute("data-sirona-modal-url");
    if (!url) return;
    contentEl.innerHTML = '<div class="p-4 text-center text-muted small">Cargando…</div>';
    modal.show();
    fetch(url, {
      headers: { "X-Requested-With": "XMLHttpRequest", Accept: "text/html" },
      credentials: "same-origin",
    })
      .then(function (r) {
        if (!r.ok) throw new Error("fetch");
        return r.text();
      })
      .then(function (html) {
        contentEl.innerHTML = html;
        if (typeof window.sironaInitProductoFormPrecio === "function") {
          window.sironaInitProductoFormPrecio(contentEl);
        }
      })
      .catch(function () {
        contentEl.innerHTML =
          '<div class="modal-body"><p class="text-danger small mb-0">No se pudo cargar el formulario.</p></div>';
      });
  });
  modalEl.addEventListener("hidden.bs.modal", function () {
    contentEl.innerHTML = "";
  });
})();

