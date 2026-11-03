"""Draw the brand images of the integration into its ``brand/`` folder.

Usage::

    uv run --with svg.path==7.1 --with pillow==13.0.0 scripts/brand.py <mdi-svg-folder> [<output-folder>]

``<mdi-svg-folder>`` holds ``radiator.svg`` and ``water-boiler.svg`` of the Pictogrammers ``@mdi/svg`` release
(version 7.4.47 was used; ``npm pack @mdi/svg`` and unpack it). ``<output-folder>`` defaults to the integration's
``brand`` folder. The drawing is made at 2048 px and scaled down for smooth edges. It writes ``icon.png`` (256),
``icon@2x.png`` (512), and ``logo.png`` and ``logo@2x.png`` (the same square drawing, the largest size Home
Assistant allows for the shortest side: 256 and 512), each with a dark slate outline and pipes. The four ``dark_``
files (``dark_icon.png`` and so on) are the same drawing with a light grey outline and pipes, for dark backgrounds.
Pillow is used for drawing.

Credit: the heat waves are the top of the ``radiator`` glyph and the pipes are the bottom of the ``water-boiler``
glyph of Material Design Icons, (c) Pictogrammers, under the Apache License 2.0 (full text in ``LICENSE-MDI`` in
the repository root).
"""

from pathlib import Path
import re
import sys

from PIL import Image, ImageChops, ImageDraw
from svg.path import Arc, parse_path

CANVAS = 2048
HOT = (255, 72, 9)
WARM = (255, 183, 77)
COLD = (24, 108, 255)
RIM = (120, 144, 156)  # the gauge face, and the outline of the dark variants
BAND = 120  # the height of the yellow band between the layers
INK = (55, 71, 79)
WHITE = (255, 255, 255)
INTEGRATION = Path(__file__).resolve().parent.parent / (
    "custom_components/hot_water_tank_estimator"
)


def glyph_path(folder: Path, name: str) -> str:
    """Return the path data of an MDI glyph."""
    svg = (folder / f"{name}.svg").read_text("utf-8")
    match = re.search(r'\sd="([^"]+)"', svg)
    assert match
    return match.group(1)


def split_subpaths(d: str) -> list[str]:
    """Split path data at each move command."""
    return re.findall(r"[Mm][^Mm]*", d)


def glyph_mask(d: str, scale: float, left: float, top: float) -> Image.Image:
    """Return a mask of path data (even-odd fill), mapped from its 24-unit grid to the canvas."""
    mask = Image.new("L", (CANVAS, CANVAS), 0)
    for part in split_subpaths(d):
        points = []
        for segment in parse_path(part):
            steps = 48 if isinstance(segment, Arc) else 1
            for i in range(steps):
                p = segment.point(i / steps)
                points.append((left + p.real * scale, top + p.imag * scale))
        piece = Image.new("L", mask.size, 0)
        ImageDraw.Draw(piece).polygon(points, fill=255)
        mask = ImageChops.difference(mask, piece)
    return mask


def fill(image: Image.Image, mask: Image.Image, colour: tuple[int, int, int]) -> None:
    """Paint a colour through a mask."""
    image.paste(Image.new("RGBA", image.size, (*colour, 255)), (0, 0), mask)


def rounded(box: tuple[int, int, int, int], radius: int) -> Image.Image:
    """Return a mask of a rounded rectangle."""
    mask = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius, fill=255)
    return mask


def smoothstep(x: float) -> float:
    """Ease from 0 to 1 over 0 <= x <= 1, with no slope at the ends."""
    return x * x * (3 - 2 * x)


def mix(a: tuple[int, int, int], b: tuple[int, int, int], x: float) -> tuple[int, ...]:
    """Blend colour a into colour b by x."""
    return tuple(round(p + (q - p) * x) for p, q in zip(a, b, strict=True))


def layers(split: int) -> Image.Image:
    """Return the colours of the tank water: hot above the split, cold below it.

    The yellow band starts at the split. Its first third eases from the hot colour into yellow
    (smoothstep), its middle third is plain yellow, and its last third eases from yellow into
    the cold colour, so the band has no hard edges.
    """
    third = BAND // 3
    column = Image.new("RGBA", (1, CANVAS))
    for y in range(CANVAS):
        if y < split:
            colour = HOT
        elif y < split + third:
            colour = mix(HOT, WARM, smoothstep((y - split + 0.5) / third))
        elif y < split + BAND - third:
            colour = WARM
        elif y < split + BAND:
            colour = mix(
                WARM, COLD, smoothstep((y - split - BAND + third + 0.5) / third)
            )
        else:
            colour = COLD
        column.putpixel((0, y), (*colour, 255))
    return column.resize((CANVAS, CANVAS))


def draw(folder: Path, outline: tuple[int, int, int] = INK) -> Image.Image:
    """Draw the tank with its gauge and pipes under heat waves, at the canvas size.

    ``outline`` is the colour of the tank outline and the pipes.
    """
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    left, right, top, bottom, radius, inset = 640, 1408, 400, 1700, 260, 56

    # Pipes: the bottom of the water-boiler glyph, under the tank.
    legs = glyph_mask(
        glyph_path(folder, "water-boiler"), 64, 1024 - 12 * 64, 1640 - 18 * 64
    )
    legs.paste(0, (0, 0, CANVAS, 1640))
    fill(image, legs, outline)

    # Tank: dark outline, then hot layer over the thermocline over the cold layer.
    rim = rounded((left, top, right, bottom), radius)
    fill(image, rim, outline)
    inner = rounded(
        (left + inset, top + inset, right - inset, bottom - inset), radius - inset
    )
    split = top + int((bottom - top) * 0.52)
    image.paste(layers(split), (0, 0), inner)

    # Gauge: grey face in a dark ring, centred in the hot layer, with a dark needle and hub.
    d = ImageDraw.Draw(image)
    cx, r = 1024, 200
    cy = (top + inset + split) // 2
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*INK, 255))
    d.ellipse((cx - r + 40, cy - r + 40, cx + r - 40, cy + r - 40), fill=(*RIM, 255))
    d.line((cx, cy, cx + 90, cy - 85), fill=(*INK, 255), width=34)
    d.ellipse((cx - 36, cy - 36, cx + 36, cy + 36), fill=(*INK, 255))

    # Heat waves: the three waves at the top of the radiator glyph.
    scale = 36
    waves = Image.new("L", image.size, 0)
    for part in split_subpaths(glyph_path(folder, "radiator"))[:3]:
        shape = glyph_mask(part, scale, 1024 - 12.1 * scale, 40 - 2 * scale)
        waves = ImageChops.lighter(waves, shape)
    fill(image, waves, HOT)
    return image


def fit(image: Image.Image) -> Image.Image:
    """Scale the drawing so that the top margin equals the bottom margin, which is kept as drawn."""
    box = image.getbbox()
    assert box
    cropped = image.crop(box)
    margin = CANVAS - box[3]
    height = box[3] - margin
    width = round(cropped.width * height / cropped.height)
    cropped = cropped.resize((width, height), Image.LANCZOS)
    out = Image.new("RGBA", image.size, (0, 0, 0, 0))
    out.paste(cropped, ((CANVAS - width) // 2, margin))
    return out


def main() -> None:
    """Write the brand images."""
    folder = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else INTEGRATION / "brand"
    out.mkdir(parents=True, exist_ok=True)
    for prefix, outline in (("", INK), ("dark_", RIM)):
        big = fit(draw(folder, outline))
        for name, size in (
            ("icon.png", 256),
            ("icon@2x.png", 512),
            ("logo.png", 256),
            ("logo@2x.png", 512),
        ):
            big.resize((size, size), Image.LANCZOS).save(
                out / f"{prefix}{name}", optimize=True
            )


if __name__ == "__main__":
    main()
