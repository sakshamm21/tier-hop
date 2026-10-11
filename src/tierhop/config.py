"""Loading API keys and settings from the working directory."""

from __future__ import annotations

import json
import os
import threading
import warnings
from pathlib import Path
from typing import Any

from .router import Router

CONFIG_FILE = "tierhop.config.json"


def load_env_file(path: str | Path = ".env") -> None:
    """Reads KEY=VALUE lines into the environment without overriding what is already set."""
    path = Path(path)
    if not path.exists():
        return
    # Notepad and PowerShell start the file with a byte-order mark; utf-8-sig drops it.
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip().removeprefix("export ")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Reads the given config file, or ./tierhop.config.json if there is one."""
    file = Path(path or CONFIG_FILE)
    if not file.exists():
        if path:
            raise FileNotFoundError(f"Config file not found: {file}")
        return {}
    config: dict[str, Any] = json.loads(file.read_text(encoding="utf-8"))
    return config


_default: Router | None = None
_default_lock = threading.Lock()


def default_router() -> Router:
    """The router that Chat and ask() share when none is passed in.

    Built on first use from ./.env and ./tierhop.config.json, the same way the
    command line does it.
    """
    global _default
    with _default_lock:
        if _default is None:
            load_env_file()
            _default = Router.create(load_config(), warn=lambda m: warnings.warn(m, stacklevel=2))
        return _default
