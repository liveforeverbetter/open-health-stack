# SPDX-FileCopyrightText: 2026 Wellnizz contributors
# SPDX-License-Identifier: Apache-2.0
"""Hash-linked access log plus a device-held witness of its head.

Each log entry stores the hash of the previous entry, so deleting, editing or
reordering any entry breaks the chain. The chain alone cannot reveal a
truncated tail or an entry forged by someone who recomputes the hashes, so
after every append the device writes a *witness*: the latest sequence number
and head hash, authenticated with HMAC-SHA256 under a key kept outside the
database (``device.key``). The verifier compares the log with the witness.

In this prototype the key is a file with mode 0600. Moving it into a TPM,
secure element or FIDO2 token, and replacing the witness file with a hardware
monotonic counter, is the research step (see docs/PRIVACY.md, "Known gaps").
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

GENESIS = "0" * 64
ENTRY_FIELDS = (
    "seq", "ts", "session", "tool", "args_json", "granted", "declared",
    "decision", "reason", "tables_read", "result_sha256", "prev_hash",
)


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def entry_hash(entry: dict) -> str:
    return sha256_hex(canonical({k: entry[k] for k in ENTRY_FIELDS}))


def _write_atomic(path: Path, data: bytes, mode: int = 0o600) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


class DeviceKey:
    def __init__(self, home: Path):
        self.path = Path(home) / "device.key"
        if not self.path.exists():
            _write_atomic(self.path, secrets.token_bytes(32))
        self._key = self.path.read_bytes()

    def mac(self, message: str) -> str:
        return hmac.new(self._key, message.encode("utf-8"), hashlib.sha256).hexdigest()

    def check(self, message: str, tag: str) -> bool:
        return hmac.compare_digest(self.mac(message), tag)


class Witness:
    def __init__(self, home: Path, key: DeviceKey):
        self.path = Path(home) / "witness.json"
        self.key = key

    @staticmethod
    def _message(seq: int, head: str) -> str:
        return f"wellnizz-local/witness/v1:{seq}:{head}"

    def write(self, seq: int, head: str) -> None:
        body = {"seq": seq, "head": head, "mac": self.key.mac(self._message(seq, head))}
        _write_atomic(self.path, canonical(body).encode("utf-8"))

    def read(self) -> dict | None:
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text("utf-8"))

    def valid(self, body: dict) -> bool:
        return self.key.check(self._message(int(body["seq"]), str(body["head"])), str(body["mac"]))
