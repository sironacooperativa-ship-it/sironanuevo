/**
 * Posiciona menús fijos de búsqueda de producto y reserva espacio al final del
 * scroll de la página para que la lista interna no compita con el scroll general.
 *
 * En móvil usa panel tipo bottom-sheet (más cómodo en portal vendedor / celular).
 */
(function (global) {
  var PAD_CLASS = "sirona-select-search-scroll-pad";
  var SHEET_CLASS = "sirona-select-search-menu--sheet";
  var BODY_SHEET_CLASS = "sirona-select-search-sheet-open";
  var GAP = 4;
  var VIEWPORT_MARGIN = 14;
  var MIN_LIST = 120;
  var MOBILE_BP = 767;
  var openMenus = 0;
  var backdropEl = null;

  function scrollPadTarget() {
    return (
      document.querySelector("main.app-main.page-shell") ||
      document.querySelector("main.app-main") ||
      document.body
    );
  }

  function isMobileViewport() {
    try {
      return window.innerWidth <= MOBILE_BP;
    } catch (e) {
      return false;
    }
  }

  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"']/g, function (ch) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch];
    });
  }

  function ensureBackdrop() {
    if (backdropEl && document.body.contains(backdropEl)) return backdropEl;
    backdropEl = document.createElement("div");
    backdropEl.className = "sirona-select-search-backdrop";
    backdropEl.hidden = true;
    backdropEl.setAttribute("aria-hidden", "true");
    backdropEl.addEventListener("click", function () {
      document.querySelectorAll(".sirona-select-search-menu:not([hidden])").forEach(function (menu) {
        menu.dispatchEvent(new CustomEvent("sirona:select-search-close", { bubbles: true }));
      });
    });
    document.body.appendChild(backdropEl);
    return backdropEl;
  }

  function showBackdrop() {
    if (!isMobileViewport()) return;
    var el = ensureBackdrop();
    el.hidden = false;
    document.body.classList.add(BODY_SHEET_CLASS);
  }

  function hideBackdrop() {
    if (backdropEl) {
      backdropEl.hidden = true;
    }
    if (openMenus <= 0) {
      document.body.classList.remove(BODY_SHEET_CLASS);
    }
  }

  function applyPageScrollPad(px) {
    if (isMobileViewport()) {
      clearPageScrollPad();
      return;
    }
    var el = scrollPadTarget();
    var n = Math.max(0, Math.round(px || 0));
    document.documentElement.classList.toggle(PAD_CLASS, n > 0);
    if (n > 0) {
      el.style.paddingBottom = n + "px";
      document.documentElement.style.setProperty("--sirona-select-search-scroll-pad", n + "px");
    } else {
      el.style.removeProperty("padding-bottom");
      document.documentElement.style.removeProperty("--sirona-select-search-scroll-pad");
    }
  }

  function clearPageScrollPad() {
    var el = scrollPadTarget();
    document.documentElement.classList.remove(PAD_CLASS);
    el.style.removeProperty("padding-bottom");
    document.documentElement.style.removeProperty("--sirona-select-search-scroll-pad");
  }

  function menuChromeHeight(menu, searchInput) {
    var h = 0;
    try {
      var cs = getComputedStyle(menu);
      h += (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
      h += (parseFloat(cs.borderTopWidth) || 0) + (parseFloat(cs.borderBottomWidth) || 0);
    } catch (e) {}
    var head = menu.querySelector(".sirona-select-search-sheet-head");
    if (head) h += head.offsetHeight || 0;
    if (searchInput && menu.contains(searchInput)) {
      h += searchInput.offsetHeight || 0;
      try {
        var is = getComputedStyle(searchInput);
        h += parseFloat(is.marginBottom) || 0;
      } catch (e2) {}
    }
    return h;
  }

  function ensureSheetHeader(menu) {
    if (!menu || menu.querySelector(".sirona-select-search-sheet-head")) return;
    var head = document.createElement("div");
    head.className = "sirona-select-search-sheet-head";
    head.innerHTML =
      '<span class="sirona-select-search-sheet-title">Elegir producto</span>' +
      '<button type="button" class="sirona-select-search-sheet-close" aria-label="Cerrar">×</button>';
    menu.insertBefore(head, menu.firstChild);
    var closeBtn = head.querySelector(".sirona-select-search-sheet-close");
    if (closeBtn) {
      closeBtn.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        menu.dispatchEvent(new CustomEvent("sirona:select-search-close", { bubbles: true }));
      });
    }
  }

  function clearSheetHeader(menu) {
    if (!menu) return;
    var head = menu.querySelector(".sirona-select-search-sheet-head");
    if (head) head.remove();
  }

  /**
   * @param {{ menu: HTMLElement, anchor: HTMLElement, list: HTMLElement, searchInput?: HTMLElement }} opts
   */
  function position(opts) {
    var menu = opts && opts.menu;
    var anchor = opts && opts.anchor;
    var list = opts && opts.list;
    var searchInput = opts && opts.searchInput;
    if (!menu || !anchor || !list) return;

    var vh = window.innerHeight;

    if (isMobileViewport()) {
      menu.classList.add(SHEET_CLASS);
      ensureSheetHeader(menu);
      menu.style.position = "fixed";
      menu.style.top = "auto";
      menu.style.bottom = "0";
      menu.style.left = "0";
      menu.style.right = "0";
      menu.style.width = "100%";
      menu.style.maxWidth = "100%";
      menu.style.zIndex = "2001";
      menu.style.transform = "";

      var chrome = menuChromeHeight(menu, searchInput);
      var listH = Math.max(MIN_LIST, Math.min(Math.floor(vh * 0.52), vh - chrome - VIEWPORT_MARGIN - 24));
      list.style.maxHeight = listH + "px";
      list.style.overflow = "auto";
      list.style.overscrollBehavior = "contain";
      clearPageScrollPad();
      return;
    }

    menu.classList.remove(SHEET_CLASS);
    clearSheetHeader(menu);

    var r = anchor.getBoundingClientRect();
    menu.style.position = "fixed";
    menu.style.bottom = "auto";
    menu.style.right = "auto";
    menu.style.top = Math.round(r.bottom + GAP) + "px";
    menu.style.left = Math.round(r.left) + "px";
    menu.style.width = Math.max(280, Math.round(r.width)) + "px";
    menu.style.zIndex = "2000";

    var menuTop = r.bottom + GAP;
    var chrome = menuChromeHeight(menu, searchInput);
    var maxCap = Math.min(480, Math.floor(vh * 0.72));
    var avail = vh - menuTop - VIEWPORT_MARGIN;
    var listH = Math.max(MIN_LIST, Math.min(maxCap, avail - chrome));

    list.style.maxHeight = listH + "px";
    list.style.overflow = "auto";
    list.style.overscrollBehavior = "contain";

    var totalH = chrome + listH;
    var viewportBelow = vh - menuTop - VIEWPORT_MARGIN;
    var padViewport = Math.max(0, totalH - viewportBelow);

    var docBottom = r.bottom + (window.scrollY || 0);
    var docH = Math.max(document.documentElement.scrollHeight || 0, document.body.scrollHeight || 0);
    var padDoc = Math.max(0, totalH - (docH - docBottom - VIEWPORT_MARGIN));

    applyPageScrollPad(Math.max(padViewport, padDoc));
  }

  /**
   * Ítem de producto con layout legible (código, descripción, stock).
   * @param {object} p
   * @param {() => void} onSelect
   */
  function createProductItem(p, onSelect) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "sirona-select-search-item";
    var code = escapeHtml(p && p.codigo ? p.codigo : "");
    var desc = escapeHtml(p && p.descripcion ? p.descripcion : "Producto");
    var stock = p && p.stock != null ? escapeHtml(String(p.stock)) : "—";
    btn.innerHTML =
      '<span class="sirona-pick-item-body">' +
      '<span class="sirona-pick-item-code">' +
      code +
      "</span>" +
      '<span class="sirona-pick-item-desc">' +
      desc +
      "</span>" +
      "</span>" +
      '<span class="sirona-pick-item-meta">Stock ' +
      stock +
      "</span>";
    btn.addEventListener("click", function (ev) {
      ev.preventDefault();
      if (typeof onSelect === "function") onSelect();
    });
    return btn;
  }

  function onOpen() {
    openMenus += 1;
    showBackdrop();
  }

  function onClose() {
    openMenus = Math.max(0, openMenus - 1);
    if (openMenus === 0) {
      clearPageScrollPad();
      hideBackdrop();
    }
  }

  global.SironaSelectSearchMenu = {
    position: position,
    clearPageScrollPad: clearPageScrollPad,
    onOpen: onOpen,
    onClose: onClose,
    createProductItem: createProductItem,
    isMobileViewport: isMobileViewport,
  };
})(typeof window !== "undefined" ? window : this);
