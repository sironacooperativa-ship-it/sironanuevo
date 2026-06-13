(function () {
  function csrfToken() {
    var el = document.querySelector("[name=csrfmiddlewaretoken]");
    if (el && el.value) return el.value;
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function rowFor(el) {
    return el.closest("tr.venta-despacho-row");
  }

  function formForRow(row) {
    if (!row) return null;
    var id = row.id || "";
    var pk = id.replace("pedido-", "");
    if (!pk) return null;
    return document.getElementById("despacho-form-" + pk);
  }

  function applyRowState(row, data) {
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
    }

    var text = row.querySelector(".venta-despacho-estado-text");
    if (text && data.label) text.textContent = data.label;

    var armado = row.querySelector(".venta-despacho-armado");
    var despachado = row.querySelector(".venta-despacho-despachado");
    if (armado) armado.checked = !!data.despacho_armado;
    if (despachado) despachado.checked = !!data.despacho_despachado;
  }

  function syncCheckboxes(changed) {
    var row = rowFor(changed);
    if (!row) return;
    var armado = row.querySelector(".venta-despacho-armado");
    var despachado = row.querySelector(".venta-despacho-despachado");
    if (!armado || !despachado) return;

    if (changed.classList.contains("venta-despacho-despachado") && despachado.checked) {
      armado.checked = true;
    }
    if (changed.classList.contains("venta-despacho-armado") && !armado.checked) {
      despachado.checked = false;
    }
  }

  function submitRow(changed) {
    var row = rowFor(changed);
    var form = formForRow(row);
    if (!row || !form) return;

    syncCheckboxes(changed);

    var armado = row.querySelector(".venta-despacho-armado");
    var despachado = row.querySelector(".venta-despacho-despachado");

    row.classList.add("venta-despacho-row--saving");
    if (armado) armado.disabled = true;
    if (despachado) despachado.disabled = true;

    var body = new URLSearchParams(new FormData(form));

    fetch(form.action, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        Accept: "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-CSRFToken": csrfToken(),
      },
      body: body.toString(),
    })
      .then(function (r) {
        return r.json().then(function (data) {
          if (!r.ok) throw new Error((data && data.error) || "Error al guardar");
          return data;
        });
      })
      .then(function (data) {
        if (window.SironaDespachoSync) {
          window.SironaDespachoSync.publish(data, "despachos");
        } else {
          applyRowState(row, data);
        }
      })
      .catch(function () {
        window.alert("No se pudo actualizar el despacho. Intentá de nuevo.");
      })
      .finally(function () {
        row.classList.remove("venta-despacho-row--saving");
        if (armado) armado.disabled = false;
        if (despachado) despachado.disabled = false;
      });
  }

  document.addEventListener("change", function (ev) {
    var t = ev.target;
    if (!t || !t.classList) return;
    if (
      t.classList.contains("venta-despacho-armado") ||
      t.classList.contains("venta-despacho-despachado")
    ) {
      submitRow(t);
    }
  });
})();
