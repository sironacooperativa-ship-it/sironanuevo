/**
 * Antes de confirmar venta/pedido/presupuesto: conflictos de stock.
 * - Sin stock (0): aviso + botón «Agregar stock» (modal sin salir de la página).
 * - Falta stock: ajustar, vender en negativo o quitar.
 * - Queda en cero: elegir vigente o deshabilitar (no se apaga solo).
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
    const demand = {};
    rows.forEach(function (r) {
      demand[r.pid] = (demand[r.pid] || 0) + r.qty;
    });
    return { rows: rows, demand: demand };
  }

  function buildIssues(demand, getProduct) {
    const issues = [];
    Object.keys(demand).forEach(function (pid) {
      const p = getProduct(pid);
      if (!p) return;
      const avail = parseInt10(p.stock);
      const d = demand[pid];
      if (avail <= 0 && d > 0) {
        issues.push({ pid: pid, type: "zero", p: p, demand: d, avail: avail });
      } else if (d > avail) {
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

  function ensureQtyWarnStyles() {
    if (document.getElementById("sironaQtyOverStockCss")) return;
    const st = document.createElement("style");
    st.id = "sironaQtyOverStockCss";
    st.textContent =
      "input[name=\"linea_cantidad\"].sirona-qty-over-stock{" +
      "color:#dc3545!important;font-weight:600}" +
      "input[name=\"linea_cantidad\"].sirona-qty-over-stock:focus{" +
      "color:#dc3545!important}";
    document.head.appendChild(st);
  }

  function refreshQtyWarnings(tbody, getProduct) {
    if (!tbody || !getProduct) return;
    const demand = collectDemandByProduct(tbody).demand;
    const overPids = {};
    Object.keys(demand).forEach(function (pid) {
      const p = getProduct(pid);
      if (!p) return;
      const avail = parseInt10(p.stock);
      if (demand[pid] > avail) overPids[pid] = true;
    });
    tbody.querySelectorAll("tr").forEach(function (tr) {
      const qIn = tr.querySelector('input[name="linea_cantidad"]');
      const sel = tr.querySelector('select[name="linea_producto"]');
      if (!qIn) return;
      const pid = sel ? String(sel.value || "").trim() : "";
      const qty = parseInt10(qIn.value);
      const over = !!(pid && qty > 0 && overPids[pid]);
      qIn.classList.toggle("sirona-qty-over-stock", over);
    });
  }

  function clearQtyWarnings(tbody) {
    if (!tbody) return;
    tbody.querySelectorAll('input[name="linea_cantidad"]').forEach(function (qIn) {
      qIn.classList.remove("sirona-qty-over-stock");
    });
  }

  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"']/g, function (ch) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch];
    });
  }

  function openAgregarStock(pid, onUpdated) {
    const url =
      (w.SIRONA_STOCK_QUICK_ADD_URL || "/stock/quick-add/").replace(/\/$/, "") +
      "/" +
      encodeURIComponent(pid) +
      "/?modal=1";
    const contentEl = document.getElementById("sironaModalContent");
    const modalEl = document.getElementById("sironaModal");
    if (!contentEl || !modalEl || !w.bootstrap) {
      w.open(url.replace("?modal=1", ""), "_blank");
      return;
    }
    contentEl.innerHTML = '<div class="p-4 text-center text-muted small">Cargando…</div>';
    w.bootstrap.Modal.getOrCreateInstance(modalEl).show();
    fetch(url, {
      headers: { "X-Requested-With": "XMLHttpRequest", Accept: "text/html" },
      credentials: "same-origin",
    })
      .then(function (r) {
        if (!r.ok) throw new Error("stock");
        return r.text();
      })
      .then(function (html) {
        contentEl.innerHTML = html;
        const form = contentEl.querySelector("form.js-stock-quick-add");
        if (form) {
          form.addEventListener("submit", function (ev) {
            ev.preventDefault();
            const fd = new FormData(form);
            fetch(form.action, {
              method: "POST",
              body: fd,
              credentials: "same-origin",
              headers: { "X-Requested-With": "XMLHttpRequest" },
            })
              .then(function (r) {
                return r.json();
              })
              .then(function (data) {
                if (data && data.ok && typeof onUpdated === "function") {
                  onUpdated(data);
                }
                w.bootstrap.Modal.getOrCreateInstance(modalEl).hide();
              })
              .catch(function () {
                alert("No se pudo actualizar el stock.");
              });
          });
        }
      })
      .catch(function () {
        alert("No se pudo abrir la carga de stock.");
      });
  }

  function ensureModal() {
    let el = document.getElementById("sironaStockVentaModal");
    if (el) return el;
    el = document.createElement("div");
    el.className = "modal fade";
    el.id = "sironaStockVentaModal";
    el.tabIndex = -1;
    el.innerHTML =
      '<div class="modal-dialog modal-dialog-scrollable modal-lg">' +
      '<div class="modal-content">' +
      '<div class="modal-header">' +
      '<h5 class="modal-title">Stock del depósito</h5>' +
      '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Cerrar"></button>' +
      "</div>" +
      '<div class="modal-body" id="sironaStockVentaModalBody"></div>' +
      '<div class="modal-footer flex-wrap gap-2">' +
      '<button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancelar carga</button>' +
      '<button type="button" class="btn btn-primary" id="sironaStockVentaModalOk">Continuar con estas opciones</button>' +
      "</div></div></div>";
    document.body.appendChild(el);
    return el;
  }

  function renderCeroChoice(idBase) {
    return (
      '<div class="mt-2 fw-semibold small">Al quedar sin stock:</div>' +
      '<div class="form-check mt-1"><input class="form-check-input" type="radio" name="' +
      idBase +
      '_cero" id="' +
      idBase +
      '_cv" value="vigente" checked />' +
      '<label class="form-check-label" for="' +
      idBase +
      '_cv">Dejar vigente (se puede seguir vendiendo con aviso)</label></div>' +
      '<div class="form-check"><input class="form-check-input" type="radio" name="' +
      idBase +
      '_cero" id="' +
      idBase +
      '_cd" value="deshabilitar" />' +
      '<label class="form-check-label" for="' +
      idBase +
      '_cd">Deshabilitar producto</label></div>'
    );
  }

  w.SironaVentaStockConfirm = {
    refreshQty: function (form) {
      if (form && typeof form.__sironaStockQtyRefresh === "function") {
        form.__sironaStockQtyRefresh();
      }
    },
    bind: function (opts) {
      const form = opts.form;
      const tbody = opts.tbody;
      const getProduct = opts.getProduct;
      const setProductStock = opts.setProductStock;
      const hiddenId = opts.hiddenId || "id_stock_venta_json";
      if (!form || !tbody || !getProduct) return;

      ensureQtyWarnStyles();

      function syncQtyWarnings() {
        refreshQtyWarnings(tbody, getProduct);
      }

      form.__sironaStockQtyRefresh = syncQtyWarnings;

      function clearHidden() {
        const h = document.getElementById(hiddenId);
        if (h) h.value = "";
      }

      tbody.addEventListener("input", function (ev) {
        if (ev.target && ev.target.matches('input[name="linea_cantidad"]')) {
          clearHidden();
          syncQtyWarnings();
        }
      });
      tbody.addEventListener("change", function (ev) {
        if (ev.target && ev.target.matches('select[name="linea_producto"]')) {
          clearHidden();
          syncQtyWarnings();
        }
      });

      syncQtyWarnings();

      form.addEventListener("submit", function (ev) {
        const sub = ev.submitter;
        if (sub && sub.getAttribute("name") === "accion" && sub.value === "solo_cabecera") return;
        if (String(form.getAttribute("data-pedido-pagado") || "") === "1") return;
        if (typeof opts.skip === "function" && opts.skip(ev)) return;

        const collected = collectDemandByProduct(tbody);
        const demand = collected.demand;
        if (!Object.keys(demand).length) return;

        const issues = buildIssues(demand, getProduct);
        if (!issues.length) {
          clearHidden();
          return;
        }

        const hidden = document.getElementById(hiddenId);
        if (hidden && String(hidden.value || "").trim()) {
          clearQtyWarnings(tbody);
          return;
        }

        ev.preventDefault();

        const modalEl = ensureModal();
        const body = document.getElementById("sironaStockVentaModalBody");

        function renderBody() {
          let html =
            '<p class="small text-muted mb-3">Revisá cada producto antes de confirmar. Podés cargar stock sin salir de esta pantalla.</p>';
          issues.forEach(function (it, idx) {
            const cod = escapeHtml(it.p.codigo || "");
            const desc = escapeHtml(it.p.descripcion || "");
            const idBase = "ssv_" + idx + "_" + it.pid;
            html += '<div class="border rounded p-3 mb-3 bg-light" data-issue-pid="' + escapeHtml(it.pid) + '">';
            html += "<div><strong>" + cod + "</strong> — " + desc + "</div>";
            html +=
              '<div class="small mt-1">Stock disponible: <strong>' +
              it.avail +
              "</strong> · Cantidad pedida: <strong>" +
              it.demand +
              "</strong></div>";
            html +=
              '<button type="button" class="btn btn-sm btn-outline-primary mt-2 js-agregar-stock" data-pid="' +
              escapeHtml(it.pid) +
              '">Agregar stock</button>';

            if (it.type === "zero") {
              html +=
                '<div class="alert alert-warning small mt-2 mb-0">No hay stock en depósito. <strong>Consultá si hay stock disponible</strong>, cargá unidades o elegí vender en negativo.</div>';
              html += '<div class="mt-2 fw-semibold small">¿Cómo seguimos?</div>';
              html +=
                '<div class="form-check mt-1"><input class="form-check-input" type="radio" name="' +
                idBase +
                '_m" id="' +
                idBase +
                '_neg" value="neg" />' +
                '<label class="form-check-label" for="' +
                idBase +
                '_neg">Vender la cantidad pedida (stock negativo)</label></div>';
              html +=
                '<div class="form-check"><input class="form-check-input" type="radio" name="' +
                idBase +
                '_m" id="' +
                idBase +
                '_can" value="can" checked />' +
                '<label class="form-check-label" for="' +
                idBase +
                '_can">Cancelar hasta cargar stock</label></div>';
            } else if (it.type === "short") {
              html +=
                '<div class="alert alert-warning small mt-2 mb-0">Pedís más unidades de las que figura en stock (' +
                it.avail +
                " u.). <strong>Consultá si hay stock disponible</strong> antes de continuar (podés cargar unidades con el botón de arriba).</div>";
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
                " u.)</label></div>";
              html +=
                '<div class="form-check"><input class="form-check-input" type="radio" name="' +
                idBase +
                '_m" id="' +
                idBase +
                '_can" value="can" />' +
                '<label class="form-check-label" for="' +
                idBase +
                '_can">No vender este producto (cancelar carga)</label></div>';
              if (it.avail > 0 && it.demand > it.avail) {
                html += renderCeroChoice(idBase);
              }
            } else {
              html += renderCeroChoice(idBase);
            }
            html += "</div>";
          });
          body.innerHTML = html;

          body.querySelectorAll(".js-agregar-stock").forEach(function (btn) {
            btn.addEventListener("click", function () {
              const pid = btn.getAttribute("data-pid");
              openAgregarStock(pid, function (data) {
                if (typeof setProductStock === "function") {
                  setProductStock(pid, data.stock);
                } else if (getProduct(pid)) {
                  getProduct(pid).stock = data.stock;
                }
                const block = btn.closest("[data-issue-pid]");
                if (block) {
                  const strong = block.querySelector(".small strong");
                  if (strong) strong.textContent = String(data.stock);
                }
                syncQtyWarnings();
              });
            });
          });
        }

        renderBody();

        const btnOk = document.getElementById("sironaStockVentaModalOk");
        const modal = w.bootstrap && w.bootstrap.Modal ? w.bootstrap.Modal.getOrCreateInstance(modalEl) : null;

        function onOk() {
          const json = {};
          let cancelAll = false;
          issues.forEach(function (it, idx) {
            const idBase = "ssv_" + idx + "_" + it.pid;
            let neg = false;
            let desh = false;
            if (it.type === "zero") {
              const r = body.querySelector('input[name="' + idBase + '_m"]:checked');
              const mode = r ? r.value : "can";
              if (mode === "can") {
                cancelAll = true;
              } else {
                neg = true;
                desh = false;
              }
            } else if (it.type === "short") {
              const r = body.querySelector('input[name="' + idBase + '_m"]:checked');
              const mode = r ? r.value : "neg";
              if (mode === "can") {
                cancelAll = true;
              } else if (mode === "adj") {
                adjustQtysToStock(it.pid, it.avail, tbody);
                neg = false;
              } else {
                neg = true;
              }
              const ceroR = body.querySelector('input[name="' + idBase + '_cero"]:checked');
              if (ceroR && ceroR.value === "deshabilitar") desh = true;
            } else {
              const ceroR = body.querySelector('input[name="' + idBase + '_cero"]:checked');
              desh = ceroR ? ceroR.value === "deshabilitar" : false;
            }
            json[it.pid] = { neg: neg, desh: desh };
          });

          if (cancelAll) {
            if (modal) modal.hide();
            return;
          }

          const h = document.getElementById(hiddenId);
          if (h) h.value = JSON.stringify(json);
          clearQtyWarnings(tbody);
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
        else if (window.confirm("Hay conflictos de stock. ¿Continuar?")) onOk();
      });
    },
  };
})(typeof window !== "undefined" ? window : this);
