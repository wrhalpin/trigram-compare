# Tutorial: Your First Binary Comparison

This tutorial walks you through installing trigram-compare, generating test files, and running your first comparisons. By the end you will have seen all three similarity scenarios the tool detects and understand what the output means.

## Prerequisites

Python 3.10 or later. No third-party packages are required.

## Step 1 — Generate test binaries

The repository ships with a script that creates four synthetic binary files:

```bash
python3 gen_testdata.py
```

You should see:

```
  wrote testdata/base.bin (8,192 bytes)
  wrote testdata/similar.bin (8,192 bytes)
  wrote testdata/embedded.bin (8,192 bytes)
  wrote testdata/unrelated.bin (8,192 bytes)

Test files ready in ./testdata/
```

What each file contains:

| File | Description |
|---|---|
| `base.bin` | Simulated PE binary with x86-like opcodes and import strings |
| `similar.bin` | `base.bin` with 4 % of bytes randomly mutated — a polymorphic variant |
| `embedded.bin` | An ELF-like binary with a 2 KB chunk of `base.bin` spliced in at offset 4000 |
| `unrelated.bin` | Completely different, high-entropy random data |

## Step 2 — Compare the similar variant

```bash
python3 trigram_compare.py testdata/base.bin testdata/similar.bin
```

The report header identifies the files and their trigram statistics. Focus on the **VERDICT** and **SIMILARITY METRICS** sections:

```
  VERDICT  HIGHLY SIMILAR

SIMILARITY METRICS

  Jaccard (set overlap)    [███████████████████████████░░░░░░░░░░░]  70.2%
  Cosine  (freq-weighted)  [██████████████████████████████████████] 100.0%

  Containment A→B          [███████████████████████████████████░░░]  92.5%
  Containment B→A          [████████████████████████████░░░░░░░░░░]  74.4%
```

A Jaccard score above 50 % triggers **HIGHLY SIMILAR**. The high containment A→B (92.5 %) means almost all of `base.bin`'s trigrams appear somewhere in `similar.bin` — consistent with mutations that replace existing trigrams with new ones rather than adding large new regions.

The **HOTSPOTS** table shows the byte ranges where the two files align most densely. High density in overlapping windows is expected for files that are mostly the same.

## Step 3 — Find an embedded payload

```bash
python3 trigram_compare.py testdata/base.bin testdata/embedded.bin
```

This time the verdict changes:

```
  VERDICT  SHARED CODE REGION DETECTED
```

Jaccard is low (~18 %) because most of `embedded.bin` is random noise from `unrelated.bin`. But the **HOTSPOTS** table reveals several dense windows clustered around offset `0x0fa0` in file B (decimal 4000) — exactly where the payload was inserted. This is the primary use case: finding a known malware stub transplanted into a carrier file.

## Step 4 — Confirm two unrelated files

```bash
python3 trigram_compare.py testdata/base.bin testdata/unrelated.bin
```

```
  VERDICT  DISSIMILAR

  Jaccard (set overlap)    [░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░]   0.0%
```

Jaccard is effectively zero. The single shared trigram is statistical noise. No hotspots are reported.

## Step 5 — Try machine-readable output

Add `--json` for output you can pipe into `jq`, store, or feed to another tool:

```bash
python3 trigram_compare.py --json testdata/base.bin testdata/similar.bin | python3 -m json.tool
```

The JSON schema is documented in the [CLI reference](reference-cli.md).

## What's next

- Learn how to tune window size and threshold for your files: [How-to: tuning sensitivity](how-to-tune-sensitivity.md)
- Understand the math behind the metrics: [Explanation: similarity metrics](explanation-similarity-metrics.md)
- Full option reference: [CLI reference](reference-cli.md)
