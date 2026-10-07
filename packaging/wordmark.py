"""Regenerates assets/wordmark-{dark,light}.png: the sidebar header (icon + "< Atalaya />" + subtitle).

Run on Windows from the project root after changing the text or the palette:
    .venv\\Scripts\\python.exe packaging\\wordmark.py
Drawn at 3x so it stays sharp at the 48 px the GUI shows; Segoe UI is only needed here, not at runtime.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = Path(r"C:\Windows\Fonts")
SCALE, HEIGHT = 3, 48
SUBTITLE = "Monitor local · solo lectura"
THEMES = {  # same values as .streamlit/config.toml
    "dark": {"ink": "#E6E9EC", "muted": "#A7B0BA", "brand": "#6BC043"},
    "light": {"ink": "#13171F", "muted": "#5B6570", "brand": "#367C1D"},
}


def render(theme: dict[str, str]) -> Image.Image:
    h = HEIGHT * SCALE
    title = ImageFont.truetype(str(FONTS / "segoeuib.ttf"), 25 * SCALE)
    bracket = ImageFont.truetype(str(FONTS / "segoeui.ttf"), 25 * SCALE)
    small = ImageFont.truetype(str(FONTS / "segoeui.ttf"), 11 * SCALE)
    parts = [("< ", bracket, theme["brand"]), ("Atalaya", title, theme["ink"]), (" />", bracket, theme["brand"])]
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    text_x = h + 12 * SCALE
    width = max(text_x + sum(probe.textlength(text, font=font) for text, font, _ in parts),
                text_x + probe.textlength(SUBTITLE, font=small)) + 2 * SCALE

    image = Image.new("RGBA", (int(width), h), (0, 0, 0, 0))
    icon = Image.open(ROOT / "assets" / "icon.png").convert("RGBA").resize((h, h), Image.Resampling.LANCZOS)
    mask = Image.new("L", (h, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, h - 1, h - 1), radius=10 * SCALE, fill=255)
    image.paste(icon, (0, 0), mask)

    draw = ImageDraw.Draw(image)
    x, baseline = text_x, 29 * SCALE
    for text, font, color in parts:
        draw.text((x, baseline), text, font=font, fill=color, anchor="ls")
        x += draw.textlength(text, font=font)
    draw.text((text_x, 44 * SCALE), SUBTITLE, font=small, fill=theme["muted"], anchor="ls")
    return image


if __name__ == "__main__":
    for name, theme in THEMES.items():
        path = ROOT / "assets" / f"wordmark-{name}.png"
        render(theme).save(path, optimize=True)
        print(path, Image.open(path).size)
