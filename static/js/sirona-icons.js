(function () {
  function paintIcons() {
    var L = typeof lucide !== "undefined" ? lucide : window.lucide;
    if (L && typeof L.createIcons === "function") {
      L.createIcons({
        attrs: {
          "stroke-width": 1.65,
          width: 18,
          height: 18,
        },
      });
    }
  }

  paintIcons();

  ["sironaMenu", "sironaCalc"].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener("shown.bs.offcanvas", paintIcons);
  });
})();

