/**
 * Edición manual en aumentos: lapicito por fila, costo → precio al 30%, precio → % implícito.
 */
(function (w) {
  var PCT_PREESTABLECIDO = 30;
  var DELEGATE_FLAG = "__aumentoDelegated";

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
    var saveBtn = tr.querySelector(".js-aumento-guardar-fila");
    if (saveBtn) saveBtn.classList.toggle("d-none", !on);
    if (on) {
      syncPctDisplay(tr);
      var focusInp = tr.querySelector(".js-aumento-costo-inp, .js-aumento-precio-inp");
      if (focusInp && typeof focusInp.focus === "function") {
        try {
          focusInp.focus();
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
        if (tr) rows.push(tr);
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

  function disableAllEditInputs(form) {
    form.querySelectorAll(".aumento-edit").forEach(function (el) {
      if (el.tagName === "INPUT" || el.tagName === "SELECT" || el.tagName === "TEXTAREA") {
        el.disabled = true;
      }
    });
  }

  function enableInputsForSubmit(form, step) {
    disableAllEditInputs(form);
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
    if (!form || form.__aumentoSubmitBound) return;
    form.__aumentoSubmitBound = true;

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

  function restoreDisabledState(form) {
    form.querySelectorAll("tr.aumento-row").forEach(function (tr) {
      tr.querySelectorAll(".aumento-edit").forEach(function (el) {
        if (el.tagName === "INPUT" || el.tagName === "SELECT" || el.tagName === "TEXTAREA") {
          el.disabled = !rowEditing(tr);
        }
      });
    });
  }

  function handleEditClick(btn) {
    var tr = btn.closest("tr.aumento-row");
    if (!tr) return;
    var opening = !rowEditing(tr);
    if (opening) {
      closeOtherEditingRows(tr);
      resetFilterFormStep();
      setRowEditing(tr, true);
      return;
    }
    setRowEditing(tr, false);
  }

  function handleSaveRowClick(btn) {
    var tr = btn.closest("tr.aumento-row");
    var form = tr && tr.closest("form");
    if (!tr || !form) return;

    if (!rowEditing(tr)) setRowEditing(tr, true);

    var cb = tr.querySelector(".sel-producto");
    if (cb) cb.checked = true;

    if (form.id === "formAumento") {
      setFormStep(form, "guardar_manual");
    }

    if (typeof form.requestSubmit === "function") form.requestSubmit();
    else form.submit();
  }

  function bindDelegated(root) {
    root = root || document;
    if (root[DELEGATE_FLAG]) return;
    root[DELEGATE_FLAG] = true;

    root.addEventListener("click", function (ev) {
      var editBtn = ev.target.closest(".js-aumento-editar");
      if (editBtn) {
        ev.preventDefault();
        handleEditClick(editBtn);
        return;
      }
      var saveBtn = ev.target.closest(".js-aumento-guardar-fila");
      if (saveBtn) {
        ev.preventDefault();
        handleSaveRowClick(saveBtn);
      }
    });
  }

  function bind(root) {
    root = root || document;

    bindDelegated(root);

    root.querySelectorAll("tr.aumento-row").forEach(function (tr) {
      bindRowCalculations(tr);
      tr.querySelectorAll(".aumento-edit").forEach(function (el) {
        if (el.tagName === "INPUT" || el.tagName === "SELECT" || el.tagName === "TEXTAREA") {
          el.disabled = !rowEditing(tr);
        }
      });
    });

    root.querySelectorAll("form").forEach(function (form) {
      if (!form.querySelector("tr.aumento-row")) return;
      bindFormSubmit(form);
    });

    if (w.lucide && typeof w.lucide.createIcons === "function") {
      try {
        w.lucide.createIcons();
      } catch (e) {}
    }
  }

  w.sironaInitAumentoEdit = bind;

  function boot() {
    bind(document);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  window.addEventListener("pageshow", function (ev) {
    if (ev.persisted) boot();
  });
})(typeof window !== "undefined" ? window : this);
