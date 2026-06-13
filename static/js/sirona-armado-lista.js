(function () {
  function refresh() {
    var boxes = document.querySelectorAll(".armado-sel-pedido");
    var n = 0;
    boxes.forEach(function (b) {
      if (b.checked) n += 1;
    });
    var btn = document.getElementById("btn-armado-colectivo");
    var lbl = document.getElementById("armado-sel-todos");
    var cnt = document.getElementById("armado-seleccion-count");
    if (btn) btn.disabled = n === 0;
    if (cnt) cnt.textContent = n + " seleccionado" + (n === 1 ? "" : "s");
    if (lbl && boxes.length) {
      lbl.checked = n > 0 && n === boxes.length;
      lbl.indeterminate = n > 0 && n < boxes.length;
    }
  }

  document.addEventListener("change", function (ev) {
    var t = ev.target;
    if (!t) return;
    if (t.id === "armado-sel-todos") {
      document.querySelectorAll(".armado-sel-pedido").forEach(function (b) {
        b.checked = t.checked;
      });
      refresh();
      return;
    }
    if (t.classList && t.classList.contains("armado-sel-pedido")) {
      refresh();
    }
  });

  var form = document.getElementById("armado-seleccion-form");
  if (form) {
    form.addEventListener("submit", function (ev) {
      var n = document.querySelectorAll(".armado-sel-pedido:checked").length;
      if (!n) {
        ev.preventDefault();
        window.alert("Seleccioná al menos un pedido.");
      }
    });
  }

  refresh();
})();
