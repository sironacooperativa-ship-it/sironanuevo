/**
 * Desplegable “Buscar producto”: al enfocar o tocar el campo se abre el listado;
 * lo que escribís en la barra filtra por código/descripción; al elegir un ítem
 * rellena el campo `q` y opcionalmente envía el formulario.
 *
 * SironaProductosQPicker.attach({
 *   dataScriptId: 'productos-list-picker-data',
 *   inputId: 'productos-filter-q',
 *   submitOnPick: true   // default true
 * });
 */
(function (global) {
  function ensureCss() {
    try {
      if (document.getElementById("sironaSelectSearchCss")) return;
      var st = document.createElement("style");
      st.id = "sironaSelectSearchCss";
      st.textContent =
        ".sirona-select-search-menu{background:#fff;border:1px solid rgba(15,23,42,.12);border-radius:10px;box-shadow:0 10px 24px rgba(15,23,42,.12);padding:8px}" +
        ".sirona-select-search-list{max-height:320px;overflow:auto;display:flex;flex-direction:column;gap:4px}" +
        ".sirona-select-search-item{width:100%;text-align:left;border:1px solid rgba(15,23,42,.08);background:#fff;border-radius:8px;padding:6px 10px;font-size:.85rem}" +
        ".sirona-select-search-item:hover{background:#f1f5f9}";
      document.head.appendChild(st);
    } catch (e) {}
  }

  function normalizeSearch(s) {
    return String(s || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "");
  }

  function productLabel(p) {
    var c = p && p.codigo ? String(p.codigo) : "";
    var d = p && p.descripcion ? String(p.descripcion) : "";
    if (c && d) return c + " — " + d;
    return d || c || "Producto";
  }

  function attach(opts) {
    var dataScriptId = opts && opts.dataScriptId;
    var inputId = opts && opts.inputId;
    var submitOnPick = opts && opts.submitOnPick !== false;

    var dataEl = dataScriptId ? document.getElementById(dataScriptId) : null;
    var productos = [];
    try {
      productos = dataEl ? JSON.parse(dataEl.textContent || "[]") : [];
    } catch (e1) {
      productos = [];
    }
    var inpQ = inputId ? document.getElementById(inputId) : null;
    if (!inpQ || !Array.isArray(productos) || productos.length === 0) return;

    ensureCss();

    var menuId = "sirona-q-picker-menu-" + inputId.replace(/[^a-zA-Z0-9_-]/g, "_");
    var menu = document.createElement("div");
    menu.id = menuId;
    menu.className = "sirona-select-search-menu";
    menu.setAttribute("role", "listbox");
    menu.hidden = true;

    var list = document.createElement("div");
    list.className = "sirona-select-search-list";

    inpQ.setAttribute("role", "combobox");
    inpQ.setAttribute("aria-autocomplete", "list");
    inpQ.setAttribute("aria-expanded", "false");
    inpQ.setAttribute("aria-controls", menuId);
    inpQ.setAttribute("aria-haspopup", "listbox");

    function positionMenu() {
      try {
        var r = inpQ.getBoundingClientRect();
        menu.style.position = "fixed";
        menu.style.top = Math.round(r.bottom + 4) + "px";
        if (window.innerWidth <= 575) {
          menu.style.left = "8px";
          menu.style.width = Math.max(260, window.innerWidth - 16) + "px";
        } else {
          menu.style.left = Math.round(r.left) + "px";
          menu.style.width = Math.max(280, Math.round(r.width)) + "px";
        }
        menu.style.zIndex = "2000";
      } catch (e2) {}
    }

    function close() {
      menu.hidden = true;
      inpQ.setAttribute("aria-expanded", "false");
      try {
        if (menu.parentNode) menu.parentNode.removeChild(menu);
      } catch (e3) {}
    }

    function renderList() {
      var q = normalizeSearch(inpQ.value);
      var items = q
        ? productos.filter(function (p) {
            return normalizeSearch((p.codigo || "") + " " + (p.descripcion || "")).indexOf(q) !== -1;
          })
        : productos;
      list.innerHTML = "";

      items.slice(0, 400).forEach(function (p) {
        var it = document.createElement("button");
        it.type = "button";
        it.className = "sirona-select-search-item";
        it.textContent = productLabel(p);
        it.addEventListener("click", function () {
          inpQ.value = p && p.codigo ? String(p.codigo) : "";
          if (submitOnPick) {
            var form = inpQ.closest("form");
            if (form) form.submit();
          }
          close();
        });
        list.appendChild(it);
      });

      if (items.length === 0) {
        list.innerHTML = '<div class="text-muted small px-2 py-1">Sin resultados</div>';
      }
    }

    function openMenu() {
      menu.hidden = false;
      inpQ.setAttribute("aria-expanded", "true");
      try {
        document.body.appendChild(menu);
      } catch (e4) {}
      positionMenu();
      renderList();
    }

    inpQ.addEventListener("focus", openMenu);
    inpQ.addEventListener("click", function () {
      if (menu.hidden) openMenu();
      else {
        positionMenu();
        renderList();
      }
    });
    inpQ.addEventListener("blur", function () {
      window.setTimeout(function () {
        try {
          var ae = document.activeElement;
          if (ae && menu.contains(ae)) return;
          if (ae === inpQ) return;
          if (!menu.hidden) close();
        } catch (e) {}
      }, 0);
    });
    inpQ.addEventListener("input", function () {
      if (!menu.hidden) renderList();
    });

    document.addEventListener(
      "click",
      function (ev) {
        if (menu.hidden) return;
        if (menu.contains(ev.target)) return;
        if (inpQ === ev.target || (inpQ.contains && inpQ.contains(ev.target))) return;
        close();
      },
      true
    );

    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && !menu.hidden) close();
    });

    window.addEventListener(
      "scroll",
      function () {
        if (!menu.hidden) positionMenu();
      },
      true
    );
    window.addEventListener("resize", function () {
      if (!menu.hidden) positionMenu();
    });

    menu.appendChild(list);
  }

  global.SironaProductosQPicker = { attach: attach };
})(typeof window !== "undefined" ? window : this);
