/**
 * Antes de confirmar venta/pedido: si hay conflicto de stock (falta o queda exacto en cero),
 * muestra modal Bootstrap y arma `stock_venta_json` para el POST.
 */
(function (w) {
  "use strict";

  function parseInt10(s) {
    const n = parseInt(String(s || "").trim(), 10);
    return Number.isFinite(n) ? n : 0;
  }

  function collectDemandByProduct(tbody) {
    const rows = [];
    tbody.querySelectorAll("tr").forEach(function (tr) {
      const sel = tr.querySelector('select[name="linea_producto"]');
      const qIn = tr.querySelector('input[name="linea_cantidad"]');
      if (!sel || !qIn) return;
      const pid = String(sel.value || "").trim();
      const qty = parseInt10(qIn.value);
      if (!pid || qty <= 0) return;
      rows.push({ tr: tr, pid: pid, qty: qty });
    });
    const startStock = {};
    const demand = {};
    rows.forEach(function (r) {
      demand[r.pid] = (demand[r.pid] || 0) + r.qty;
    });
    return { rows: rows, demand: demand };
  }

  function buildIssues(rows, demand, getProduct) {
    const issues = [];
    Object.keys(demand).forEach(function (pid) {
      const p = getProduct(pid);
      if (!p) return;
      const avail = parseInt10(p.stock);
      const d = demand[pid];
      if (d > avail) {
        issues.push({ pid: pid, type: "short", p: p, demand: d, avail: avail });
      } else if (d === avail && avail > 0) {
        issues.push({ pid: pid, type: "exact", p: p, demand: d, avail: avail });
      }
    });
    return issues;
  }

  function adjustQtysToStock(pid, avail, tbody) {
    let left = avail;
    tbody.querySelectorAll("tr").forEach(function (tr) {
      const s = tr.querySelector('select[name="linea_producto"]');
      if (!s || String(s.value) !== pid) return;
      const qIn = tr.querySelector('input[name="linea_cantidad"]');
      if (!qIn) return;
      const q = parseInt10(qIn.value);
      const take = Math.max(0, Math.min(q, left));
      qIn.value = String(take);
      left -= take;
    });
  }

  function ensureModal() {
    let el = document.getElementById("sironaStockVentaModal");
    if (el) return el;
    el = document.createElement("div");
    el.className = "modal fade";
    el.id = "sironaStockVentaModal";
    el.tabIndex = -1;
    el.setAttribute("aria-labelledby", "sironaStockVentaModalLabel");
    el.innerHTML =
      '<div class="modal-dialog modal-dialog-scrollable">' +
      '<div class="modal-content">' +
      '<div class="modal-header">' +
      '<h5 class="modal-title" id="sironaStockVentaModalLabel">Stock del depósito</h5>' +
      '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Cerrar"></button>' +
      "</div>" +
      '<div class="modal-body" id="sironaStockVentaModalBody"></div>' +
      '<div class="modal-footer flex-wrap gap-2">' +
      '<button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancelar carga</button>' +
      '<button type="button" class="btn btn-primary" id="sironaStockVentaModalOk">Continuar con estas opciones</button>' +
      "</div>" +
      "</div>" +
      "</div>";
    document.body.appendChild(el);
    return el;
  }

  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"']/g, function (ch) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch];
    });
  }

  w.SironaVentaStockConfirm = {
    bind: function (opts) {
      const form = opts.form;
      const tbody = opts.tbody;
      const getProduct = opts.getProduct;
      const hiddenId = opts.hiddenId || "id_stock_venta_json";
      if (!form || !tbody || !getProduct) return;

      function clearHidden() {
        const h = document.getElementById(hiddenId);
        if (h) h.value = "";
      }

      tbody.addEventListener("input", function (ev) {
        if (ev.target && ev.target.matches('input[name="linea_cantidad"]')) clearHidden();
      });
      tbody.addEventListener("change", function (ev) {
        if (ev.target && ev.target.matches('select[name="linea_producto"]')) clearHidden();
      });

      form.addEventListener("submit", function (ev) {
        const sub = ev.submitter;
        if (sub && sub.getAttribute("name") === "accion" && sub.value === "solo_cabecera") return;
        if (String(form.getAttribute("data-pedido-pagado") || "") === "1") return;
        if (typeof opts.skip === "function" && opts.skip(ev)) return;

        const { demand } = collectDemandByProduct(tbody);
        if (!Object.keys(demand).length) return;

        const issues = buildIssues(rows, demand, getProduct);
        if (!issues.length) {
          clearHidden();
          return;
        }

        const hidden = document.getElementById(hiddenId);
        if (hidden && String(hidden.value || "").trim()) {
          return;
        }

        ev.preventDefault();

        const modalEl = ensureModal();
        const body = document.getElementById("sironaStockVentaModalBody");
        const state = {};

        issues.forEach(function (it) {
          state[it.pid] =
            it.type === "short"
              ? { neg: false, desh: true, mode: "neg" }
              : { neg: false, desh: true, mode: "exact" };
        });

        function renderBody() {
          let html =
            "<p class=\"small text-muted mb-3\">Revisá cada producto. Podés vender por encima del stock " +
            "(saldo negativo) o ajustar las cantidades al disponible antes de continuar.</p>";
          issues.forEach(function (it, idx) {
            const cod = escapeHtml(it.p.codigo || "");
            const desc = escapeHtml(it.p.descripcion || "");
            const idBase = "ssv_" + idx + "_" + it.pid;
            html += '<div class="border rounded p-3 mb-3 bg-light">';
            html += "<div><strong>" + cod + "</strong> — " + desc + "</div>";
            html +=
              '<div class="small mt-1">Stock disponible: <strong>' +
              it.avail +
              "</strong> · Cantidad pedida (total líneas): <strong>" +
              it.demand +
              "</strong></div>";
            if (it.type === "short") {
              html += '<div class="mt-2 fw-semibold small">¿Cómo seguimos?</div>';
              html +=
                '<div class="form-check mt-1"><input class="form-check-input" type="radio" name="' +
                idBase +
                '_m" id="' +
                idBase +
                '_neg" value="neg" checked />' +
                '<label class="form-check-label" for="' +
                idBase +
                '_neg">Vender la cantidad pedida (puede quedar stock negativo)</label></div>';
              html +=
                '<div class="form-check"><input class="form-check-input" type="radio" name="' +
                idBase +
                '_m" id="' +
                idBase +
                '_adj" value="adj" />' +
                '<label class="form-check-label" for="' +
                idBase +
                '_adj">Ajustar cantidades al stock disponible (' +
                it.avail +
                " u.) y continuar</label></div>";
              html +=
                '<div class="form-check"><input class="form-check-input" type="radio" name="' +
                idBase +
                '_m" id="' +
                idBase +
                '_can" value="can" />' +
                '<label class="form-check-label" for="' +
                idBase +
                '_can">No vender este producto (cancelar toda la carga)</label></div>';
            } else {
              html +=
                '<div class="form-check mt-2">' +
                '<input class="form-check-input" type="checkbox" id="' +
                idBase +
                '_desh" checked />' +
                '<label class="form-check-label" for="' +
                idBase +
                '_desh">Al quedar en cero, deshabilitar el producto para nuevas ventas</label></div>';
            }
            html += "</div>";
          });
          body.innerHTML = html;
        }

        renderBody();

        const btnOk = document.getElementById("sironaStockVentaModalOk");
        const modal = w.bootstrap && w.bootstrap.Modal ? w.bootstrap.Modal.getOrCreateInstance(modalEl) : null;

        function onOk() {
          const json = {};
          let cancelAll = false;
          issues.forEach(function (it, idx) {
            const idBase = "ssv_" + idx + "_" + it.pid;
            if (it.type === "short") {
              const r = body.querySelector('input[name="' + idBase + '_m"]:checked');
              const mode = r ? r.value : "neg";
              if (mode === "can") {
                cancelAll = true;
              } else if (mode === "adj") {
                adjustQtysToStock(it.pid, it.avail, tbody);
                json[it.pid] = { neg: false, desh: true };
              } else {
                json[it.pid] = { neg: true, desh: true };
              }
            } else {
              const ch = body.querySelector("#" + idBase + "_desh");
              json[it.pid] = { neg: false, desh: ch ? ch.checked : true };
            }
          });

          if (cancelAll) {
            if (modal) modal.hide();
            return;
          }

          const h = document.getElementById(hiddenId);
          if (h) h.value = JSON.stringify(json);
          if (modal) modal.hide();
          try {
            if (sub && typeof form.requestSubmit === "function") {
              form.requestSubmit(sub);
            } else {
              form.submit();
            }
          } catch (e) {
            form.submit();
          }
        }

        const newBtn = btnOk.cloneNode(true);
        btnOk.parentNode.replaceChild(newBtn, btnOk);
        newBtn.addEventListener("click", onOk);

        if (modal) modal.show();
        else if (window.confirm("Conflicto de stock: ¿continuar con saldo negativo donde falte?")) onOk();
      });
    },
  };
})(typeof window !== "undefined" ? window : this);
