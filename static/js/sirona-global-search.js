(function () {
  "use strict";

  function debounce(fn, ms) {
    let t;
    return function () {
      const args = arguments;
      const self = this;
      clearTimeout(t);
      t = setTimeout(function () {
        fn.apply(self, args);
      }, ms);
    };
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function initWrap(wrap) {
    const url = wrap.getAttribute("data-search-url");
    if (!url) return;

    const dropdown = wrap.querySelector("[data-sirona-search-dropdown]");
    const inputs = wrap.querySelectorAll("[data-sirona-search-input]");
    if (!dropdown || !inputs.length) return;

    let activeIndex = -1;
    let lastResults = [];

    function hideDropdown() {
      dropdown.hidden = true;
      dropdown.innerHTML = "";
      activeIndex = -1;
      lastResults = [];
    }

    function showDropdown() {
      dropdown.hidden = false;
    }

    function renderResults(data) {
      const results = (data && data.results) || [];
      lastResults = results;
      activeIndex = -1;
      if (!results.length) {
        const q = (data && data.q) || "";
        dropdown.innerHTML =
          '<div class="sirona-search-dropdown-empty text-muted small px-3 py-2">' +
          (q.length < 2
            ? "Escribí al menos 2 caracteres."
            : "Sin resultados para «" + escapeHtml(q) + "».") +
          "</div>";
        showDropdown();
        return;
      }

      let html = "";
      let lastGroup = "";
      results.forEach(function (item, idx) {
        if (item.group && item.group !== lastGroup) {
          lastGroup = item.group;
          html +=
            '<div class="sirona-search-dropdown-group px-3 pt-2 pb-1 small text-muted fw-semibold">' +
            escapeHtml(lastGroup) +
            "</div>";
        }
        html +=
          '<a class="sirona-search-dropdown-item" href="' +
          escapeHtml(item.url) +
          '" data-idx="' +
          idx +
          '" role="option">' +
          '<div class="sirona-search-dropdown-title">' +
          escapeHtml(item.title) +
          "</div>" +
          (item.subtitle
            ? '<div class="sirona-search-dropdown-sub text-muted small">' +
              escapeHtml(item.subtitle) +
              "</div>"
            : "") +
          "</a>";
      });
      dropdown.innerHTML = html;
      showDropdown();
    }

    function fetchResults(q) {
      const u = url + (url.indexOf("?") >= 0 ? "&" : "?") + "q=" + encodeURIComponent(q);
      fetch(u, {
        headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      })
        .then(function (r) {
          if (!r.ok) throw new Error("search failed");
          return r.json();
        })
        .then(renderResults)
        .catch(function () {
          dropdown.innerHTML =
            '<div class="sirona-search-dropdown-empty text-danger small px-3 py-2">No se pudo buscar. Intentá de nuevo.</div>';
          showDropdown();
        });
    }

    const onInput = debounce(function (ev) {
      const q = (ev.target.value || "").trim();
      inputs.forEach(function (inp) {
        if (inp !== ev.target) inp.value = q;
      });
      if (q.length < 2) {
        hideDropdown();
        return;
      }
      fetchResults(q);
    }, 280);

    function goFirstResult() {
      if (lastResults.length) {
        window.location.assign(lastResults[0].url);
        return true;
      }
      return false;
    }

    inputs.forEach(function (inp) {
      inp.addEventListener("input", onInput);
      inp.addEventListener("keydown", function (ev) {
        const items = dropdown.querySelectorAll(".sirona-search-dropdown-item");
        if (ev.key === "Escape") {
          hideDropdown();
          return;
        }
        if (ev.key === "Enter") {
          ev.preventDefault();
          if (activeIndex >= 0 && items[activeIndex]) {
            window.location.assign(items[activeIndex].getAttribute("href"));
          } else {
            goFirstResult();
          }
          return;
        }
        if (ev.key === "ArrowDown" && items.length) {
          ev.preventDefault();
          activeIndex = Math.min(activeIndex + 1, items.length - 1);
          items.forEach(function (el, i) {
            el.classList.toggle("is-active", i === activeIndex);
          });
          return;
        }
        if (ev.key === "ArrowUp" && items.length) {
          ev.preventDefault();
          activeIndex = Math.max(activeIndex - 1, 0);
          items.forEach(function (el, i) {
            el.classList.toggle("is-active", i === activeIndex);
          });
        }
      });
      inp.addEventListener("focus", function () {
        const q = (inp.value || "").trim();
        if (q.length >= 2 && !dropdown.innerHTML) fetchResults(q);
        else if (q.length >= 2 && lastResults.length) showDropdown();
      });
    });

    document.addEventListener("click", function (ev) {
      if (!wrap.contains(ev.target)) hideDropdown();
    });
  }

  document.querySelectorAll("[data-sirona-global-search]").forEach(initWrap);
})();
