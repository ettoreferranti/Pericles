import json
import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from pericles.llm.backend import Backend, BackendError, LLMSetupError
from pericles.llm.ollama import OllamaBackend, http_json, tagged
from pericles.llm.types import BackendCall, Message, Sampling

CALL = BackendCall(
    "qwen3",
    (Message("system", "be brief"), Message("user", "plan")),
    Sampling(0.7, 0.9, 128),
    42,
    {"type": "object"},
    "plan",
    "ada",
)


class Stub:
    """A local HTTP server answering canned (status, body) per path."""

    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, bytes]] = {}
        self.seen: list[tuple[str, str, Any]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                stub.seen.append((self.command, self.path, body))
                status, payload = stub.routes.get(self.path, (404, b'{"error": "no route"}'))
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = _answer

            def log_message(self, *args: Any) -> None:
                return None

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stub() -> Iterator[Stub]:
    server = Stub()
    yield server
    server.close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.mark.req("REQ-LLM-002")
def test_http_json_posts_json_and_reads_json(stub: Stub) -> None:
    """AC2: the transport speaks JSON both ways."""
    stub.routes["/api/chat"] = (200, b'{"ok": true}')
    assert http_json("POST", stub.url + "/api/chat", {"a": 1}, 5.0) == {"ok": True}
    assert stub.seen == [("POST", "/api/chat", {"a": 1})]


@pytest.mark.req("REQ-LLM-009")
@pytest.mark.parametrize(
    ("route", "message"),
    [
        ((500, b"model crashed"), "HTTP 500: model crashed"),
        ((200, b"not json"), "not JSON"),
        ((200, b"[1, 2]"), "not a JSON object"),
        ((200, b"\xff\xfe"), "not valid UTF-8"),
    ],
)
def test_http_failures_are_backend_errors(
    stub: Stub, route: tuple[int, bytes], message: str
) -> None:
    """AC1: server errors and garbage are BackendErrors, so the gateway backs off."""
    stub.routes["/x"] = route
    with pytest.raises(BackendError, match=message):
        http_json("GET", stub.url + "/x", None, 5.0)


@pytest.mark.req("REQ-LLM-009")
def test_a_refused_connection_is_a_backend_error() -> None:
    """AC1: an Ollama that is not running is a BackendError naming the URL."""
    url = f"http://127.0.0.1:{free_port()}/api/tags"
    with pytest.raises(BackendError, match=url):
        http_json("GET", url, None, 2.0)


@pytest.mark.req("REQ-LLM-001")
def test_ollama_implements_the_interface() -> None:
    """AC2: OllamaBackend satisfies the Backend protocol."""
    backend: Backend = OllamaBackend("http://localhost:11434/", 30.0, 2)
    assert (backend.kind, backend.concurrency) == ("ollama", 2)
    assert backend.describe() == "ollama at http://localhost:11434"


@pytest.mark.req("REQ-LLM-002")
def test_complete_sends_schema_sampling_and_seed(stub: Stub) -> None:
    """AC2: schema-constrained output via `format`; sampling and seed as options."""
    stub.routes["/api/chat"] = (
        200,
        b'{"message": {"role": "assistant", "content": "{}"}, '
        b'"prompt_eval_count": 30, "eval_count": 4}',
    )
    completion = OllamaBackend(stub.url, 5.0, 1).complete(CALL)
    assert (completion.text, completion.tokens_in, completion.tokens_out) == ("{}", 30, 4)
    _, path, body = stub.seen[0]
    assert path == "/api/chat"
    assert body == {
        "model": "qwen3",
        "messages": [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "plan"},
        ],
        "stream": False,
        "format": {"type": "object"},
        "options": {"temperature": 0.7, "top_p": 0.9, "num_predict": 128, "seed": 42},
    }


@pytest.mark.req("REQ-LLM-002")
def test_complete_without_schema_sends_no_format(stub: Stub) -> None:
    """AC2: free-text calls are not constrained."""
    stub.routes["/api/chat"] = (200, b'{"message": {"content": "hi"}}')
    completion = OllamaBackend(stub.url, 5.0, 1).complete(
        BackendCall("m", (Message("user", "x"),), Sampling(0.1, 1.0, 8), 1)
    )
    assert (completion.text, completion.tokens_in, completion.tokens_out) == ("hi", 0, 0)
    assert "format" not in stub.seen[0][2]


@pytest.mark.req("REQ-LLM-009")
def test_an_unexpected_reply_shape_is_a_backend_error(stub: Stub) -> None:
    """AC1: a reply without message.content is a BackendError, not a KeyError."""
    stub.routes["/api/chat"] = (200, b'{"done": true}')
    with pytest.raises(BackendError, match="unexpected reply"):
        OllamaBackend(stub.url, 5.0, 1).complete(CALL)


@pytest.mark.req("REQ-LLM-002")
def test_check_lists_models_and_names_the_missing_ones(stub: Stub) -> None:
    """AC1: lists the models and fails fast with a clear message."""
    stub.routes["/api/tags"] = (
        200,
        b'{"models": [{"name": "qwen3:latest"}, {"name": "llama3.1:8b"}]}',
    )
    backend = OllamaBackend(stub.url, 5.0, 1)
    assert backend.available() == ["llama3.1:8b", "qwen3:latest"]
    backend.check(["qwen3", "llama3.1:8b"])
    with pytest.raises(LLMSetupError) as error:
        backend.check(["qwen3", "mistral-nemo"])
    text = str(error.value)
    assert f"ollama at {stub.url}" in text
    assert "not available: mistral-nemo" in text
    assert "ollama pull mistral-nemo" in text
    assert "llama3.1:8b, qwen3:latest" in text


@pytest.mark.req("REQ-LLM-002")
def test_check_on_an_unreachable_server_says_how_to_start_it() -> None:
    """AC1: an Ollama that is not running fails fast."""
    backend = OllamaBackend(f"http://127.0.0.1:{free_port()}", 2.0, 1)
    with pytest.raises(LLMSetupError, match=r"cannot reach ollama at .*`ollama serve`"):
        backend.check(["qwen3"])


@pytest.mark.req("REQ-LLM-002")
def test_a_tag_listing_of_the_wrong_shape_is_a_setup_error(stub: Stub) -> None:
    """AC1: a server that is not Ollama is reported, not a KeyError."""
    stub.routes["/api/tags"] = (200, b'{"models": "none"}')
    with pytest.raises(LLMSetupError, match="unexpected model listing"):
        OllamaBackend(stub.url, 5.0, 1).check(["qwen3"])


def test_a_name_without_a_tag_means_latest() -> None:
    """Ollama treats `qwen3` and `qwen3:latest` as the same model."""
    assert tagged("qwen3") == "qwen3:latest"
    assert tagged("qwen3:8b") == "qwen3:8b"
