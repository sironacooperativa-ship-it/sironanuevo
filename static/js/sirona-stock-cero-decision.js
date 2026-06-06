/**
 * Modal global: producto quedó sin stock → ¿vigente o deshabilitar?
 * También expone SironaStockCeroDecision.prompt(lista) para uso programático.
 */
(function (w) {
  "use strict";

  var RESOLVER_URL = w.SIRONA_STOCK_CERO_RESOLVER_URL || "/productos/stock-cero-resolver/";

  function csrfToken() {
    var el = document.querySelector("[name=csrfmiddlewaretoken]");
    return el ? el.value : "";
  }

  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"']/g, function (ch) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch];
    });
  }

  function ensureModal() {
    var el = document.getElementById("sironaStockCeroDecisionModal");
    if (el) return el;
    el = document.createElement("div");
    el.className = "modal fade";
    el.id = "sironaStockCeroDecisionModal";
    el.tabIndex = -1;
    el.innerHTML =
      '<div class="modal-dialog modal-dialog-scrollable">' +
      '<div class="modal-content">' +
      '<div class="modal-header">' +
      '<h5 class="modal-title">Producto sin stock</h5>' +
      '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Cerrar"></button>' +
      "</div>" +
      '<div class="modal-body" id="sironaStockCeroDecisionBody"></div>' +
      '<div class="modal-footer flex-wrap gap-2">' +
      '<button type="button" class="btn btn-primary" id="sironaStockCeroDecisionOk">Confirmar</button>' +
      "</div>" +
      "</div></div>";
    document.body.appendChild(el);
    return el;
  }

  function renderBody(body, productos) {
    var html =
      '<p class="small text-muted mb-3">El producto quedó sin stock. ¿Lo dejás <strong>vigente</strong> (se puede seguir vendiendo, con aviso) o lo <strong>deshabilitás</strong> como si lo apagaras manualmente?</p>';
    productos.forEach(function (p, idx) {
      var base = "scd_" + idx + "_" + p.id;
      html += '<div class="border rounded p-3 mb-3 bg-light">';
      html += "<div><strong>" + escapeHtml(p.codigo) + "</strong> — " + escapeHtml(p.descripcion) + "</div>";
      html += '<div class="small text-muted mt-1">Stock actual: <strong>' + escapeHtml(p.stock) + "</strong></div>";
      html +=
        '<div class="form-check mt-2"><input class="form-check-input" type="radio" name="' +
        base +
        '" id="' +
        base +
        '_v" value="vigente" checked />' +
        '<label class="form-check-label" for="' +
        base +
        '_v">Dejar vigente (habilitado, con aviso al vender)</label></div>';
      html +=
        '<div class="form-check"><input class="form-check-input" type="radio" name="' +
        base +
        '" id="' +
        base +
        '_d" value="deshabilitar" />' +
        '<label class="form-check-label" for="' +
        base +
        '_d">Deshabilitar producto</label></div>';
      html += "</div>";
    });
    body.innerHTML = html;
  }

  function prompt(productos) {
    return new Promise(function (resolve, reject) {
      if (!productos || !productos.length) {
        resolve([]);
        return;
      }
      if (!w.bootstrap || !w.bootstrap.Modal) {
        reject(new Error("bootstrap"));
        return;
      }
      var modalEl = ensureModal();
      var body = document.getElementById("sironaStockCeroDecisionBody");
      renderBody(body, productos);
      var modal = w.bootstrap.Modal.getOrCreateInstance(modalEl);
      var btn = document.getElementById("sironaStockCeroDecisionOk");

      function cleanup() {
        btn.removeEventListener("click", onOk);
      }

      function onOk() {
        var decisiones = productos.map(function (p, idx) {
          var base = "scd_" + idx + "_" + p.id;
          var r = body.querySelector('input[name="' + base + '"]:checked');
          return { id: p.id, accion: r ? r.value : "vigente" };
        });
        fetch(RESOLVER_URL, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": csrfToken(),
          },
          body: JSON.stringify({ decisiones: decisiones }),
        })
          .then(function (r) {
            if (!r.ok) throw new Error("resolver");
            return r.json();
          })
          .then(function (data) {
            cleanup();
            modal.hide();
            resolve(data.resueltos || []);
          })
          .catch(function (e) {
            cleanup();
            reject(e);
          });
      }

      btn.addEventListener("click", onOk);
      modal.show();
    });
  }

  w.SironaStockCeroDecision = { prompt: prompt };

  document.addEventListener("DOMContentLoaded", function () {
    try {
      var el = document.getElementById("sirona-stock-cero-prompt-data");
      if (!el) return;
      var productos = JSON.parse(el.textContent || "[]");
      if (productos.length) prompt(productos);
    } catch (e) {}
  });
})(typeof window !== "undefined" ? window : this);
