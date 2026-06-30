#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import hashlib
import binascii
import hmac
import os

# Constants for key derivation
SALT_SIZE = 16  # 128 bits
ITERATIONS = 260000  # Recommended by OWASP for PBKDF2-HMAC-SHA256
DKLEN = 32  # 256-bit key
V2_PREFIX = "v2:"
NONCE_SIZE = 16
TAG_SIZE = 32


def derive_key(password: str, salt: bytes) -> bytes:
    if not password or not salt:
        return b""
    password_bytes = password.encode("utf-8")
    return hashlib.pbkdf2_hmac("sha256", password_bytes, salt, ITERATIONS, dklen=DKLEN)


def xor_cipher(data: bytes, key: bytes) -> bytes:
    key_len = len(key)
    if key_len == 0:
        return data
    return bytes(data[i] ^ key[i % key_len] for i in range(len(data)))


def _derive_subkey(key: bytes, label: bytes) -> bytes:
    return hmac.new(key, label, hashlib.sha256).digest()


def _xor_stream(data: bytes, key: bytes, nonce: bytes) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < len(data):
        counter_bytes = counter.to_bytes(8, "big")
        output.extend(hmac.new(key, nonce + counter_bytes, hashlib.sha256).digest())
        counter += 1
    return bytes(b ^ k for b, k in zip(data, output))


def encrypt(plaintext: str, key: bytes) -> str:
    if not plaintext or not key:
        return plaintext
    enc_key = _derive_subkey(key, b"sshgo-v2-encryption")
    mac_key = _derive_subkey(key, b"sshgo-v2-authentication")
    nonce = os.urandom(NONCE_SIZE)
    plaintext_bytes = plaintext.encode("utf-8")
    encrypted_bytes = _xor_stream(plaintext_bytes, enc_key, nonce)
    tag = hmac.new(mac_key, nonce + encrypted_bytes, hashlib.sha256).digest()
    payload = nonce + encrypted_bytes + tag
    return V2_PREFIX + base64.urlsafe_b64encode(payload).decode("utf-8")


def decrypt(ciphertext: str, key: bytes) -> str:
    """Decrypts Base64 encoded ciphertext. Returns original ciphertext on failure."""
    if not ciphertext or not key:
        return ciphertext
    if ciphertext.startswith(V2_PREFIX):
        try:
            payload = base64.urlsafe_b64decode(
                ciphertext[len(V2_PREFIX):].encode("utf-8")
            )
            if len(payload) < NONCE_SIZE + TAG_SIZE:
                return ciphertext
            nonce = payload[:NONCE_SIZE]
            tag = payload[-TAG_SIZE:]
            encrypted_bytes = payload[NONCE_SIZE:-TAG_SIZE]
            enc_key = _derive_subkey(key, b"sshgo-v2-encryption")
            mac_key = _derive_subkey(key, b"sshgo-v2-authentication")
            expected_tag = hmac.new(
                mac_key, nonce + encrypted_bytes, hashlib.sha256
            ).digest()
            if not hmac.compare_digest(tag, expected_tag):
                return ciphertext
            return _xor_stream(encrypted_bytes, enc_key, nonce).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return ciphertext

    try:
        decoded_bytes = base64.urlsafe_b64decode(ciphertext.encode("utf-8"))
        decrypted_bytes = xor_cipher(decoded_bytes, key)
        return decrypted_bytes.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        # This can happen if the data was not valid Base64 or not valid UTF-8 after decryption.
        # A likely scenario is a wrong password leading to garbage data.
        return ciphertext
