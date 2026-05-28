/**
 * Posiciona menús fijos de búsqueda de producto y reserva espacio al final del
 * scroll de la página para que la lista interna no compita con el scroll general.
 */
(function (global) {
  var PAD_CLASS = "sirona-select-search-scroll-pad";
  var GAP = 4;
  var VIEWPORT_MARGIN = 14;
  var MIN_LIST = 120;
  var openMenus = 0;

  function scrollPadTarget() {
    return (
      document.querySelector("main.app-main.page-shell") ||
      document.querySelector("main.app-main") ||
      document.body
    );
  }

  function applyPageScrollPad(px) {
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
    applyPageScrollPad(0);
  }

  function menuChromeHeight(menu, searchInput) {
    var h = 0;
    try {
      var cs = getComputedStyle(menu);
      h += (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
      h += (parseFloat(cs.borderTopWidth) || 0) + (parseFloat(cs.borderBottomWidth) || 0);
    } catch (e) {}
    if (searchInput && menu.contains(searchInput)) {
      h += searchInput.offsetHeight || 0;
      try {
        var is = getComputedStyle(searchInput);
        h += parseFloat(is.marginBottom) || 0;
      } catch (e2) {}
    }
    return h;
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

    var r = anchor.getBoundingClientRect();
    menu.style.position = "fixed";
    menu.style.top = Math.round(r.bottom + GAP) + "px";
    if (window.innerWidth <= 575) {
      menu.style.left = "8px";
      menu.style.width = Math.max(260, window.innerWidth - 16) + "px";
    } else {
      menu.style.left = Math.round(r.left) + "px";
      menu.style.width = Math.max(280, Math.round(r.width)) + "px";
    }
    menu.style.zIndex = "2000";

    var vh = window.innerHeight;
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
    var docH = Math.max(
      document.documentElement.scrollHeight || 0,
      document.body.scrollHeight || 0
    );
    var padDoc = Math.max(0, totalH - (docH - docBottom - VIEWPORT_MARGIN));

    applyPageScrollPad(Math.max(padViewport, padDoc));
  }

  function onOpen() {
    openMenus += 1;
  }

  function onClose() {
    openMenus = Math.max(0, openMenus - 1);
    if (openMenus === 0) clearPageScrollPad();
  }

  global.SironaSelectSearchMenu = {
    position: position,
    clearPageScrollPad: clearPageScrollPad,
    onOpen: onOpen,
    onClose: onClose,
  };
})(typeof window !== "undefined" ? window : this);
