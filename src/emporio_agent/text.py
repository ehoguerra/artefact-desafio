"""Text and money helpers shared by the store and the tools."""

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal

_CENTS = Decimal("0.01")
_LETTER_DIGIT_BOUNDARY = re.compile(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])")
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")
_PLURAL_SUFFIXES = (("oes", "ao"), ("aes", "ao"), ("ais", "al"), ("eis", "el"), ("s", ""))


def normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation, and split letter/digit runs ("GD20" -> "gd 20")."""
    decomposed = unicodedata.normalize("NFKD", text)
    unaccented = "".join(char for char in decomposed if not unicodedata.combining(char))
    spaced = _LETTER_DIGIT_BOUNDARY.sub(" ", unaccented.casefold())
    return _NON_ALPHANUMERIC.sub(" ", spaced).strip()


def tokens(text: str) -> tuple[str, ...]:
    return tuple(singular(token) for token in normalize(text).split())


def singular(token: str) -> str:
    """Crude Portuguese singularization ("violoes" -> "violao"); short tokens are left alone."""
    if len(token) <= 3:
        return token
    for suffix, replacement in _PLURAL_SUFFIXES:
        if token.endswith(suffix):
            return token[: -len(suffix)] + replacement
    return token


def digits(text: str) -> str:
    return "".join(char for char in text if char.isdigit())


def round_money(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def format_brl(value: Decimal) -> str:
    """Format as Brazilian currency: Decimal("2199") -> "R$ 2.199,00"."""
    us_style = f"{round_money(value):,.2f}"
    return "R$ " + us_style.replace(",", "_").replace(".", ",").replace("_", ".")
