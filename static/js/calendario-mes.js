/**
 * Calendario mensual (vista agenda) — solo UI.
 * Lee JSON en #calendario-mes-data: { hoy, eventos: [{ fecha, titulo, tipo }, ...] }
 */
(function () {
  var root = document.getElementById("calendario-mes-root");
  var dataEl = document.getElementById("calendario-mes-data");
  if (!root || !dataEl) return;

  var data;
  try {
    data = JSON.parse(dataEl.textContent);
  } catch (e) {
    return;
  }

  var hoyIso = data.hoy;
  var eventos = data.eventos || [];
  var byDate = {};
  for (var i = 0; i < eventos.length; i++) {
    var ev = eventos[i];
    if (!ev.fecha) continue;
    if (!byDate[ev.fecha]) byDate[ev.fecha] = [];
    byDate[ev.fecha].push(ev);
  }

  var now = new Date();
  var y = now.getFullYear();
  var m = now.getMonth();

  var LABELS_DOW = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
  var MAX_TIT = 22;
  var MAX_VISIBLE = 2;

  function esc(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function trunc(s, n) {
    s = s || "";
    if (s.length <= n) return s;
    return s.slice(0, n - 1) + "…";
  }

  function monthTitle(year, month) {
    try {
      return new Date(year, month, 1).toLocaleString("es-AR", {
        month: "long",
        year: "numeric",
      });
    } catch (e) {
      return year + " — " + (month + 1);
    }
  }

  function render() {
    var first = new Date(y, m, 1);
    var startDow = (first.getDay() + 6) % 7;
    var daysInMonth = new Date(y, m + 1, 0).getDate();
    var totalCells = startDow + daysInMonth;
    var numRows = Math.ceil(totalCells / 7);
    if (numRows < 5) numRows = 5;
    if (numRows < 6) numRows = 6;

    var parts = [];
    parts.push('<div class="calen-mes-nav" role="navigation" aria-label="Mes">');
    parts.push('<div class="calen-mes-nav-left">');
    parts.push(
      '<button type="button" class="calen-mes-nav-btn" data-act="prev" aria-label="Mes anterior">'
    );
    parts.push("‹");
    parts.push("</button>");
    parts.push("</div>");

    parts.push('<div class="calen-mes-nav-center">');
    parts.push(
      '<h3 class="calen-mes-title" id="calen-mes-heading">' +
        esc(monthTitle(y, m)) +
        "</h3>"
    );
    parts.push("</div>");

    parts.push('<div class="calen-mes-nav-right">');
    parts.push(
      '<button type="button" class="calen-mes-nav-btn" data-act="next" aria-label="Mes siguiente">'
    );
    parts.push("›");
    parts.push("</button>");
    parts.push(
      '<button type="button" class="calen-mes-nav-today" data-act="today">Hoy</button>'
    );
    parts.push("</div>");
    parts.push("</div>");

    parts.push('<div class="calen-mes-weekdays" aria-hidden="true">');
    for (var d = 0; d < 7; d++) {
      parts.push('<div class="calen-mes-wd">' + esc(LABELS_DOW[d]) + "</div>");
    }
    parts.push("</div>");

    parts.push(
      '<div class="calen-mes-grid" role="grid" aria-labelledby="calen-mes-heading">'
    );
    for (var cell = 0; cell < numRows * 7; cell++) {
      var dayNum = cell - startDow + 1;
      var inMonth = dayNum >= 1 && dayNum <= daysInMonth;
      var iso = inMonth
        ? y +
          "-" +
          String(m + 1).padStart(2, "0") +
          "-" +
          String(dayNum).padStart(2, "0")
        : "";
      var isHoy = inMonth && hoyIso === iso;
      var cellClass = "calen-mes-cell";
      if (!inMonth) cellClass += " calen-mes-cell--pad";
      if (isHoy) cellClass += " calen-mes-cell--today";
      if (inMonth) cellClass += " calen-mes-cell--in";

      parts.push(
        '<div class="' +
          cellClass +
          '" role="gridcell" data-date="' +
          (inMonth ? esc(iso) : "") +
          '">'
      );

      if (inMonth) {
        parts.push(
          '<div class="calen-mes-daynum" aria-label="' +
            esc("Día " + dayNum) +
            '">' +
            String(dayNum) +
            "</div>"
        );
        var list = byDate[iso] || [];
        if (list.length) {
          parts.push('<ul class="calen-mes-evs">');
          for (var k = 0; k < list.length && k < MAX_VISIBLE; k++) {
            var t = trunc(list[k].titulo, MAX_TIT);
            var fullTit = String(list[k].titulo || "");
            var fullDesc = String(list[k].descripcion || "");
            var fullHora = String(list[k].hora || "");
            var fullTipo = String(list[k].tipo || "MAN");
            var fullReal = list[k].realizado ? "1" : "0";
            var tipoRaw = String(list[k].tipo || "MAN").toUpperCase();
            var tipoKey =
              tipoRaw === "PED"
                ? "pedido"
                : tipoRaw === "COM"
                  ? "compra"
                  : tipoRaw === "COB"
                    ? "cobro"
                    : tipoRaw === "PAG"
                      ? "pago"
                      : tipoRaw === "ENT"
                        ? "entrega"
                        : tipoRaw === "VEN"
                          ? "vencimiento"
                          : tipoRaw === "MAN"
                            ? "manual"
                            : String(list[k].tipo || "MAN").toLowerCase();
            var dot = " calen-mes-dot--" + esc(tipoKey);
            parts.push(
              '<li class="calen-mes-ev" role="button" tabindex="0" data-date="' +
                esc(iso) +
                '" data-hora="' +
                esc(fullHora) +
                '" data-tipo="' +
                esc(fullTipo) +
                '" data-realizado="' +
                esc(fullReal) +
                '" data-titulo="' +
                esc(fullTit) +
                '" data-desc="' +
                esc(fullDesc) +
                '"><span class="calen-mes-dot' +
                dot +
                '" aria-hidden="true"></span><span class="calen-mes-ev-txt">' +
                esc(t) +
                "</span></li>"
            );
          }
          if (list.length > MAX_VISIBLE) {
            parts.push(
              '<li class="calen-mes-more" role="button" tabindex="0" data-date="' +
                esc(iso) +
                '" aria-label="Más eventos">+ ' +
                String(list.length - MAX_VISIBLE) +
                " más</li>"
            );
          }
          parts.push("</ul>");
        }
      }

      parts.push("</div>");
    }
    parts.push("</div>");

    root.innerHTML = parts.join("");

    // Tooltip premium (hover) para ver detalles completos sin cortar texto.
    try {
      var tip = document.getElementById("sironaCalTip");
      if (!tip) {
        tip = document.createElement("div");
        tip.id = "sironaCalTip";
        tip.className = "sirona-cal-tooltip d-none";
        document.body.appendChild(tip);
      }

      function showTip(anchor) {
        if (!anchor) return;
        var titulo = anchor.getAttribute("data-titulo") || "";
        var desc = anchor.getAttribute("data-desc") || "";
        var fecha = anchor.getAttribute("data-date") || "";
        var hora = anchor.getAttribute("data-hora") || "";
        var tipo = anchor.getAttribute("data-tipo") || "";
        var tipoLabel =
          tipo === "PED"
            ? "Pedido"
            : tipo === "COM"
            ? "Compra"
            : tipo === "VEN"
            ? "Vencimiento"
            : tipo === "COB"
            ? "Cobro"
            : tipo === "PAG"
            ? "Pago"
            : tipo === "ENT"
            ? "Entrega"
            : "Manual";
        var realizado = anchor.getAttribute("data-realizado") === "1";

        var when = fecha ? fecha.split("-").reverse().join("/") : "—";
        if (hora) when = when + " " + hora;
        var estado = realizado ? "Realizado" : "Pendiente";

        tip.innerHTML =
          '<div class="sirona-cal-tip-title">' +
          esc(titulo) +
          '</div><div class="sirona-cal-tip-meta">' +
          esc(when) +
          " · " +
          esc(tipoLabel) +
          '</div>' +
          (desc ? '<div class="sirona-cal-tip-desc">' + esc(desc) + "</div>" : "") +
          '<div class="sirona-cal-tip-foot"><span class="sirona-cal-tip-badge ' +
          (realizado ? "is-ok" : "is-pend") +
          '">' +
          estado +
          "</span></div>";

        tip.classList.remove("d-none");
        // position near anchor, clamp to viewport
        var r = anchor.getBoundingClientRect();
        var pad = 10;
        var top = r.bottom + 8;
        var left = r.left;
        // measure after content
        tip.style.left = "0px";
        tip.style.top = "0px";
        tip.style.maxWidth = "360px";
        var tw = tip.offsetWidth || 320;
        var th = tip.offsetHeight || 120;
        if (left + tw + pad > window.innerWidth) left = window.innerWidth - tw - pad;
        if (left < pad) left = pad;
        if (top + th + pad > window.innerHeight) top = r.top - th - 8;
        if (top < pad) top = pad;
        tip.style.left = left + "px";
        tip.style.top = top + "px";
      }

      function hideTip() {
        tip.classList.add("d-none");
      }

      root.querySelectorAll(".calen-mes-ev[data-date]").forEach(function (evEl) {
        evEl.addEventListener("mouseenter", function () { showTip(evEl); });
        evEl.addEventListener("mousemove", function () { showTip(evEl); });
        evEl.addEventListener("mouseleave", hideTip);
        evEl.addEventListener("focus", function () { showTip(evEl); });
        evEl.addEventListener("blur", hideTip);
      });
    } catch (e) {}

    var btns = root.querySelectorAll("[data-act]");
    for (var b = 0; b < btns.length; b++) {
      btns[b].addEventListener("click", function (ev) {
        var act = ev.currentTarget.getAttribute("data-act");
        if (act === "prev") {
          m -= 1;
          if (m < 0) {
            m = 11;
            y -= 1;
          }
        } else if (act === "next") {
          m += 1;
          if (m > 11) {
            m = 0;
            y += 1;
          }
        } else if (act === "today") {
          var t = new Date();
          y = t.getFullYear();
          m = t.getMonth();
        }
        render();
      });
    }

    // Click en número de día: prellenar fecha del "Nuevo evento" (sin abrir agenda)
    try {
      var fechaIn = document.getElementById("id_fecha");
      var tituloIn = document.getElementById("id_titulo");
      if (fechaIn) {
        root.querySelectorAll(".calen-mes-cell--in[data-date] .calen-mes-daynum").forEach(function (dayEl) {
          dayEl.addEventListener("click", function (ev) {
            if (ev) ev.stopPropagation();
            var cellEl = dayEl.closest(".calen-mes-cell--in[data-date]");
            var iso = cellEl ? cellEl.getAttribute("data-date") : "";
            if (!iso) return;
            fechaIn.value = iso;
            try {
              fechaIn.dispatchEvent(new Event("change", { bubbles: true }));
            } catch (e) {}
            try {
              fechaIn.scrollIntoView({ block: "center", behavior: "smooth" });
            } catch (e) {}
            if (tituloIn) {
              try {
                tituloIn.focus({ preventScroll: true });
              } catch (e) {
                tituloIn.focus();
              }
            }
          });
        });
      }
    } catch (e) {}

    // Click en celda o "+X más": abrir agenda diaria en modal
    try {
      function openAgenda(iso) {
        if (!iso) return;
        var u = new URL(window.location.href);
        var qs = u.searchParams.toString();
        var url = "/calendario/dia/" + String(iso) + "/?modal=1" + (qs ? "&" + qs : "");
        // Disparar el loader global de sirona-modal.js sin duplicar lógica.
        var a = document.createElement("a");
        a.setAttribute("href", url);
        a.setAttribute("data-sirona-modal-url", url);
        document.body.appendChild(a);
        try {
          a.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
        } finally {
          a.remove();
        }
      }

      root.querySelectorAll(".calen-mes-cell--in[data-date]").forEach(function (cellEl) {
        cellEl.addEventListener("click", function (ev) {
          // Si click fue en un evento (tooltip/acciones), no duplicar.
          if (ev && ev.target && ev.target.closest && ev.target.closest(".calen-mes-ev, .calen-mes-more, .calen-mes-nav")) return;
          var iso = cellEl.getAttribute("data-date");
          if (iso) openAgenda(iso);
        });
      });
      root.querySelectorAll(".calen-mes-more[data-date]").forEach(function (moreEl) {
        moreEl.addEventListener("click", function (ev) {
          if (ev) ev.stopPropagation();
          var iso = moreEl.getAttribute("data-date");
          if (iso) openAgenda(iso);
        });
      });

      // Click sobre evento: abre agenda del día (y deja tooltip para hover)
      root.querySelectorAll(".calen-mes-ev[data-date]").forEach(function (evEl) {
        evEl.addEventListener("click", function (ev) {
          if (ev) ev.stopPropagation();
          var iso = evEl.getAttribute("data-date");
          if (iso) openAgenda(iso);
        });
        evEl.addEventListener("keydown", function (e) {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            var iso = evEl.getAttribute("data-date");
            if (iso) openAgenda(iso);
          }
        });
      });
    } catch (e) {}
  }

  render();
})();
