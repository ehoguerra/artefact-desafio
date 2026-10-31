"""Tool schemas exposed to the model and their executor (never raises)."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from emporio_agent.store.catalog import Catalog, Order, OrderStatus, Product
from emporio_agent.store.hours import (
    OPENING_HOURS,
    STORE_TIMEZONE,
    WEEKDAY_NAMES,
    store_status,
)
from emporio_agent.store.policies import PolicyBook, PolicyTopic
from emporio_agent.store.pricing import MIN_TOTAL_FOR_INSTALLMENTS, PriceQuote, quote
from emporio_agent.text import format_brl

MAX_SEARCH_RESULTS = 15
MAX_CANDIDATES = 10
MAX_ALTERNATIVES = 3

ORDER_NOT_FOUND = (
    "Não foi possível localizar um pedido com esse número e esse e-mail/telefone. "
    "Peça ao cliente para conferir os dados informados."
)
_INTERNAL_ERROR = (
    "Erro interno ao executar a ferramenta. Não invente a informação; ofereça ajuda humana."
)

_ORDER_STATUS_LABELS = {
    OrderStatus.PENDING: "pendente",
    OrderStatus.CONFIRMED: "confirmado",
    OrderStatus.SHIPPED: "enviado",
    OrderStatus.DELIVERED: "entregue",
    OrderStatus.CANCELLED: "cancelado",
}
_PAYMENT_LABELS = {"pix": "PIX", "boleto": "Boleto bancário", "debit": "Cartão de débito"}


def _tool(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    _tool(
        "buscar_produtos",
        "Busca instrumentos no catálogo da loja. Use SEMPRE que o cliente perguntar o que "
        "a loja tem, pedir opções/sugestões, filtrar por categoria (violão, guitarra, "
        "ukulele, teclado, bateria...), faixa de preço ou disponibilidade, ou citar um "
        "produto de forma vaga. Retorna até 15 produtos do mais barato ao mais caro, com "
        "preço final já calculado (promoção, PIX, parcelamento), disponibilidade e "
        "`total_encontrado`. Nunca informe preço ou estoque sem esta tool ou "
        "`detalhar_produto`. Não use para acessórios (a loja não vende).",
        {
            "termo": {
                "type": ["string", "null"],
                "description": "Palavras do nome/modelo/marca (ex.: 'yamaha', 'nylon'); "
                "null para não filtrar.",
            },
            "categoria": {
                "type": ["string", "null"],
                "description": "Categoria como o cliente disse (ex.: 'violão', 'ukulele'); "
                "null = todas.",
            },
            "preco_min": {
                "type": ["number", "null"],
                "description": "Preço final mínimo em reais.",
            },
            "preco_max": {
                "type": ["number", "null"],
                "description": "Preço final máximo em reais.",
            },
            "apenas_disponiveis": {
                "type": "boolean",
                "description": "true para listar só o que tem em estoque e pode ser vendido agora.",
            },
        },
    ),
    _tool(
        "detalhar_produto",
        "Detalha UM produto: descrição, especificações, estoque, preço com promoção ativa, "
        "PIX e parcelamento. Use quando o cliente citar um modelo (ex.: 'Takamine GD20') ou "
        "um id vindo de `buscar_produtos`, e antes de afirmar preço, promoção ou "
        "disponibilidade de um item. Se o produto estiver esgotado, descontinuado ou em "
        "breve, devolve `alternativas` disponíveis; se o nome for ambíguo, devolve "
        "`candidatos` para você perguntar qual o cliente quer.",
        {"produto": {"type": "string", "description": "Id numérico ou nome/modelo do produto."}},
    ),
    _tool(
        "consultar_pedido",
        "Consulta status, itens, pagamento, rastreio e previsão de entrega de um pedido. "
        "Use quando o cliente perguntar sobre um pedido dele (onde está, quando chega, "
        "troca/devolução de algo comprado). Exige o número do pedido E o e-mail ou telefone "
        "cadastrado: peça os dois ao cliente antes; nunca invente nem chute. Se os dados não "
        "conferirem, a resposta é um erro genérico: peça para o cliente conferir.",
        {
            "numero_pedido": {"type": "integer", "description": "Número do pedido."},
            "email_ou_telefone": {
                "type": "string",
                "description": "E-mail ou telefone exatamente como o cliente informou.",
            },
        },
    ),
    _tool(
        "consultar_politica",
        "Devolve o texto oficial de uma política da loja. Use para QUALQUER dúvida sobre "
        "regras: endereço e contato, horário, formas de pagamento e parcelamento, "
        "trocas/devoluções/arrependimento, frete e prazos de entrega, rastreamento, regras "
        "de promoção, garantia, privacidade, e o que a loja vende ou não (acessórios, fora "
        "do escopo, reclamações). Não responda políticas de memória.",
        {"topico": {"type": "string", "enum": [topic.value for topic in PolicyTopic]}},
    ),
    _tool(
        "status_loja",
        "Informa data e hora atuais em Campo Grande (MS), se a loja está aberta agora, a que "
        "horas fecha ou quando abre de novo, e a tabela de horários. Use para 'estão "
        "abertos?', 'até que horas?', 'abre domingo?' e sempre que precisar saber a data de "
        "hoje (ex.: calcular prazos de troca ou entrega).",
        {},
    ),
]

_EXPECTED_ARGUMENTS = {
    tool["name"]: frozenset(tool["input_schema"]["properties"]) for tool in TOOL_DEFINITIONS
}


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    content: str
    is_error: bool


class ToolError(Exception):
    """A failure whose message is safe to show the model."""


class ToolExecutor:
    def __init__(
        self, catalog: Catalog, policies: PolicyBook, clock: Callable[[], datetime]
    ) -> None:
        self._catalog = catalog
        self._policies = policies
        self._clock = clock
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "buscar_produtos": self._search_products,
            "detalhar_produto": self._describe_product,
            "consultar_pedido": self._lookup_order,
            "consultar_politica": self._lookup_policy,
            "status_loja": self._store_status,
        }

    def execute(self, name: str, arguments: dict) -> ToolOutcome:
        handler = self._handlers.get(name)
        if handler is None:
            return _error(f"Ferramenta desconhecida: {name}.")
        try:
            _check_argument_names(name, arguments)
            return ToolOutcome(_to_json(handler(arguments)), is_error=False)
        except ToolError as error:
            return _error(str(error))
        except Exception:
            return _error(_INTERNAL_ERROR)

    def _search_products(self, args: dict[str, Any]) -> dict[str, Any]:
        category_name = _optional_str(args, "categoria")
        category = self._catalog.category_by_name(category_name) if category_name else None
        if category_name and category is None:
            names = ", ".join(c.name for c in self._catalog.categories)
            raise ToolError(f"Categoria '{category_name}' não encontrada. Categorias: {names}.")
        found = self._catalog.search(
            term=_optional_str(args, "termo"),
            category=category,
            min_price=_optional_money(args, "preco_min"),
            max_price=_optional_money(args, "preco_max"),
            only_available=_required_bool(args, "apenas_disponiveis"),
        )
        return {
            "total_encontrado": len(found),
            "exibidos": min(len(found), MAX_SEARCH_RESULTS),
            "produtos": [self._summary(p) for p in found[:MAX_SEARCH_RESULTS]],
        }

    def _describe_product(self, args: dict[str, Any]) -> dict[str, Any]:
        query = _required_str(args, "produto")
        matches = self._catalog.find_products(query)
        if not matches:
            return {"encontrado": False, "mensagem": f"Nenhum produto corresponde a '{query}'."}
        if len(matches) > 1:
            return {
                "encontrado": False,
                "ambiguo": True,
                "total_candidatos": len(matches),
                "candidatos": [self._summary(p) for p in matches[:MAX_CANDIDATES]],
            }
        product = matches[0]
        details = self._summary(product) | {
            "descricao": product.description,
            "especificacoes": product.specs,
            "cadastrado_em": product.created_at.isoformat(),
        }
        if not product.is_available:
            details["alternativas"] = [self._summary(p) for p in self._alternatives(product)]
        return {"encontrado": True, "produto": details}

    def _lookup_order(self, args: dict[str, Any]) -> dict[str, Any]:
        order_id = _required_int(args, "numero_pedido")
        contact = _required_str(args, "email_ou_telefone")
        order = self._catalog.order(order_id)
        customer = self._catalog.customer(order.customer_id) if order else None
        if order is None or customer is None or not customer.matches_contact(contact):
            raise ToolError(ORDER_NOT_FOUND)
        return self._order_view(order) | {"cliente_primeiro_nome": customer.first_name}

    def _lookup_policy(self, args: dict[str, Any]) -> dict[str, Any]:
        slug = _required_str(args, "topico")
        try:
            topic = PolicyTopic(slug)
        except ValueError:
            valid = ", ".join(topic.value for topic in PolicyTopic)
            raise ToolError(f"Tópico inválido: '{slug}'. Use um de: {valid}.") from None
        return {"topico": topic.value, "texto": self._policies.section(topic)}

    def _store_status(self, _args: dict[str, Any]) -> dict[str, Any]:
        status = store_status(self._clock())
        return {
            "data_hoje": status.now.date().isoformat(),
            "dia_semana": WEEKDAY_NAMES[status.now.weekday()],
            "hora_atual": status.now.strftime("%H:%M"),
            "fuso": str(STORE_TIMEZONE),
            "aberto_agora": status.is_open,
            "fecha_as": status.closes_at.strftime("%H:%M") if status.closes_at else None,
            "proxima_abertura": _describe_moment(status.next_opening)
            if status.next_opening
            else None,
            "horario": _weekly_schedule(),
            "observacao": "Feriados não são considerados aqui; em feriados a loja fica fechada.",
        }

    def _summary(self, product: Product) -> dict[str, Any]:
        category = self._catalog.category(product.category_id)
        return {
            "id": product.id,
            "nome": product.name,
            "categoria": category.name if category else None,
            "disponibilidade": product.availability.value,
            "estoque": product.stock,
            "preco": _price_view(quote(product, self._catalog.active_promotion(product.id))),
        }

    def _alternatives(self, product: Product) -> list[Product]:
        """Available products of the same category, closest in price first."""
        category = self._catalog.category(product.category_id)
        reference = self._catalog.final_price(product)
        available = self._catalog.search(category=category, only_available=True)
        available.sort(key=lambda p: abs(self._catalog.final_price(p) - reference))
        return available[:MAX_ALTERNATIVES]

    def _order_view(self, order: Order) -> dict[str, Any]:
        today = self._clock().astimezone(STORE_TIMEZONE).date()
        return {
            "numero": order.id,
            "status": _ORDER_STATUS_LABELS[order.status],
            "data_pedido": order.order_date.isoformat(),
            "dias_desde_pedido": (today - order.order_date).days,
            "total": _money(order.total),
            "forma_pagamento": _payment_label(order.payment_method),
            "itens": [self._order_item(item.product_id, item.quantity) for item in order.items],
            "codigo_rastreio": order.tracking_code,
            "previsao_entrega": _iso_or_none(order.estimated_delivery),
            "dias_desde_previsao_entrega": (
                (today - order.estimated_delivery).days if order.estimated_delivery else None
            ),
            "observacoes": order.notes,
        }

    def _order_item(self, product_id: int, quantity: int) -> dict[str, Any]:
        product = self._catalog.product(product_id)
        category = self._catalog.category(product.category_id) if product else None
        return {
            "produto": product.name if product else f"Produto #{product_id}",
            "quantidade": quantity,
            "categoria": category.name if category else None,
        }


def _price_view(price: PriceQuote) -> dict[str, Any]:
    promotion = price.promotion
    return {
        "preco_final": _money(price.final_price),
        "promocao": (
            {
                "descricao": promotion.description,
                "desconto_percentual": promotion.discount_percent,
                "preco_original": _money(price.list_price),
                "preco_promocional": _money(price.final_price),
                "desconto_pix_aplica": False,
            }
            if promotion
            else None
        ),
        "preco_pix": _money(price.pix_price) if price.pix_price is not None else None,
        "parcelamento": _installments_text(price),
    }


def _installments_text(price: PriceQuote) -> str:
    if price.max_installments == 1:
        limit = format_brl(MIN_TOTAL_FOR_INSTALLMENTS)
        return f"somente à vista (compras abaixo de {limit} não são parceladas)"
    return f"{price.max_installments}x de {format_brl(price.installment_value)} sem juros"


def _money(value: Decimal) -> dict[str, Any]:
    return {"valor": float(value), "texto": format_brl(value)}


def _payment_label(method: str) -> str:
    if method.startswith("credit_"):
        installments = method.removeprefix("credit_").removesuffix("x")
        return f"Cartão de crédito em {installments}x"
    return _PAYMENT_LABELS.get(method, method)


def _weekly_schedule() -> dict[str, str]:
    weekday_open, weekday_close = OPENING_HOURS[0]
    saturday_open, saturday_close = OPENING_HOURS[5]
    return {
        "segunda a sexta": f"{weekday_open:%H:%M} às {weekday_close:%H:%M}",
        "sábado": f"{saturday_open:%H:%M} às {saturday_close:%H:%M}",
        "domingo e feriados": "fechado",
    }


def _describe_moment(moment: datetime) -> str:
    return f"{WEEKDAY_NAMES[moment.weekday()]}, {moment.date().isoformat()} às {moment:%H:%M}"


def _iso_or_none(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _error(message: str) -> ToolOutcome:
    return ToolOutcome(_to_json({"erro": message}), is_error=True)


def _check_argument_names(name: str, arguments: object) -> None:
    if not isinstance(arguments, dict):
        raise ToolError("Os argumentos devem ser um objeto JSON.")
    expected = _EXPECTED_ARGUMENTS[name]
    if set(arguments) != expected:
        listed = ", ".join(sorted(expected)) or "nenhum"
        raise ToolError(f"Argumentos inválidos para {name}. Esperados: {listed}.")


def _required_str(args: dict[str, Any], key: str) -> str:
    value = args[key]
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"'{key}' deve ser um texto não vazio.")
    return value.strip()


def _optional_str(args: dict[str, Any], key: str) -> str | None:
    value = args[key]
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _required_str(args, key)


def _required_int(args: dict[str, Any], key: str) -> int:
    value = args[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"'{key}' deve ser um número inteiro.")
    return value


def _required_bool(args: dict[str, Any], key: str) -> bool:
    value = args[key]
    if not isinstance(value, bool):
        raise ToolError(f"'{key}' deve ser true ou false.")
    return value


def _optional_money(args: dict[str, Any], key: str) -> Decimal | None:
    value = args[key]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ToolError(f"'{key}' deve ser um valor em reais não negativo ou null.")
    return Decimal(str(value))
