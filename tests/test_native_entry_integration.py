"""Shared entry preparation with fake server/store; no clock, GUI or optional runtime."""

import builtins
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from portable import atlas_entry, native_launch
from portable.native_origin import NativeRefusal
from webapp.backend import app as app_module
from webapp.backend import serve


@pytest.fixture
def entry(monkeypatch):
    events = []
    app = SimpleNamespace(state=SimpleNamespace(frontend_ready=True,
                                               store=SimpleNamespace(close=lambda: events.append("close"))))

    def create(**kwargs):
        events.append("create")
        return app

    def run(received, **kwargs):
        events.append(("server", received, kwargs))

    monkeypatch.setattr(app_module, "create_app", create)
    monkeypatch.setattr(serve, "_writable_failure", lambda path: None)
    monkeypatch.setattr(serve, "_effective_db_path", lambda path: "synthetic.db")
    monkeypatch.setattr(serve, "_resolve_db", lambda path: "synthetic.db")
    monkeypatch.setattr(serve, "_resolve_dist", lambda path: Path("synthetic-dist"))
    monkeypatch.setattr(serve, "_resolve_scope_dist", lambda: Path("synthetic-scope"))
    monkeypatch.setattr(serve, "_schedule_browser_open", lambda url: events.append(("browser", url)))
    monkeypatch.setattr(serve, "_frozen", lambda: False)
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=run))
    return app, events


def test_packaged_default_keeps_exact_browser_and_app_while_native_dependencies_are_held(monkeypatch, entry):
    app, events = entry

    def held():
        events.append("admission")
        raise NativeRefusal("native_dependency_publication_pending")

    original_import = builtins.__import__
    optional_imports = []

    def observe_import(name, *args, **kwargs):
        if name.split(".")[0] in {"webview", "clr", "pythonnet"}:
            optional_imports.append(name)
            raise AssertionError("optional native dependency imported while held")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(native_launch, "require_native_release_admission", held)
    monkeypatch.setattr(builtins, "__import__", observe_import)
    assert atlas_entry.main(["--port", "8123"]) == 0
    assert optional_imports == []
    assert events == ["create", "admission", ("browser", "http://127.0.0.1:8123/"),
                      ("server", app, {"host": "127.0.0.1", "port": 8123, "log_level": "info"}), "close"]


@pytest.mark.parametrize("flag", ["--browser", "--no-browser"])
def test_explicit_browser_or_headless_mode_never_calls_the_packaging_preparation(monkeypatch, entry, flag):
    app, events = entry
    monkeypatch.setattr(atlas_entry, "_prepare_presentation", lambda *_: pytest.fail("native preparation reached"))
    assert atlas_entry.main(["--port", "8123", flag]) == 0
    assert events[0] == "create" and events[-1] == "close"
    assert [event for event in events if isinstance(event, tuple) and event[0] == "browser"] == (
        [("browser", "http://127.0.0.1:8123/")] if flag == "--browser" else []
    )
    assert [event[1] for event in events if isinstance(event, tuple) and event[0] == "server"] == [app]


def test_browser_and_headless_options_are_mutually_exclusive_before_writes(entry):
    _app, events = entry
    with pytest.raises(SystemExit) as raised:
        serve.main(["--browser", "--no-browser"])
    assert raised.value.code == 2
    assert events == []


def test_shared_callback_prepares_original_app_without_replacing_server_or_store_owner(entry):
    app, events = entry
    unrelated = object()

    def prepare(received, url):
        assert received is app and url == "http://127.0.0.1:8123/"
        events.append("prepare")
        return unrelated  # callback return values do not replace the shared application

    assert serve.main(["--port", "8123"], presentation_prepare=prepare) == 0
    assert events == ["create", "prepare",
                      ("server", app, {"host": "127.0.0.1", "port": 8123, "log_level": "info"}), "close"]


def test_failed_preparation_closes_the_owned_store_once_without_running_a_second_server(entry):
    _app, events = entry

    def failed(_app, _url):
        raise RuntimeError("synthetic presentation failure")

    with pytest.raises(RuntimeError, match="synthetic presentation failure"):
        serve.main([], presentation_prepare=failed)
    assert events == ["create", "close"]


def test_maintenance_write_fence_precedes_store_and_presentation(entry):
    _app, events = entry
    assert serve.main([], write_admission=lambda: True,
                      presentation_prepare=lambda *_: pytest.fail("fence bypassed")) == 1
    assert events == []


def test_engine_argv_remains_opaque_and_never_reaches_browser_or_native_parser(monkeypatch, entry):
    _app, events = entry
    seen = []
    monkeypatch.setattr(serve, "_run_engine", lambda argv: seen.append(argv) or 17)
    assert serve.main([serve.ENGINE_SENTINEL, "--browser", "--opaque-engine-flag"],
                      presentation_prepare=lambda *_: pytest.fail("engine reached presentation")) == 17
    assert seen == [["--browser", "--opaque-engine-flag"]]
    assert events == []


def test_legacy_scoped_callback_signature_receives_no_new_keyword_when_adapter_absent(monkeypatch):
    seen = []

    def old_scoped(argv, *, command_handler, write_admission):
        seen.append((argv, command_handler, write_admission))
        return 18

    def dispatch(argv):
        return None
    monkeypatch.setattr(serve, "_main_scoped", old_scoped)
    assert serve.main(["--version"], command_handler=dispatch) == 18
    assert seen == [(["--version"], dispatch, None)]
