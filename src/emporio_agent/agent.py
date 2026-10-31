import logging
from collections.abc import Sequence
from dataclasses import dataclass

import anthropic
from anthropic.types.beta import BetaContentBlock, BetaMessage

from emporio_agent.config import Settings
from emporio_agent.prompts import SYSTEM_PROMPT
from emporio_agent.tools import TOOL_DEFINITIONS, ToolExecutor, ToolOutcome

logger = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"

NO_ANSWER_REPLY = (
    "Poxa, não consegui te ajudar com isso por aqui. Posso ajudar com algo sobre nossos "
    "instrumentos? Se preferir, fale com a equipe pelo (67) 3341-4444."
)
TOO_MANY_ROUNDS_REPLY = (
    "Desculpa, me enrolei para encontrar essa informação. Pode reformular a pergunta "
    "de um jeito mais direto?"
)
RATE_LIMIT_REPLY = (
    "Estou com muitos atendimentos agora. Pode mandar sua mensagem de novo daqui a pouquinho?"
)
CONNECTION_REPLY = (
    "Estou com problema de conexão no momento. Tenta de novo em instantes, por favor? "
    "Se for urgente, fale com a gente pelo (67) 3341-4444."
)
SERVICE_ERROR_REPLY = (
    "Tive um problema técnico aqui do meu lado. Tenta de novo em instantes, por favor? "
    "Se for urgente, fale com a gente pelo (67) 3341-4444."
)


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: dict
    outcome: ToolOutcome


@dataclass(frozen=True, slots=True)
class AgentReply:
    text: str
    tool_calls: tuple[ToolCall, ...]


class Agent:
    def __init__(
        self, client: anthropic.Anthropic, settings: Settings, executor: ToolExecutor
    ) -> None:
        self._client = client
        self._settings = settings
        self._executor = executor

    def respond(self, messages: list[dict], user_text: str) -> AgentReply:
        """Run one customer turn, appending every message it produces to `messages`.

        On failure the turn's messages are removed, so the history stays valid for the next request.
        `AuthenticationError` is re-raised: it is a configuration problem, not a conversational one.
        """
        checkpoint = len(messages)
        messages.append({"role": "user", "content": user_text})
        calls: list[ToolCall] = []
        try:
            text = self._run_turn(messages, calls)
        except anthropic.AuthenticationError:
            del messages[checkpoint:]
            raise
        except anthropic.RateLimitError as error:
            text = _log_api_error(error, RATE_LIMIT_REPLY)
        except anthropic.APIStatusError as error:
            text = _log_api_error(error, SERVICE_ERROR_REPLY)
        except anthropic.APIConnectionError as error:
            text = _log_api_error(error, CONNECTION_REPLY)
        else:
            if text:
                return AgentReply(text=text, tool_calls=tuple(calls))
            text = NO_ANSWER_REPLY
        del messages[checkpoint:]
        return AgentReply(text=text, tool_calls=tuple(calls))

    def _run_turn(self, messages: list[dict], calls: list[ToolCall]) -> str:
        """Return the visible answer, or "" when the model refused or produced no text."""
        for _ in range(self._settings.max_tool_rounds + 1):
            response = self._create(messages)
            if response.stop_reason == "refusal":
                logger.warning("O modelo recusou a resposta (stop_reason=refusal)")
                return ""
            messages.append({"role": "assistant", "content": _serialize(response.content)})
            if response.stop_reason != "tool_use":
                return _visible_text(response.content)
            messages.append({"role": "user", "content": self._run_tools(response.content, calls)})
        messages.append(
            {"role": "assistant", "content": [{"type": "text", "text": TOO_MANY_ROUNDS_REPLY}]}
        )
        return TOO_MANY_ROUNDS_REPLY

    def _create(self, messages: list[dict]) -> BetaMessage:
        return self._client.beta.messages.create(
            model=self._settings.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
            output_config={"effort": self._settings.effort},
            cache_control={"type": "ephemeral"},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )

    def _run_tools(self, content: Sequence[BetaContentBlock], calls: list[ToolCall]) -> list[dict]:
        results = []
        for block in content:
            if block.type != "tool_use":
                continue
            outcome = self._executor.execute(block.name, block.input)
            calls.append(ToolCall(name=block.name, arguments=block.input, outcome=outcome))
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": outcome.content,
                    "is_error": outcome.is_error,
                }
            )
        return results


def _serialize(content: Sequence[BetaContentBlock]) -> list[dict]:
    return [block.model_dump(exclude_none=True) for block in content]


def _visible_text(content: Sequence[BetaContentBlock]) -> str:
    return "\n\n".join(block.text for block in content if block.type == "text").strip()


def _log_api_error(error: anthropic.APIError, reply: str) -> str:
    logger.error("Falha na API da Anthropic: %s", error)
    return reply
