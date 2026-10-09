"""W59 PR-1 interop fixture: an independent SSH server (asyncssh) with a fake Cisco exec shell.

RUNS ONLY AS A SUBPROCESS from its own virtualenv, built from the hash-pinned
``tools/requirements-ssh-fixture-test.txt``. No test module imports this file, and asyncssh never enters the
test interpreter (tests/test_ssh_session_interop.py holds both rules). The tests reach it over 127.0.0.1.

Why an independent peer (design section 8): if the collector hashed with SHA-256 while naming a SHA-1 method,
the handshake against a separate SSH implementation would fail -- a paramiko self-peer could not prove that.

Profiles pin EXACT algorithm lists (never asyncssh's defaults):

* ``sha1-only``      -- kex diffie-hellman-group14-sha1, host key ssh-rsa, aes128-ctr, hmac-sha1 (an old IOS box)
* ``modern``         -- ecdh-sha2-nistp256 / diffie-hellman-group14-sha256, rsa-sha2-512/256, aes128-ctr,
                        hmac-sha2-256
* ``sha1-and-sha2``  -- both, SHA-2 listed first (an IOS XE box with legacy algorithms still enabled)
* ``sha1-gex-only``  -- kex diffie-hellman-group-exchange-sha1 only (the server picks its group for the client's
                        requested size), host key ssh-rsa (W59 PR-2: the legacy tier's group-exchange half, end to end)

The fake shell prints a synthetic prompt (``lab-sw1#``) and canned ``show version`` text; every other command
gets the IOS invalid-input marker. It contains no client data. It appends one JSON line per event to ``--log``:
``ready``, ``auth``, ``shell_start`` and one ``line`` per received input line. When ``--expect-file`` names a
path, ``shell_start`` and the first ``line`` record whether that file existed and its JSON ``outcome`` at that
instant, so a test can prove the session record was complete BEFORE the first command (T16).

Usage:  python server.py --profile sha1-only --log events.jsonl [--expect-file PATH] [--password lab]
Prints ``READY <port>`` on stdout once listening; exits when stdin reaches EOF.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

import asyncssh

# The SHA-1 names below are the PEER's configuration (a test-only fixture, never shipped); the shipped-source
# identifier-scope scan (T10) covers the wheel and bundle denominators, which exclude tests/.
PROFILES = {
    "sha1-only": {
        "kex_algs": ["diffie-hellman-group14-sha1"],
        "signature_algs": ["ssh-rsa"],
        "encryption_algs": ["aes128-ctr"],
        "mac_algs": ["hmac-sha1"],
    },
    "modern": {
        "kex_algs": ["ecdh-sha2-nistp256", "diffie-hellman-group14-sha256"],
        "signature_algs": ["rsa-sha2-512", "rsa-sha2-256"],
        "encryption_algs": ["aes128-ctr"],
        "mac_algs": ["hmac-sha2-256"],
    },
    "sha1-and-sha2": {
        "kex_algs": ["diffie-hellman-group14-sha256", "diffie-hellman-group14-sha1"],
        "signature_algs": ["rsa-sha2-256", "ssh-rsa"],
        "encryption_algs": ["aes128-ctr"],
        "mac_algs": ["hmac-sha2-256", "hmac-sha1"],
    },
    "sha1-gex-only": {
        "kex_algs": ["diffie-hellman-group-exchange-sha1"],
        "signature_algs": ["ssh-rsa"],
        "encryption_algs": ["aes128-ctr"],
        "mac_algs": ["hmac-sha2-256"],
    },
}

PROMPT = "lab-sw1#"
SHOW_VERSION = (
    "Cisco IOS Software, C3560 Software (C3560-IPSERVICESK9-M), Version 12.2(55)SE, RELEASE SOFTWARE (fc2)\r\n"
    "cisco WS-C3560-48TS (PowerPC405) processor (revision A0) with 131072K bytes of memory.\r\n"
    "System serial number            : LAB0000000A\r\n"
    "Model number                    : WS-C3560-48TS\r\n")
INVALID = "                ^\r\n% Invalid input detected at '^' marker.\r\n"


class _Log:
    def __init__(self, path: str) -> None:
        self.path = path

    def write(self, event: str, **fields) -> None:
        row = {"event": event, "t": time.monotonic(), **fields}
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
            fh.flush()


def _expectation(path: str | None) -> dict:
    if not path:
        return {}
    if not os.path.isfile(path):
        return {"expect_file_exists": False, "expect_file_outcome": None}
    try:
        with open(path, encoding="utf-8") as fh:
            outcome = json.load(fh).get("outcome")
    except (OSError, ValueError):
        outcome = "<unreadable>"
    return {"expect_file_exists": True, "expect_file_outcome": outcome}


def _make_server(log: _Log, password: str):
    class _Server(asyncssh.SSHServer):
        def connection_made(self, conn) -> None:
            log.write("connection")

        def begin_auth(self, username: str) -> bool:
            return True

        def password_auth_supported(self) -> bool:
            return True

        def validate_password(self, username: str, pw: str) -> bool:
            ok = pw == password
            log.write("auth", ok=ok)
            return ok

    return _Server


def _make_shell(log: _Log, expect_file: str | None):
    async def _shell(process) -> None:
        log.write("shell_start", **_expectation(expect_file))
        process.stdout.write("\r\n" + PROMPT)
        first = True
        while True:
            line = await process.stdin.readline()
            if not line:
                break
            command = line.strip()
            fields = {"text": command}
            if first:
                fields.update(_expectation(expect_file))
                first = False
            log.write("line", **fields)
            process.stdout.write(line.rstrip("\r\n") + "\r\n")
            if command == "show version":
                process.stdout.write(SHOW_VERSION)
            elif command and not command.startswith("terminal "):
                process.stdout.write(INVALID)
            process.stdout.write("\r\n" + PROMPT)
        process.exit(0)

    return _shell


async def _main(args) -> None:
    log = _Log(args.log)
    key = asyncssh.generate_private_key("ssh-rsa", key_size=2048)
    profile = PROFILES[args.profile]
    acceptor = await asyncssh.listen(
        "127.0.0.1", 0,
        server_host_keys=[key],
        server_factory=_make_server(log, args.password),
        process_factory=_make_shell(log, args.expect_file),
        line_editor=False,
        compression_algs=None,
        server_version="Cisco-1.25",
        **profile)
    port = acceptor.get_port()
    log.write("ready", port=port, profile=args.profile)
    sys.stdout.write(f"READY {port}\n")
    sys.stdout.flush()
    loop = asyncio.get_running_loop()
    # Stay up until the test closes our stdin (a portable shutdown signal on Windows and POSIX).
    await loop.run_in_executor(None, sys.stdin.read)
    acceptor.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", choices=sorted(PROFILES), required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--expect-file", default=None)
    ap.add_argument("--password", default="lab")
    args = ap.parse_args(argv)
    asyncio.run(_main(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
