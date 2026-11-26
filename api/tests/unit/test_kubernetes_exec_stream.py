"""Pod exec output must arrive as whole lines, whatever the websocket frame boundaries."""

from unittest.mock import MagicMock, patch

from api.infrastructure.kubernetes.client import BoundedLines, KubernetesClient

# The exec API object itself is never called: k8s_stream is replaced. Reading the
# real property would load a kubeconfig.
_NO_KUBECONFIG = patch.object(KubernetesClient, "_stream_core_v1", new=MagicMock())


class FakeExec:
    """The slice of kubernetes.stream.ws_client.WSClient that line streaming reads."""

    def __init__(self, frames: list[str | None]) -> None:
        self._frames = frames
        self._pending = ""
        self.closed = False

    def is_open(self) -> bool:
        return bool(self._frames) and not self.closed

    def update(self, timeout: float = 0) -> None:
        frame = self._frames.pop(0)
        self._pending += frame or ""

    def peek_stdout(self, timeout: float = 0) -> str:
        return self._pending

    def read_stdout(self, timeout: float | None = None) -> str:
        data, self._pending = self._pending, ""
        return data

    def close(self) -> None:
        self.closed = True


def _lines(frames: list[str | None]) -> tuple[list[str | None], FakeExec]:
    fake = FakeExec(frames)
    with _NO_KUBECONFIG, patch("api.infrastructure.kubernetes.client.k8s_stream", return_value=fake) as stream:
        lines = list(KubernetesClient(config=MagicMock()).stream_exec_lines("pod", "ns", ["sh", "-c", "true"]))
    assert stream.call_args.kwargs["container"] == "agent"
    return lines, fake


def test_exec_lines_are_reassembled_across_frames_and_idle_gaps_yield_none() -> None:
    lines, fake = _lines(['{"event":"st', 'arted"}\n{"event":"qr"}\n', None, '{"event":"linked"}'])

    assert lines == ['{"event":"started"}', '{"event":"qr"}', None, '{"event":"linked"}']
    assert fake.closed


def test_closing_the_stream_early_closes_the_exec_session() -> None:
    fake = FakeExec(["one\n", "two\n"])
    with _NO_KUBECONFIG, patch("api.infrastructure.kubernetes.client.k8s_stream", return_value=fake):
        lines = KubernetesClient(config=MagicMock()).stream_exec_lines("pod", "ns", ["true"])
        assert next(lines) == "one"
        lines.close()

    assert fake.closed


def test_an_overlong_line_is_dropped_and_the_next_line_still_arrives() -> None:
    fake = FakeExec(["x" * 6, "x" * 6, "x\nshort\n", "tail"])
    with _NO_KUBECONFIG, patch("api.infrastructure.kubernetes.client.k8s_stream", return_value=fake):
        lines = list(KubernetesClient(config=MagicMock()).stream_exec_lines("pod", "ns", ["true"], max_line_chars=10))

    assert lines == ["short", "tail"]


def test_the_stream_ends_at_max_seconds_even_if_the_command_keeps_running() -> None:
    fake = FakeExec(["one\n", None, None, "late\n"])
    clock = iter([0.0, 1.0, 2.0, 99.0, 99.0])
    with (
        _NO_KUBECONFIG,
        patch("api.infrastructure.kubernetes.client.k8s_stream", return_value=fake),
        patch("api.infrastructure.kubernetes.client.time.monotonic", side_effect=lambda: next(clock)),
    ):
        lines = list(KubernetesClient(config=MagicMock()).stream_exec_lines("pod", "ns", ["true"], max_seconds=10))

    assert lines == ["one", None]
    assert fake.closed


def test_an_unfinished_line_never_holds_more_than_the_limit() -> None:
    lines = BoundedLines(max_chars=10)

    assert lines.feed("x" * 25) == []
    assert lines.pending == ""
    assert lines.feed("x" * 8) == []
    assert len(lines.pending) <= 10
    assert lines.feed("y\nok\nend") == ["ok"]
    assert lines.rest() == ["end"]
