(function () {
  var url = window.SIRONA_PUNTOS_STOCK_URL;
  if (!url) return;

  function csrfToken() {
    var el = document.querySelector("[name=csrfmiddlewaretoken]");
    if (el && el.value) return el.value;
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function showError(msg) {
    var box = document.getElementById("puntos-stock-error");
    if (!box) {
      window.alert(msg);
      return;
    }
    box.textContent = msg;
    box.classList.remove("d-none");
  }

  function clearError() {
    var box = document.getElementById("puntos-stock-error");
    if (box) {
      box.textContent = "";
      box.classList.add("d-none");
    }
  }

  function post(accion, fields) {
    var body = new URLSearchParams();
    body.set("accion", accion);
    Object.keys(fields || {}).forEach(function (k) {
      body.set(k, fields[k]);
    });
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": csrfToken(),
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: body.toString(),
    }).then(function (r) {
      return r.json().then(function (data) {
        if (!r.ok) throw new Error((data && data.error) || "Error");
        return data;
      });
    });
  }

  function renderLista(puntos) {
    var ul = document.getElementById("puntos-stock-lista");
    if (!ul) return;
    ul.innerHTML = "";
    (puntos || []).forEach(function (p) {
      var li = document.createElement("li");
      li.className = "list-group-item px-0 d-flex flex-wrap align-items-center gap-2 punto-stock-fila";
      li.setAttribute("data-punto-id", p.id);
      li.innerHTML =
        '<input type="text" class="form-control form-control-sm punto-stock-nombre flex-grow-1" value="' +
        (p.nombre || "").replace(/"/g, "&quot;") +
        '" maxlength="80" />' +
        '<button type="button" class="btn btn-sm btn-outline-primary rounded-pill punto-stock-guardar">Guardar</button>' +
        '<button type="button" class="btn btn-sm btn-outline-danger rounded-pill punto-stock-eliminar">Eliminar</button>';
      ul.appendChild(li);
    });
  }

  document.addEventListener("click", function (ev) {
    var root = document.getElementById("puntos-stock-modal-root");
    if (!root || !root.contains(ev.target)) return;

    var fila = ev.target.closest(".punto-stock-fila");
    if (!fila) return;
    var id = fila.getAttribute("data-punto-id");
    if (!id) return;

    if (ev.target.closest(".punto-stock-guardar")) {
      ev.preventDefault();
      clearError();
      var nombre = (fila.querySelector(".punto-stock-nombre") || {}).value || "";
      post("editar", { punto_id: id, nombre: nombre.trim() })
        .then(function (data) {
          if (data.puntos) renderLista(data.puntos);
        })
        .catch(function (e) {
          showError(e.message || "No se pudo guardar.");
        });
    }

    if (ev.target.closest(".punto-stock-eliminar")) {
      ev.preventDefault();
      if (!window.confirm("¿Eliminar este punto de stock?")) return;
      clearError();
      post("eliminar", { punto_id: id })
        .then(function (data) {
          if (data.puntos) renderLista(data.puntos);
        })
        .catch(function (e) {
          showError(e.message || "No se pudo eliminar.");
        });
    }
  });

  document.addEventListener("submit", function (ev) {
    if (ev.target && ev.target.id === "puntos-stock-nuevo-form") {
      ev.preventDefault();
      clearError();
      var nombre = (ev.target.querySelector("[name=nombre]") || {}).value || "";
      post("crear", { nombre: nombre.trim() })
        .then(function (data) {
          if (data.puntos) renderLista(data.puntos);
          ev.target.reset();
        })
        .catch(function (e) {
          showError(e.message || "No se pudo agregar.");
        });
    }
  });
})();
