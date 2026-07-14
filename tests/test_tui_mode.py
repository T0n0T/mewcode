from io import StringIO

import pytest

from mewcode.tui import mode
from mewcode.tui.mode import TerminalMode, detect_terminal_mode


class FakeTerminal:
    def __init__(self, interactive=True, error=None):
        self.interactive = interactive
        self.error = error

    def isatty(self):
        if self.error is not None:
            raise self.error
        return self.interactive


def test_actual_interactive_standard_streams_use_fullscreen(monkeypatch):
    stdin = FakeTerminal()
    stdout = FakeTerminal()
    monkeypatch.setattr(mode.sys, "stdin", stdin)
    monkeypatch.setattr(mode.sys, "stdout", stdout)

    assert detect_terminal_mode(stdin, stdout) is TerminalMode.FULLSCREEN


@pytest.mark.parametrize(
    ("stdin_interactive", "stdout_interactive"),
    [(False, True), (True, False), (False, False)],
)
def test_non_interactive_standard_streams_use_plain(
    monkeypatch,
    stdin_interactive,
    stdout_interactive,
):
    stdin = FakeTerminal(stdin_interactive)
    stdout = FakeTerminal(stdout_interactive)
    monkeypatch.setattr(mode.sys, "stdin", stdin)
    monkeypatch.setattr(mode.sys, "stdout", stdout)

    assert detect_terminal_mode(stdin, stdout) is TerminalMode.PLAIN


def test_injected_streams_always_use_plain():
    assert detect_terminal_mode(StringIO(), StringIO()) is TerminalMode.PLAIN


@pytest.mark.parametrize("error", [OSError("bad tty"), AttributeError("missing")])
def test_terminal_detection_errors_fall_back_to_plain(monkeypatch, error):
    stdin = FakeTerminal(error=error)
    stdout = FakeTerminal()
    monkeypatch.setattr(mode.sys, "stdin", stdin)
    monkeypatch.setattr(mode.sys, "stdout", stdout)

    assert detect_terminal_mode(stdin, stdout) is TerminalMode.PLAIN
