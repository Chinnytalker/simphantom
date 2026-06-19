"""
Generate favicon.ico, favicon.png, and apple-touch-icon.png
using the SimPhantom SP lettermark design.
Run once: python generate_favicon.py
"""
from PIL import Image, ImageDraw, ImageFont
import os

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "static", "img")

# Windows system font paths — tries Bold variants first
FONT_PATHS = [
    r"C:\Windows\Fonts\arialbd.ttf",    # Arial Bold
    r"C:\Windows\Fonts\calibrib.ttf",   # Calibri Bold
    r"C:\Windows\Fonts\seguibl.ttf",    # Segoe UI Black
    r"C:\Windows\Fonts\segoeui.ttf",    # Segoe UI (fallback)
    r"C:\Windows\Fonts\arial.ttf",      # Arial (last resort)
]


def get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_PATHS:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def draw_icon(size: int) -> Image.Image:
    """Draw the SP monogram icon at the given pixel size (2x supersampled)."""
    W = size * 2
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Background: deep indigo circle
    bg_color = (20, 17, 60)
    d.ellipse([(0, 0), (W - 1, W - 1)], fill=bg_color)

    # Subtle indigo border
    d.ellipse([(0, 0), (W - 1, W - 1)],
              fill=None, outline=(79, 70, 229, 100), width=max(1, W // 40))

    # "SP" text — light indigo (approximates gradient)
    font_size = int(W * 0.46)
    font = get_font(font_size)
    text = "SP"

    # Measure text
    bbox = d.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (W - tw) // 2 - bbox[0]
    ty = (W - th) // 2 - bbox[1] - int(W * 0.02)  # slight upward nudge

    d.text((tx, ty), text, font=font, fill=(180, 190, 252))

    # Downscale to target size
    return img.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # apple-touch-icon.png (180x180)
    touch = draw_icon(512).resize((180, 180), Image.LANCZOS)
    touch.save(os.path.join(OUTPUT_DIR, "apple-touch-icon.png"), "PNG")
    print("OK apple-touch-icon.png  (180x180)")

    # favicon.png (512x512, high-res reference)
    big = draw_icon(512)
    big.save(os.path.join(OUTPUT_DIR, "favicon.png"), "PNG")
    print("OK favicon.png           (512x512)")

    # android-chrome PNGs
    draw_icon(512).resize((512, 512), Image.LANCZOS).save(
        os.path.join(OUTPUT_DIR, "android-chrome-512x512.png"), "PNG")
    draw_icon(512).resize((192, 192), Image.LANCZOS).save(
        os.path.join(OUTPUT_DIR, "android-chrome-192x192.png"), "PNG")
    print("OK android-chrome-512x512.png / 192x192.png")

    # favicon.ico (multi-size: 16, 32, 48)
    sizes = [16, 32, 48]
    frames = [draw_icon(sz) for sz in sizes]
    frames[0].save(
        os.path.join(OUTPUT_DIR, "favicon.ico"),
        format="ICO",
        sizes=[(sz, sz) for sz in sizes],
        append_images=frames[1:],
    )
    print(f"OK favicon.ico           ({'/'.join(str(s) for s in sizes)} px)")
    print(f"\nAll files written to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
