# Arquitetura — contratos entre módulos

Este documento é o contrato que cada módulo implementa. Alterações de interface devem ser feitas aqui primeiro.

```
            stdin/stdout                        Anthropic Messages API
  cliente ───────────────► cli.py ──► agent.py ◄──────────────────────► Claude
                              │          │  (loop manual de tool use)
                              │          ▼
                      history.py    tools.py ──► store/catalog.py   (CSVs tratados)
                      tracing.py        │   ──► store/pricing.py   (preço, promo, PIX, parcelas)
                                        │   ──► store/policies.py  (knowledge/politicas_da_loja.md)
                                        │   ──► store/hours.py     (aberto/fechado, fuso de Campo Grande)
```

Pacote: `src/emporio_agent/`. Python ≥ 3.11, apenas stdlib + `anthropic`, `python-dotenv`, `tzdata`.
Estilo: dataclasses `frozen=True, slots=True`, type hints completos, funções curtas, sem comentários óbvios,
nomes de domínio em português quando são termos da loja (tópicos, nomes de tools) e código em inglês.

## config.py
```python
@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path            # default: <repo>/data
    knowledge_path: Path      # default: <repo>/knowledge/politicas_da_loja.md
    sessions_dir: Path        # env EMPORIO_SESSIONS_DIR, default <repo>/.sessions
    model: str                # env EMPORIO_MODEL, default "claude-opus-5-5"
    effort: str               # env EMPORIO_EFFORT, default "low"
    max_tool_rounds: int      # default 6
    frozen_now: datetime | None  # env EMPORIO_NOW (ISO 8601 com offset); None = relógio real

def load_settings() -> Settings  # carrega .env (python-dotenv) e valida
```

## store/catalog.py
Carrega os 6 CSVs (`data/desafio_tecnico_ai_eng - <tabela>.csv`, UTF-8) em dataclasses imutáveis.
```python
Category(id, name, description)
Product(id, name, category_id, price, description, stock, status: ProductStatus, specs: dict[str,str], created_at: date)
ProductStatus = StrEnum: ACTIVE="active", DISCONTINUED="discontinued", COMING_SOON="coming_soon"
Promotion(id, product_id, discount_percent: int, description, is_active: bool)
Customer(id, name, phone, email, city)
OrderItem(product_id, quantity)
Order(id, customer_id, order_date, status: OrderStatus, total, payment_method, tracking_code | None,
      estimated_delivery | None, notes | None, items: tuple[OrderItem, ...])
OrderStatus = StrEnum: PENDING, CONFIRMED, SHIPPED, DELIVERED, CANCELLED

class Catalog:
    @classmethod load(data_dir: Path) -> Catalog
    categories: tuple[Category, ...]
    def product(product_id: int) -> Product | None
    def find_products(name: str) -> list[Product]      # busca tolerante (acentos/caixa/tokens)
    def search(term, category, min_price, max_price, only_available) -> list[Product]
    def category(category_id) -> Category | None
    def category_by_name(name) -> Category | None     # tolerante: "violao", "Violões", "ukulele"
    def active_promotion(product_id) -> Promotion | None   # maior desconto entre is_active=1
    def order(order_id) -> Order | None
    def customer(customer_id) -> Customer | None
```
"Disponível" = `status == ACTIVE and stock > 0`.

## store/pricing.py
```python
@dataclass(frozen=True, slots=True)
class PriceQuote:
    list_price: Decimal
    promotion: Promotion | None
    final_price: Decimal          # list_price com desconto da promoção ativa (se houver)
    pix_price: Decimal | None     # 5% sobre final_price SOMENTE se não houver promoção (não cumulativo)
    max_installments: int         # maior n ≤ 12 sem juros respeitando parcela mínima
    installment_value: Decimal    # final_price / max_installments
def quote(product: Product, promotion: Promotion | None) -> PriceQuote
```
Regras de parcelamento (seção 3.1 do manual, mais específica que a tabela da seção 3):
1–3x sem mínimo (compras < R$ 50,00 não parcelam); 4–6x parcela ≥ R$ 80,00; 7–12x parcela ≥ R$ 100,00.
Valores monetários em `Decimal`, arredondamento `ROUND_HALF_UP` em 2 casas.

## store/policies.py
`knowledge/politicas_da_loja.md` é a versão curada do PDF (tabelas reconstruídas, contradições resolvidas e
anotadas). Cada seção `## <título>` tem um marcador `<!-- topic: <slug> -->`.
```python
PolicyTopic = StrEnum: SOBRE_A_LOJA="sobre_a_loja", CONTATO_E_ENDERECO="contato_e_endereco",
    HORARIO="horario", PAGAMENTO="pagamento", TROCAS_E_DEVOLUCOES="trocas_e_devolucoes",
    FRETE_E_ENTREGA="frete_e_entrega", RASTREAMENTO="rastreamento", PROMOCOES="promocoes",
    GARANTIA="garantia", PRIVACIDADE="privacidade", ESCOPO_DE_ATENDIMENTO="escopo_de_atendimento"
class PolicyBook:
    @classmethod load(path: Path) -> PolicyBook   # falha se algum tópico do enum faltar no arquivo
    def section(topic: PolicyTopic) -> str
```

## store/hours.py
Fuso `America/Campo_Grande`. Seg–Sex 09:00–18:00, Sáb 09:00–13:00, Dom fechado. Feriados não modelados.
```python
@dataclass(frozen=True, slots=True)
class StoreStatus: now: datetime; is_open: bool; closes_at: datetime | None; next_opening: datetime | None
def store_status(now: datetime) -> StoreStatus
```

## tools.py
`TOOL_DEFINITIONS: list[dict]` — schemas JSON com `strict: True`, `additionalProperties: False`, todas as
propriedades em `required` (opcionais usam `["string","null"]`). Descrições dizem QUANDO usar a tool.

| tool | entrada | saída (JSON) |
|---|---|---|
| `buscar_produtos` | `termo`, `categoria`, `preco_min`, `preco_max` (nullable), `apenas_disponiveis: bool` | lista (≤ 15) de resumos: id, nome, categoria, preço (PriceQuote), disponibilidade |
| `detalhar_produto` | `produto: str` (id ou nome) | produto completo + specs + PriceQuote + disponibilidade; se indisponível/descontinuado, `alternativas` disponíveis da mesma categoria e faixa de preço; se ambíguo, lista de candidatos |
| `consultar_pedido` | `numero_pedido: int`, `email_ou_telefone: str` | status, datas, itens, rastreio, pagamento — **somente** se o contato confere com o cliente DAQUELE pedido; caso contrário erro genérico sem vazar dados |
| `consultar_politica` | `topico: enum PolicyTopic` | texto da seção |
| `status_loja` | — | data/hora atual em Campo Grande, aberto agora, horários, próxima abertura |

```python
@dataclass(frozen=True, slots=True)
class ToolOutcome: content: str; is_error: bool
class ToolExecutor:
    def __init__(catalog: Catalog, policies: PolicyBook, clock: Callable[[], datetime])
    def execute(name: str, arguments: dict) -> ToolOutcome   # nunca lança; erros viram is_error=True
```
Preços na saída como string pt-BR (`"R$ 2.199,00"`) **e** número, para o modelo não reformatar errado.
Disponibilidade como rótulo: `disponivel`, `esgotado`, `descontinuado`, `em_breve`.

## prompts.py
`SYSTEM_PROMPT: str` estático (cacheável): persona **Lia**, assistente virtual da Empório da Música; tom
informal mas profissional (manual §7.1); nunca informar preço/estoque/prazo/status sem tool; quando consultar
dados vs políticas; escopo (só instrumentos; acessórios → redirecionar com educação; fora do tema → recusar
com gentileza e voltar ao tema); pedir nº do pedido + e-mail/telefone antes de `consultar_pedido`;
promoções sempre com preço original + %; não inventar; respostas curtas estilo WhatsApp, pt-BR.

## agent.py
```python
@dataclass(frozen=True, slots=True)
class ToolCall: name: str; arguments: dict; outcome: ToolOutcome
@dataclass(frozen=True, slots=True)
class AgentReply: text: str; tool_calls: tuple[ToolCall, ...]
class Agent:
    def __init__(client: anthropic.Anthropic, settings: Settings, executor: ToolExecutor)
    def respond(messages: list[dict], user_text: str) -> AgentReply
        # anexa a mensagem do usuário e todos os turnos (assistant/tool_result) em `messages` (append-only)
```
Loop manual: `client.beta.messages.create(model, max_tokens=16000, system=SYSTEM_PROMPT, tools=TOOL_DEFINITIONS,
output_config={"effort": settings.effort}, cache_control={"type":"ephemeral"}, messages=...,
betas=["server-side-fallback-2026-07-01"], fallbacks="default")` (endpoint beta pelo fallback de recusa no servidor).
Ferramentas são executadas sempre que a resposta contém blocos `tool_use`, qualquer que seja o `stop_reason`.
Todos os `tool_result` de um turno vão numa única mensagem `user`. Conteúdo do assistant é anexado como
`response.content` serializado (`block.model_dump(exclude_none=True)`), preservando blocos de thinking.
Limite `max_tool_rounds`; `stop_reason == "refusal"` e erros da API viram resposta amigável (sem stacktrace).

## history.py
```python
class ConversationStore:
    def __init__(directory: Path)
    def load(session_id: str) -> list[dict]     # [] se não existe
    def save(session_id: str, messages: list[dict]) -> None   # escrita atômica (tmp + replace), JSON UTF-8
```
`session_id` validado (`^[A-Za-z0-9_-]{1,64}$`).

## tracing.py
JSONL, uma linha por evento: `{"event": "user"|"tool_call"|"assistant", "ts": iso, ...}`.
`tool_call` traz `name`, `arguments`, `is_error`, `content`. `Tracer.null()` não escreve nada.

## cli.py  (`emporio-agent` / `python -m emporio_agent`)
```
emporio-agent chat [--session ID] [--trace ARQUIVO.jsonl]
```
- Lê linhas do stdin (funciona com TTY e com pipe). Prompt `Você: `; resposta impressa como `Lia: <texto>`.
- Comandos: `/sair` encerra, `/nova` limpa o histórico da sessão.
- Sem `--session`: sessão efêmera (não persiste). Com `--session`: carrega e salva após cada turno.
- Ao final de cada resposta imprime uma linha separadora vazia; saída UTF-8 (forçar `sys.stdout.reconfigure`).
- Credencial ausente → mensagem clara em stderr e exit code 2.
