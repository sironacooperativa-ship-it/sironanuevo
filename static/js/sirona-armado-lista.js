(function () {
  function selectableBoxes() {
    return Array.prototype.slice.call(document.querySelectorAll(".armado-sel-pedido:not(:disabled)"));
  }

  function applyPreselect() {
    var el = document.getElementById("armado-preselect-data");
    if (!el) return;
    var ids = [];
    try {
      ids = JSON.parse(el.textContent || "[]");
    } catch (e) {
      return;
    }
    if (!ids.length) return;
    var idSet = {};
    ids.forEach(function (id) {
      idSet[String(id)] = true;
    });
    selectableBoxes().forEach(function (b) {
      if (idSet[b.value]) b.checked = true;
    });
  }

  function refresh() {
    var boxes = selectableBoxes();
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
      selectableBoxes().forEach(function (b) {
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
        window.alert("Seleccioná al menos un pedido disponible.");
      }
    });
  }

  refresh();
  applyPreselect();
  refresh();
})();
