/**
 * Edición manual en aumentos: lapicito por fila, costo → precio al 30%, precio → % implícito.
 */
(function (w) {
  var PCT_PREESTABLECIDO = 30;

  function parseNum(raw) {
    var v = String(raw == null ? "" : raw)
      .trim()
      .replace(",", ".");
    if (v === "") return NaN;
    var n = parseFloat(v);
    return Number.isFinite(n) ? n : NaN;
  }

  function calcPct(costo, precio) {
    if (!Number.isFinite(costo) || costo <= 0) return null;
    if (!Number.isFinite(precio)) return null;
    return ((precio - costo) / costo) * 100;
  }

  function fmtPct(n) {
    if (!Number.isFinite(n)) return "—";
    try {
      return (
        n.toLocaleString("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "%"
      );
    } catch (e) {
      return String(Math.round(n * 100) / 100) + "%";
    }
  }

  function redondearPrecioMostradorArs(raw) {
    var n = Number(raw);
    if (!Number.isFinite(n) || n < 0) return 0;
    var cents = Math.round(n * 100);
    if (!Number.isFinite(cents)) return 0;
    var mod = ((cents % 100) + 100) % 100;
    if (mod === 0 || mod === 50) return cents / 100;
    if (mod < 50) cents = Math.floor(cents / 100) * 100 + 50;
    else cents = (Math.floor(cents / 100) + 1) * 100;
    return cents / 100;
  }

  function fmtMoneyInput(n) {
    if (!Number.isFinite(n)) return "";
    return n.toFixed(2);
  }

  function rowEditing(tr) {
    return tr && tr.classList.contains("is-editing");
  }

  function syncPctDisplay(tr) {
    var costoInp = tr.querySelector(".js-aumento-costo-inp");
    var precioInp = tr.querySelector(".js-aumento-precio-inp");
    var pctEl = tr.querySelector(".js-aumento-pct");
    if (!costoInp || !precioInp || !pctEl) return;
    var pct = calcPct(parseNum(costoInp.value), parseNum(precioInp.value));
    pctEl.textContent = pct === null ? "—" : fmtPct(pct);
  }

  function applyPrecioDesdeCosto(tr) {
    var costoInp = tr.querySelector(".js-aumento-costo-inp");
    var precioInp = tr.querySelector(".js-aumento-precio-inp");
    if (!costoInp || !precioInp) return;
    var costo = parseNum(costoInp.value);
    if (!Number.isFinite(costo) || costo <= 0) return;
    var raw = costo * (1 + PCT_PREESTABLECIDO / 100);
    precioInp.value = fmtMoneyInput(redondearPrecioMostradorArs(raw));
    syncPctDisplay(tr);
  }

  function bindRowCalculations(tr) {
    if (!tr || tr.__aumentoCalcBound) return;
    tr.__aumentoCalcBound = true;
    var costoInp = tr.querySelector(".js-aumento-costo-inp");
    var precioInp = tr.querySelector(".js-aumento-precio-inp");
    if (!costoInp || !precioInp) return;

    var fromCosto = false;

    costoInp.addEventListener("input", function () {
      fromCosto = true;
      applyPrecioDesdeCosto(tr);
      fromCosto = false;
    });
    costoInp.addEventListener("change", function () {
      applyPrecioDesdeCosto(tr);
    });

    precioInp.addEventListener("input", function () {
      if (fromCosto) return;
      syncPctDisplay(tr);
    });
    precioInp.addEventListener("change", syncPctDisplay.bind(null, tr));
  }

  function setRowEditing(tr, on) {
    if (!tr) return;
    tr.classList.toggle("is-editing", !!on);
    tr.querySelectorAll(".aumento-edit").forEach(function (el) {
      el.classList.toggle("d-none", !on);
      if (el.tagName === "INPUT" || el.tagName === "SELECT" || el.tagName === "TEXTAREA") {
        el.disabled = !on;
      }
    });
    var btn = tr.querySelector(".js-aumento-editar");
    if (btn) {
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      btn.title = on ? "Dejar de editar" : "Editar costo y precio";
    }
    if (on) syncPctDisplay(tr);
  }

  function bind(root) {
    root = root || document;
    root.querySelectorAll("tr.aumento-row").forEach(function (tr) {
      bindRowCalculations(tr);
    });

    root.querySelectorAll(".js-aumento-editar").forEach(function (btn) {
      if (btn.__aumentoEditBound) return;
      btn.__aumentoEditBound = true;
      btn.addEventListener("click", function () {
        var tr = btn.closest("tr.aumento-row");
        if (!tr) return;
        setRowEditing(tr, !rowEditing(tr));
      });
    });

    root.querySelectorAll("tr.aumento-row").forEach(function (tr) {
      tr.querySelectorAll(".aumento-edit").forEach(function (el) {
        if (el.tagName === "INPUT" || el.tagName === "SELECT" || el.tagName === "TEXTAREA") {
          el.disabled = !rowEditing(tr);
        }
      });
    });

    root.querySelectorAll("form").forEach(function (form) {
      if (!form.querySelector("tr.aumento-row") || form.__aumentoSubmitBound) return;
      form.__aumentoSubmitBound = true;
      form.addEventListener("submit", function () {
        form.querySelectorAll(".aumento-edit").forEach(function (el) {
          el.disabled = false;
        });
      });
    });
  }

  w.sironaInitAumentoEdit = bind;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      bind(document);
    });
  } else {
    bind(document);
  }
})(typeof window !== "undefined" ? window : this);
