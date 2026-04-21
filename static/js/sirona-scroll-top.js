(function () {
  const btn = document.getElementById("btnScrollTop");
  if (!btn) return;

  function refresh() {
    const y = window.scrollY || document.documentElement.scrollTop || 0;
    btn.classList.toggle("is-visible", y > 250);
  }

  btn.addEventListener("click", function () {
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  window.addEventListener("scroll", refresh, { passive: true });
  refresh();
})();

