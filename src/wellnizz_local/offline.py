# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
"""Runtime offline guard.

Installs a Python audit hook (PEP 578) that refuses network, subprocess and
native-library events while the guard is enabled. Every refused attempt is
recorded so a run can report "0 network attempts" as a checked fact rather
than a promise.

Limits (stated plainly): an audit hook protects against Python code in this
process. It does not stop native code, another process, or a modified
interpreter. See docs/PRIVACY.md.
"""

from __future__ import annotations

import sys
import threading

BLOCKED_EVENT_PREFIXES = (
    "socket.",            # socket.__new__, connect, bind, getaddrinfo, sendto, ...
    "urllib.Request",
    "http.client.",
    "ftplib.",
    "smtplib.",
    "poplib.",
    "imaplib.",
    "nntplib.",
    "telnetlib.",
    "webbrowser.",
    "subprocess.Popen",
    "os.system",
    "os.exec",
    "os.posix_spawn",
    "os.spawn",
    "os.fork",
    "ctypes.dlopen",
    "sqlite3.enable_load_extension",
    "sqlite3.load_extension",
)


class NetworkBlocked(PermissionError):
    """Raised when code tries to reach the network (or spawn a process) under the guard."""


class _State:
    def __init__(self) -> None:
        self.enabled = False
        self.installed = False
        self.attempts: list[str] = []
        self.lock = threading.Lock()


_state = _State()


def _hook(event: str, args: tuple) -> None:
    if not _state.enabled:
        return
    if event.startswith(BLOCKED_EVENT_PREFIXES):
        with _state.lock:
            _state.attempts.append(event)
        raise NetworkBlocked(f"wellnizz-local offline guard blocked audit event {event!r}")


def enable() -> None:
    """Install (once) and enable the guard. Audit hooks cannot be removed, only disabled."""
    if not _state.installed:
        sys.addaudithook(_hook)
        _state.installed = True
    _state.enabled = True


def disable() -> None:
    _state.enabled = False


def attempts() -> list[str]:
    with _state.lock:
        return list(_state.attempts)


def reset_attempts() -> None:
    with _state.lock:
        _state.attempts.clear()


def is_enabled() -> bool:
    return _state.enabled
