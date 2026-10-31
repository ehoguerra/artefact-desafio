"""Cenários de pedidos ponta a ponta: garantia, rastreio e cancelamento.

Os nomes dos testes correspondem à coluna "Verificação" de docs/FAILURE_MODES.md (E4–E6).
"""

import pytest

from .support.runner import RunConversation, ToolCall
from .support.scenario import Scenario

pytestmark = pytest.mark.e2e

STORE_OPEN_WEDNESDAY = "2026-03-25T10:00:00-04:00"
GARANTIA_TOPICS = {"garantia", "trocas_e_devolucoes"}

PRAZO_VENCIDO = [
    "expir",
    "venc",
    "fora do prazo",
    "passou",
    "passaram",
    "encerr",
    "ultrapass",
    "excede",
    "nao esta mais",
    "ja nao",
    "nao se aplica",
    "nao cobre",
]
TROCA_PROMETIDA = [
    "pode trocar sim",
    "consegue trocar sim",
    "dentro do prazo de troca",
    "dentro do prazo para troca",
    "dentro do prazo de garantia legal",
]
EM_TRANSITO = ["enviado", "a caminho", "despachad", "em transito", "saiu para entrega", "postado"]


def _order(number: int):
    def matches(call: ToolCall) -> bool:
        return call.arguments.get("numero_pedido") == number and not call.is_error

    return matches


def test_defeito_fora_do_prazo_de_troca(
    scenario: Scenario, run_conversation: RunConversation
) -> None:
    """Defeito relatado cerca de 150 dias após a entrega: prazos de troca por defeito (30 dias) e
    de garantia legal (90 dias) vencidos, então o cliente é encaminhado à garantia do fabricante."""
    transcript = run_conversation(
        scenario.name,
        [
            "Meu violão do pedido 1 apresentou defeito. Meu e-mail é pedro.oliveira@jmail.com. "
            "Consigo trocar?"
        ],
        STORE_OPEN_WEDNESDAY,
    )
    reply = transcript.replies[0]

    scenario.expect_tool(transcript, ("consultar_pedido",), _order(1), "numero_pedido=1 e sem erro")
    scenario.expect_tool(
        transcript,
        ("consultar_politica",),
        lambda call: call.arguments.get("topico") in GARANTIA_TOPICS,
        "topico=garantia ou trocas_e_devolucoes",
    )
    scenario.expect_mentions("encaminha à garantia do fabricante", reply, ["fabricante"])
    scenario.expect_mentions("diz que os prazos da loja venceram", reply, PRAZO_VENCIDO)
    scenario.expect_absent("não promete troca dentro do prazo", reply, TROCA_PROMETIDA)
    scenario.assert_all_checks_passed()


def test_rastreio_de_pedido_enviado(scenario: Scenario, run_conversation: RunConversation) -> None:
    """Pedido enviado verificado por telefone em formato livre; a resposta traz o código de
    rastreio."""
    transcript = run_conversation(
        scenario.name, ["Cadê meu pedido 8? Meu telefone é 67 99654-7821"], STORE_OPEN_WEDNESDAY
    )
    reply = transcript.replies[0]

    scenario.expect_tool(transcript, ("consultar_pedido",), _order(8), "numero_pedido=8 e sem erro")
    scenario.expect_mentions("informa o código de rastreio", reply, ["BRJL5544332BR"])
    scenario.expect_mentions("diz que o pedido foi enviado", reply, EM_TRANSITO)
    scenario.assert_all_checks_passed()


def test_pedido_cancelado_com_motivo(scenario: Scenario, run_conversation: RunConversation) -> None:
    """Pedido cancelado é informado como cancelado, com o motivo registrado (falta de estoque)."""
    transcript = run_conversation(
        scenario.name,
        ["Qual a situação do pedido 18? E-mail gustavo.nunes@inlook.com"],
        STORE_OPEN_WEDNESDAY,
    )
    reply = transcript.replies[0]

    scenario.expect_tool(
        transcript, ("consultar_pedido",), _order(18), "numero_pedido=18 e sem erro"
    )
    scenario.expect_mentions("informa que foi cancelado", reply, ["cancelad"])
    scenario.expect_mentions("informa o motivo (estoque)", reply, ["estoque"])
    scenario.assert_all_checks_passed()
