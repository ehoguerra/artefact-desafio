import argparse
import io
import logging
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import anthropic

from emporio_agent.agent import Agent
from emporio_agent.config import Settings, load_settings
from emporio_agent.history import ConversationStore
from emporio_agent.store.catalog import Catalog
from emporio_agent.store.policies import PolicyBook
from emporio_agent.tools import ToolExecutor
from emporio_agent.tracing import Tracer

EXIT_CONFIG_ERROR = 2
MISSING_KEY_MESSAGE = (
    "ANTHROPIC_API_KEY não definida. Configure-a no ambiente ou no arquivo .env "
    "(veja .env.example)."
)
INVALID_KEY_MESSAGE = "A API da Anthropic recusou a credencial. Confira a ANTHROPIC_API_KEY."


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args(argv)
    try:
        settings = load_settings()
        store = ConversationStore(settings.sessions_dir)
        messages = store.load(args.session) if args.session else []
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return _fail(MISSING_KEY_MESSAGE)
        agent = _build_agent(settings)
    except (ValueError, OSError) as error:
        return _fail(str(error))
    tracer = Tracer.open(args.trace) if args.trace else Tracer.null()
    with tracer:
        try:
            _chat(agent, messages, store, args.session, tracer)
        except anthropic.AuthenticationError:
            return _fail(INVALID_KEY_MESSAGE)
        except KeyboardInterrupt:
            print()
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="emporio-agent", description="Atendimento da Empório da Música por mensagens."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    chat = commands.add_parser("chat", help="conversa com a Lia pelo terminal")
    chat.add_argument("--session", help="ID da sessão a carregar e salvar (sem ele, não persiste)")
    chat.add_argument("--trace", type=Path, help="arquivo JSONL para registrar os eventos")
    return parser.parse_args(argv)


def _build_agent(settings: Settings) -> Agent:
    catalog = Catalog.load(settings.data_dir)
    policies = PolicyBook.load(settings.knowledge_path)
    executor = ToolExecutor(catalog, policies, settings.clock)
    return Agent(anthropic.Anthropic(), settings, executor)


def _chat(
    agent: Agent,
    messages: list[dict],
    store: ConversationStore,
    session_id: str | None,
    tracer: Tracer,
) -> None:
    for text in _read_inputs(interactive=sys.stdin.isatty()):
        if text == "/sair":
            return
        if text == "/nova":
            messages.clear()
            _say("(conversa reiniciada)")
        else:
            _answer(agent, messages, text, tracer)
        if session_id:
            store.save(session_id, messages)


def _answer(agent: Agent, messages: list[dict], text: str, tracer: Tracer) -> None:
    tracer.user(text)
    reply = agent.respond(messages, text)
    for call in reply.tool_calls:
        tracer.tool_call(call.name, call.arguments, call.outcome.is_error, call.outcome.content)
    tracer.assistant(reply.text)
    _say(f"Lia: {reply.text}")


def _read_inputs(interactive: bool) -> Iterator[str]:
    while True:
        if interactive:
            print("Você: ", end="", flush=True)
        line = sys.stdin.readline()
        if not line:
            return
        if text := line.strip():
            yield text


def _say(text: str) -> None:
    print(text, end="\n\n", flush=True)


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return EXIT_CONFIG_ERROR


def _force_utf8() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
