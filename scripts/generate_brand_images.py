"""Draw the BeamIn brand icons: QR finder patterns with a sign-in arrow."""

from pathlib import Path

from PIL import Image, ImageDraw

BRAND_DIR = Path(__file__).resolve().parents[1] / "custom_components/beamin/brand"
BLUE = (3, 169, 244, 255)
WHITE = (255, 255, 255, 255)
CANVAS = 2048  # Drawn large, then downscaled for smooth edges.


def finder(pen: ImageDraw.ImageDraw, left: float, top: float, size: float) -> None:
    """Draw one QR finder pattern: a ring around a square."""
    ring = size / 7
    pen.rounded_rectangle(
        (left, top, left + size, top + size), radius=1.2 * ring, fill=WHITE
    )
    pen.rounded_rectangle(
        (left + ring, top + ring, left + size - ring, top + size - ring),
        radius=0.6 * ring,
        fill=BLUE,
    )
    pen.rounded_rectangle(
        (
            left + 2 * ring,
            top + 2 * ring,
            left + size - 2 * ring,
            top + size - 2 * ring,
        ),
        radius=0.5 * ring,
        fill=WHITE,
    )


def draw() -> Image.Image:
    """Draw the icon at full resolution."""
    size = CANVAS
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    pen.rounded_rectangle((0, 0, size - 1, size - 1), radius=0.22 * size, fill=BLUE)

    margin = 0.15 * size
    pattern = 0.29 * size
    far = size - margin - pattern
    for left, top in ((margin, margin), (far, margin), (margin, far)):
        finder(pen, left, top, pattern)

    # Arrow beaming into the bottom-right corner.
    width = 0.085 * size
    start = (0.50 * size, 0.50 * size)
    tip = (0.80 * size, 0.80 * size)
    pen.line(
        (start, (tip[0] - 0.06 * size, tip[1] - 0.06 * size)),
        fill=WHITE,
        width=int(width),
    )
    head = 0.17 * size
    pen.polygon(
        [tip, (tip[0] - head, tip[1]), (tip[0], tip[1] - head)],
        fill=WHITE,
    )
    return image


def main() -> None:
    """Write icon.png (256 px) and icon@2x.png (512 px)."""
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    image = draw()
    for name, pixels in (("icon.png", 256), ("icon@2x.png", 512)):
        image.resize((pixels, pixels), Image.Resampling.LANCZOS).save(
            BRAND_DIR / name, optimize=True
        )


if __name__ == "__main__":
    main()
