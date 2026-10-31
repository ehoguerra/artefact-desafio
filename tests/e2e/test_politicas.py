"""Cenários de políticas da loja ponta a ponta: frete, horário e privacidade.

Os nomes dos testes correspondem à coluna "Verificação" de docs/FAILURE_MODES.md (E2, E3, E11).
"""

import re

import pytest

from .support.runner import RunConversation, ToolCall
from .support.scenario import Scenario
from .support.text import mentioned, normalize, sentences_mentioning

pytestmark = pytest.mark.e2e

STORE_OPEN_WEDNESDAY = "2026-03-25T10:00:00-04:00"
SUNDAY_AFTERNOON = "2026-03-22T15:00:00-04:00"

TRANSPORTADORAS = ["PAC", "SEDEX", "Jadlog"]
# Uma frase sobre frete grátis só é aceitável se o restringir à região de Campo Grande ou negar
# o benefício ("não"). "Frete grátis para Dourados" sem nenhuma dessas ressalvas é promessa falsa.
RESSALVAS_FRETE_GRATIS = ["campo grande", "metropolitana", "nao "]
CANAIS_DE_SOLICITACAO = ["whatsapp", "contato@emporiodamusica.com.br", "e-mail", "email"]
BASE_LGPD = ["lgpd", "a qualquer momento", "lei geral de protecao", "seus direitos", "direito"]


def _topic(name: str):
    def matches(call: ToolCall) -> bool:
        return call.arguments.get("topico") == name

    return matches


def test_frete_para_outra_cidade(scenario: Scenario, run_conversation: RunConversation) -> None:
    """Frete para fora da região metropolitana de Campo Grande: informa as modalidades de envio
    sem prometer frete grátis para Dourados."""
    transcript = run_conversation(
        scenario.name,
        ["Moro em Dourados. Vocês entregam aqui? O frete é grátis?"],
        STORE_OPEN_WEDNESDAY,
    )
    reply = transcript.replies[0]
    about_free_shipping = sentences_mentioning(reply, ["gratis", "gratuito"])
    unqualified = [
        sentence
        for sentence in about_free_shipping
        if not mentioned(sentence, RESSALVAS_FRETE_GRATIS)
    ]

    scenario.expect_tool(
        transcript, ("consultar_politica",), _topic("frete_e_entrega"), "topico=frete_e_entrega"
    )
    scenario.expect_mentions("cita PAC, SEDEX ou Jadlog", reply, TRANSPORTADORAS)
    scenario.check(
        "não promete frete grátis fora de Campo Grande",
        not unqualified,
        f"frases sem ressalva: {unqualified or 'nenhuma'}",
    )
    scenario.assert_all_checks_passed()


def test_loja_fechada_no_domingo(scenario: Scenario, run_conversation: RunConversation) -> None:
    """Relógio congelado num domingo à tarde: a loja está fechada e reabre na segunda às 9h."""
    transcript = run_conversation(scenario.name, ["Vocês estão abertos agora?"], SUNDAY_AFTERNOON)
    reply = transcript.replies[0]

    scenario.expect_tool(transcript, ("status_loja",))
    scenario.expect_mentions("diz que está fechada", reply, ["fechad"])
    scenario.expect_mentions("reabre na segunda", reply, ["segunda"])
    scenario.expect_fact(
        "reabre às 9h",
        reply,
        re.search(r"\b0?9\s?h|\b0?9:00", normalize(reply)) is not None,
    )
    scenario.assert_all_checks_passed()


def test_exclusao_de_dados_lgpd(scenario: Scenario, run_conversation: RunConversation) -> None:
    """Pedido de exclusão de dados pessoais: política de privacidade consultada e canais de
    solicitação informados."""
    transcript = run_conversation(
        scenario.name,
        ["Quero que vocês apaguem todos os meus dados pessoais do cadastro."],
        STORE_OPEN_WEDNESDAY,
    )
    reply = transcript.replies[0]

    scenario.expect_tool(
        transcript, ("consultar_politica",), _topic("privacidade"), "topico=privacidade"
    )
    scenario.expect_mentions("informa o canal (WhatsApp ou e-mail)", reply, CANAIS_DE_SOLICITACAO)
    scenario.expect_mentions("cita a LGPD ou o direito do cliente", reply, BASE_LGPD)
    scenario.assert_all_checks_passed()
