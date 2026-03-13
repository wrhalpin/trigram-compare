#!/usr/bin/env python3
“””
Generate test binary files to demonstrate trigram comparison:

- base.bin         : a simulated binary with realistic byte distribution
- similar.bin      : base.bin with minor mutations (polymorphic variant)
- embedded.bin     : different file but with a chunk of base.bin embedded
- unrelated.bin    : completely different random-ish content
  “””

import os
import struct
import random

rng = random.Random(42)

def write(path, data: bytes):
with open(path, “wb”) as f:
f.write(data)
print(f”  wrote {path} ({len(data):,} bytes)”)

def make_base(size=8192) -> bytes:
“”“Simulate a binary: PE-like header, code section, data section.”””
# Fake MZ header
header = b”MZ” + bytes([0x90, 0x00, 0x03, 0x00]) + bytes(58)
# Fake code section: mostly low-entropy x86-ish opcodes
code_ops = [0x55, 0x89, 0xe5, 0x83, 0xec, 0x10, 0x8b, 0x45,
0xfc, 0x29, 0xc4, 0xc3, 0x90, 0xeb, 0x0a, 0x74]
code = bytes([rng.choice(code_ops) for _ in range(size // 2)])
# Data section: strings + nulls
strings = b”kernel32.dll\x00VirtualAlloc\x00LoadLibraryA\x00” * 20
padding = bytes(size - len(header) - len(code) - len(strings))
return header + code + strings + padding

def mutate(data: bytes, mutation_rate: float = 0.05) -> bytes:
“”“Apply random byte mutations (polymorphic variant).”””
arr = bytearray(data)
for i in range(len(arr)):
if rng.random() < mutation_rate:
arr[i] = rng.randint(0, 255)
return bytes(arr)

def embed(host: bytes, payload: bytes, offset: int = None) -> bytes:
“”“Embed payload into host at a given offset.”””
arr = bytearray(host)
if offset is None:
offset = len(host) // 3
arr[offset:offset + len(payload)] = payload[:len(host) - offset]
return bytes(arr)

def make_unrelated(size=8192) -> bytes:
“”“Different structure entirely: ELF-like with high entropy data.”””
header = b”\x7fELF” + bytes([2, 1, 1, 0]) + bytes(8) + struct.pack(”<H”, 2)
body = bytes([rng.randint(0, 255) for _ in range(size - len(header))])
return header + body

os.makedirs(“testdata”, exist_ok=True)

base = make_base(8192)
write(“testdata/base.bin”, base)

similar = mutate(base, mutation_rate=0.04)   # 4% mutations
write(“testdata/similar.bin”, similar)

unrelated = make_unrelated(8192)

# embed a 2KB chunk of base into unrelated

payload = base[1024:3072]
embedded = embed(unrelated, payload, offset=4000)
write(“testdata/embedded.bin”, embedded)

write(“testdata/unrelated.bin”, unrelated)

print(”\nTest files ready in ./testdata/”)