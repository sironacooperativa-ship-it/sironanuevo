/**
 * Al editar un producto en varias listas: comparativa y popup para elegir dónde aplicar el precio.
 */
(function (w) {
  function parseNum(el) {
    if (!el) return NaN;
    var v = (el.value || "").trim().replace(",", ".");
    if (v === "") return NaN;
    var n = parseFloat(v);
    return Number.isFinite(n) ? n : NaN;
  }

  function fmtMoney(n) {
    try {
      return Number(n).toLocaleString("es-AR", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
    } catch (e) {
      return String(n);
    }
  }

  function escapeHtml(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function hayCambioPrecio(formEl) {
    var costo = formEl.querySelector("#id_costo");
    var pct = formEl.querySelector("#id_porcentaje_ganancia");
    var precio = formEl.querySelector("#id_precio_venta");
    if (!costo || !pct || !precio) return false;
    var ic = parseFloat(formEl.getAttribute("data-initial-costo") || "");
    var ip = parseFloat(formEl.getAttribute("data-initial-pct") || "");
    var iv = parseFloat(formEl.getAttribute("data-initial-precio") || "");
    if (Number.isFinite(ic) && parseNum(costo) !== ic) return true;
    if (Number.isFinite(ip) && parseNum(pct) !== ip) return true;
    if (Number.isFinite(iv) && parseNum(precio) !== iv) return true;
    return false;
  }

  function fetchComparativa(formEl, url) {
    var csrf = formEl.querySelector("[name=csrfmiddlewaretoken]");
    var fd = new FormData(formEl);
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": csrf ? csrf.value : "",
      },
      body: fd,
    }).then(function (r) {
      if (!r.ok) throw new Error("comparativa");
      return r.json();
    });
  }

  function renderTabla(data, tbody, soloLectura) {
    var listas = data.listas || [];
    tbody.innerHTML = "";
    listas.forEach(function (row) {
      var tr = document.createElement("tr");
      if (row.impacta) tr.classList.add("table-warning");
      var chk = "";
      if (!soloLectura) {
        chk =
          '<input class="form-check-input" type="checkbox" name="aplicar_precio_listas_pick" value="' +
          String(row.lista_id) +
          '" data-lista-id="' +
          String(row.lista_id) +
          '"' +
          (row.impacta ? " checked" : "") +
          (row.es_farmacia ? ' disabled title="Farmacia usa el precio del producto"' : "") +
          " />";
      } else {
        chk = row.impacta ? '<span class="badge text-bg-warning text-dark">Impacta</span>' : '<span class="text-muted">—</span>';
      }
      var farmaciaTag = row.es_farmacia ? ' <span class="text-muted small">(catálogo)</span>' : "";
      tr.innerHTML =
        '<td class="text-center">' +
        chk +
        "</td>" +
        "<td>" +
        escapeHtml(row.nombre) +
        farmaciaTag +
        "</td>" +
        '<td class="text-end col-money">$ ' +
        fmtMoney(row.precio_actual) +
        "</td>" +
        '<td class="text-end col-money fw-semibold">$ ' +
        fmtMoney(row.precio_propuesto) +
        "</td>" +
        '<td class="text-end col-money">' +
        (row.impacta ? (Number(row.diferencia) >= 0 ? "+" : "") + "$ " + fmtMoney(row.diferencia) : "—") +
        "</td>";
      tbody.appendChild(tr);
    });
    return listas;
  }

  function bind(root) {
    root = root || document;
    var forms = root.querySelectorAll("form[data-sirona-producto-listas-propagar]");
    if (!forms.length) return;

    var modalEl = document.getElementById("sironaProductoListasPropagar");
    if (!modalEl || typeof bootstrap === "undefined") return;
    var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    var tbody = document.getElementById("sironaProductoListasPropagarBody");
    var precioLbl = document.getElementById("sironaProductoListasPropagarPrecio");
    var btnConfirm = document.getElementById("sironaProductoListasPropagarConfirm");
    var hint = document.getElementById("sironaProductoListasPropagarHint");
    var emptyNote = document.getElementById("sironaProductoListasPropagarEmpty");
    var pendingForm = null;
    var pendingSoloVista = false;

    function limpiarHiddenAplicar(formEl) {
      formEl.querySelectorAll('input[name="aplicar_precio_listas"]').forEach(function (n) {
        n.remove();
      });
    }

    function abrirComparativa(formEl, soloVista) {
      var url = formEl.getAttribute("data-comparativa-url");
      var minListas = parseInt(formEl.getAttribute("data-listas-count") || "0", 10);
      if (!url || minListas < 1) return Promise.resolve(null);
      pendingForm = formEl;
      pendingSoloVista = !!soloVista;
      if (hint) {
        hint.textContent = soloVista
          ? "Vista previa: precio actual en cada lista vs. el precio que estás guardando en el producto."
          : "Este producto está en varias listas. Marcá en cuáles querés actualizar el precio de venta.";
      }
      if (btnConfirm) btnConfirm.style.display = soloVista ? "none" : "";
      return fetchComparativa(formEl, url)
        .then(function (data) {
          if (precioLbl) precioLbl.textContent = "$ " + fmtMoney(data.precio_propuesto);
          renderTabla(data, tbody, soloVista);
          if (emptyNote) emptyNote.hidden = (data.listas_con_impacto || 0) > 0;
          modal.show();
          return data;
        })
        .catch(function () {
          window.alert("No se pudo cargar la comparativa de listas.");
          return null;
        });
    }

    if (btnConfirm) {
      btnConfirm.addEventListener("click", function () {
        if (!pendingForm || pendingSoloVista) {
          modal.hide();
          return;
        }
        limpiarHiddenAplicar(pendingForm);
        modalEl.querySelectorAll('input[name="aplicar_precio_listas_pick"]:checked').forEach(function (chk) {
          var hid = document.createElement("input");
          hid.type = "hidden";
          hid.name = "aplicar_precio_listas";
          hid.value = chk.value;
          pendingForm.appendChild(hid);
        });
        pendingForm.setAttribute("data-sirona-propagar-ok", "1");
        modal.hide();
        if (typeof pendingForm.requestSubmit === "function") {
          pendingForm.requestSubmit();
        } else {
          pendingForm.submit();
        }
      });
    }

    forms.forEach(function (formEl) {
      if (formEl.__sironaListasPropagarBound) return;
      formEl.__sironaListasPropagarBound = true;

      var btnVer = formEl.querySelector("[data-producto-listas-comparativa]");
      if (btnVer) {
        btnVer.addEventListener("click", function () {
          abrirComparativa(formEl, true);
        });
      }

      formEl.addEventListener("submit", function (ev) {
        if (formEl.getAttribute("data-sirona-propagar-ok") === "1") {
          formEl.removeAttribute("data-sirona-propagar-ok");
          return;
        }
        try {
          var minListas = parseInt(formEl.getAttribute("data-listas-count") || "0", 10);
          if (minListas < 1) return;
          if (!hayCambioPrecio(formEl)) return;
          var present = formEl.querySelector('input[name="listas_extra_present"]');
          if (!present) return;
          var url = formEl.getAttribute("data-comparativa-url");
          if (!url) return;
          ev.preventDefault();
          ev.stopPropagation();
          fetchComparativa(formEl, url).then(function (data) {
            if (!data || !data.listas || !data.listas.length) {
              formEl.setAttribute("data-sirona-propagar-ok", "1");
              formEl.submit();
              return;
            }
            if ((data.listas_con_impacto || 0) === 0) {
              formEl.setAttribute("data-sirona-propagar-ok", "1");
              formEl.submit();
              return;
            }
            abrirComparativa(formEl, false);
          });
        } catch (e) {}
      });
    });
  }

  w.sironaInitProductoListasPropagar = bind;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      bind(document);
    });
  } else {
    bind(document);
  }
})(typeof window !== "undefined" ? window : this);
