"""Draw the app's launcher icon and opening screen from the brand files.

Run after `npx cap add android` (which writes Capacitor's own placeholders) and
whenever the logo or the mascot changes:

    python mobile/make-icons.py

Both come from the web app's own assets, so there is one logo, not a copy per
platform:
  - icon: assets/brand-icon-art.webp — the lettering of the owner's POS WAI icon
  - opening screen: assets/mascot-pos.webp above the same logo

Needs Pillow (`pip install pillow`).
"""

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
RES = HERE / "android" / "app" / "src" / "main" / "res"
IOS = HERE / "ios" / "App" / "App" / "Assets.xcassets"

LOGO = ASSETS / "brand-icon-art.webp"   # the lettering of the owner's POS WAI icon
MASCOT = ASSETS / "mascot-pos.webp"
BACKGROUND = (250, 246, 238, 255)       # warm white: the yellow logo reads well on it
BACKGROUND_HEX = "#FAF6EE"

# Android density buckets: the multiplier from dp to pixels.
DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}


def fit(image: Image.Image, width: int, height: int) -> Image.Image:
    """Scale to fit inside width x height, keeping the shape."""
    scale = min(width / image.width, height / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.LANCZOS)


def centred(canvas: Image.Image, image: Image.Image, top: int | None = None) -> None:
    x = (canvas.width - image.width) // 2
    y = (canvas.height - image.height) // 2 if top is None else top
    canvas.alpha_composite(image, (x, y))


def legacy_icon(logo: Image.Image, px: int, round_: bool) -> Image.Image:
    """Phones before Android 8 show this file as it is: a tile with the logo."""
    tile = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    mask = Image.new("L", (px, px), 0)
    draw = ImageDraw.Draw(mask)
    if round_:
        draw.ellipse((0, 0, px - 1, px - 1), fill=255)
    else:
        draw.rounded_rectangle((0, 0, px - 1, px - 1), radius=round(px * 0.22), fill=255)
    tile.paste(Image.new("RGBA", (px, px), BACKGROUND), (0, 0), mask)
    # A circle has less room at its corners than a rounded square.
    share = 0.70 if round_ else 0.80
    centred(tile, fit(logo, round(px * share), round(px * share)))
    return tile


def adaptive_foreground(logo: Image.Image, px: int) -> Image.Image:
    """Android 8 and later cut this 108dp layer to the launcher's own shape and
    may show only its middle 66dp, so the logo stays inside that circle."""
    layer = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    safe = px * 66 / 108
    centred(layer, fit(logo, round(safe * 0.92), round(safe * 0.92)))
    return layer


def opening_screen(logo: Image.Image, mascot: Image.Image, scale: float) -> Image.Image:
    """The mascot over the logo, as one picture the launch theme centres."""
    width = round(180 * scale)
    mascot_part = fit(mascot, width, round(150 * scale))
    logo_part = fit(logo, round(150 * scale), round(80 * scale))
    space = round(12 * scale)
    picture = Image.new("RGBA", (width, mascot_part.height + space + logo_part.height), (0, 0, 0, 0))
    centred(picture, mascot_part, top=0)
    centred(picture, logo_part, top=mascot_part.height + space)
    return picture


def ios_app_icon(logo: Image.Image, px: int = 1024) -> Image.Image:
    """iPhone's one icon file. Square, filled to the edge, and with no see-through
    anywhere: the App Store turns away an icon that has an alpha channel."""
    tile = Image.new("RGBA", (px, px), BACKGROUND)
    centred(tile, fit(logo, round(px * 0.78), round(px * 0.78)))
    return tile.convert("RGB")


def ios_opening_screen(logo: Image.Image, mascot: Image.Image, px: int = 2732) -> Image.Image:
    """Capacitor shows one square picture on every iPhone and iPad, cropped to the
    screen, so the mascot and logo sit in the middle of a wide field of colour."""
    canvas = Image.new("RGBA", (px, px), BACKGROUND)
    centred(canvas, opening_screen(logo, mascot, px / 180 * 0.42))
    return canvas.convert("RGB")


def write_ios(logo: Image.Image, mascot: Image.Image) -> None:
    icons = IOS / "AppIcon.appiconset"
    icons.mkdir(parents=True, exist_ok=True)
    ios_app_icon(logo).save(icons / "AppIcon-512@2x.png")

    splash = IOS / "Splash.imageset"
    splash.mkdir(parents=True, exist_ok=True)
    # 2732 square of mostly flat colour: 255 shades hold the mascot's gradients
    # and save about 2.3 MB across the three copies the app carries.
    picture = ios_opening_screen(logo, mascot).quantize(colors=255, method=Image.MEDIANCUT)
    # Capacitor asks for the same picture at 1x, 2x and 3x.
    for name in ("splash-2732x2732.png", "splash-2732x2732-1.png", "splash-2732x2732-2.png"):
        picture.save(splash / name, optimize=True)
    print("iPhone icon and opening screen written to", IOS)


def main() -> None:
    if not RES.exists():
        raise SystemExit("ยังไม่มีโฟลเดอร์ android ให้รัน npx cap add android ก่อน")
    logo = Image.open(LOGO).convert("RGBA")
    mascot = Image.open(MASCOT).convert("RGBA")

    for name, scale in DENSITIES.items():
        folder = RES / f"mipmap-{name}"
        folder.mkdir(exist_ok=True)
        legacy_icon(logo, round(48 * scale), False).save(folder / "ic_launcher.png")
        legacy_icon(logo, round(48 * scale), True).save(folder / "ic_launcher_round.png")
        adaptive_foreground(logo, round(108 * scale)).save(folder / "ic_launcher_foreground.png")

        splash = RES / f"drawable-{name}"
        splash.mkdir(exist_ok=True)
        opening_screen(logo, mascot, scale).save(splash / "splash_brand.png")

    (RES / "values" / "ic_launcher_background.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
        f'    <color name="ic_launcher_background">{BACKGROUND_HEX}</color>\n</resources>\n',
        encoding="utf-8")

    # Capacitor's placeholder opening screen is a full-screen bitmap that the
    # launch theme stretches to fit. Ours is a colour with the picture in the
    # middle, so it never distorts on a tall or a wide screen.
    for old in RES.glob("drawable*/splash.png"):
        old.unlink()
    (RES / "drawable" / "splash.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<layer-list xmlns:android="http://schemas.android.com/apk/res/android">\n'
        f'    <item><color android:color="{BACKGROUND_HEX}"/></item>\n'
        '    <item><bitmap android:gravity="center" android:src="@drawable/splash_brand"/></item>\n'
        '</layer-list>\n', encoding="utf-8")
    print("icons and opening screen written to", RES)

    # The iPhone project is optional: it only exists once `npx cap add ios` ran.
    if IOS.exists():
        write_ios(logo, mascot)


if __name__ == "__main__":
    main()
