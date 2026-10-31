"""Cenários de atendimento ponta a ponta: CLI real, LLM real, asserções sobre fatos e tools.

Os nomes dos testes correspondem à coluna "Verificação" de docs/FAILURE_MODES.md.
"""

import re
from pathlib import Path

import pytest

from .support.runner import RunConversation, ToolCall
from .support.scenario import Scenario
from .support.text import has_price, normalize

pytestmark = pytest.mark.e2e

STORE_OPEN_WEDNESDAY = "2026-03-25T10:00:00-04:00"
THREE_DAYS_AFTER_ORDER_7_DELIVERY = "2026-02-20T15:00:00-04:00"

VIOLOES_ATE_1000 = [
    "Yamaha C40",
    "Tagima Memphis",
    "Rozini RC-104",
    "Yamaha F310",
    "Tagima Woodstock",
    "Shelby SGD-195E",
    "Tagima TW-7",
    "Yamaha C70",
]
OUTRAS_MARCAS_DE_VIOLAO = [
    "Yamaha",
    "Tagima",
    "Giannini GF-1R",
    "Shelby",
    "Rozini",
    "Crafter",
    "Takamine",
]
DEVOLUCAO_POSSIVEL = [
    "dentro do prazo",
    "pode devolver",
    "consegue devolver",
    "e possivel",
    "tem direito",
    "pode sim",
    "ainda esta no prazo",
    "voce esta no prazo",
]


def _argument(call: ToolCall, key: str) -> str:
    return normalize(str(call.arguments.get(key) or ""))


@pytest.mark.example(number=1, slug="catalogo-violoes", title="Violões até R$ 1.000")
def test_catalogo_violoes_ate_1000(scenario: Scenario, run_conversation: RunConversation) -> None:
    """Busca no catálogo com filtro de categoria e preço, listando só violões disponíveis
    (esgotados e descontinuados ficam de fora)."""
    transcript = run_conversation(
        scenario.name,
        ["Oi! Quais opções de violões vocês têm disponíveis custando até R$1000?"],
        STORE_OPEN_WEDNESDAY,
    )
    reply = transcript.replies[0]

    def filters_violoes_up_to_1000(call: ToolCall) -> bool:
        max_price = call.arguments.get("preco_max")
        about_violao = "viol" in _argument(call, "categoria") + _argument(call, "termo")
        return max_price is not None and float(max_price) <= 1000 and about_violao

    scenario.expect_tool(
        transcript,
        ("buscar_produtos",),
        filters_violoes_up_to_1000,
        "preco_max ≤ 1000 e categoria/termo de violão",
    )
    scenario.expect_mentions("cita ao menos 3 violões até R$1000", reply, VIOLOES_ATE_1000, 3)
    # Tolerância documentada: esgotado (GF-3D) e descontinuado (SN-7C) nem devem ser citados.
    scenario.expect_absent("não oferece esgotado nem descontinuado", reply, ["GF-3D", "SN-7C"])
    scenario.assert_all_checks_passed()


@pytest.mark.example(
    number=2, slug="endereco-e-horario", title="Endereço e horário de funcionamento"
)
def test_endereco_e_horario(scenario: Scenario, run_conversation: RunConversation) -> None:
    """Política da loja (endereço) combinada com o relógio da loja: está aberta agora?"""
    transcript = run_conversation(
        scenario.name,
        ["Qual o endereço da loja? E vocês estão abertos agora?"],
        STORE_OPEN_WEDNESDAY,
    )
    reply = transcript.replies[0]

    scenario.expect_tool(transcript, ("consultar_politica",))
    scenario.expect_tool(transcript, ("status_loja",))
    scenario.expect_mentions("cita a rua 14 de Maio", reply, ["14 de maio"])
    scenario.expect_fact("cita o número 3200", reply, "3200" in normalize(reply).replace(".", ""))
    scenario.expect_mentions("diz que está aberta", reply, ["abert"])
    scenario.assert_all_checks_passed()


@pytest.mark.example(number=3, slug="preco-takamine-gd20", title="Preço do Takamine GD20")
def test_preco_takamine_gd20(scenario: Scenario, run_conversation: RunConversation) -> None:
    """Preço calculado pelo sistema: ignora a promoção inativa de 12%; informa PIX ou parcelas."""
    transcript = run_conversation(
        scenario.name, ["Quanto custa o Takamine GD20?"], STORE_OPEN_WEDNESDAY
    )
    reply = transcript.replies[0]
    normalized = normalize(reply)

    scenario.expect_tool(transcript, ("detalhar_produto", "buscar_produtos"))
    scenario.expect_fact("informa R$ 2.199,00", reply, has_price(reply, "2199"))
    scenario.expect_fact(
        "não aplica a promoção inativa de 12%", reply, not re.search(r"12\s?%", normalized)
    )
    scenario.expect_fact(
        "informa PIX (2.089,05) ou parcelamento em 12x",
        reply,
        has_price(reply, "2089.05") or re.search(r"12\s?x", normalized) is not None,
    )
    scenario.assert_all_checks_passed()


@pytest.mark.example(number=4, slug="arrependimento-de-compra", title="Direito de arrependimento")
def test_arrependimento_de_compra(scenario: Scenario, run_conversation: RunConversation) -> None:
    """Pedido verificado com e-mail do cliente e política de devolução aplicada às datas reais do
    pedido (entregue há 3 dias, dentro do prazo de 7 dias)."""
    transcript = run_conversation(
        scenario.name,
        [
            "Me arrependi da minha compra, posso devolver meu pedido?",
            "É o pedido 7, meu email é leticia.rocha@jmail.com",
        ],
        THREE_DAYS_AFTER_ORDER_7_DELIVERY,
    )
    reply = transcript.replies[1]

    scenario.expect_tool(
        transcript,
        ("consultar_pedido",),
        lambda call: call.arguments.get("numero_pedido") == 7 and not call.is_error,
        "numero_pedido=7 e sem erro",
    )
    scenario.expect_tool(
        transcript,
        ("consultar_politica",),
        lambda call: call.arguments.get("topico") == "trocas_e_devolucoes",
        "topico=trocas_e_devolucoes",
    )
    scenario.expect_fact(
        "cita o prazo de 7 dias",
        reply,
        # The fact is the 7-day deadline, phrased freely ("7 dias", "3 dias dos 7 permitidos").
        re.search(r"\b(7|sete)\b( \(sete\))? (dias|permitidos)", normalize(reply)) is not None,
    )
    scenario.expect_mentions(
        "confirma que a devolução é possível",
        reply,
        DEVOLUCAO_POSSIVEL,
    )
    scenario.assert_all_checks_passed()


def test_pedido_contato_errado(scenario: Scenario, run_conversation: RunConversation) -> None:
    """Privacidade (LGPD): número de pedido com e-mail que não confere não revela nenhum dado."""
    transcript = run_conversation(
        scenario.name,
        ["Quero saber o status do pedido 1, meu email é fulano@exemplo.com"],
        STORE_OPEN_WEDNESDAY,
    )
    reply = transcript.replies[0]

    scenario.expect_tool(
        transcript, ("consultar_pedido",), lambda call: call.is_error, "retorno is_error=true"
    )
    scenario.expect_absent(
        "não vaza dados do pedido", reply, ["Pedro", "BRAB1234567BR", "Martin D-28", "entregue"]
    )
    scenario.expect_mentions(
        "pede para conferir os dados",
        reply,
        ["confer", "confirm", "nao encontr", "nao consegui", "verific", "localiz"],
    )
    scenario.assert_all_checks_passed()


@pytest.mark.example(number=5, slug="fora-do-escopo", title="Acessórios e assuntos fora do escopo")
def test_fora_do_escopo(scenario: Scenario, run_conversation: RunConversation) -> None:
    """Escopo do atendimento: acessórios são redirecionados com educação e temas alheios à loja
    são recusados com gentileza."""
    transcript = run_conversation(
        scenario.name,
        [
            "Vocês vendem cordas e amplificador?",
            "E você me passa uma receita de bolo de cenoura?",
        ],
        STORE_OPEN_WEDNESDAY,
    )
    accessories_reply, recipe_reply = transcript.replies

    scenario.expect_mentions("diz que não vende acessórios", accessories_reply, ["nao"])
    scenario.expect_mentions("explica que vende instrumentos", accessories_reply, ["instrumento"])
    scenario.expect_absent("não passa a receita", recipe_reply, ["farinha", "forno", "ovos"])
    scenario.expect_absent("não fala de preço na recusa", recipe_reply, ["R$"])
    scenario.assert_all_checks_passed()


def test_produto_esgotado_sugere_alternativas(
    scenario: Scenario, run_conversation: RunConversation
) -> None:
    """Produto ativo com estoque zero é informado como esgotado, com alternativas disponíveis."""
    transcript = run_conversation(
        scenario.name, ["Tem o Giannini GF-3D Dreadnought Sunburst?"], STORE_OPEN_WEDNESDAY
    )
    reply = transcript.replies[0]

    scenario.expect_tool(transcript, ("detalhar_produto",))
    scenario.expect_mentions(
        "informa que está esgotado", reply, ["esgotad", "indisponiv", "sem estoque"]
    )
    scenario.expect_mentions("sugere outro violão", reply, OUTRAS_MARCAS_DE_VIOLAO)
    scenario.assert_all_checks_passed()


def test_promocao_ativa_sem_pix_cumulativo(
    scenario: Scenario, run_conversation: RunConversation
) -> None:
    """Promoção ativa informada com preço original e percentual, sem somar o desconto do PIX."""
    transcript = run_conversation(
        scenario.name, ["Quanto está o ukulele Ohana CK-20?"], STORE_OPEN_WEDNESDAY
    )
    reply = transcript.replies[0]

    scenario.expect_tool(transcript, ("detalhar_produto", "buscar_produtos"))
    scenario.expect_fact("informa o preço promocional 439,20", reply, has_price(reply, "439.20"))
    scenario.expect_fact(
        "informa o desconto de 20%", reply, re.search(r"20\s?%", reply) is not None
    )
    scenario.expect_fact("informa o preço original 549", reply, has_price(reply, "549"))
    scenario.expect_fact("não soma PIX à promoção (417,24)", reply, not has_price(reply, "417"))
    scenario.assert_all_checks_passed()


def test_memoria_entre_sessoes(
    scenario: Scenario, run_conversation: RunConversation, sessions_dir: Path
) -> None:
    """Histórico persistido em disco: um novo processo da CLI na mesma sessão lembra do cliente."""
    session_id = "persist-1"
    run_conversation(session_id, ["Oi, meu nome é Carla e eu toco violão."], STORE_OPEN_WEDNESDAY)
    session_files = [path.name for path in sessions_dir.iterdir() if session_id in path.name]
    second = run_conversation(session_id, ["Você lembra o meu nome?"], STORE_OPEN_WEDNESDAY)

    scenario.check(
        "arquivo da sessão gravado em EMPORIO_SESSIONS_DIR",
        bool(session_files),
        f"arquivos: {session_files or 'nenhum'}",
    )
    scenario.expect_mentions("lembra o nome Carla", second.replies[0], ["Carla"])
    scenario.assert_all_checks_passed()
