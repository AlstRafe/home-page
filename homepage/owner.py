"""持ち主のログイン: the owner gets every site with everything under the public names too, from any
device, without Tailscale.

Under a public name every request is a visitor's (homepage.server.Public), unless it carries the
owner's cookie, which ``/owner`` gives for the password set on the server with
``sudo bash deploy/setup.sh --owner`` (``python -m homepage.owner``). The password is kept as an
scrypt hash, with the key the cookies are signed with, in ``FILE`` (``state/owner.json`` beside the
Home Page folder, readable by the server's account only). A new password comes with a new key, so
setting one signs every device out. Without the file there is no login: the public names are
visitors' only, as before.

Wrong passwords are limited for everyone together (``LIMITS``), so a password cannot be found by
trying, however many addresses the tries come from, and only one try is checked at a time (scrypt
is made to be slow), so tries cannot keep the small server busy either.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time
from collections import deque
from pathlib import Path

FILE = Path(__file__).resolve().parents[2] / "state" / "owner.json"
COOKIE = "__Host-owner"
#: How long a device stays signed in (the longest browsers keep a cookie).
SECONDS = 400 * 24 * 3600
#: At most this many wrong passwords in so many seconds, for all comers together.
LIMITS = ((60, 5), (3600, 20))
SHORTEST = 10
SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hash(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=64 * 1024 * 1024, dklen=32)


def write(password: str, path: Path = FILE) -> None:
    """Sets the owner's password (and a new cookie key, which signs every device out)."""
    if len(password) < SHORTEST:
        raise ValueError(f"パスワードは {SHORTEST} 文字以上にしてください。")
    salt = secrets.token_bytes(16)
    data = {
        "scrypt": {**SCRYPT, "salt": _b64(salt), "hash": _b64(_hash(password, salt, **SCRYPT))},
        "key": _b64(secrets.token_bytes(32)),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(path.name + ".new")
    descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        json.dump(data, file)
    os.replace(staged, path)


class Owner:
    """The owner's password and cookies, read from ``path`` (again whenever the file changes)."""

    def __init__(self, path: Path = FILE):
        self.path = Path(path)
        self._stamp: tuple | None = None
        self._data: dict | None = None
        self._failures: deque[float] = deque()
        self._lock = threading.Lock()
        self._trying = threading.Lock()

    def _read(self) -> dict | None:
        try:
            info = self.path.stat()
        except OSError:
            return None
        stamp = (info.st_mtime_ns, info.st_size)
        if stamp != self._stamp:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                found = raw["scrypt"]
                data = {
                    "salt": _unb64(found["salt"]),
                    "hash": _unb64(found["hash"]),
                    "cost": {key: int(found[key]) for key in ("n", "r", "p")},
                    "key": _unb64(raw["key"]),
                }
                if len(data["key"]) < 32 or not data["hash"]:
                    raise ValueError("too short")
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                data = None
            self._stamp, self._data = stamp, data
        return self._data

    @property
    def ready(self) -> bool:
        """Whether a password is set (else there is no login)."""
        return self._read() is not None

    def login(self, password: str, now: float | None = None) -> str:
        """The result of a try: "ok", "wrong", "busy" (too many wrong lately, or another being checked), "off"."""
        data = self._read()
        if data is None:
            return "off"
        now = time.time() if now is None else now
        with self._lock:
            while self._failures and now - self._failures[0] >= LIMITS[-1][0]:
                self._failures.popleft()
            if any(sum(1 for at in self._failures if now - at < span) >= most for span, most in LIMITS):
                return "busy"
        if not self._trying.acquire(blocking=False):
            return "busy"
        try:
            right = hmac.compare_digest(_hash(password[:1024], data["salt"], **data["cost"]), data["hash"])
        finally:
            self._trying.release()
        if right:
            return "ok"
        with self._lock:
            self._failures.append(now)
        return "wrong"

    def _sign(self, key: bytes, issued: int) -> str:
        return _b64(hmac.new(key, f"owner {issued}".encode(), hashlib.sha256).digest())

    def cookie(self, now: float | None = None) -> tuple[str, str]:
        """The Set-Cookie header that makes this device the owner's."""
        data = self._read()
        if data is None:
            raise RuntimeError("no password is set")
        issued = int(time.time() if now is None else now)
        value = f"{issued}.{self._sign(data['key'], issued)}"
        return "Set-Cookie", f"{COOKIE}={value}; Path=/; Max-Age={SECONDS}; Secure; HttpOnly; SameSite=Lax"

    @staticmethod
    def forget() -> tuple[str, str]:
        return "Set-Cookie", f"{COOKIE}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax"

    def signed_in(self, environ, now: float | None = None) -> bool:
        """Whether this request carries a cookie this server gave (for the password set now)."""
        raw = environ.get("HTTP_COOKIE", "")
        if COOKIE not in raw:
            return False
        data = self._read()
        if data is None:
            return False
        # Read by hand: SimpleCookie drops every cookie after one it cannot parse (a site's own may be such).
        value = next(
            (part.strip()[len(COOKIE) + 1 :] for part in raw.split(";") if part.strip().startswith(COOKIE + "=")), ""
        )
        issued, _, signature = value.partition(".")
        if not issued.isdecimal():
            return False
        now = time.time() if now is None else now
        if not -60 <= now - int(issued) <= SECONDS:
            return False
        return hmac.compare_digest(signature, self._sign(data["key"], int(issued)))


def without_cookie(raw: str) -> str:
    """The Cookie header without the owner's cookie (the sites never need to see it)."""
    return "; ".join(
        part.strip() for part in raw.split(";") if part.strip() and not part.strip().startswith(COOKIE + "=")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m homepage.owner", description="持ち主のログインのパスワード")
    parser.add_argument("--stdin", action="store_true", help="パスワードを標準入力の1行目から読む（setup.sh --owner）")
    parser.add_argument("--off", action="store_true", help="ログインをやめる（パスワードを消す）")
    parser.add_argument("--file", type=Path, default=FILE, help=f"置き場所（既定: {FILE}）")
    args = parser.parse_args(argv)
    if args.off:
        args.file.unlink(missing_ok=True)
        print("持ち主のログインをやめました。公開の名前では、だれでも訪問者として表示されます。")
        return 0
    if args.stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("新しいパスワード: ")
        if getpass.getpass("もう一度: ") != password:
            print("2回の入力が違います。", file=sys.stderr)
            return 2
    try:
        write(password, args.file)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    print("パスワードを決めました。今までログインしていた端末は、ログアウトされます。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
