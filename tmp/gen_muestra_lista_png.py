"""Muestra visual aproximada al export JS (Pillow, no el canvas del navegador)."""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

W, SCALE = 1480, 3
PAD = 44
headerH, filterH = 184, 96
rowH = 68
nrows = 8
pad_bottom = 44
h = headerH + filterH + PAD + nrows * rowH + pad_bottom


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    root = os.environ.get("WINDIR", "C:/Windows")
    name = "arialbd.ttf" if bold else "arial.ttf"
    path = os.path.join(root, "Fonts", name)
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def main() -> None:
    f_title = load_font(50, True)
    f_sub = load_font(29, False)
    f_filt_b = load_font(25, True)
    f_filt = load_font(23, False)
    f_th = load_font(25, True)
    f_td = load_font(32, False)

    cw, ch = W * SCALE, h * SCALE
    img = Image.new("RGB", (cw, ch), "#ffffff")
    draw = ImageDraw.Draw(img)

    for yy in range(headerH * SCALE):
        t = yy / max(1, headerH * SCALE - 1)
        r = int(14 + (56 - 14) * min(1, t * 1.2))
        g = int(165 + (99 - 165) * t)
        b = int(165 + (248 - 165) * min(1, t * 1.5))
        draw.rectangle([0, yy, cw, yy + 1], fill=(r, g, b))

    def xy(x: float, y: float) -> tuple[int, int]:
        return (int(x * SCALE), int(y * SCALE))

    draw.text(xy(PAD, 68), "Lista de precios — Farmacia (muestra)", fill="#ffffff", font=f_title)
    draw.text(xy(PAD, 122), "Emitido: 09/05/2026 15:00  ·  Activa", fill="#ffffff", font=f_sub)

    y0 = headerH + 20
    draw.text(xy(PAD, y0 + 28), "Filtros aplicados", fill="#0f172a", font=f_filt_b)
    draw.text(xy(PAD, y0 + 62), "Buscar: —", fill="#64748b", font=f_filt)
    w_txt = "Tipo: Todos  ·  Proveedor: Todos  ·  Estado: Todos"
    bbox = draw.textbbox((0, 0), w_txt, font=f_filt)
    tw = bbox[2] - bbox[0]
    draw.text((int((W - PAD) * SCALE - tw), int((y0 + 62) * SCALE)), w_txt, fill="#64748b", font=f_filt)

    y = headerH + filterH
    draw.text(xy(PAD, y + 26), "Código", fill="#404040", font=f_th)
    draw.text(xy(PAD + 190, y + 26), "Tipo", fill="#404040", font=f_th)
    draw.text(xy(PAD + 434, y + 26), "Descripción", fill="#404040", font=f_th)
    precio_label = "Precio"
    bbox = draw.textbbox((0, 0), precio_label, font=f_th)
    pw = bbox[2] - bbox[0]
    draw.text((int((W - PAD) * SCALE - pw), int((y + 26) * SCALE)), precio_label, fill="#404040", font=f_th)

    y += 46
    draw.line([xy(PAD, y), xy(W - PAD, y)], fill="#c8c8c8", width=max(1, SCALE))
    y += 22

    rows = [
        ("100", "Medicamentos", "Ibuprofeno 600 mg comp. x20", "$ 8.500,00"),
        ("220", "Accesorios", "Termómetro digital", "$ 12.300,00"),
        ("305", "Medicamentos", "Paracetamol jarabe 120 ml", "$ 6.200,00"),
        ("412", "Otros", "Barbijo descartable x50", "$ 15.000,00"),
        ("501", "Medicamentos", "Omeprazol 20 mg x28", "$ 22.400,00"),
    ]
    for i, (cod, tipo, desc, precio) in enumerate(rows[:nrows]):
        yy = y + i * rowH
        if i % 2 == 1:
            draw.rectangle(
                [0, int((yy - 8) * SCALE), cw, int((yy - 8 + rowH) * SCALE)],
                fill="#f1f5f9",
            )
        base = yy + 38
        draw.text(xy(PAD, base), cod, fill="#0a0a0a", font=f_td)
        draw.text(xy(PAD + 190, base), tipo, fill="#0a0a0a", font=f_td)
        draw.text(xy(PAD + 434, base), desc, fill="#0a0a0a", font=f_td)
        bbox = draw.textbbox((0, 0), precio, font=f_td)
        pr_w = bbox[2] - bbox[0]
        draw.text(
            (int((W - PAD) * SCALE - pr_w), int(base * SCALE)),
            precio,
            fill="#0a0a0a",
            font=f_td,
        )

    out_dir = os.path.join(os.path.dirname(__file__))
    out = os.path.join(out_dir, "lista_precios_muestra_export.png")
    img.save(out, "PNG", optimize=True)
    print(out)


if __name__ == "__main__":
    main()
