#!/usr/bin/env python
"""Generate the two shared secrets the pilot gate needs.

    python scripts/gen-pilot-secrets.py              # print .env lines
    python scripts/gen-pilot-secrets.py --write      # update backend/.env
    python scripts/gen-pilot-secrets.py --invite-only

Two secrets, and they do different jobs:

  FISHAGENT_PILOT_INVITE_CODE    the shared code you hand to pilot users. It is
                                 checked only when someone logs in, so changing
                                 it does NOT log anyone out -- people already
                                 inside stay inside until their cookie expires.

  FISHAGENT_PILOT_TOKEN_SECRET   signs the session cookies. Changing it
                                 invalidates every outstanding session at once,
                                 which is what you want after a leak or when
                                 removing someone. --invite-only leaves it
                                 alone, because rotating it is a separate
                                 decision with a visible cost.

The invite code is meant to be read aloud and typed on a phone, so it uses an
alphabet without look-alikes: no 0/O, no 1/l/I. It is not a password -- it is
deliberately shared by 3-5 people -- so it needs length rather than symbols:
20 characters over this alphabet is ~90 bits, which nobody is going to guess
against a 10-attempts-per-minute limit.

Never commit the output. backend/.env is gitignored for this reason.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import secrets
import sys
from pathlib import Path

# 32 unambiguous characters. Excluding look-alikes is worth the ~5 bits it
# costs, because a mistyped code looks like a wrong code and the user has no
# way to tell the difference.
INVITE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
INVITE_LENGTH = 20

ENV_PATH = Path(__file__).resolve().parent.parent / "backend" / ".env"

MIN_INVITE = 6  # what fishagent/pilot/state.py enforces at startup
MIN_SECRET = 32  # ditto


def make_invite_code(length: int = INVITE_LENGTH) -> str:
    # secrets.choice over a str would repeat characters more than a shuffle;
    # rejection-free here because 32 is a power of two.
    return "".join(secrets.choice(INVITE_ALPHABET) for _ in range(length))


def make_token_secret() -> str:
    return secrets.token_urlsafe(32)


def invite_fingerprint(code: str) -> str:
    """Must match fishagent.pilot.state.invite_fingerprint, so the server's
    startup log line and this output can be compared directly."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()[:8]


def update_env(path: Path, values: dict[str, str]) -> list[str]:
    """Replace the given keys in .env, appending any that are missing.

    Rewrites line by line rather than regenerating the file, so unrelated
    settings -- including the real API keys -- are left byte-for-byte alone.
    """
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending = dict(values)
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in pending:
            out.append(f"{key}={pending.pop(key)}")
        else:
            out.append(line)
    for key, value in pending.items():
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return list(values)


def _print_fingerprint() -> int:
    """Report which code .env currently holds, without revealing it.

    Answers the one question that a "I changed the code and it still won't
    take" report really has: is the running process serving an older code
    (needs a restart) or is the value itself not what you think it is?
    """
    if not ENV_PATH.exists():
        print(f"error: {ENV_PATH} does not exist", file=sys.stderr)
        return 1
    match = re.search(
        r"^FISHAGENT_PILOT_INVITE_CODE=(.*)$",
        ENV_PATH.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if not match:
        print("error: FISHAGENT_PILOT_INVITE_CODE is not set in .env", file=sys.stderr)
        return 1
    code = match.group(1).strip()
    if not code:
        print("error: FISHAGENT_PILOT_INVITE_CODE is empty in .env", file=sys.stderr)
        return 1
    print(f"invite code fingerprint: {invite_fingerprint(code)}  (length {len(code)})")
    print(
        "compare against the server's startup line:\n"
        '  "pilot gate enabled; invite code fingerprint <same value>"'
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--write",
        action="store_true",
        help="write into backend/.env instead of printing (the values never leave the file)",
    )
    parser.add_argument(
        "--invite-only",
        action="store_true",
        help="leave the token secret alone, so existing sessions stay logged in",
    )
    parser.add_argument(
        "--length",
        type=int,
        default=INVITE_LENGTH,
        help=f"invite code length (default {INVITE_LENGTH}, minimum {MIN_INVITE})",
    )
    parser.add_argument(
        "--fingerprint",
        action="store_true",
        help="print the fingerprint of the code currently in .env, to compare "
        "against the server's startup log line (no changes are made)",
    )
    args = parser.parse_args(argv)

    if args.fingerprint:
        return _print_fingerprint()

    if args.length < MIN_INVITE:
        parser.error(f"--length must be at least {MIN_INVITE}")

    values = {"FISHAGENT_PILOT_INVITE_CODE": make_invite_code(args.length)}
    if not args.invite_only:
        values["FISHAGENT_PILOT_TOKEN_SECRET"] = make_token_secret()
    assert len(values["FISHAGENT_PILOT_INVITE_CODE"]) >= MIN_INVITE
    if "FISHAGENT_PILOT_TOKEN_SECRET" in values:
        assert len(values["FISHAGENT_PILOT_TOKEN_SECRET"]) >= MIN_SECRET

    if args.write:
        if not ENV_PATH.exists():
            print(f"error: {ENV_PATH} does not exist; copy .env.example first", file=sys.stderr)
            return 1
        update_env(ENV_PATH, values)
        print(f"updated {ENV_PATH}")
        print(f"  invite code: {values['FISHAGENT_PILOT_INVITE_CODE']}")
        print(
            "  invite fingerprint: "
            f"{invite_fingerprint(values['FISHAGENT_PILOT_INVITE_CODE'])}"
        )
        if "FISHAGENT_PILOT_TOKEN_SECRET" in values:
            print("  token secret: rotated -- every existing session is now logged out")
        else:
            print("  token secret: unchanged")
        print(
            "\nRestart the server for the change to take effect -- settings are read\n"
            "once at startup, so until then the old code is still the one accepted.\n"
            "After the restart, the startup log prints the same fingerprint; if it\n"
            "differs, the process did not pick up this file."
        )
    else:
        for key, value in values.items():
            print(f"{key}={value}")

    if "FISHAGENT_PILOT_TOKEN_SECRET" not in values:
        print(
            "note: the invite code alone does not end existing sessions; "
            "run without --invite-only to revoke them.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
