/**
 * Genera el PNG de lista de precios (canvas 2D).
 * Lienzo ancho (~1480px lógicos × EXPORT_SCALE) para que la tabla no quede
 * comprimida ni ilegible al compartir por WhatsApp.
 */
(function (global) {
  /** Retina / nitidez en apps que reescalan la imagen */
  var EXPORT_SCALE = 2;
  /** Ancho útil de diseño (px CSS antes del scale); mayor que 1080 = más columna Descripción */
  var BASE_WIDTH = 1480;
  var PAD = 52;
  var COL_GAP = 18;

  function paintListaPreciosCanvas(canvas, parte, cfg) {
    var chunk = (parte && parte.productos) || [];
    var baseTitulo = (cfg && cfg.baseTitulo) || "";
    var qtxt = (cfg && cfg.qtxt) || "";
    var logo = cfg && cfg.logo;
    var emitidoSuffix = (cfg && cfg.emitidoSuffix) || "";

    var w = BASE_WIDTH;
    var pad = PAD;
    var tableRight = w - pad;
    var colCodigo = { x: pad, width: 172 };
    var colTipo = { x: colCodigo.x + colCodigo.width + COL_GAP, width: 224 };
    var colPrecio = { width: 248, x: tableRight - 248 };
    var colDesc = {
      x: colTipo.x + colTipo.width + COL_GAP,
      width: Math.max(180, colPrecio.x - COL_GAP - (colTipo.x + colTipo.width + COL_GAP)),
    };

    var headerH = 176;
    var filterH = 92;
    var dense = chunk.length > 400;
    var rowH = dense ? 50 : 60;
    var h = headerH + filterH + pad + Math.max(1, chunk.length) * rowH + pad;

    canvas.width = Math.round(w * EXPORT_SCALE);
    canvas.height = Math.round(h * EXPORT_SCALE);
    var ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    /* Suavizado solo útil para drawImage (logo); el texto se define más nítido sin escala fraccionaria. */
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.scale(EXPORT_SCALE, EXPORT_SCALE);
    var strokeW = 2 / EXPORT_SCALE;

    /** Media unidad lógica con scale 2 → píxeles enteros (menos texto “nublado”). */
    function snapY(v) {
      return Math.round(Number(v) * 2) / 2;
    }

    var headerTitle = parte.titulo_suffix ? baseTitulo + " · " + parte.titulo_suffix : baseTitulo;
    var filtrosRight = parte.titulo_suffix
      ? "Categoría: " + parte.titulo_suffix
      : "Tipo: Todos  ·  Proveedor: Todos  ·  Estado: Todos";

    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, w, h);

    var grad = ctx.createLinearGradient(0, 0, w, headerH);
    grad.addColorStop(0, "#0ea5a5");
    grad.addColorStop(0.65, "#2563eb");
    grad.addColorStop(1, "#38bdf8");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, w, headerH);

    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 48px Arial, Helvetica, sans-serif";
    ctx.fillText(headerTitle, pad, snapY(66));
    ctx.font = "28px Arial, Helvetica, sans-serif";
    var fecha = new Date().toLocaleString("es-AR", { dateStyle: "short", timeStyle: "short" });
    ctx.fillText("Emitido: " + fecha + emitidoSuffix, pad, snapY(118));

    function drawLogo() {
      try {
        if (!logo || !logo.complete || !logo.width) return;
        var lh = 40;
        var lw = Math.round((logo.width / logo.height) * lh);
        ctx.save();
        ctx.fillStyle = "rgba(255,255,255,0.92)";
        ctx.strokeStyle = "rgba(255,255,255,0.25)";
        ctx.lineWidth = strokeW;
        var bx = w - pad - lw - 18;
        var by = 26;
        var bw = lw + 18;
        var bh = lh + 16;
        var r = 14;
        ctx.beginPath();
        ctx.moveTo(bx + r, by);
        ctx.arcTo(bx + bw, by, bx + bw, by + bh, r);
        ctx.arcTo(bx + bw, by + bh, bx, by + bh, r);
        ctx.arcTo(bx, by + bh, bx, by, r);
        ctx.arcTo(bx, by, bx + bw, by, r);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
        ctx.imageSmoothingEnabled = true;
        ctx.drawImage(logo, bx + 9, by + 8, lw, lh);
        ctx.restore();
      } catch (e) {}
    }

    var y = headerH + 20;
    ctx.fillStyle = "#0f172a";
    ctx.font = "bold 24px Arial, Helvetica, sans-serif";
    ctx.fillText("Filtros aplicados", pad, snapY(y + 26));
    ctx.fillStyle = "#64748b";
    ctx.font = "22px Arial, Helvetica, sans-serif";
    ctx.fillText("Buscar: " + (qtxt ? qtxt : "—"), pad, snapY(y + 58));
    ctx.textAlign = "right";
    ctx.fillText(filtrosRight, w - pad, snapY(y + 58));
    ctx.textAlign = "left";
    y += filterH;

    if (logo && logo.complete) drawLogo();

    function drawClippedText(text, col, baseline, options) {
      var cfgOpt = options || {};
      var align = cfgOpt.align || "left";
      var height = cfgOpt.height || rowH;
      var top = cfgOpt.top != null ? cfgOpt.top : baseline - 32;
      ctx.save();
      ctx.beginPath();
      ctx.rect(col.x, top, col.width, height);
      ctx.clip();
      ctx.textAlign = align;
      var textX = align === "right" ? col.x + col.width : col.x;
      ctx.fillText(String(text || ""), textX, baseline);
      ctx.restore();
      ctx.textAlign = "left";
    }

    ctx.fillStyle = "#505050";
    ctx.font = "24px Arial, Helvetica, sans-serif";
    var hdrBaseline = snapY(y + 24);
    drawClippedText("Código", colCodigo, hdrBaseline, { height: 38, top: y - 4 });
    drawClippedText("Tipo", colTipo, hdrBaseline, { height: 38, top: y - 4 });
    drawClippedText("Descripción", colDesc, hdrBaseline, { height: 38, top: y - 4 });
    drawClippedText("Precio", colPrecio, hdrBaseline, { align: "right", height: 38, top: y - 4 });
    y += 44;
    ctx.strokeStyle = "#dcdcdc";
    ctx.lineWidth = strokeW;
    ctx.beginPath();
    ctx.moveTo(pad, y);
    ctx.lineTo(tableRight, y);
    ctx.stroke();
    y += 20;

    ctx.font = dense ? "24px Arial, Helvetica, sans-serif" : "28px Arial, Helvetica, sans-serif";
    for (var i = 0; i < chunk.length; i++) {
      var p = chunk[i];
      var rowBaseline = snapY(dense ? y + 32 : y + 34);
      if (i % 2 === 1) {
        ctx.fillStyle = "#f8fafc";
        ctx.fillRect(0, y - 8, w, rowH);
      }
      ctx.fillStyle = "#1e1e1e";
      drawClippedText(p.codigo, colCodigo, rowBaseline, { top: y - 8, height: rowH });
      drawClippedText(p.tipo, colTipo, rowBaseline, { top: y - 8, height: rowH });
      drawClippedText(p.descripcion, colDesc, rowBaseline, { top: y - 8, height: rowH });
      drawClippedText(p.precio, colPrecio, rowBaseline, { align: "right", top: y - 8, height: rowH });
      y += rowH;
    }
  }

  global.SironaListaPreciosPng = {
    paint: paintListaPreciosCanvas,
    getLogicalWidth: function () {
      return BASE_WIDTH;
    },
    getExportScale: function () {
      return EXPORT_SCALE;
    },
  };
})(typeof window !== "undefined" ? window : this);
