(function () {
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
    });
  }

  refreshAll();
})();
