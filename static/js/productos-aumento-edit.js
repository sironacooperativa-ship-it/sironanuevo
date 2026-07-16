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
    return !!(tr && tr.classList.contains("is-editing"));
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
    if (!tr || tr.dataset.aumentoCalcBound === "1") return;
    tr.dataset.aumentoCalcBound = "1";
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
    precioInp.addEventListener("change", function () {
      syncPctDisplay(tr);
    });
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
    var saveBtn = tr.querySelector(".js-aumento-guardar-fila");
    if (saveBtn) saveBtn.classList.toggle("d-none", !on);
    if (on) {
      syncPctDisplay(tr);
      var focusInp = tr.querySelector(".js-aumento-costo-inp");
      if (focusInp) {
        try {
          focusInp.focus();
          focusInp.select();
        } catch (e) {}
      }
    }
  }

  function closeOtherEditingRows(activeTr) {
    document.querySelectorAll("tr.aumento-row.is-editing").forEach(function (tr) {
      if (tr !== activeTr) setRowEditing(tr, false);
    });
  }

  function resetFilterFormStep() {
    var stepInp = document.getElementById("formAumentoStep");
    if (stepInp) stepInp.value = "preview";
  }

  function setFormStep(form, step) {
    var stepInp = form.querySelector("#formAumentoStep");
    if (stepInp) stepInp.value = step;
  }

  function rowsForSubmit(form, step) {
    var rows = [];
    if (form.id === "formAumento" && step === "guardar_manual") {
      form.querySelectorAll(".sel-producto:checked").forEach(function (cb) {
        var tr = cb.closest("tr.aumento-row");
        if (tr && rows.indexOf(tr) === -1) rows.push(tr);
      });
      form.querySelectorAll("tr.aumento-row.is-editing").forEach(function (tr) {
        if (rows.indexOf(tr) === -1) rows.push(tr);
      });
      return rows;
    }
    if (form.id === "formAumento") {
      form.querySelectorAll(".sel-producto:checked").forEach(function (cb) {
        var tr = cb.closest("tr.aumento-row");
        if (tr) rows.push(tr);
      });
      return rows;
    }
    form.querySelectorAll("tr.aumento-row").forEach(function (tr) {
      rows.push(tr);
    });
    return rows;
  }

  function restoreDisabledState(form) {
    form.querySelectorAll("tr.aumento-row").forEach(function (tr) {
      tr.querySelectorAll(".aumento-edit").forEach(function (el) {
        if (el.tagName === "INPUT" || el.tagName === "SELECT" || el.tagName === "TEXTAREA") {
          el.disabled = !rowEditing(tr);
        }
      });
    });
  }

  function enableInputsForSubmit(form, step) {
    form.querySelectorAll(".aumento-edit").forEach(function (el) {
      if (el.tagName === "INPUT" || el.tagName === "SELECT" || el.tagName === "TEXTAREA") {
        el.disabled = true;
      }
    });
    rowsForSubmit(form, step).forEach(function (tr) {
      tr.querySelectorAll(".aumento-edit").forEach(function (el) {
        if (el.tagName === "INPUT" || el.tagName === "SELECT" || el.tagName === "TEXTAREA") {
          el.disabled = false;
        }
      });
    });
  }

  function autoSelectEditingRows(form) {
    form.querySelectorAll("tr.aumento-row.is-editing").forEach(function (tr) {
      var cb = tr.querySelector(".sel-producto");
      if (cb) cb.checked = true;
    });
  }

  function bindFormSubmit(form) {
    if (!form || form.dataset.aumentoSubmitBound === "1") return;
    form.dataset.aumentoSubmitBound = "1";

    form.querySelectorAll("[data-aumento-step]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        setFormStep(form, btn.getAttribute("data-aumento-step") || "preview");
      });
    });

    form.addEventListener("submit", function (ev) {
      var stepInp = form.querySelector("#formAumentoStep");
      var step = stepInp ? stepInp.value : form.id === "formAumentoConfirm" ? "confirm" : "preview";

      enableInputsForSubmit(form, step);

      if (form.id !== "formAumento") return;

      if (step === "guardar_manual") {
        autoSelectEditingRows(form);
        enableInputsForSubmit(form, step);
        var any = false;
        form.querySelectorAll(".sel-producto:checked").forEach(function () {
          any = true;
        });
        if (!any) {
          ev.preventDefault();
          alert("Seleccioná al menos un producto para guardar.");
          restoreDisabledState(form);
        }
        return;
      }

      var anySel = false;
      form.querySelectorAll(".sel-producto:checked").forEach(function () {
        anySel = true;
      });
      if (!anySel) {
        ev.preventDefault();
        alert("Seleccioná al menos un producto.");
        restoreDisabledState(form);
        return;
      }
      var pct = (document.getElementById("pct_aumento") || {}).value;
      if (!String(pct || "").trim()) {
        ev.preventDefault();
        alert("Indicá el porcentaje de aumento sobre el costo.");
        restoreDisabledState(form);
      }
    });
  }

  function bindEditButtons(root) {
    root.querySelectorAll(".js-aumento-editar").forEach(function (btn) {
      if (btn.dataset.aumentoEditBound === "1") return;
      btn.dataset.aumentoEditBound = "1";
      btn.addEventListener("click", function (ev) {
        ev.preventDefault();
        var tr = btn.closest("tr.aumento-row");
        if (!tr) return;
        if (rowEditing(tr)) {
          setRowEditing(tr, false);
          return;
        }
        closeOtherEditingRows(tr);
        resetFilterFormStep();
        setRowEditing(tr, true);
      });
    });
  }

  function bindSaveButtons(root) {
    root.querySelectorAll(".js-aumento-guardar-fila").forEach(function (btn) {
      if (btn.dataset.aumentoSaveBound === "1") return;
      btn.dataset.aumentoSaveBound = "1";
      btn.addEventListener("click", function (ev) {
        ev.preventDefault();
        var tr = btn.closest("tr.aumento-row");
        var form = tr && tr.closest("form");
        if (!tr || !form) return;

        if (!rowEditing(tr)) setRowEditing(tr, true);

        var cb = tr.querySelector(".sel-producto");
        if (cb) cb.checked = true;

        if (form.id === "formAumento") {
          setFormStep(form, "guardar_manual");
        }

        enableInputsForSubmit(form, form.id === "formAumento" ? "guardar_manual" : "confirm");

        if (typeof form.requestSubmit === "function") form.requestSubmit();
        else form.submit();
      });
    });
  }

  function bind(root) {
    root = root || document;

    root.querySelectorAll("tr.aumento-row").forEach(function (tr) {
      bindRowCalculations(tr);
      tr.querySelectorAll(".aumento-edit").forEach(function (el) {
        if (el.tagName === "INPUT" || el.tagName === "SELECT" || el.tagName === "TEXTAREA") {
          el.disabled = !rowEditing(tr);
        }
      });
    });

    bindEditButtons(root);
    bindSaveButtons(root);

    root.querySelectorAll("form").forEach(function (form) {
      if (!form.querySelector("tr.aumento-row")) return;
      bindFormSubmit(form);
    });

    if (typeof w.sironaPaintIcons === "function") {
      w.sironaPaintIcons();
    }
  }

  w.sironaInitAumentoEdit = bind;
})(typeof window !== "undefined" ? window : this);
