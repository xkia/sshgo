#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import hmac, base64, struct, hashlib, time, argparse, sys


def get_hotp_token(secret, intervals_no):
    """This is where the magic happens."""
    key = base64.b32decode(
        normalize(secret), True
    )  # True is to fold lower into uppercase
    msg = struct.pack(">Q", intervals_no)
    h = bytearray(hmac.new(key, msg, hashlib.sha1).digest())
    o = h[19] & 15
    h = str((struct.unpack(">I", h[o : o + 4])[0] & 0x7FFFFFFF) % 1000000)
    return prefix0(h)


def get_totp_token(secret):
    """The TOTP token is just a HOTP token seeded with every 30 seconds."""
    return get_hotp_token(secret, intervals_no=int(time.time()) // 30)


def normalize(key):
    """Normalizes secret by removing spaces and padding with = to a multiple of 8"""
    k2 = key.strip().replace(" ", "")
    if not k2:
        raise ValueError("Secret key cannot be empty after normalization.")
    if len(k2) % 8 != 0:
        k2 += "=" * (8 - len(k2) % 8)
    return k2


def prefix0(h):
    """Prefixes code with leading zeros if missing."""
    return h.zfill(6)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate TOTP token from secret key.")
    parser.add_argument(
        "secret",
        type=str,
        help="Base32 encoded secret key, or '-' to read it from stdin",
    )
    args = parser.parse_args()
    try:
        secret = sys.stdin.read().strip() if args.secret == "-" else args.secret
        print(get_totp_token(secret))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
