from PIL import Image, ImageDraw, ImageFont

for size in [192, 512]:
    img = Image.new("RGBA", (size, size), (10, 10, 15, 255))
    draw = ImageDraw.Draw(img)
    margin = int(size * 0.1)
    draw.ellipse([margin, margin, size - margin, size - margin], fill=(120, 115, 245, 255))
    font = ImageFont.truetype("arial.ttf", int(size * 0.35))
    bbox = draw.textbbox((0, 0), "RW", font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (size - tw) // 2
    y = (size - th) // 2 - int(size * 0.03)
    draw.text((x, y), "RW", fill=(255, 255, 255, 255), font=font)
    img.save(f"C:/Users/salut/sakyowon-ai/icon-{size}.png")
    print(f"icon-{size}.png saved")
