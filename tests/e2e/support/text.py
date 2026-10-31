"""Normalização de texto para checar fatos sem depender da redação do LLM (FAILURE_MODES A11)."""

import re
import unicodedata
from decimal import Decimal


def normalize(text: str) -> str:
    """Minúsculas, sem acentos e com espaços colapsados."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(without_accents.lower().split())


def mentioned(text: str, terms: list[str]) -> list[str]:
    """Termos (comparados já normalizados) que aparecem no texto."""
    haystack = normalize(text)
    return [term for term in terms if normalize(term) in haystack]


def price_pattern(amount: str) -> re.Pattern[str]:
    """Regex que aceita um valor em reais escrito como "2.199", "2199", "2.199,00" ou "2199.00".

    Centavos diferentes de zero são obrigatórios; ",00" é opcional.
    """
    value = Decimal(amount).quantize(Decimal("0.01"))
    integer, cents = f"{value:.2f}".split(".")
    groups = _thousands_groups(integer)
    integer_regex = r"[.\s]?".join(groups)
    cents_regex = r"(?:[.,]00)?" if cents == "00" else rf"[.,]{cents}"
    return re.compile(rf"(?<![\d.,]){integer_regex}{cents_regex}(?!\d)")


def has_price(text: str, amount: str) -> bool:
    return price_pattern(amount).search(text) is not None


def _thousands_groups(integer: str) -> list[str]:
    head_length = len(integer) % 3 or 3
    head, tail = integer[:head_length], integer[head_length:]
    return [head, *(tail[index : index + 3] for index in range(0, len(tail), 3))]


def sentences_mentioning(text: str, terms: list[str]) -> list[str]:
    """Frases (ou linhas) do texto que citam algum dos termos, para checar o que é dito sobre eles.

    A quebra exige espaço após a pontuação, então "R$ 1.000,00" não é cortado no meio.
    """
    pieces = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [piece for piece in pieces if mentioned(piece, terms)]
