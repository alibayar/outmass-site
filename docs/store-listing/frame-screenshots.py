"""Frame 1280x800 captures onto 1920x1080 canvases for Softonic.

Softonic's gallery demands a minimum of 1920x1080 and our captures are
1280x800 (16:10). Upscaling 1.5x would blur UI text, and cropping to 16:9
would cut the sidebar, so each capture is placed at native resolution on a
neutral canvas with a soft shadow. Nothing is resampled.
"""
import glob
import os

from PIL import Image, ImageDraw, ImageFilter

W, H = 1920, 1080
BG_TOP = (0xF6, 0xF8, 0xFB)
BG_BOTTOM = (0xE7, 0xEC, 0xF4)
OUT = "docs/ss/softonic"

os.makedirs(OUT, exist_ok=True)

sources = sorted(glob.glob("docs/ss/outmass-ss*.jpg"))
if not sources:
    raise SystemExit("no source captures found")

for src in sources:
    shot = Image.open(src).convert("RGB")

    canvas = Image.new("RGB", (W, H))
    px = canvas.load()
    for y in range(H):
        t = y / (H - 1)
        row = tuple(round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM))
        for x in range(W):
            px[x, y] = row

    x0 = (W - shot.width) // 2
    y0 = (H - shot.height) // 2

    # Soft drop shadow, drawn on its own layer then blurred.
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [x0, y0 + 8, x0 + shot.width, y0 + shot.height + 8],
        radius=10,
        fill=(15, 23, 42, 70),
    )
    canvas = Image.alpha_composite(
        canvas.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(18))
    ).convert("RGB")

    canvas.paste(shot, (x0, y0))

    dst = os.path.join(OUT, os.path.basename(src).replace(".jpg", "-1920.jpg"))
    canvas.save(dst, "JPEG", quality=92)
    print(dst, canvas.size, f"{os.path.getsize(dst) // 1024}KB")
