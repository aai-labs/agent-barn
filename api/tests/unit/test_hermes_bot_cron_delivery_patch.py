import importlib.util
import sys
from pathlib import Path

import pytest

_PATCH = Path(__file__).parents[3] / "hermes-base" / "patch-bot-cron-delivery.py"

_RUN = """def start(runner, cron_start_kwargs, profile_homes):
    if True:
        if True:
            if True:
                cron_start_kwargs["profile_homes"] = profile_homes
"""

_PROVIDER = """class Scheduler:
    def start(
        self,
        profile_homes=None,
    ):
        pass

    def forward(self, profile_homes, adapters):
        if True:
            self._start_multiplex(
                profile_homes=profile_homes,
                adapters=adapters,
            )

    def _start_multiplex(
        self,
        profile_homes,
        adapters=None,
    ):
        for entry in profile_homes:
            if True:
                if True:
                    if True:
                        if True:
                            if True:
                                cron_tick(
                                    verbose=False,
                                    adapters=adapters,
                                )
"""

_SEND = """def send(runner, platform):
    if runner is not None:
        try:
            adapter = runner.adapters.get(platform)
        except Exception:
            adapter = None
"""

_SOURCES = {
    "gateway/run.py": _RUN,
    "cron/scheduler_provider.py": _PROVIDER,
    "tools/send_message_tool.py": _SEND,
}


def _write_sources(root: Path, sources: dict[str, str] = _SOURCES) -> None:
    for relative, source in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def _patch(monkeypatch, root: Path) -> None:
    spec = importlib.util.spec_from_file_location("patch_bot_cron_delivery", _PATCH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(sys, "argv", ["patch", str(root)])
    module.main()


def _read(root: Path, relative: str) -> str:
    return (root / relative).read_text(encoding="utf-8")


def test_the_gateway_hands_the_scheduler_every_bots_connections(monkeypatch, tmp_path) -> None:
    _write_sources(tmp_path)

    _patch(monkeypatch, tmp_path)

    assert 'cron_start_kwargs["profile_adapters"] = runner._profile_adapters' in _read(tmp_path, "gateway/run.py")


def test_each_named_profile_ticks_with_its_own_connections(monkeypatch, tmp_path) -> None:
    _write_sources(tmp_path)

    _patch(monkeypatch, tmp_path)

    patched = _read(tmp_path, "cron/scheduler_provider.py")
    assert 'adapters=adapters if entry[0] == "default" else (profile_adapters or {}).get(entry[0], {}),' in patched
    assert patched.count("profile_adapters=None,") == 2
    assert "profile_adapters=profile_adapters," in patched


def test_a_named_profile_never_sends_through_the_default_connection(monkeypatch, tmp_path) -> None:
    _write_sources(tmp_path)

    _patch(monkeypatch, tmp_path)

    assert 'adapter = None if get_hermes_home().parent.name == "profiles" else runner.adapters.get(platform)' in _read(
        tmp_path, "tools/send_message_tool.py"
    )


def test_patched_files_still_compile(monkeypatch, tmp_path) -> None:
    _write_sources(tmp_path)

    _patch(monkeypatch, tmp_path)

    for relative in _SOURCES:
        compile(_read(tmp_path, relative), relative, "exec")


def test_patching_twice_changes_nothing(monkeypatch, tmp_path) -> None:
    _write_sources(tmp_path)

    _patch(monkeypatch, tmp_path)
    once = {relative: _read(tmp_path, relative) for relative in _SOURCES}
    _patch(monkeypatch, tmp_path)

    assert {relative: _read(tmp_path, relative) for relative in _SOURCES} == once


@pytest.mark.parametrize(
    ("relative", "anchor"),
    [
        ("gateway/run.py", 'cron_start_kwargs["profile_homes"]'),
        ("cron/scheduler_provider.py", "profile_homes=None"),
        ("cron/scheduler_provider.py", "profile_homes=profile_homes"),
        ("cron/scheduler_provider.py", "        profile_homes,\n"),
        ("cron/scheduler_provider.py", "cron_tick("),
        ("tools/send_message_tool.py", "runner.adapters.get(platform)"),
    ],
)
def test_a_changed_hermes_source_fails_the_build(monkeypatch, tmp_path, relative, anchor) -> None:
    sources = {**_SOURCES, relative: _SOURCES[relative].replace(anchor, "changed", 1)}
    _write_sources(tmp_path, sources)

    with pytest.raises(SystemExit):
        _patch(monkeypatch, tmp_path)
