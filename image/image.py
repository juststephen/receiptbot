from escpos.escpos import Escpos  # pyright: ignore[reportMissingTypeStubs]
import io
from PIL import Image, ImageEnhance

# ESC/POS command to print graphics from the print buffer
print_graphics = bytes([
    0x1D, 0x28, 0x4C,  # GS 8 L
    0x02, 0x00,  # pL, pH
    48, 50  # m=48, fn=50
])


def print_image(printer: Escpos, image_bytes: bytes) -> None:
    """
    Print images using the GS ( L ESC/POS command in multiple tone mode,
    which prints raster images from the print buffer.
    """
    image = Image.open(io.BytesIO(image_bytes))

    # Scale image if larger than maximum
    width, height = image.size
    max_width = int(printer.profile.profile_data['media']['width']['pixels'])
    if width > max_width:
        target_height = int(height * max_width / width)
        image = image.resize((max_width, target_height), Image.Resampling.LANCZOS)
    width, height = image.size
    width_bytes = (width + 7) // 8

    # Remove transparency
    if image.mode in ('RGBA', 'LA', 'p'):
        if image.mode == 'p':
            image = image.convert('RGBA')
        bg = Image.new('RGBA', image.size, 'WHITE')
        image = Image.alpha_composite(bg, image)

    # Convert to grayscale
    image = image.convert('L')

    # Enhance image for printing
    enhancer = ImageEnhance.Sharpness(image)
    image = enhancer.enhance(10)
    enhancer = ImageEnhance.Contrast(image)
    image = enhancer.enhance(1.5)

    # Limit to 16 shades and add dithering
    image = image.quantize(16, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.ORDERED)
    # Convert to bytes for converting to the printer's format
    image_bytes = image.tobytes()

    # Printing has to be done in sections to fit within the print buffer
    section_lines = 128
    for section_start in range(0, height, section_lines):
        section_end = min(section_start + section_lines, height)
        section_height = section_end - section_start
        pixels = image_bytes[section_start * width : section_end * width]

        for color_i, color in enumerate(range(49, 53)):
            # Pad each row with zero bits so it aligns to full bytes
            raster = [0 for _ in range(width_bytes * section_height)]
            # Get color data per pixel
            for index, pixel in enumerate(pixels):
                if (pixel >> (3 - color_i)) & 1:
                    img_x = index % width
                    img_y = index // width
                    raster[img_y * width_bytes + img_x // 8] |= 1 << 7 - img_x % 8

            # Store raster data in the print buffer
            store_raster = (
                bytes([
                    0x1D, 0x28, 0x4C,  # GS ( L
                    (10 + len(raster)) & 0xFF,  # pL
                    (10 + len(raster) >> 8)  & 0xFF,  # pH
                    48, 112,  # m=48, fn=112
                    52,  # a=52 (multi-tone)
                    1, 1,  # bx, by (no scaling)
                    color,  # c
                    width & 0xFF, (width >> 8) & 0xFF,
                    section_height & 0xFF, (section_height >> 8) & 0xFF,
                ]) + bytes(raster)
            )
            printer._raw(store_raster)  # pyright: ignore[reportPrivateUsage]

        # Print raster graphic from the print buffer
        printer._raw(print_graphics)  # pyright: ignore[reportPrivateUsage]
