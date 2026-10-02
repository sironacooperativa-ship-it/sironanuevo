(function () {
  if ('serviceWorker' in navigator) window.addEventListener('load', function () { navigator.serviceWorker.register('/sw.js', {scope:'/'}).catch(function () {}); });
  var promptEvent, panel = document.getElementById('sironaInstallPanel');
  if (!panel) return;
  window.addEventListener('beforeinstallprompt', function (event) { event.preventDefault(); promptEvent = event; panel.hidden = false; });
  document.getElementById('sironaInstall').addEventListener('click', async function () { if (!promptEvent) return; await promptEvent.prompt(); await promptEvent.userChoice; promptEvent = null; panel.hidden = true; });
  document.getElementById('sironaInstallClose').addEventListener('click', function () { panel.hidden = true; });
  window.addEventListener('appinstalled', function () { panel.hidden = true; promptEvent = null; });
})();

(function () {
 var button = document.querySelector('.sirona-filters-toggle');
 var content = document.getElementById('sironaListFilters');
 if (!button || !content) return;
 var active = Array.from(content.querySelectorAll('input[name],select[name]')).some(function (input) { return input.name !== 'pestana' && input.type !== 'hidden' && input.value !== ''; });
 if (active) { content.classList.add('is-open'); button.setAttribute('aria-expanded','true'); }
 button.addEventListener('click', function () { var open = content.classList.toggle('is-open'); button.setAttribute('aria-expanded', String(open)); });
})();
