(function () {
  const modalEl = document.getElementById("sironaModal");
  const contentEl = document.getElementById("sironaModalContent");
  if (!modalEl || !contentEl || typeof bootstrap === "undefined") return;

  const modal = new bootstrap.Modal(modalEl);
  function applyDialogOptions(root) {
    try {
      const dlg = modalEl.querySelector(".modal-dialog");
      if (!dlg) return;
      const host = (root || contentEl).querySelector("[data-sirona-dialog-class]");
      if (!host) return;
      const cls = (host.getAttribute("data-sirona-dialog-class") || "").trim();
      const centered = host.getAttribute("data-sirona-dialog-centered") === "1";
      const noScroll = host.getAttribute("data-sirona-dialog-no-scroll") === "1";
      if (noScroll) dlg.classList.remove("modal-dialog-scrollable");
      if (centered) dlg.classList.add("modal-dialog-centered");
      if (cls) dlg.classList.add(cls);
    } catch (e) {}
  }
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
        applyDialogOptions(contentEl);
        if (typeof window.sironaInitProductoFormPrecio === "function") {
          window.sironaInitProductoFormPrecio(contentEl);
        }
        if (typeof lucide !== "undefined") {
          try {
            lucide.createIcons();
          } catch (e) {}
        }
      })
      .catch(function () {
        contentEl.innerHTML =
          '<div class="modal-body"><p class="text-danger small mb-0">No se pudo cargar el formulario.</p></div>';
      });
  });
  modalEl.addEventListener("hidden.bs.modal", function () {
    contentEl.innerHTML = "";
    try {
      const dlg = modalEl.querySelector(".modal-dialog");
      if (!dlg) return;
      dlg.classList.remove("sirona-modal-dialog--product", "sirona-modal-dialog--caja-mov", "modal-dialog-centered");
      dlg.classList.add("modal-dialog-scrollable");
    } catch (e) {}
  });
})();

