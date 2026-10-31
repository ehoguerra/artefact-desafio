"""LLM como juiz (FAILURE_MODES J1–J3): tom, cordialidade, clareza e fidelidade às tools.

O juiz usa um modelo diferente do agente, saída estruturada e justificativa obrigatória antes
de cada nota. A suíte continua caixa-preta: a rubrica abaixo resume a persona sem importar `src/`.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated

import anthropic
from pydantic import BaseModel, Field, ValidationError

from .runner import ToolCall, Transcript, Turn

DEFAULT_JUDGE_MODEL = "claude-sonnet-5-5"
JUDGE_MAX_TOKENS = 16000
JUDGE_EFFORT = "medium"
CHECK_PREFIX = "juiz: "

# Nota mínima (1–5) para cada critério passar. Fidelidade é mais exigente: alucinação é bug.
PASS_THRESHOLDS: dict[str, int] = {
    "tom": 3,
    "cordialidade": 3,
    "clareza": 3,
    "fidelidade": 4,
}

JUDGE_SYSTEM_PROMPT = """\
Você é um avaliador rigoroso de qualidade de atendimento. Vai ler conversas reais entre clientes \
e a Lia, assistente virtual por mensagens de texto da Empório da Música (loja de instrumentos \
musicais em Campo Grande/MS), e dar uma nota de 1 a 5 para cada critério da rubrica.

# Como a Lia deve se comportar (manual da loja, §7.1, e regras da persona)
- Português do Brasil, tom informal mas profissional: acolhedora, como uma amiga que entende de \
música. Nada de linguagem robótica, burocrática ou formal demais.
- Mensagens curtas, estilo WhatsApp; listas só quando ajudam a comparar opções; emoji com \
moderação.
- Cumprimenta pelo nome quando sabe; entende a necessidade, responde com clareza e, ao fechar, \
pergunta se pode ajudar em mais alguma coisa quando isso cabe.
- Preço, estoque, promoção, prazo, status de pedido e regras da loja vêm SEMPRE das ferramentas; \
nunca inventa produto, especificação, política ou condição. Se a ferramenta não trouxe o dado, \
diz que não tem a informação.
- Pedido só é consultado com número + e-mail/telefone; se a verificação falhar, não revela nada.
- A loja vende só instrumentos: acessórios e assuntos alheios são recusados com gentileza, \
voltando aos instrumentos. Na dúvida, oferece atendimento humano.

# Fatos fixos que a Lia conhece sem ferramenta (não contam como invenção)
Nome Lia; Empório da Música, slogan "Sua música começa aqui."; endereço Rua 14 de Maio, 3200 – \
Centro, Campo Grande/MS; telefone/WhatsApp (67) 3341-4444; e-mail contato@emporiodamusica.com.br; \
a loja não vende acessórios (cordas, palhetas, cabos, cases, pedais, amplificadores).

# O que as ferramentas da Lia sabem fazer (descrever isso não é invenção)
buscar_produtos (catálogo por termo, categoria e faixa de preço); detalhar_produto (preço, PIX, \
parcelamento, estoque, ficha técnica, alternativas); consultar_pedido (status, itens, datas, \
rastreio e pagamento, só após verificar número do pedido + e-mail/telefone do titular); \
consultar_politica (manual da loja por tópico); status_loja (data/hora em Campo Grande, aberto ou \
fechado). Dizer o que poderá consultar com essas ferramentas é fiel; afirmar o resultado de uma \
consulta que não aconteceu não é.

# Rubrica
- tom: informal mas profissional, acolhedor, natural; não robótico nem formal demais, e também \
não exageradamente íntimo ou cheio de emojis.
- cordialidade: educada e empática; recusas e notícias ruins dadas com gentileza; fecha \
oferecendo ajuda quando cabe.
- clareza: objetiva, estilo mensagem de WhatsApp, sem enrolação nem repetição; a informação \
pedida é fácil de achar; listas só quando ajudam.
- fidelidade: toda afirmação factual (preços, estoque, datas, prazos, políticas, dados de pedido, \
horários) tem apoio nas saídas de ferramenta mostradas na conversa (em qualquer turno anterior \
ou no mesmo turno), nos fatos fixos acima ou no que o próprio cliente disse. Arredondar ou \
reformular sem mudar o sentido é fiel; recusar, dizer que não tem o dado ou pedir dados é fiel. \
Citar tipos de instrumento como exemplo ao oferecer uma busca (violão, guitarra, baixo, \
teclado...) e conhecimento musical geral (ex.: nylon soa mais suave) não são afirmações sobre a \
loja. Encaminhar o cliente à equipe humana pelos canais fixos (para abrir uma solicitação, \
resolver o que a Lia não resolve) é o procedimento previsto pela persona e é fiel. \
Qualquer número, data, condição, procedimento da loja ou promessa sem apoio derruba a nota.

# Escala (seja exigente)
5 = nada a melhorar; 4 = bom, com um detalhe menor; 3 = aceitável, com problemas perceptíveis; \
2 = fraco, falha clara no critério; 1 = inaceitável. Avalie todas as respostas da Lia na conversa \
e dê a nota pela pior falha relevante, não pela média. Em cada critério escreva primeiro a \
justificativa (curta, em português, citando o trecho que pesou) e só depois a nota.
"""


class CriterionAssessment(BaseModel):
    justificativa: str = Field(description="Por que a nota: 1 a 3 frases citando trechos.")
    nota: Annotated[int, Field(ge=1, le=5, description="Nota de 1 a 5.")]


class Assessment(BaseModel):
    tom: CriterionAssessment
    cordialidade: CriterionAssessment
    clareza: CriterionAssessment
    fidelidade: CriterionAssessment


@dataclass(frozen=True, slots=True)
class CriterionScore:
    criterion: str
    score: int
    justification: str

    @property
    def threshold(self) -> int:
        return PASS_THRESHOLDS[self.criterion]

    @property
    def passed(self) -> bool:
        return self.score >= self.threshold

    @property
    def check_name(self) -> str:
        return f"{CHECK_PREFIX}{self.criterion}"


@dataclass(frozen=True, slots=True)
class Judgement:
    model: str
    scores: tuple[CriterionScore, ...] = ()
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(score.passed for score in self.scores)

    @property
    def average(self) -> float | None:
        if not self.scores:
            return None
        return sum(score.score for score in self.scores) / len(self.scores)


@dataclass(frozen=True, slots=True)
class Judge:
    client: anthropic.Anthropic
    model: str

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "Judge | None":
        """`EMPORIO_JUDGE=off` desliga o juiz; `EMPORIO_JUDGE_MODEL` troca o modelo."""
        if environment.get("EMPORIO_JUDGE", "").strip().lower() == "off":
            return None
        client = anthropic.Anthropic(api_key=environment.get("ANTHROPIC_API_KEY"))
        return cls(client, environment.get("EMPORIO_JUDGE_MODEL") or DEFAULT_JUDGE_MODEL)

    def evaluate(self, description: str, transcripts: list[Transcript]) -> Judgement:
        try:
            response = self.client.messages.parse(
                model=self.model,
                max_tokens=JUDGE_MAX_TOKENS,
                system=JUDGE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": judge_input(description, transcripts)}],
                output_format=Assessment,
                output_config={"effort": JUDGE_EFFORT},
            )
        except (anthropic.APIError, ValidationError, ValueError) as error:
            return Judgement(self.model, error=f"falha ao chamar o juiz: {error}")
        if response.stop_reason != "end_turn" or response.parsed_output is None:
            reason = f"juiz sem veredito (stop_reason={response.stop_reason})"
            return Judgement(self.model, error=reason)
        return Judgement(self.model, scores=_scores(response.parsed_output))


def judge_input(description: str, transcripts: list[Transcript]) -> str:
    sections = [f"# Cenário avaliado\n{description}"]
    for index, transcript in enumerate(transcripts, start=1):
        sections.append(_session(index, transcript))
    sections.append("Avalie as respostas da Lia segundo a rubrica.")
    return "\n\n".join(sections)


def _session(index: int, transcript: Transcript) -> str:
    header = (
        f"# Sessão {index} (id `{transcript.session_id}`, data/hora da loja {transcript.now}; "
        "o mesmo id continua o histórico da sessão anterior)"
    )
    turns = [_turn(number, turn) for number, turn in enumerate(transcript.turns, start=1)]
    return "\n\n".join([header, *turns])


def _turn(number: int, turn: Turn) -> str:
    tools = "\n".join(_tool_call(call) for call in turn.tool_calls) or "(nenhuma ferramenta)"
    return (
        f"## Turno {number}\n"
        f"### Cliente\n{turn.user}\n"
        f"### Ferramentas consultadas pela Lia\n{tools}\n"
        f"### Resposta da Lia\n{turn.reply}"
    )


def _tool_call(call: ToolCall) -> str:
    arguments = json.dumps(call.arguments, ensure_ascii=False)
    error = " (retornou erro)" if call.is_error else ""
    return f"- `{call.name}({arguments})`{error} devolveu:\n```\n{call.content}\n```"


def _scores(assessment: Assessment) -> tuple[CriterionScore, ...]:
    items = ((criterion, getattr(assessment, criterion)) for criterion in PASS_THRESHOLDS)
    return tuple(CriterionScore(name, item.nota, item.justificativa) for name, item in items)
