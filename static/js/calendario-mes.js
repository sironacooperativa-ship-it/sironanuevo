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
            var tipoRaw = String(list[k].tipo || "MAN").toUpperCase();
            var tipoKey =
              tipoRaw === "PED"
                ? "pedido"
                : tipoRaw === "COM"
                  ? "compra"
                  : tipoRaw === "MAN"
                    ? "manual"
                    : String(list[k].tipo || "MAN").toLowerCase();
            var dot = " calen-mes-dot--" + esc(tipoKey);
            parts.push(
              '<li class="calen-mes-ev"><span class="calen-mes-dot' +
                dot +
                '" aria-hidden="true"></span><span class="calen-mes-ev-txt">' +
                esc(t) +
                "</span></li>"
            );
          }
          if (list.length > MAX_VISIBLE) {
            parts.push(
              '<li class="calen-mes-more" aria-label="Más eventos">…</li>'
            );
          }
          parts.push("</ul>");
        }
      }

      parts.push("</div>");
    }
    parts.push("</div>");

    root.innerHTML = parts.join("");

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
  }

  render();
})();
