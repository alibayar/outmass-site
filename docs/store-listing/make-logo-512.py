from PIL import Image, ImageDraw, ImageFont

SIZE = 512
C0 = (0x00, 0x78, 0xd4)
C1 = (0x4b, 0x2e, 0x8e)

# Diagonal gradient, matching canvas createLinearGradient(0,0,size,size)
grad = Image.new("RGB", (SIZE, SIZE))
px = grad.load()
for y in range(SIZE):
    for x in range(SIZE):
        t = (x + y) / (2 * (SIZE - 1))
        px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(C0, C1))

# Rounded-square mask, radius = 0.22 * size (same ratio as the generator)
radius = round(SIZE * 0.22)
mask = Image.new("L", (SIZE * 4, SIZE * 4), 0)
ImageDraw.Draw(mask).rounded_rectangle(
    [0, 0, SIZE * 4 - 1, SIZE * 4 - 1], radius=radius * 4, fill=255
)
mask = mask.resize((SIZE, SIZE), Image.LANCZOS)

icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
icon.paste(grad, (0, 0), mask)

# "OM" mark: 0.42 * size, centred with the generator's +0.02 nudge
font = ImageFont.truetype("C:/Windows/Fonts/seguibl.ttf", round(SIZE * 0.42))
d = ImageDraw.Draw(icon)
d.text((SIZE / 2, SIZE / 2 + SIZE * 0.02), "OM", font=font,
       fill=(255, 255, 255, 255), anchor="mm")

icon.save("docs/ss/logo-512.png", "PNG")
print("written docs/ss/logo-512.png", icon.size)
