/**
 * Formato de montos alineado con el filtro Django |ars:
 * miles con punto, decimales con coma ($ 1.234.567,89).
 */
(function (w) {
  w.formatMontoArs = function (n) {
    let num = Number(n);
    if (!Number.isFinite(num)) num = 0;
    const neg = num < 0;
    num = Math.abs(num);
    const rounded = Math.round(num * 100) / 100;
    const parts = rounded.toFixed(2).split(".");
    let intPart = parts[0];
    const decPart = parts[1] || "00";
    const groups = [];
    while (intPart.length > 3) {
      groups.unshift(intPart.slice(-3));
      intPart = intPart.slice(0, -3);
    }
    if (intPart.length) groups.unshift(intPart);
    const body = groups.join(".") + "," + decPart;
    return (neg ? "-$ " : "$ ") + body;
  };
})(typeof window !== "undefined" ? window : this);
