"""Cenários de catálogo ponta a ponta: parcelamento, descontinuados, inexistentes e promoções.

Os nomes dos testes correspondem à coluna "Verificação" de docs/FAILURE_MODES.md (E1, E7–E9).
"""

import re

import pytest

from .support.runner import RunConversation
from .support.scenario import Scenario
from .support.text import has_price, normalize, sentences_mentioning

pytestmark = pytest.mark.e2e

STORE_OPEN_WEDNESDAY = "2026-03-25T10:00:00-04:00"
PRODUCT_TOOLS = ("detalhar_produto", "buscar_produtos")

ALTERNATIVAS_AO_SN_7C = [
    "Rozini",
    "Giannini",
    "Tagima",
    "Yamaha",
    "Takamine",
    "Crafter",
    "RV-174",
    "GWNE-7",
    "TW-7",
]
DESCONTINUADO = [
    "descontinu",
    "nao fabricamos",
    "saiu de linha",
    "fora de linha",
    "nao faz mais parte",
    "nao trabalhamos mais",
    "nao vendemos mais",
]
NAO_ESTA_NO_CATALOGO = [
    "nao temos",
    "nao encontr",
    "nao trabalhamos",
    "nao tem",
    "nao consta",
    "nao esta",
    "nao faz parte",
    "nao vendemos",
    "nao possuimos",
]
PROMOCAO_INATIVA = [
    "nao esta ativ",
    "encerr",
    "nao esta mais",
    "expir",
    "nao vale",
    "nao esta vigente",
    "nao temos essa promo",
    "nao ha promo",
    "nao tem promo",
    "sem promo",
    "nao esta em promo",
    "nao esta valendo",
    "nao ta valendo",
    "nao esta mais valendo",
    "terminou",
    "acabou",
]


def test_parcelamento_por_faixa(scenario: Scenario, run_conversation: RunConversation) -> None:
    """Parcelamento calculado pelo sistema: 12x num violão de R$ 599,90 deixaria a parcela abaixo
    do mínimo de R$ 100, então o máximo é 6x de R$ 99,98 sem juros."""
    transcript = run_conversation(
        scenario.name, ["Dá pra parcelar o violão Yamaha C40 em 12x?"], STORE_OPEN_WEDNESDAY
    )
    reply = transcript.replies[0]
    normalized = normalize(reply)

    scenario.expect_tool(transcript, PRODUCT_TOOLS)
    scenario.expect_fact(
        "informa o máximo de 6x", reply, re.search(r"\b6\s?x", normalized) is not None
    )
    scenario.expect_fact("informa a parcela de R$ 99,98", reply, has_price(reply, "99.98"))
    scenario.expect_fact(
        "não oferece 12x de R$ 49,99",
        reply,
        re.search(r"\b12\s?x\s?de\b", normalized) is None and not has_price(reply, "49.99"),
    )
    scenario.assert_all_checks_passed()


def test_produto_descontinuado(scenario: Scenario, run_conversation: RunConversation) -> None:
    """Produto descontinuado não é vendido como disponível; o cliente recebe alternativas de
    violões de 7 cordas ou nylon disponíveis."""
    transcript = run_conversation(
        scenario.name, ["Ainda tem o violão Shelby SN-7C?"], STORE_OPEN_WEDNESDAY
    )
    reply = transcript.replies[0]

    scenario.expect_tool(transcript, PRODUCT_TOOLS)
    scenario.expect_mentions("informa que foi descontinuado", reply, DESCONTINUADO)
    scenario.expect_mentions("sugere outro violão disponível", reply, ALTERNATIVAS_AO_SN_7C)
    scenario.assert_all_checks_passed()


def test_produto_inexistente_sem_alucinacao(
    scenario: Scenario, run_conversation: RunConversation
) -> None:
    """Produto fora do catálogo (Gibson J-45): a tool devolve "não encontrado" e o agente não
    inventa preço."""
    transcript = run_conversation(
        scenario.name, ["Quanto custa o violão Gibson J-45?"], STORE_OPEN_WEDNESDAY
    )
    reply = transcript.replies[0]
    about_j45 = sentences_mentioning(reply, ["gibson", "j-45", "j45", "j 45"])

    scenario.expect_tool(transcript, PRODUCT_TOOLS)
    scenario.expect_mentions("diz que não está no catálogo", reply, NAO_ESTA_NO_CATALOGO)
    # Tolerância documentada: preços de alternativas reais podem aparecer em outras frases;
    # o que não pode é um "R$" na mesma frase/linha que cita o Gibson J-45.
    scenario.check(
        "não atribui preço ao Gibson J-45",
        not any("R$" in sentence for sentence in about_j45),
        f"frases sobre o J-45: {about_j45 or 'nenhuma'}",
    )
    scenario.assert_all_checks_passed()


def test_promocao_expirada_nao_e_honrada(
    scenario: Scenario, run_conversation: RunConversation
) -> None:
    """Promoção inativa citada pelo cliente (12% no Takamine GD20) não é honrada; vale o preço
    atual de R$ 2.199,00."""
    transcript = run_conversation(
        scenario.name,
        ["Vi que o Takamine GD20 estava com 12% de desconto. Ainda tá valendo?"],
        STORE_OPEN_WEDNESDAY,
    )
    reply = transcript.replies[0]

    scenario.expect_tool(transcript, PRODUCT_TOOLS)
    scenario.expect_fact("informa o preço atual R$ 2.199,00", reply, has_price(reply, "2199"))
    scenario.expect_fact(
        "não aplica os 12% (R$ 1.935,12)",
        reply,
        not has_price(reply, "1935") and not has_price(reply, "1935.12"),
    )
    scenario.expect_mentions("diz que a promoção não está ativa", reply, PROMOCAO_INATIVA)
    scenario.assert_all_checks_passed()
