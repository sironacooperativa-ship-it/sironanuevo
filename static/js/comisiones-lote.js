(function () {
  function init() {
    document.querySelectorAll('form[data-comision-lote]').forEach(function (form) {
      var all = form.querySelector('[data-comision-todas]');
      var checks = Array.from(form.querySelectorAll('input[name="venta_id"]'));
      var summary = form.querySelector('[data-comision-resumen]');
      var button = form.querySelector('[data-comision-pagar]');
      function update() {
        var selected = checks.filter(function (c) { return c.checked; });
        var cents = selected.reduce(function (total, c) { return total + Math.round(Number(c.dataset.comisionMonto) * 100); }, 0);
        var money = (cents / 100).toLocaleString('es-AR', {style:'currency',currency:'ARS'});
        summary.textContent = selected.length + ' seleccionadas · ' + money;
        all.checked = selected.length === checks.length;
        all.indeterminate = selected.length > 0 && selected.length < checks.length;
        button.disabled = selected.length === 0 || cents <= 0;
      }
      all.addEventListener('change', function () { checks.forEach(function (c) { c.checked = all.checked; }); update(); });
      checks.forEach(function (c) { c.addEventListener('change', update); });
      form.addEventListener('submit', function (ev) {
        if (!checks.some(function (c) { return c.checked; })) { ev.preventDefault(); return; }
        if (!window.confirm('Registrar pago: ' + summary.textContent + '?')) ev.preventDefault();
      });
      update();
    });
    document.querySelectorAll('form.comision-liquidacion-form:not([data-comision-lote])').forEach(function(form) {
      form.querySelectorAll('input[name="venta_id"]').forEach(function(c) {
        c.addEventListener('change', function() { var selected = form.querySelector('input[name="liquidar_modo"][value="seleccion"]'); if(selected) selected.checked = true; });
      });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
