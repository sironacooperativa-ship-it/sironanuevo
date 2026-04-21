(function () {
  var menu = document.getElementById("sironaMenu");
  if (!menu || typeof bootstrap === "undefined") return;
  menu.querySelectorAll("a.sirona-offcanvas-nav-link[href]").forEach(function (anchor) {
    anchor.addEventListener("click", function (ev) {
      var href = anchor.getAttribute("href");
      if (!href || href === "#") return;
      if (ev.defaultPrevented) return;
      if (ev.button !== 0 || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) return;
      if (!menu.classList.contains("show")) return;
      var inst = bootstrap.Offcanvas.getOrCreateInstance(menu);
      ev.preventDefault();
      function go() {
        menu.removeEventListener("hidden.bs.offcanvas", go);
        window.location.assign(href);
      }
      menu.addEventListener("hidden.bs.offcanvas", go);
      inst.hide();
    });
  });
})();

