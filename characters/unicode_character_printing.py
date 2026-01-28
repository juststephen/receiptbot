from escpos.constants import ESC  # pyright: ignore[reportMissingTypeStubs]
from escpos.escpos import Escpos  # pyright: ignore[reportMissingTypeStubs]
import unicodedata

from .cache import SLRUCache
from .unifont import load_unifont


class UnicodeCharacterPrinting(SLRUCache[str, int]):
    """
    User defined character cache using unifont translation layer to
    allow for printing more characters on an ESC/POS printer.
    """
    def __init__(self, printer: Escpos, prob_capacity: int = 8) -> None:
        """
        Initialise cache.
        """
        self.char_first = 0x20
        self.char_last = 0x7E

        super().__init__(
            self._next_ascii_code,
            self.char_last - self.char_first + 1,
            prob_capacity
        )

        self.printer: Escpos = printer

        self.font = load_unifont()

    def _next_ascii_code(self) -> int:
        """
        Returns the next uncached ASCII code.
        """
        used_codes = set(
            self.probationary.values()
        ) | set(
            self.protected.values()
        )
        for code in range(self.char_first, self.char_last + 1):
            if code not in used_codes:
                return code

        # Should never reach here
        raise RuntimeError('No free ASCII code available')

    def _raw(self, msg: bytes) -> None:
        """
        Send raw bytes to the printer.
        """
        self.printer._raw(msg)  # pyright: ignore[reportPrivateUsage]

    def _select_udc(self) -> None:
        """
        Select user defined characters.
        """
        self._raw(ESC + b'%\x01')

    def _cancel_udc(self) -> None:
        """
        Cancel user defined characters.
        """
        self._raw(ESC + b'%\x00')

    def _define_udc(self, code: int, bitmap: bytes) -> None:
        """
        Define a user defined character.
        """
        len_bitmap = len(bitmap)
        if len_bitmap > 27:
            raise ValueError('bitmap too large, maximum 27 bytes for font B.')
        rows = len_bitmap // 3
        self._raw(ESC + b'&' + bytes([3, code, code, rows]) + bitmap)

    def text(self, txt: str) -> None:
        """
        Print text using unifont.
        """
        # Ensure font B is used
        self.printer.set(font='b')
        # Turn on user defined characters
        self._select_udc()

        codes = bytearray()
        for char in txt:
            # Always skip control characters
            if unicodedata.category(char) == 'Cc':
                codes.append(ord(char))
                continue

            # Fetch bitmap, defaults to a question mark
            bitmap = self.font.get(char)
            if bitmap is None:
                bitmap = self.font['?']

            # Check cache for character, define if not cached
            code, cache_hit = self[char]
            codes.append(code)
            if not cache_hit:
                self._define_udc(code, bitmap[0])

                # Transmit codes
                self._raw(codes)
                codes.clear()

            # If the bitmap is two characters wide, check another code
            if len(bitmap) == 2:
                code, cache_hit = self[f'_{char}']
                codes.append(code)
                if not cache_hit:
                    self._define_udc(code, bitmap[1])

                    # Transmit codes
                    self._raw(codes)
                    codes.clear()

        # Transmit any remaining codes
        if codes:
            self._raw(codes)

        # Turn off user defined characters
        self._cancel_udc()
