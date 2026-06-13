(function () {
  var ESTADOS = [
    {
      clave: "no_armado",
      label: "No armado",
      hint: "El pedido aún no fue preparado.",
      css: "venta-despacho-ico--no_armado",
    },
    {
      clave: "armado",
      label: "Pedido armado",
      hint: "Listo para entregar o despachar.",
      css: "venta-despacho-ico--armado",
    },
    {
      clave: "despachado",
      label: "Pedido despachado",
      hint: "Ya fue entregado al cliente.",
      css: "venta-despacho-ico--despachado",
    },
  ];

  function csrfToken() {
    var el = document.querySelector("[name=csrfmiddlewaretoken]");
    if (el && el.value) return el.value;
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function modalParts() {
    var modalEl = document.getElementById("sironaModal");
    var contentEl = document.getElementById("sironaModalContent");
    if (!modalEl || !contentEl || typeof bootstrap === "undefined") return null;
    var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    return { modalEl: modalEl, contentEl: contentEl, modal: modal };
  }

  function applyIconState(btn, estado, label) {
    if (!btn) return;
    btn.setAttribute("data-despacho-estado", estado);
    btn.setAttribute("title", label);
    btn.setAttribute("aria-label", "Cambiar estado de despacho: " + label);
    btn.classList.remove(
      "venta-despacho-ico--no_armado",
      "venta-despacho-ico--armado",
      "venta-despacho-ico--despachado"
    );
    btn.classList.add("venta-despacho-ico--" + estado);
  }

  function buildModalHtml(ventaId, estadoActual) {
    var opciones = ESTADOS.map(function (st) {
      var active = st.clave === estadoActual ? " is-active" : "";
      return (
        '<button type="button" class="venta-despacho-opcion' +
        active +
        '" data-estado="' +
        st.clave +
        '">' +
        '<span class="btn-icon venta-despacho-ico ' +
        st.css +
        '" aria-hidden="true"><i data-lucide="package"></i></span>' +
        '<span class="venta-despacho-opcion-text">' +
        '<span class="venta-despacho-opcion-label">' +
        st.label +
        "</span>" +
        '<span class="venta-despacho-opcion-hint">' +
        st.hint +
        "</span>" +
        "</span>" +
        "</button>"
      );
    }).join("");

    return (
      '<div class="modal-header border-0 pb-0">' +
      '<h5 class="modal-title mb-0">Pedido #' +
      ventaId +
      "</h5>" +
      '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Cerrar"></button>' +
      "</div>" +
      '<div class="modal-body pt-2 pb-3">' +
      '<p class="text-muted small mb-3 mb-md-3">¿En qué estado está el pedido?</p>' +
      '<div class="venta-despacho-estado-opciones">' +
      opciones +
      "</div>" +
      "</div>"
    );
  }

  function guardarEstado(btn, url, estado, parts) {
    var ventaId = btn.getAttribute("data-venta-id");
    parts.contentEl.classList.add("venta-despacho-modal-busy");
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        Accept: "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-CSRFToken": csrfToken(),
      },
      body: "estado=" + encodeURIComponent(estado),
    })
      .then(function (r) {
        return r.json().then(function (data) {
          if (!r.ok) throw new Error((data && data.error) || "Error al guardar");
          return data;
        });
      })
      .then(function (data) {
        applyIconState(btn, data.estado, data.label);
        parts.modal.hide();
      })
      .catch(function () {
        window.alert("No se pudo actualizar el estado del pedido #" + ventaId + ".");
      })
      .finally(function () {
        parts.contentEl.classList.remove("venta-despacho-modal-busy");
      });
  }

  function openModal(btn) {
    var parts = modalParts();
    if (!parts) return;

    var ventaId = btn.getAttribute("data-venta-id");
    var url = btn.getAttribute("data-venta-despacho-url");
    var estadoActual = btn.getAttribute("data-despacho-estado") || "no_armado";
    if (!ventaId || !url) return;

    parts.contentEl.innerHTML = buildModalHtml(ventaId, estadoActual);
    try {
      var dlg = parts.modalEl.querySelector(".modal-dialog");
      if (dlg) {
        dlg.classList.remove("modal-lg", "sirona-modal-dialog--product");
        dlg.classList.add("modal-dialog-centered");
      }
    } catch (e) {}

    parts.contentEl.querySelectorAll(".venta-despacho-opcion").forEach(function (op) {
      op.addEventListener("click", function () {
        var estado = op.getAttribute("data-estado");
        if (!estado || op.disabled) return;
        op.disabled = true;
        guardarEstado(btn, url, estado, parts);
      });
    });

    if (typeof lucide !== "undefined") {
      try {
        lucide.createIcons();
      } catch (e) {}
    }
    parts.modal.show();
  }

  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest(".venta-despacho-ico-btn");
    if (!btn) return;
    ev.preventDefault();
    ev.stopPropagation();
    openModal(btn);
  });
})();
