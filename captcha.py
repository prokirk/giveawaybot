import io
import random
import string
import uuid
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os


def _get_font(size: int):
    """Try to load a system font, fall back to default."""
    font_candidates = [
        "arial.ttf", "Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/verdana.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    for path in font_candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def generate_captcha() -> tuple[bytes, str]:
    """
    Generate a math-based image captcha.
    Returns (image_bytes_png, answer_string).
    """
    # Generate a simple math problem
    ops = ['+', '-', '×']
    op = random.choice(ops)
    if op == '+':
        a, b = random.randint(10, 50), random.randint(10, 50)
        answer = str(a + b)
        question = f"{a} + {b} = ?"
    elif op == '-':
        a, b = random.randint(20, 70), random.randint(5, 20)
        answer = str(a - b)
        question = f"{a} - {b} = ?"
    else:  # multiply small numbers
        a, b = random.randint(2, 9), random.randint(2, 9)
        answer = str(a * b)
        question = f"{a} × {b} = ?"

    # Canvas
    width, height = 280, 100
    bg_color = (15, 17, 26)
    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)

    # Decorative noise lines
    for _ in range(12):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        color = (random.randint(30, 80), random.randint(30, 80), random.randint(80, 150))
        draw.line([(x1, y1), (x2, y2)], fill=color, width=1)

    # Noise dots
    for _ in range(200):
        x = random.randint(0, width)
        y = random.randint(0, height)
        r = random.randint(40, 120)
        draw.point((x, y), fill=(r, r, r))

    # Draw question text
    font_large = _get_font(38)
    font_small = _get_font(13)

    # Centered question
    text_w = draw.textlength(question, font=font_large) if hasattr(draw, 'textlength') else 180
    x_pos = max(10, (width - text_w) // 2)

    # Shadow
    draw.text((x_pos + 2, 27), question, font=font_large, fill=(20, 20, 60))
    # Gradient-ish: draw in bright color
    draw.text((x_pos, 25), question, font=font_large, fill=(100, 180, 255))

    # Label
    draw.text((8, 4), "🔐 Solve to Enter", font=font_small, fill=(100, 100, 140))
    draw.text((8, height - 18), "Type the answer below ↓", font=font_small, fill=(80, 80, 120))

    # Slight blur to deter OCR
    img = img.filter(ImageFilter.GaussianBlur(radius=0.6))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read(), answer


def generate_token() -> str:
    return str(uuid.uuid4()).replace("-", "")
