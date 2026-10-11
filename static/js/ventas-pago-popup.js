(function () {
  'use strict';
  let host, content, modal, saved = false, busy = false;
  function initFields(scope) {
    const medio = scope.querySelector('[name="medio_pago"]');
    if (!medio) return;
    function update() {
      scope.querySelector('[data-pago-transferencia]').hidden = !['TRF', 'MP'].includes(medio.value);
      scope.querySelector('[data-pago-cheque]').hidden = medio.value !== 'CHQ';
    }
    medio.addEventListener('change', update); update();
  }
  function display(html) {
    content.innerHTML = html;
    saved = content.querySelector('[data-pago-guardado="1"]') !== null;
    initFields(content);
  }
  window.sironaOpenPago = async function (url) {
    if (!host) {
      host = document.createElement('div'); host.className = 'modal fade'; host.tabIndex = -1;
      host.setAttribute('aria-label', 'Registrar pago');
      host.innerHTML = '<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable"><div class="modal-content"></div></div>';
      document.body.appendChild(host); content = host.querySelector('.modal-content');
      modal = bootstrap.Modal.getOrCreateInstance(host);
      host.addEventListener('hide.bs.modal', function (e) { if (busy) e.preventDefault(); });
      host.addEventListener('hidden.bs.modal', function () { if (saved) window.location.reload(); });
      host.addEventListener('submit', async function (e) {
        const form = e.target.closest('[data-pago-form]'); if (!form) return;
        e.preventDefault(); e.stopImmediatePropagation(); if (busy) return;
        busy = true;
        const button = form.querySelector('[type="submit"]'); button.disabled = true;
        try {
          const response = await fetch(form.action, {method:'POST', body:new FormData(form), credentials:'same-origin', headers:{'X-Requested-With':'XMLHttpRequest'}});
          if (![200,422].includes(response.status) || response.redirected) throw new Error('No se pudo confirmar el pago. Cerrá y revisá el estado del pedido antes de volver a intentar.');
          display(await response.text());
        } catch (error) {
          const message = document.createElement('div'); message.className = 'alert alert-danger'; message.textContent = error.message; form.prepend(message);
          // Do not automatically repeat an uncertain financial operation.
          button.disabled = true;
        } finally { busy = false; }
      });
    }
    saved = false; content.innerHTML = '<div class="modal-body">Cargando…</div>'; modal.show();
    try {
      const target = new URL(url, window.location.href); target.searchParams.set('modal','1');
      const response = await fetch(target, {credentials:'same-origin', headers:{'X-Requested-With':'XMLHttpRequest'}});
      if (!response.ok || response.redirected) throw new Error('No se pudo cargar el pedido. Cerrá y volvé a intentarlo.');
      display(await response.text());
    } catch(error) { content.innerHTML = '<div class="modal-body"></div><div class="modal-footer"><button class="btn btn-secondary" data-bs-dismiss="modal">Cerrar</button></div>'; content.firstChild.textContent = error.message; }
  };
  document.addEventListener('click', function(e) {
    const link = e.target.closest('a[href]'); if (!link || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button) return;
    const url = new URL(link.href, window.location.href);
    if (url.origin === window.location.origin && /^\/ventas\/\d+\/pago\/$/.test(url.pathname)) { e.preventDefault(); e.stopImmediatePropagation(); window.sironaOpenPago(url.href); }
  }, true);
  document.querySelectorAll('[data-pago-form]').forEach(initFields);
})();
