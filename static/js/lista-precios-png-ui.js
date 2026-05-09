/**
 * UI export PNG lista de precios: modo único o por categoría (Farmacia / Accesorios / Otros)
 * con hojas ya definidas en el JSON del servidor.
 */
(function (global) {
  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function sanitizeId(s) {
    return String(s || "").replace(/[^a-zA-Z0-9_-]/g, "_");
  }

  function boot(opts) {
    var pngExport = opts.png_export || {};
    var modo = pngExport.modo || "unico";
    var baseTitulo = opts.baseTitulo || "";
    var qtxt = opts.qtxt || "";
    var emitidoSuffix = opts.emitidoSuffix != null ? opts.emitidoSuffix : "";
    var baseSlug = opts.baseSlug || "lista";
    var logoSrc = opts.logoSrc || "";
    var metaEl = opts.metaEl;
    var btnDownload = opts.btnDownload;
    var btnShare = opts.btnShare;
    var totalProductos = opts.totalProductos || 0;
    var panelHost = opts.panelHost;
    var placeholderEl = opts.placeholderEl;
    var categoryButtons = opts.categoryButtons;

    var logo = new Image();
    logo.crossOrigin = "anonymous";
    logo.src = logoSrc;

    function filenameForParte(parte) {
      if (!parte.filename_suffix) return baseSlug + ".png";
      return baseSlug + "--" + parte.filename_suffix + ".png";
    }

    function paintParte(canvas, parte) {
      if (!window.SironaListaPreciosPng) return;
      SironaListaPreciosPng.paint(canvas, parte, {
        baseTitulo: baseTitulo,
        qtxt: qtxt,
        logo: logo,
        emitidoSuffix: emitidoSuffix,
      });
    }

    function updateMeta(extra) {
      if (!metaEl) return;
      var t =
        "Productos: " +
        totalProductos +
        (extra ? " · " + extra : "") +
        (qtxt ? " · Buscar: " + qtxt : "");
      metaEl.textContent = t;
    }

    function canvasToBlob(canvas) {
      return new Promise(function (resolve) {
        canvas.toBlob(function (b) {
          resolve(b);
        }, "image/png");
      });
    }

    function triggerBlobDownload(blob, filename) {
      if (!blob) return;
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () {
        URL.revokeObjectURL(url);
      }, 5000);
    }

    function delay(ms) {
      return new Promise(function (r) {
        setTimeout(r, ms);
      });
    }

    function refreshLucide() {
      try {
        if (global.lucide && typeof global.lucide.createIcons === "function") {
          global.lucide.createIcons();
        }
      } catch (e) {}
    }

    /** Modo lista corta: una o más partes ya en el DOM (canvas fijos). */
    function runUnico(partes, canvasSelectorPrefix) {
      var partesArr = partes || [];
      function renderAll() {
        partesArr.forEach(function (parte, i) {
          var c = document.getElementById((canvasSelectorPrefix || "cnv-") + i);
          if (c) paintParte(c, parte);
        });
        updateMeta("PNG: " + partesArr.length);
        if (btnDownload) btnDownload.disabled = false;
        if (btnShare) btnShare.disabled = false;
        document.querySelectorAll(".lp-download-one").forEach(function (b) {
          b.disabled = false;
        });
      }
      logo.addEventListener("load", renderAll);
      renderAll();

      if (btnDownload) {
        btnDownload.onclick = async function () {
          for (var i = 0; i < partesArr.length; i++) {
            var c = document.getElementById((canvasSelectorPrefix || "cnv-") + i);
            if (!c) continue;
            var blob = await canvasToBlob(c);
            if (!blob) continue;
            triggerBlobDownload(blob, filenameForParte(partesArr[i]));
            if (partesArr.length > 1) await delay(280);
          }
        };
      }

      if (btnShare) {
        btnShare.onclick = async function () {
          var paired = [];
          for (var i = 0; i < partesArr.length; i++) {
            var c = document.getElementById((canvasSelectorPrefix || "cnv-") + i);
            if (!c) continue;
            var blob = await canvasToBlob(c);
            if (blob) paired.push({ blob: blob, parte: partesArr[i] });
          }
          if (!paired.length) return;
          for (var j = 0; j < paired.length; j++) {
            triggerBlobDownload(paired[j].blob, filenameForParte(paired[j].parte));
            if (paired.length > 1) await delay(280);
          }
          var files = paired.map(function (x) {
            return new File([x.blob], filenameForParte(x.parte), { type: "image/png" });
          });
          if (navigator.canShare && navigator.canShare({ files: files }) && navigator.share) {
            try {
              await navigator.share({ title: "Lista de precios", files: files });
              return;
            } catch (e) {}
          }
          alert(
            "Ya se descargaron los mismos PNG que exportarías con «Descargar». Si el navegador no abre el menú para compartir, adjuntá esos archivos en WhatsApp."
          );
        };
      }

      document.querySelectorAll(".lp-download-one").forEach(function (btn) {
        btn.onclick = async function () {
          var idx = Number(btn.getAttribute("data-idx"));
          var c = document.getElementById((canvasSelectorPrefix || "cnv-") + idx);
          if (!c || !partesArr[idx]) return;
          var blob = await canvasToBlob(c);
          if (!blob) return;
          var url = URL.createObjectURL(blob);
          var a = document.createElement("a");
          a.href = url;
          a.download = filenameForParte(partesArr[idx]);
          document.body.appendChild(a);
          a.click();
          a.remove();
          setTimeout(function () {
            URL.revokeObjectURL(url);
          }, 5000);
        };
      });
    }

    /** Lista grande: elegir categoría y luego hojas. */
    function runPorCategoria(categorias) {
      if (btnDownload) btnDownload.disabled = true;
      if (btnShare) btnShare.disabled = true;

      var activeTipo = null;
      var activeCat = null;

      function setDownloadShareEnabled(on) {
        if (btnDownload) btnDownload.disabled = !on;
        if (btnShare) btnShare.disabled = !on;
      }

      logo.addEventListener("load", function () {
        if (!activeTipo || !activeCat || !panelHost) return;
        var sid = sanitizeId(activeTipo);
        (activeCat.partes || []).forEach(function (parte, j) {
          var c = document.getElementById("cnv-" + sid + "-" + j);
          if (c) paintParte(c, parte);
        });
      });

      function renderCategory(tipoKey) {
        activeTipo = tipoKey;
        activeCat = null;
        for (var i = 0; i < categorias.length; i++) {
          if (categorias[i].tipo_key === tipoKey) activeCat = categorias[i];
        }
        if (!activeCat || !panelHost) return;

        if (placeholderEl) placeholderEl.classList.add("d-none");

        var partes = activeCat.partes || [];
        var sid = sanitizeId(tipoKey);
        var html = "";
        for (var j = 0; j < partes.length; j++) {
          var parte = partes[j];
          var cid = "cnv-" + sid + "-" + j;
          var btnHoja =
            parte.hojas_total > 1
              ? "Hoja " + parte.hoja_num + " / " + parte.hojas_total + " — Descargar"
              : "Descargar PNG";
          html +=
            '<div class="lp-parte-preview mb-4 pb-4 border-bottom lp-hoja-block" style="border-color:#e2e8f0!important">';
          html += '<div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">';
          html += '<div class="fw-semibold text-secondary">' + esc(parte.titulo_suffix || "Parte") + " ";
          html +=
            '<span class="text-muted fw-normal small">(' +
            (parte.productos && parte.productos.length ? parte.productos.length : 0) +
            " ítems)</span></div>";
          html +=
            '<button type="button" class="btn btn-sm btn-outline-primary lp-download-hoja" data-canvas-id="' +
            esc(cid) +
            '" data-filename-key="' +
            esc(parte.filename_suffix || "") +
            '">';
          html += esc(btnHoja);
          html += "</button></div>";
          html +=
            '<canvas id="' +
            esc(cid) +
            '" class="lp-dynamic-canvas" style="max-width:100%;height:auto;border:1px solid #e2e8f0;border-radius:12px;display:block"></canvas>';
          html += "</div>";
        }
        panelHost.innerHTML = html;
        panelHost.classList.remove("d-none");

        partes.forEach(function (parte, j) {
          var c = document.getElementById("cnv-" + sid + "-" + j);
          if (c) paintParte(c, parte);
        });

        updateMeta(activeCat.button_label + " · " + partes.length + " PNG");
        setDownloadShareEnabled(true);
        refreshLucide();

        panelHost.querySelectorAll(".lp-download-hoja").forEach(function (b) {
          b.onclick = async function () {
            var id = b.getAttribute("data-canvas-id");
            var c = document.getElementById(id);
            if (!c) return;
            var blob = await canvasToBlob(c);
            if (!blob) return;
            var url = URL.createObjectURL(blob);
            var a = document.createElement("a");
            a.href = url;
            var suf = b.getAttribute("data-filename-key");
            var parteFake = { filename_suffix: suf };
            a.download = filenameForParte(parteFake);
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(function () {
              URL.revokeObjectURL(url);
            }, 5000);
          };
        });
      }

      if (categoryButtons && categoryButtons.length) {
        categoryButtons.forEach(function (btn) {
          btn.addEventListener("click", function () {
            var tk = btn.getAttribute("data-tipo");
            categoryButtons.forEach(function (b) {
              b.classList.remove("active");
            });
            btn.classList.add("active");
            renderCategory(tk);
          });
        });
      }

      function bindDownloadAllInCategory() {
        if (!btnDownload) return;
        btnDownload.onclick = async function () {
          if (!activeCat) return;
          var sid = sanitizeId(activeTipo);
          var partes = activeCat.partes || [];
          for (var j = 0; j < partes.length; j++) {
            var c = document.getElementById("cnv-" + sid + "-" + j);
            if (!c) continue;
            var blob = await canvasToBlob(c);
            if (!blob) continue;
            triggerBlobDownload(blob, filenameForParte(partes[j]));
            if (partes.length > 1) await delay(280);
          }
        };
      }

      function bindShareCategory() {
        if (!btnShare) return;
        btnShare.onclick = async function () {
          if (!activeCat) return;
          var sid = sanitizeId(activeTipo);
          var partes = activeCat.partes || [];
          var paired = [];
          for (var j = 0; j < partes.length; j++) {
            var c = document.getElementById("cnv-" + sid + "-" + j);
            if (!c) continue;
            var blob = await canvasToBlob(c);
            if (blob) paired.push({ blob: blob, parte: partes[j] });
          }
          if (!paired.length) return;
          for (var k = 0; k < paired.length; k++) {
            triggerBlobDownload(paired[k].blob, filenameForParte(paired[k].parte));
            if (paired.length > 1) await delay(280);
          }
          var files = paired.map(function (x) {
            return new File([x.blob], filenameForParte(x.parte), { type: "image/png" });
          });
          if (navigator.canShare && navigator.canShare({ files: files }) && navigator.share) {
            try {
              await navigator.share({ title: "Lista de precios", files: files });
              return;
            } catch (e) {}
          }
          alert(
            "Ya se descargaron los mismos PNG. Si no se abrió el menú para compartir, adjuntalos en WhatsApp desde archivos descargados."
          );
        };
      }

      bindDownloadAllInCategory();
      bindShareCategory();

      updateMeta("Elegí una categoría");
    }

    if (modo === "por_categoria") {
      runPorCategoria(pngExport.categorias || []);
    } else {
      runUnico(pngExport.partes || [], opts.canvasIdPrefix || "cnv-");
    }
  }

  global.SironaListaPreciosPngUi = { boot: boot };
})(typeof window !== "undefined" ? window : this);
