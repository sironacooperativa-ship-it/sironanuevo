(function () {
  // Logout por inactividad (cliente): permite cerrar sesión sin esperar a la próxima navegación.
  // Nota: el middleware del servidor también valida inactividad y actúa en la siguiente request.
  const IDLE_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutos
  let lastActivity = Date.now();
  let fired = false;

  function markActivity() {
    lastActivity = Date.now();
  }

  ["mousemove", "mousedown", "keydown", "touchstart", "scroll"].forEach(function (ev) {
    window.addEventListener(ev, markActivity, { passive: true });
  });

  function tick() {
    if (fired) return;
    const idleFor = Date.now() - lastActivity;
    if (idleFor >= IDLE_TIMEOUT_MS) {
      fired = true;
      const next = window.location.pathname + window.location.search + window.location.hash;

      const logoutUrl = document.body && document.body.dataset ? document.body.dataset.logoutUrl : "";
      const loginUrl = document.body && document.body.dataset ? document.body.dataset.loginUrl : "";

      try {
        if (logoutUrl) {
          fetch(logoutUrl, { method: "GET", credentials: "same-origin", keepalive: true });
        }
      } catch (e) {}

      if (loginUrl) {
        window.location.assign(loginUrl + "?idle=1&next=" + encodeURIComponent(next));
      }
      return;
    }
    window.setTimeout(tick, 15 * 1000);
  }

  window.setTimeout(tick, 15 * 1000);
})();

