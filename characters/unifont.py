import pickle
from os.path import isfile


def unifont_to_fontb(src: bytes) -> list[bytes]:
    """
    Rotate a unifont bitmap 90° anticlockwise and pad to fit in ESC/POS font B.
    """
    len_src: int = len(src)
    if len_src not in (16, 32):
        raise ValueError('bitmap not 8x16 or 16x16.')

    # For 16x16 we call this function again for every other byte
    dst_2nd: bytes | None = None
    if len_src == 32:
        dst_2nd, *_ = unifont_to_fontb(src[1::2])
        src = src[0::2]

    dst = bytearray(24)

    # Go over every row's bits and map them into the destination array
    for y in range(16):
        for x in range(8):
            # Only map 1s
            if src[y] & (0x80 >> x):
                # New coordinates in 2D
                new_x: int = y
                new_y: int = x

                # 2D coordinates mapped to the 1D array
                byte_index: int = new_y * 3 + new_x // 8
                bit_index: int = 7 - (new_x % 8)

                dst[byte_index] |= 1 << bit_index

    out: list[bytes] = [bytes(dst)]
    if dst_2nd is not None:
        # Add a blank row to prevent a gap between the two parts in font B
        out[0] = b'\x00\x00\x00' + out[0]
        out.append(dst_2nd)

    return out


def load_unifont(version: str = '17.0.03') -> dict[str, list[bytes]]:
    """
    Load the unifont dictionary prepared for ESC/POS printers' font B.
    """
    pickle_filename: str = f'unifont-{version}.pickle'
    unifont: dict[str, list[bytes]] = {}

    # Load from pickle if available, otherwise process
    if isfile(pickle_filename):
        with open(pickle_filename, 'rb') as f:
            unifont = pickle.load(f)
    else:
        with open(f'unifont_all-{version}.hex', 'r') as f:
            for line in f:
                code, bitmap= line.strip().split(':')
                # Convert the bitmap format and use the character as the key
                unifont[chr(int(code, 16))] = unifont_to_fontb(
                    bytes.fromhex(bitmap)
                )

        # Store processed unifont as pickle
        with open(pickle_filename, 'wb') as f:
            pickle.dump(unifont, f)

    return unifont


if __name__ == '__main__':
    load_unifont()
