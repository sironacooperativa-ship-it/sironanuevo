(function () {
  var pending = false;

  function paintIcons() {
    pending = false;
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

  window.sironaPaintIcons = paintIcons;

  function schedulePaint() {
    if (pending) return;
    pending = true;
    window.requestAnimationFrame(paintIcons);
  }

  paintIcons();

  ["sironaMenu", "sironaCalc"].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener("shown.bs.offcanvas", paintIcons);
  });

  if (window.MutationObserver) {
    new MutationObserver(function (mutations) {
      for (var i = 0; i < mutations.length; i += 1) {
        var nodes = mutations[i].addedNodes;
        for (var j = 0; j < nodes.length; j += 1) {
          var node = nodes[j];
          if (node.nodeType !== 1) continue;
          if (
            node.matches &&
            (node.matches("[data-lucide]") || node.querySelector("[data-lucide]"))
          ) {
            schedulePaint();
            return;
          }
        }
      }
    }).observe(document.documentElement, { childList: true, subtree: true });
  }
})();

