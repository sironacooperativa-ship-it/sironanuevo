(function () {
  var pending = false;
  var observer;

  function paintIcons() {
    pending = false;
    var L = typeof lucide !== "undefined" ? lucide : window.lucide;
    var fresh = document.querySelectorAll("[data-lucide]:not(svg)");
    if (!fresh.length) return;
    if (L && typeof L.createIcons === "function") {
      if (observer) observer.disconnect();
      fresh.forEach(function (el) {
        el.setAttribute("data-sirona-icon-pending", el.getAttribute("data-lucide"));
      });
      L.createIcons({
        nameAttr: "data-sirona-icon-pending",
        attrs: {
          "stroke-width": 1.75,
          width: 18,
          height: 18,
        },
      });
      document.querySelectorAll("[data-sirona-icon-pending]").forEach(function (el) {
        el.removeAttribute("data-sirona-icon-pending");
      });
      if (observer) observer.observe(document.documentElement, { childList: true, subtree: true });
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
    observer = new MutationObserver(function (mutations) {
      for (var i = 0; i < mutations.length; i += 1) {
        var nodes = mutations[i].addedNodes;
        for (var j = 0; j < nodes.length; j += 1) {
          var node = nodes[j];
          if (node.nodeType !== 1) continue;
          if (
            node.matches &&
            (node.matches("[data-lucide]:not(svg)") || node.querySelector("[data-lucide]:not(svg)"))
          ) {
            schedulePaint();
            return;
          }
        }
      }
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }
})();

