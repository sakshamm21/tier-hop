import os

import pytest

from tierhop import Provider, Router, Target, UpstreamResponse, __version__, create_server
from tierhop.cli import main, run_check, run_init, run_server
from tierhop.config import load_env_file


def test_init_creates_a_template_that_loads_as_no_keys(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    assert run_init(env) == 0
    text = env.read_text(encoding="utf-8")
    assert "GROQ_API_KEY=\n" in text and "https://openrouter.ai/keys" in text
    assert "Created" in capsys.readouterr().out

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    load_env_file(env)
    assert not os.environ.get("GROQ_API_KEY")


def test_init_keeps_existing_keys_and_adds_only_missing_ones(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=real-key\nOTHER=1", encoding="utf-8")
    run_init(env)
    text = env.read_text(encoding="utf-8")
    assert text.startswith("GROQ_API_KEY=real-key\nOTHER=1\n")
    assert text.count("GROQ_API_KEY") == 1
    assert "GEMINI_API_KEY=\n" in text

    run_init(env)
    assert env.read_text(encoding="utf-8") == text, "a second run changes nothing"
    assert "already lists every provider key" in capsys.readouterr().out


def test_env_file_parsing(tmp_path, monkeypatch):
    for name in ("PLAIN", "QUOTED", "EXPORTED", "ALREADY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ALREADY", "from-shell")
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nPLAIN = one\nQUOTED=\"two words\"\nexport EXPORTED='three'\nALREADY=file\n",
        encoding="utf-8",
    )
    load_env_file(env)
    assert os.environ["PLAIN"] == "one"
    assert os.environ["QUOTED"] == "two words"
    assert os.environ["EXPORTED"] == "three"
    assert os.environ["ALREADY"] == "from-shell", "the real environment wins"


def test_env_file_saved_with_a_byte_order_mark_keeps_its_first_key(tmp_path, monkeypatch):
    monkeypatch.delenv("FIRST", raising=False)
    env = tmp_path / ".env"
    env.write_text("FIRST=one\n", encoding="utf-8-sig")
    load_env_file(env)
    assert os.environ["FIRST"] == "one"


def test_version_flag_prints_the_version(capsys):
    with pytest.raises(SystemExit) as stopped:
        main(["--version"])
    assert stopped.value.code == 0
    assert capsys.readouterr().out.strip() == f"tierhop {__version__}"


def test_serve_explains_a_port_that_is_already_in_use(capsys):
    router = Router([Target(Provider("a", "https://a.test/v1"), "m")])
    taken = create_server(router, port=0)
    try:
        port = taken.server_address[1]
        assert run_server(router, "127.0.0.1", port, None) == 1
    finally:
        taken.server_close()
    assert f"cannot listen on 127.0.0.1:{port}" in capsys.readouterr().err


def test_check_reports_each_provider(capsys, monkeypatch):
    for name in ("GROQ_API_KEY", "CEREBRAS_API_KEY", "GEMINI_API_KEY", "MISTRAL_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "set")

    def transport(method, url, headers, body, timeout):
        if "good.test" in url:
            return UpstreamResponse.of(200, {"choices": [{"message": {"content": "ok"}}]})
        return UpstreamResponse.of(401, {"error": {"message": "invalid api key"}})

    targets = [
        Target(Provider("good", "https://good.test/v1"), "m1"),
        Target(Provider("good", "https://good.test/v1"), "m2"),
        Target(Provider("bad", "https://bad.test/v1"), "m3"),
    ]
    assert run_check(Router(targets, transport=transport)) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["ok", "good", "2", "models,", "answered", "with", "m1"]
    assert lines[1].split()[:2] == ["failed", "bad"] and "invalid api key" in lines[1]
    assert any(line.split()[:3] == ["no", "key", "groq"] for line in lines)
    assert not any("openrouter" in line for line in lines), "a set key is not reported missing"
    assert lines[-1] == "1 of 2 configured providers are working."


def test_check_fails_when_nothing_works(capsys):
    transport = lambda *args: UpstreamResponse.of(500, {})
    target = Target(Provider("bad", "https://bad.test/v1"), "m")
    assert run_check(Router([target], transport=transport)) == 1
