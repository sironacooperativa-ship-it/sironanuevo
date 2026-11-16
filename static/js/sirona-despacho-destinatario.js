(function () {
  function setup(content) {
    var form = content.querySelector('#despacho-destinatario-form');
    if (!form) return;
    var select = form.querySelector('[name=destinatario]');
    var input = form.querySelector('[name=otro]');
    function toggle() {
      var otro = select.value === 'otro';
      content.querySelector('#despacho-otro-campo').hidden = !otro;
      input.required = otro;
      input.disabled = !otro;
    }
    select.addEventListener('change', toggle);
    toggle();
    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      var button = form.querySelector('[type=submit]');
      if (button.disabled) return;
      button.disabled = true;
      try {
        var response = await fetch(form.action, {method: 'POST', credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}, body: new FormData(form)});
        if (response.status === 400 && (response.headers.get('Content-Type') || '').includes('text/html')) {
          content.innerHTML = await response.text();
          setup(content);
          return;
        }
        if (!response.ok) throw new Error();
        var data = await response.json();
        if (window.SironaDespachoSync) (data.ventas || [data]).forEach(function (item) {window.SironaDespachoSync.publish(item, 'destinatario');});
        window.location.reload();
      } catch (error) {
        form.querySelector('#despacho-error').textContent = 'No se pudo guardar. Intentá de nuevo.';
        button.disabled = false;
      }
    });
  }
  window.SironaDestinatario = {open: async function (url) {
    var modal = document.getElementById('sironaModal');
    var content = document.getElementById('sironaModalContent');
    try {
      var response = await fetch(url, {credentials: 'same-origin'});
      if (!response.ok) throw new Error();
      content.innerHTML = await response.text();
      setup(content);
      bootstrap.Modal.getOrCreateInstance(modal).show();
    } catch (error) {window.alert('No se pudo abrir el despacho. Intentá de nuevo.');}
  }};
  document.addEventListener('click', function (event) {
    var button = event.target.closest('[data-destinatario-url]');
    if (!button) return;
    event.preventDefault();
    window.SironaDestinatario.open(button.dataset.destinatarioUrl);
  });
})();
