"""Generates the mock ID images used to test the agent.

These are NOT attempts to look like a real government ID — each one is
clearly labeled as a test fixture. The verification stub in mock_api.py
keys off the FILENAME only (it never reads pixels), so what's drawn here
is purely for legibility: anyone watching a session or reviewing a
screenshot should be able to tell, at a glance, which scenario is being
tested.

Run once with: python3 assets/generate_sample_ids.py
The output files are committed to the repo, so nobody else needs to
re-run this — it's here for transparency about how the fixtures were made.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT_DIR = Path(__file__).parent
SIZE = (640, 400)

FONT_DIR = Path("/System/Library/Fonts/Supplemental")
FONT_BOLD = ImageFont.truetype(str(FONT_DIR / "Arial Bold.ttf"), 26)
FONT_REGULAR = ImageFont.truetype(str(FONT_DIR / "Arial.ttf"), 18)
FONT_SMALL = ImageFont.truetype(str(FONT_DIR / "Arial.ttf"), 13)


def _card(bg: tuple[int, int, int], badge_text: str, badge_color: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", SIZE, bg)
    draw = ImageDraw.Draw(img)

    draw.rectangle([12, 12, SIZE[0] - 12, SIZE[1] - 12], outline=(60, 60, 60), width=2)
    draw.text((36, 32), "MOCK ID DOCUMENT", font=FONT_BOLD, fill=(20, 20, 20))

    draw.rounded_rectangle([36, 76, 36 + 9 * len(badge_text) + 24, 108], radius=6, fill=badge_color)
    draw.text((48, 82), badge_text, font=FONT_SMALL, fill=(255, 255, 255))

    return img, draw


def _footer(draw: ImageDraw.ImageDraw) -> None:
    draw.text(
        (36, SIZE[1] - 48),
        "Not a real document. Test fixture only — used to exercise",
        font=FONT_SMALL,
        fill=(110, 110, 110),
    )
    draw.text(
        (36, SIZE[1] - 30),
        "Partiful's mock ID verification (see mock_api.py).",
        font=FONT_SMALL,
        fill=(110, 110, 110),
    )


def make_valid() -> Image.Image:
    img, draw = _card((234, 245, 236), "TEST FIXTURE: VALID", (43, 138, 62))
    draw.text((36, 140), "Name on document:  SAMPLE APPLICANT", font=FONT_REGULAR, fill=(30, 30, 30))
    draw.text((36, 175), "Document #:  X0192837465", font=FONT_REGULAR, fill=(30, 30, 30))
    draw.text((36, 210), "Expires:  03 / 2031", font=FONT_REGULAR, fill=(30, 30, 30))
    _footer(draw)
    return img


def make_expired() -> Image.Image:
    img, draw = _card((250, 240, 222), "TEST FIXTURE: EXPIRED", (181, 122, 21))
    draw.text((36, 140), "Name on document:  SAMPLE APPLICANT", font=FONT_REGULAR, fill=(30, 30, 30))
    draw.text((36, 175), "Document #:  X0192837465", font=FONT_REGULAR, fill=(30, 30, 30))
    draw.text((36, 210), "Expires:  03 / 2020", font=FONT_REGULAR, fill=(150, 30, 30))
    draw.text((36, 235), "(EXPIRED)", font=FONT_BOLD, fill=(150, 30, 30))
    _footer(draw)
    return img


def make_mismatch() -> Image.Image:
    img, draw = _card((246, 233, 240), "TEST FIXTURE: NAME MISMATCH", (140, 42, 96))
    draw.text((36, 140), "Name on document:  ALEX MORGAN", font=FONT_REGULAR, fill=(30, 30, 30))
    draw.text((36, 175), "Document #:  X0192837465", font=FONT_REGULAR, fill=(30, 30, 30))
    draw.text((36, 210), "Expires:  03 / 2031", font=FONT_REGULAR, fill=(30, 30, 30))
    draw.text(
        (36, 240), "(Does not match either seeded account's name)", font=FONT_SMALL, fill=(110, 40, 70)
    )
    _footer(draw)
    return img


def make_blurry() -> Image.Image:
    img = make_valid()
    img = img.filter(ImageFilter.GaussianBlur(radius=6))
    return img


def main() -> None:
    fixtures = {
        "valid_id.jpg": make_valid(),
        "expired_id.jpg": make_expired(),
        "mismatch_id.jpg": make_mismatch(),
        "blurry_id.jpg": make_blurry(),
    }
    for filename, image in fixtures.items():
        path = OUT_DIR / filename
        image.convert("RGB").save(path, quality=90)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
