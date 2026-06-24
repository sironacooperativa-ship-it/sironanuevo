(function () {
  function csrfToken() {
    var el = document.querySelector("[name=csrfmiddlewaretoken]");
    if (el && el.value) return el.value;
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function publishDespachoSync(ventas) {
    if (!ventas || !window.SironaDespachoSync) return;
    ventas.forEach(function (payload) {
      window.SironaDespachoSync.publish(payload, "armado");
    });
  }

  function rowSum(row) {
    var total = 0;
    row.querySelectorAll(".armado-alloc-input").forEach(function (inp) {
      var v = parseInt(inp.value, 10);
      if (!isNaN(v) && v > 0) total += v;
    });
    var cell = row.querySelector(".armado-asignado-sum");
    if (cell) cell.textContent = String(total);
    return total;
  }

  function refreshAll() {
    document.querySelectorAll("#armado-colectivo-tabla tbody tr[data-producto-id]").forEach(rowSum);
  }

  function validateForm() {
    var ok = true;
    var msg = "";
    document.querySelectorAll("#armado-colectivo-tabla tbody tr[data-producto-id]").forEach(function (row) {
      var max = parseInt(row.getAttribute("data-cant-max") || "0", 10);
      var sum = rowSum(row);
      row.classList.remove("table-danger");
      if (sum > max) {
        ok = false;
        row.classList.add("table-danger");
        if (!msg) {
          var code = row.querySelector("td") ? row.querySelector("td").textContent : "";
          msg =
            "La suma en puntos de stock (" +
            sum +
            ") supera la cantidad total (" +
            max +
            ") para el producto " +
            code +
            ".";
        }
      }
    });
    if (!ok) window.alert(msg || "Revisá las cantidades por punto de stock.");
    return ok;
  }

  document.addEventListener("input", function (ev) {
    if (ev.target && ev.target.classList.contains("armado-alloc-input")) {
      var row = ev.target.closest("tr");
      if (row) rowSum(row);
    }
  });

  var form = document.getElementById("armado-colectivo-form");
  if (form) {
    form.addEventListener("submit", function (ev) {
      if (!validateForm()) {
        ev.preventDefault();
        return;
      }

      var submitter = ev.submitter;
      if (!submitter || submitter.id !== "btn-armado-imprimir") return;

      ev.preventDefault();

      var fd = new FormData(form);
      fetch(form.action, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          Accept: "application/json",
          "X-CSRFToken": csrfToken(),
        },
        body: fd,
      })
        .then(function (r) {
          return r.json().then(function (data) {
            if (!r.ok) throw new Error((data && data.error) || "Error al marcar armado");
            return data;
          });
        })
        .then(function (data) {
          publishDespachoSync(data.ventas);
          var pdfOnly = document.createElement("input");
          pdfOnly.type = "hidden";
          pdfOnly.name = "_pdf_only";
          pdfOnly.value = "1";
          form.appendChild(pdfOnly);
          form.target = "_blank";
          HTMLFormElement.prototype.submit.call(form);
          form.removeChild(pdfOnly);
          form.target = "";
        })
        .catch(function () {
          window.alert("No se pudo actualizar el estado de armado. Intentá imprimir de nuevo.");
        });
    });
  }

  var btnDespachar = document.getElementById("btn-armado-marcar-despachados");
  var despForm = document.getElementById("armado-marcar-despachados-form");
  if (btnDespachar && despForm) {
    btnDespachar.addEventListener("click", function (ev) {
      ev.preventDefault();
      if (
        !window.confirm(
          "¿Marcar todos los pedidos de este armado como despachados? Quedarán archivados y no se podrán editar."
        )
      ) {
        return;
      }

      btnDespachar.disabled = true;
      fetch(despForm.action, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          Accept: "application/json",
          "X-CSRFToken": csrfToken(),
        },
        body: new FormData(despForm),
      })
        .then(function (r) {
          return r.json().then(function (data) {
            if (!r.ok) throw new Error((data && data.error) || "Error al despachar");
            return data;
          });
        })
        .then(function (data) {
          publishDespachoSync(data.ventas);
          window.location.reload();
        })
        .catch(function () {
          btnDespachar.disabled = false;
          window.alert("No se pudieron marcar los pedidos como despachados. Intentá de nuevo.");
        });
    });
  }

  refreshAll();
})();
