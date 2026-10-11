from __future__ import annotations

import argparse
import math
import os
import sys
import time
from pathlib import Path

from ._version import __version__
from .chat import Chat, StreamError
from .config import load_config, load_env_file
from .providers import DEFAULT_ORDER, PRESETS, setup_help
from .router import TRANSPORT_ERRORS, Attempt, ExhaustedError, Router
from .server import create_server

COMMANDS = {
    "serve": "start the local OpenAI-compatible proxy (default)",
    "chat": "talk to the free models in this terminal",
    "init": "create a .env file to put your API keys in",
    "check": "test each API key with one small request",
    "models": "list the free models found for your API keys",
}


def log_attempt(attempt: Attempt) -> None:
    now = time.strftime("%H:%M:%S")
    if attempt.ok:
        print(f"{now}  ok    {attempt.target}  {attempt.seconds * 1000:.0f}ms", flush=True)
        return
    bench = f", benched {attempt.cooldown:.0f}s" if attempt.cooldown else ""
    print(f"{now}  skip  {attempt.target}  {attempt.kind}{bench}: {attempt.error}", flush=True)


def note_switch(attempt: Attempt) -> None:
    if not attempt.ok:
        print(f"     ({attempt.target}: {attempt.kind}, switching)", flush=True)


def run_init(path: Path = Path(".env")) -> int:
    """Writes a .env template, or adds the variables an existing .env does not mention."""
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    missing = [PRESETS[name] for name in DEFAULT_ORDER if PRESETS[name].api_key_env not in existing]
    if not missing:
        print(f"{path} already lists every provider key. Fill in at least one.")
        return 0
    header = "# Free API keys for tierhop. Fill in at least one; leave the rest empty."
    lines = [] if existing else [header]
    for preset in missing:
        lines += ["", f"# {preset.keys_url}", *(f"{name}=" for name in preset.env_vars)]
    separator = "" if not existing or existing.endswith("\n") else "\n"
    path.write_text(existing + separator + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"{'Updated' if existing else 'Created'} {path}. Paste at least one key into it:\n")
    print(setup_help())
    print("\nThen run: tierhop check\nKeep this file out of git; it holds secrets.")
    return 0


def run_check(router: Router) -> int:
    """Sends one small request per provider and reports which keys work."""
    active = dict.fromkeys(t.provider.name for t in router.targets)
    working = 0
    for name in active:
        request = {"model": name, "messages": [{"role": "user", "content": "Reply with: ok"}]}
        try:
            result = router.chat(request)
        except ExhaustedError as err:
            reason = err.attempts[-1].error if err.attempts else str(err)
            print(f"  failed  {name:<12}{reason}")
            continue
        result.response.close()
        working += 1
        models = sum(1 for t in router.targets if t.provider.name == name)
        print(f"  ok      {name:<12}{models} models, answered with {result.target.model}")
    for name in DEFAULT_ORDER:
        if name not in active and not os.environ.get(PRESETS[name].api_key_env):
            print(f"  no key  {name:<12}{PRESETS[name].keys_url}")
    print(f"\n{working} of {len(active)} configured providers are working.")
    return 0 if working else 1


def run_chat(router: Router, system: str | None, model: str) -> int:
    chat = Chat(system, model=model, router=router)
    print(f"tierhop chat: {len(router.targets)} free models ready.")
    print("/reset clears the conversation, /exit quits.\n", flush=True)
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text:
            continue
        if text in ("/exit", "/quit"):
            return 0
        if text == "/reset":
            chat.reset()
            print("(conversation cleared)\n")
            continue
        try:
            started = False
            for piece in chat.stream(text):
                if not started:
                    print("bot> ", end="")
                    started = True
                print(piece, end="", flush=True)
            print(f"\n     [{chat.last_target}]\n" if started else "bot> (empty reply)\n")
        except ExhaustedError as err:
            if err.rejection:
                print(f"{err}\n{err.rejection.body[:300]}\n")
            else:
                print(f"{err} Try again in {math.ceil(err.retry_after)}s.\n")
        except (StreamError, *TRANSPORT_ERRORS) as err:
            print(f"\n(reply cut off: {err})\n")
        except KeyboardInterrupt:
            print("\n(stopped)\n")


def run_server(router: Router, host: str, port: int, api_key: str | None) -> int:
    providers = dict.fromkeys(t.provider.name for t in router.targets)
    try:
        server = create_server(router, host, port, api_key)
    except OSError as err:
        print(
            f"error: cannot listen on {host}:{port} ({err.strerror or err}).\n"
            "Is tierhop already running? Stop it, or choose another port with --port.",
            file=sys.stderr,
        )
        return 1
    print(f"tierhop: {len(router.targets)} free models across {', '.join(providers)}")
    print(f'listening on http://{host}:{port}/v1  (use model "auto")')
    if api_key:
        print("clients must send the proxy API key")
    elif host not in ("127.0.0.1", "localhost", "::1"):
        print("warning: reachable from other machines without a key; set --api-key")
    print(flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tierhop",
        description="One OpenAI-compatible endpoint over free LLM tiers.\n\n"
        + "\n".join(f"  {name:<8}{text}" for name, text in COMMANDS.items()),
        epilog="API keys are read from the environment or a .env file in the current "
        f"directory. Set any of:\n{setup_help()}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", nargs="?", default="serve", choices=list(COMMANDS))
    parser.add_argument("-V", "--version", action="version", version=f"tierhop {__version__}")
    parser.add_argument("-c", "--config", help="config file (default ./tierhop.config.json)")
    parser.add_argument("-p", "--port", type=int, help="serve: port (default $PORT or 4141)")
    parser.add_argument("--host", help="serve: address to bind (default $HOST or 127.0.0.1)")
    parser.add_argument("--api-key", help="serve: key clients must send (default $TIERHOP_API_KEY)")
    parser.add_argument("-m", "--model", default="auto", help="chat: model, provider or alias")
    parser.add_argument("-s", "--system", help="chat: system prompt")
    args = parser.parse_args(argv)

    # Replies can contain characters the Windows console encoding lacks.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    if args.command == "init":
        return run_init()

    load_env_file()
    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    on_attempt = {"serve": log_attempt, "chat": note_switch}.get(args.command)
    router = Router.create(
        config,
        warn=lambda message: print(f"warning: {message}", file=sys.stderr),
        on_attempt=on_attempt,
    )

    if not router.targets:
        print(
            "No free models available. Run `tierhop init`, or set at least one provider\n"
            f"API key in your environment or in a .env file here:\n\n{setup_help()}",
            file=sys.stderr,
        )
        return 1

    if args.command == "models":
        for target in router.targets:
            print(target.id)
        return 0
    if args.command == "check":
        return run_check(router)
    if args.command == "chat":
        return run_chat(router, args.system, args.model)
    host = args.host or os.environ.get("HOST") or "127.0.0.1"
    port = args.port or int(os.environ.get("PORT") or 4141)
    return run_server(router, host, port, args.api_key or os.environ.get("TIERHOP_API_KEY"))


if __name__ == "__main__":
    sys.exit(main())
