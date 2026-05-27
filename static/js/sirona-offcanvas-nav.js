(function () {
  var menu = document.getElementById("sironaMenu");
  if (!menu) return;
  menu.querySelectorAll("a.sirona-offcanvas-nav-link[href]").forEach(function (anchor) {
    anchor.addEventListener("click", function (ev) {
      var href = anchor.getAttribute("href");
      if (!href || href === "#") return;
      if (ev.defaultPrevented) return;
      if (ev.button !== 0 || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) return;
      if (!menu.classList.contains("show")) return;
      // Navegar de inmediato. Antes se esperaba el cierre animado del offcanvas
      // y eso agregaba una demora perceptible al tocar cualquier opción.
      try {
        menu.classList.remove("show");
        document.body.classList.remove("offcanvas-open");
        document.querySelectorAll(".offcanvas-backdrop").forEach(function (bd) {
          if (bd.parentNode) bd.parentNode.removeChild(bd);
        });
      } catch (e) {}
    });
  });
})();

