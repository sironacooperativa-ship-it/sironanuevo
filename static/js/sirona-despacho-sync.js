(function (global) {
  var CHANNEL_NAME = "sirona-despacho-sync";
  var STORAGE_KEY = "sirona-despacho-sync";
  var ESTADO_CLASSES = [
    "venta-despacho-ico--no_armado",
    "venta-despacho-ico--armado",
    "venta-despacho-ico--despachado",
  ];
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

  function applyEstadoClasses(el, estado) {
    if (!el) return;
    ESTADO_CLASSES.forEach(function (cls) {
      el.classList.remove(cls);
    });
    el.classList.add("venta-despacho-ico--" + estado);
  }

  function applyToIconEl(icon, data) {
    if (!icon || !data) return;
    var estado = data.estado || "no_armado";
    applyEstadoClasses(icon, estado);
    if (data.label) {
      icon.setAttribute("title", data.label);
      icon.setAttribute("aria-label", data.label);
    }
  }

  function historialIconEl(btn) {
    if (!btn) return null;
    return btn.querySelector(".venta-despacho-ico") || (btn.classList.contains("venta-despacho-ico") ? btn : null);
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

    applyToIconEl(row.querySelector(".venta-despacho-ico"), data);

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
      btn.setAttribute("aria-label", "Cambiar estado de despacho: " + data.label);
    }
    applyToIconEl(historialIconEl(btn), data);
    if (btn.classList.contains("venta-despacho-ico")) {
      applyToIconEl(btn, data);
    }
  }

  function findHistorialButtons(ventaId) {
    var id = String(ventaId);
    var buttons = Array.prototype.slice.call(
      document.querySelectorAll('.venta-despacho-ico-btn[data-venta-id="' + id + '"]')
    );
    if (buttons.length) return buttons;
    var row = document.querySelector('[data-venta-id="' + id + '"]');
    if (!row) return [];
    return Array.prototype.slice.call(row.querySelectorAll(".venta-despacho-ico-btn"));
  }

  function applyAll(data) {
    var payload = normalizePayload(data);
    if (!payload) return;
    var id = String(payload.venta_id);
    var row = document.getElementById("pedido-" + id);
    if (row) applyToDespachosRow(row, payload);
    findHistorialButtons(id).forEach(function (btn) {
      applyToHistorialButton(btn, payload);
    });
  }

  function initFromDom() {
    document.querySelectorAll(".venta-despacho-ico-btn[data-venta-id]").forEach(function (btn) {
      var estado = btn.getAttribute("data-despacho-estado") || "no_armado";
      var icon = historialIconEl(btn);
      var label =
        (icon && icon.getAttribute("title")) ||
        btn.getAttribute("aria-label") ||
        "";
      if (label.indexOf("Cambiar estado de despacho: ") === 0) {
        label = label.slice("Cambiar estado de despacho: ".length);
      }
      applyToHistorialButton(btn, {
        venta_id: btn.getAttribute("data-venta-id"),
        estado: estado,
        label: label,
        despacho_armado: estado !== "no_armado",
        despacho_despachado: estado === "despachado",
      });
    });

    document.querySelectorAll(".venta-despacho-row[data-venta-id], .venta-despacho-row[id^='pedido-']").forEach(function (row) {
      var id = row.getAttribute("data-venta-id") || (row.id || "").replace("pedido-", "");
      if (!id) return;
      var icon = row.querySelector(".venta-despacho-ico");
      if (!icon) return;
      var estado = "no_armado";
      ESTADO_CLASSES.forEach(function (cls) {
        if (icon.classList.contains(cls)) estado = cls.replace("venta-despacho-ico--", "");
      });
      applyToDespachosRow(row, {
        venta_id: id,
        estado: estado,
        label: icon.getAttribute("title") || "",
        despacho_armado: estado !== "no_armado",
        despacho_despachado: estado === "despachado",
      });
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
      setTimeout(function () {
        try {
          localStorage.removeItem(STORAGE_KEY);
        } catch (e2) {}
      }, 250);
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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initFromDom);
  } else {
    initFromDom();
  }

  global.SironaDespachoSync = {
    applyAll: applyAll,
    publish: publish,
    initFromDom: initFromDom,
    applyToDespachosRow: applyToDespachosRow,
    applyToHistorialButton: applyToHistorialButton,
  };
})(window);
