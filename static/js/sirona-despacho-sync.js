(function (global) {
  var CHANNEL_NAME = "sirona-despacho-sync";
  var STORAGE_KEY = "sirona-despacho-sync";
  var channel = null;

  try {
    channel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel(CHANNEL_NAME) : null;
  } catch (e) {}

  function normalizePayload(data) {
    if (!data || data.venta_id == null) return null;
    return {
      venta_id: data.venta_id,
      estado: data.estado || "no_armado",
      label: data.label || "",
      despacho_armado: !!data.despacho_armado,
      despacho_despachado: !!data.despacho_despachado,
      despacho_despachado_en: data.despacho_despachado_en || null,
    };
  }

  function applyToDespachosRow(row, data) {
    if (!row || !data) return;
    var estado = data.estado || "no_armado";
    row.classList.remove(
      "venta-despacho-row--no_armado",
      "venta-despacho-row--armado",
      "venta-despacho-row--despachado"
    );
    row.classList.add("venta-despacho-row--" + estado);

    var badge = row.querySelector(".venta-despacho-estado-badge");
    if (badge) {
      badge.classList.remove(
        "venta-despacho-estado-badge--no_armado",
        "venta-despacho-estado-badge--armado",
        "venta-despacho-estado-badge--despachado"
      );
      badge.classList.add("venta-despacho-estado-badge--" + estado);
    }

    var icon = row.querySelector(".venta-despacho-ico");
    if (icon) {
      icon.classList.remove(
        "venta-despacho-ico--no_armado",
        "venta-despacho-ico--armado",
        "venta-despacho-ico--despachado"
      );
      icon.classList.add("venta-despacho-ico--" + estado);
      if (data.label) {
        icon.setAttribute("title", data.label);
        icon.setAttribute("aria-label", data.label);
      }
    }

    var text = row.querySelector(".venta-despacho-estado-text");
    if (text && data.label) text.textContent = data.label;

    var armado = row.querySelector(".venta-despacho-armado");
    var despachado = row.querySelector(".venta-despacho-despachado");
    if (armado) armado.checked = !!data.despacho_armado;
    if (despachado) despachado.checked = !!data.despacho_despachado;

    var tsCell = row.querySelector(".venta-despacho-despachado-en");
    if (tsCell) {
      tsCell.textContent = data.despacho_despachado_en || "—";
    }
  }

  function applyToHistorialButton(btn, data) {
    if (!btn || !data) return;
    var estado = data.estado || "no_armado";
    btn.setAttribute("data-despacho-estado", estado);
    if (data.label) {
      btn.setAttribute("title", data.label);
      btn.setAttribute("aria-label", "Cambiar estado de despacho: " + data.label);
    }
    btn.classList.remove(
      "venta-despacho-ico--no_armado",
      "venta-despacho-ico--armado",
      "venta-despacho-ico--despachado"
    );
    btn.classList.add("venta-despacho-ico--" + estado);
  }

  function applyAll(data) {
    var payload = normalizePayload(data);
    if (!payload) return;
    var id = String(payload.venta_id);
    var row = document.getElementById("pedido-" + id);
    if (row) applyToDespachosRow(row, payload);
    document.querySelectorAll('.venta-despacho-ico-btn[data-venta-id="' + id + '"]').forEach(function (btn) {
      applyToHistorialButton(btn, payload);
    });
  }

  function publish(data, source) {
    var payload = normalizePayload(data);
    if (!payload) return;
    applyAll(payload);
    var msg = { payload: payload, source: source || "local", ts: Date.now() };
    if (channel) {
      try {
        channel.postMessage(msg);
      } catch (e) {}
    }
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(msg));
      localStorage.removeItem(STORAGE_KEY);
    } catch (e) {}
  }

  function onRemoteMessage(msg) {
    if (!msg || !msg.payload) return;
    applyAll(msg.payload);
  }

  if (channel) {
    channel.onmessage = function (ev) {
      onRemoteMessage(ev.data);
    };
  }

  window.addEventListener("storage", function (ev) {
    if (ev.key !== STORAGE_KEY || !ev.newValue) return;
    try {
      onRemoteMessage(JSON.parse(ev.newValue));
    } catch (e) {}
  });

  global.SironaDespachoSync = {
    applyAll: applyAll,
    publish: publish,
    applyToDespachosRow: applyToDespachosRow,
    applyToHistorialButton: applyToHistorialButton,
  };
})(window);
