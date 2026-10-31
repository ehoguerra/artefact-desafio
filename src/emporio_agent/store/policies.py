"""Curated store policies (knowledge/politicas_da_loja.md), addressed by topic."""

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

_SECTION_HEADING = re.compile(r"^## ", re.MULTILINE)
_TOPIC_MARKER = re.compile(r"^<!-- topic: ([a-z_]+) -->\s*$", re.MULTILINE)


class PolicyTopic(StrEnum):
    SOBRE_A_LOJA = "sobre_a_loja"
    CONTATO_E_ENDERECO = "contato_e_endereco"
    HORARIO = "horario"
    PAGAMENTO = "pagamento"
    TROCAS_E_DEVOLUCOES = "trocas_e_devolucoes"
    FRETE_E_ENTREGA = "frete_e_entrega"
    RASTREAMENTO = "rastreamento"
    PROMOCOES = "promocoes"
    GARANTIA = "garantia"
    PRIVACIDADE = "privacidade"
    ESCOPO_DE_ATENDIMENTO = "escopo_de_atendimento"


_TOPIC_SLUGS = frozenset(topic.value for topic in PolicyTopic)


@dataclass(frozen=True, slots=True)
class PolicyBook:
    sections: dict[PolicyTopic, str]

    @classmethod
    def load(cls, path: Path) -> "PolicyBook":
        sections = _parse_sections(path.read_text(encoding="utf-8"))
        missing = [topic.value for topic in PolicyTopic if topic not in sections]
        if missing:
            raise ValueError(f"{path}: missing policy topics: {', '.join(missing)}")
        return cls(sections)

    def section(self, topic: PolicyTopic) -> str:
        return self.sections[topic]


def _parse_sections(markdown: str) -> dict[PolicyTopic, str]:
    """Map each `## ` section carrying a known topic marker to its text (marker removed)."""
    sections: dict[PolicyTopic, str] = {}
    for chunk in _SECTION_HEADING.split(markdown)[1:]:
        marker = _TOPIC_MARKER.search(chunk)
        if marker and marker.group(1) in _TOPIC_SLUGS:
            text = _TOPIC_MARKER.sub("", chunk, count=1)
            sections[PolicyTopic(marker.group(1))] = "## " + re.sub(r"\n{3,}", "\n\n", text).strip()
    return sections
