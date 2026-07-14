/**
 * Edición manual de costo y precio en pantalla de aumentos (lapicito por fila).
 */
(function (w) {
  function rowEditing(tr) {
    return tr && tr.classList.contains("is-editing");
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
  }

  function bind(root) {
    root = root || document;
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
