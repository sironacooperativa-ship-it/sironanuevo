(function () {
  function rowFor(el) {
    return el.closest("tr.venta-despacho-row");
  }

  function formForRow(row) {
    if (!row) return null;
    var id = row.id || "";
    var pk = id.replace("pedido-", "");
    if (!pk) return null;
    return document.getElementById("despacho-form-" + pk);
  }

  function syncAndSubmit(changed) {
    var row = rowFor(changed);
    var form = formForRow(row);
    if (!form) return;

    var armado = row.querySelector(".venta-despacho-armado");
    var despachado = row.querySelector(".venta-despacho-despachado");
    if (!armado || !despachado) return;

    if (changed.classList.contains("venta-despacho-despachado") && despachado.checked) {
      armado.checked = true;
    }
    if (changed.classList.contains("venta-despacho-armado") && !armado.checked) {
      despachado.checked = false;
    }

    form.submit();
  }

  document.addEventListener("change", function (ev) {
    var t = ev.target;
    if (!t || !t.classList) return;
    if (
      t.classList.contains("venta-despacho-armado") ||
      t.classList.contains("venta-despacho-despachado")
    ) {
      syncAndSubmit(t);
    }
  });
})();
