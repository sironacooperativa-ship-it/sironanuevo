/**
 * Ficha de producto: al cambiar costo o % ganancia, sugiere precio de venta con
 * redondeo a pesos enteros o con ,50; el resto sube (misma regla que en servidor).
 */
(function (w) {
  function parseNum(el) {
    if (!el) return NaN;
    var v = (el.value || "").trim().replace(",", ".");
    if (v === "") return NaN;
    var n = parseFloat(v);
    return Number.isFinite(n) ? n : NaN;
  }

  function redondearPrecioMostradorArs(raw) {
    var n = Number(raw);
    if (!Number.isFinite(n) || n < 0) return 0;
    var cents = Math.round(n * 100);
    if (!Number.isFinite(cents)) return 0;
    var mod = ((cents % 100) + 100) % 100;
    if (mod === 0 || mod === 50) return cents / 100;
    if (mod < 50) cents = Math.floor(cents / 100) * 100 + 50;
    else cents = (Math.floor(cents / 100) + 1) * 100;
    return cents / 100;
  }

  function bind(root) {
    root = root || document;
    var costoEl = root.querySelector("#id_costo");
    var pctEl = root.querySelector("#id_porcentaje_ganancia");
    var precioEl = root.querySelector("#id_precio_venta");
    if (!costoEl || !pctEl || !precioEl) return;

    function actualizar() {
      var costo = parseNum(costoEl);
      var pct = parseNum(pctEl);
      if (!Number.isFinite(costo) || !Number.isFinite(pct)) return;
      var raw = costo * (1 + pct / 100);
      var red = redondearPrecioMostradorArs(raw);
      precioEl.value = red.toFixed(2);
    }

    costoEl.addEventListener("input", actualizar);
    costoEl.addEventListener("change", actualizar);
    pctEl.addEventListener("input", actualizar);
    pctEl.addEventListener("change", actualizar);
  }

  w.sironaInitProductoFormPrecio = bind;

  function domReady() {
    bind(document);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", domReady);
  } else {
    domReady();
  }
})(typeof window !== "undefined" ? window : this);
