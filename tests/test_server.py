import json
import threading
import urllib.error
import urllib.request

import pytest

from tierhop import Provider, Router, Target, UpstreamResponse, create_server

REQUEST = {"model": "auto", "messages": [{"role": "user", "content": "hello"}]}


@pytest.fixture
def serve():
    servers = []

    def start(transport, names=("a", "b")):
        targets = [Target(Provider(name, f"https://{name}.test/v1"), "model") for name in names]
        server = create_server(Router(targets, transport=transport), port=0)
        servers.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def call(url, body=None, method=None):
    """Returns (status, headers, body) for error statuses too."""
    data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method)
    try:
        response = urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as err:
        response = err
    with response:
        return response.status, response.headers, response.read()


def test_proxies_a_completion_and_reports_which_target_served_it(serve):
    def transport(method, url, headers, body, timeout):
        if "a.test" in url:
            return UpstreamResponse.of(429, {}, {"retry-after": "60"})
        return UpstreamResponse.of(200, {"choices": [{"message": {"content": "from b"}}]})

    status, headers, body = call(f"{serve(transport)}/v1/chat/completions", REQUEST)
    assert status == 200
    assert headers["x-tierhop-target"] == "b/model"
    assert headers["x-tierhop-attempts"] == "2"
    assert json.loads(body)["choices"][0]["message"]["content"] == "from b"


def test_passes_a_streamed_response_through(serve):
    events = b'data: {"n":1}\n\ndata: {"n":2}\n\ndata: [DONE]\n\n'
    headers = {"content-type": "text/event-stream"}
    transport = lambda *args: UpstreamResponse.of(200, events, headers)

    url = f"{serve(transport)}/v1/chat/completions"
    status, headers, body = call(url, {**REQUEST, "stream": True})
    assert status == 200
    assert headers["content-type"] == "text/event-stream"
    assert headers["transfer-encoding"] == "chunked"
    assert body == events


def test_answers_429_with_retry_after_when_every_target_is_exhausted(serve):
    transport = lambda *args: UpstreamResponse.of(429, {}, {"retry-after": "90"})
    status, headers, body = call(f"{serve(transport)}/v1/chat/completions", REQUEST)
    assert status == 429
    assert headers["retry-after"] == "90"
    payload = json.loads(body)
    assert payload["error"]["code"] == "all_targets_exhausted"
    assert len(payload["attempts"]) == 2


def test_returns_the_upstream_error_when_the_request_itself_is_invalid(serve):
    transport = lambda *args: UpstreamResponse.of(400, {"error": {"message": "bad tool schema"}})
    status, _, body = call(f"{serve(transport)}/v1/chat/completions", REQUEST)
    assert status == 400
    assert b"bad tool schema" in body


def test_validates_the_request_body_before_calling_upstream(serve):
    called = []
    base = serve(lambda *args: called.append(1) or UpstreamResponse.of(200, {}))
    assert call(f"{base}/v1/chat/completions", b"not json")[0] == 400
    assert call(f"{base}/v1/chat/completions", {"model": "auto"})[0] == 400
    assert not called


def test_lists_model_names_and_target_status(serve):
    base = serve(lambda *args: UpstreamResponse.of(200, {}))
    models = json.loads(call(f"{base}/v1/models")[2])
    assert [m["id"] for m in models["data"]] == ["auto", "a", "b", "a/model", "b/model"]
    status = json.loads(call(f"{base}/status")[2])
    assert [t["id"] for t in status["targets"]] == ["a/model", "b/model"]
    assert status["targets"][0]["available"] is True


def test_unknown_routes_are_404(serve):
    base = serve(lambda *args: UpstreamResponse.of(200, {}))
    assert call(f"{base}/v1/embeddings", {"input": "x"})[0] == 404
    assert call(f"{base}/nope")[0] == 404
    assert call(f"{base}/v1/models", method="OPTIONS")[0] == 204


def test_a_proxy_key_is_required_when_one_is_set():
    target = Target(Provider("a", "https://a.test/v1"), "model")
    router = Router([target], transport=lambda *args: UpstreamResponse.of(200, {"ok": True}))
    server = create_server(router, port=0, api_key="secret")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions"
    try:

        def post(key):
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            request = urllib.request.Request(url, json.dumps(REQUEST).encode(), headers)
            try:
                return urllib.request.urlopen(request, timeout=10).status
            except urllib.error.HTTPError as err:
                return err.code

        assert post(None) == 401
        assert post("wrong") == 401
        assert post("secret") == 200
    finally:
        server.shutdown()
        server.server_close()


def test_start_runs_the_proxy_in_this_process_and_points_the_openai_sdk_at_it(monkeypatch):
    import os

    import tierhop

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://elsewhere.test/v1")
    target = Target(Provider("a", "https://a.test/v1"), "model")
    reply = {"choices": [{"message": {"content": "hi"}}]}
    router = Router([target], transport=lambda *args: UpstreamResponse.of(200, reply))
    try:
        url = tierhop.start(router)
        assert url.startswith("http://127.0.0.1:") and url.endswith("/v1")
        assert os.environ["OPENAI_BASE_URL"] == url
        assert os.environ["OPENAI_API_KEY"]
        assert tierhop.start(router) == url, "a second call reuses the running proxy"
        status, _, body = call(f"{url}/chat/completions", REQUEST)
        assert status == 200 and json.loads(body) == reply
    finally:
        tierhop.stop()
    # monkeypatch restores the environment variables that start() changed.


def test_start_without_any_key_explains_what_to_do():
    import tierhop

    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        tierhop.start(Router([]))
