/**
 * Genera el PNG de lista de precios (canvas 2D).
 * Escala adaptativa (2× o 3×) según alto del lienzo para máxima nitidez sin
 * superar límites típicos del canvas (~32k px).
 */
(function (global) {
  var BASE_WIDTH = 1480;
  var PAD = 44;
  var COL_GAP = 18;
  /** Por debajo de esto (px dispositivo) se puede usar trazado 3× más denso */
  var MAX_DEVICE_DIM = 30000;

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

    var dense = chunk.length > 400;
    var fontRow = dense ? "600 27px Arial, Helvetica, sans-serif" : "600 32px Arial, Helvetica, sans-serif";
    var rowH = dense ? 54 : 68;
    var headerH = 184;
    var filterH = 96;
    var h =
      headerH + filterH + pad + Math.max(1, chunk.length) * rowH + pad;

    var exportScale =
      h * 3 <= MAX_DEVICE_DIM && w * 3 <= MAX_DEVICE_DIM ? 3 : 2;

    canvas.width = Math.round(w * exportScale);
    canvas.height = Math.round(h * exportScale);
    var ctx = canvas.getContext("2d", { alpha: false });
    if (!ctx) return;

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.scale(exportScale, exportScale);
    var strokeW = 2 / exportScale;
    ctx.textBaseline = "alphabetic";

    /** Alinea al grid de píxeles reales del bitmap (evita subpixel “borroso”). */
    function snap(v) {
      return Math.round(Number(v) * exportScale) / exportScale;
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
    ctx.font = "bold 50px Arial, Helvetica, sans-serif";
    ctx.fillText(headerTitle, snap(pad), snap(68));
    ctx.font = "29px Arial, Helvetica, sans-serif";
    var fecha = new Date().toLocaleString("es-AR", { dateStyle: "short", timeStyle: "short" });
    ctx.fillText("Emitido: " + fecha + emitidoSuffix, snap(pad), snap(122));

    function drawLogo() {
      try {
        if (!logo || !logo.complete || !logo.width) return;
        var lh = 42;
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
    ctx.font = "bold 25px Arial, Helvetica, sans-serif";
    ctx.fillText("Filtros aplicados", snap(pad), snap(y + 28));
    ctx.fillStyle = "#64748b";
    ctx.font = "23px Arial, Helvetica, sans-serif";
    ctx.fillText("Buscar: " + (qtxt ? qtxt : "—"), snap(pad), snap(y + 62));
    ctx.textAlign = "right";
    ctx.fillText(filtrosRight, snap(w - pad), snap(y + 62));
    ctx.textAlign = "left";
    y += filterH;

    if (logo && logo.complete) drawLogo();

    function drawClippedText(text, col, baseline, options) {
      var cfgOpt = options || {};
      var align = cfgOpt.align || "left";
      var height = cfgOpt.height || rowH;
      var top = cfgOpt.top != null ? cfgOpt.top : baseline - 34;
      ctx.save();
      ctx.beginPath();
      ctx.rect(col.x, top, col.width, height);
      ctx.clip();
      ctx.textAlign = align;
      var textX = align === "right" ? snap(col.x + col.width) : snap(col.x);
      ctx.fillText(String(text || ""), textX, snap(baseline));
      ctx.restore();
      ctx.textAlign = "left";
    }

    ctx.fillStyle = "#404040";
    ctx.font = "bold 25px Arial, Helvetica, sans-serif";
    var hdrBaseline = snap(y + 26);
    drawClippedText("Código", colCodigo, hdrBaseline, { height: 42, top: y - 4 });
    drawClippedText("Tipo", colTipo, hdrBaseline, { height: 42, top: y - 4 });
    drawClippedText("Descripción", colDesc, hdrBaseline, { height: 42, top: y - 4 });
    drawClippedText("Precio", colPrecio, hdrBaseline, { align: "right", height: 42, top: y - 4 });
    y += 46;
    ctx.strokeStyle = "#c8c8c8";
    ctx.lineWidth = strokeW;
    ctx.beginPath();
    ctx.moveTo(snap(pad), snap(y));
    ctx.lineTo(snap(tableRight), snap(y));
    ctx.stroke();
    y += 22;

    ctx.font = fontRow;
    for (var i = 0; i < chunk.length; i++) {
      var p = chunk[i];
      var rowBaseline = snap(dense ? y + 36 : y + 38);
      if (i % 2 === 1) {
        ctx.fillStyle = "#f1f5f9";
        ctx.fillRect(0, y - 8, w, rowH);
      }
      ctx.fillStyle = "#0a0a0a";
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
  };
})(typeof window !== "undefined" ? window : this);
