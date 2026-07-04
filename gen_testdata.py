#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Bill Halpin
"""
Generate test binary files to demonstrate trigram comparison:

  base.bin      - simulated binary with realistic byte distribution
  similar.bin   - base.bin with minor mutations (polymorphic variant)
  embedded.bin  - different file with a chunk of base.bin embedded inside
  unrelated.bin - completely different random-ish content
"""

import os
import random
import struct

rng = random.Random(42)


def write(path: str, data: bytes) -> None:
    """Write *data* to *path* in binary mode and print the resulting file size."""
    with open(path, "wb") as f:
        f.write(data)
    print(f"  wrote {path} ({len(data):,} bytes)")


def make_base(size: int = 8192) -> bytes:
    """Simulate a binary: PE-like header, code section, data section.

    Raises ValueError for sizes below 2048 bytes, where the fixed header and
    string sections would not fit alongside the code section.
    """
    if size < 2048:
        raise ValueError("size must be at least 2048 bytes")
    header = b"MZ" + bytes([0x90, 0x00, 0x03, 0x00]) + bytes(58)
    code_ops = [0x55, 0x89, 0xe5, 0x83, 0xec, 0x10, 0x8b, 0x45,
                0xfc, 0x29, 0xc4, 0xc3, 0x90, 0xeb, 0x0a, 0x74]
    code = bytes([rng.choice(code_ops) for _ in range(size // 2)])
    strings = b"kernel32.dll\x00VirtualAlloc\x00LoadLibraryA\x00" * 20
    padding = bytes(size - len(header) - len(code) - len(strings))
    return header + code + strings + padding


def mutate(data: bytes, mutation_rate: float = 0.05) -> bytes:
    """Apply random byte mutations to simulate a polymorphic variant."""
    arr = bytearray(data)
    for i in range(len(arr)):
        if rng.random() < mutation_rate:
            arr[i] = rng.randint(0, 255)
    return bytes(arr)


def embed(host: bytes, payload: bytes, offset: int | None = None) -> bytes:
    """Embed payload into host at the given offset (default: 1/3 into host)."""
    arr = bytearray(host)
    if offset is None:
        offset = len(host) // 3
    arr[offset:offset + len(payload)] = payload[:len(host) - offset]
    return bytes(arr)


def make_unrelated(size: int = 8192) -> bytes:
    """Different structure entirely: ELF-like header with high-entropy body."""
    header = b"\x7fELF" + bytes([2, 1, 1, 0]) + bytes(8) + struct.pack("<H", 2)
    body = bytes([rng.randint(0, 255) for _ in range(size - len(header))])
    return header + body


if __name__ == "__main__":
    os.makedirs("testdata", exist_ok=True)

    base = make_base(8192)
    write("testdata/base.bin", base)

    similar = mutate(base, mutation_rate=0.04)
    write("testdata/similar.bin", similar)

    unrelated = make_unrelated(8192)

    payload = base[1024:3072]
    embedded = embed(unrelated, payload, offset=4000)
    write("testdata/embedded.bin", embedded)

    write("testdata/unrelated.bin", unrelated)

    print("\nTest files ready in ./testdata/")
