/**
 * Selección múltiple y total acumulado en «Pedidos a pagar» (historial de ventas).
 */
(function (w) {
  function fmtMoney(n) {
    try {
      return Number(n).toLocaleString("es-AR", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
    } catch (e) {
      return String(n);
    }
  }

  function bind(root) {
    root = root || document;
    const bar = root.getElementById("ventasPagoMasivoBar");
    const formGo = root.getElementById("ventasPagoMasivoGo");
    if (!bar || !formGo) return;

    const chkAll = root.getElementById("ventasPagoMasivoTodo");
    const countEl = root.getElementById("ventasPagoMasivoCount");
    const totalEl = root.getElementById("ventasPagoMasivoTotal");
    const checks = () => Array.from(root.querySelectorAll(".js-venta-pago-sel"));

    function refresh() {
      const picked = checks().filter((c) => c.checked);
      const n = picked.length;
      let sum = 0;
      picked.forEach((c) => {
        const raw = c.getAttribute("data-monto") || "0";
        const v = parseFloat(String(raw).replace(",", "."));
        if (Number.isFinite(v)) sum += v;
      });
      if (countEl) countEl.textContent = String(n);
      if (totalEl) totalEl.textContent = "$ " + fmtMoney(sum);
      formGo.disabled = n === 0;
      if (chkAll) {
        const all = checks();
        chkAll.indeterminate = n > 0 && n < all.length;
        chkAll.checked = all.length > 0 && n === all.length;
      }
    }

    if (chkAll) {
      chkAll.addEventListener("change", function () {
        const on = chkAll.checked;
        checks().forEach((c) => {
          c.checked = on;
        });
        refresh();
      });
    }

    checks().forEach((c) => c.addEventListener("change", refresh));

    formGo.addEventListener("click", function () {
      const ids = checks()
        .filter((c) => c.checked)
        .map((c) => c.value);
      if (!ids.length) return;
      const base = formGo.getAttribute("data-url") || "";
      const retorno = formGo.getAttribute("data-retorno") || "";
      const params = new URLSearchParams();
      ids.forEach((id) => params.append("venta_id", id));
      if (retorno) params.set("retorno", retorno);
      w.location.href = base + "?" + params.toString();
    });

    refresh();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      bind(document);
    });
  } else {
    bind(document);
  }
})(typeof window !== "undefined" ? window : this);
