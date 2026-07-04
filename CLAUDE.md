# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

`trigram-compare` detects structural similarity between binary files using 3-byte n-gram (trigram) analysis. It identifies polymorphic variants, embedded payloads, and shared code regions without requiring format-specific parsers.

## Running the Tool

```bash
# Basic comparison
python3 trigram_compare.py file_a file_b

# JSON output (pipeline-friendly)
python3 trigram_compare.py --json file_a file_b

# Tune sensitivity
python3 trigram_compare.py --window 512 --threshold 0.15 file_a file_b

# Generate synthetic test binaries (creates testdata/)
python3 gen_testdata.py

# Run the regression tests
python3 -m unittest test_trigram.py -v
```

There is no build step or linter configured. The project is pure Python stdlib — no packages to install. Tests live in `test_trigram.py` (stdlib `unittest`, self-contained fixtures with deterministic seeds).

## Architecture

Two modules; one is a pure library, the other is CLI glue:

**`trigram_index.py`** — engine and data model, no I/O side effects
- `TrigramIndex` — builds `dict[int, array('i')]` (trigram packed as 24-bit int → sorted byte offsets, 4 bytes each) from a single full read of the file. Call `.build()` then `.compare(other)`. Files are capped at 2 GiB so offsets fit 32 bits.
- `compare()` computes Jaccard, cosine, and containment scores, then delegates to `_find_hotspots()` and `_build_coverage_map()`.
- `_find_hotspots()` — grids all (offset_a, offset_b) pairs for shared trigrams into window-sized cells; dense cells become `Hotspot` objects. Counts *distinct A positions* per cell (density ≤ 1). Trigrams with >10,000 offset pairs are subsampled to 100 evenly-strided offsets per side (not skipped); the count of sampled trigrams surfaces as `SimilarityReport.sampled_trigrams`.
- `_build_coverage_map()` — slides a window over file A counting shared trigrams with multiset-min matching (each occurrence in the window matches at most as many occurrences as exist in B); produces `CoverageSegment` objects, then merges segments that overlap in A *and* map to consistent B ranges (within one window) via `_merge_coverage_segments()`. A final tail window is always flush with EOF.
- `SimilarityReport.verdict` — derived property that classifies the result using Jaccard and containment thresholds.

**`trigram_compare.py`** — CLI and rendering only, imports everything from `trigram_index`
- `render_report()` — pretty-prints the report with ANSI color
- `report_to_dict()` — serializes a `SimilarityReport` to a JSON-compatible dict
- `main()` — argument parsing, file validation, timing, output dispatch

**`gen_testdata.py`** — standalone script to generate `testdata/` with four synthetic binaries covering the main similarity scenarios (near-identical, embedded, dissimilar).

## Key Design Decisions

- Trigrams are stored as `int` keys (`(b0 << 16) | (b1 << 8) | b2`) rather than `bytes` for ~2× speed.
- Postings are `array('i')` rather than lists of boxed ints (~3× less RAM overall; ~17 bytes of RSS per input byte for structured binaries). `compare()` never materializes the key union — Jaccard uses inclusion–exclusion and cosine sums the dot product over the intersection only.
- `_build_coverage_map` uses the median of all matched B-offsets in a window to anchor the corresponding B-side range — this is an approximation, not an exact alignment.
- `coverage_window` defaults to `4 × hotspot_window`; `coverage_min_density` defaults to `0.6 × hotspot_min_density`. These ratios are baked into `main()`.
- Hotspots are capped at 50; coverage segments at 20. `verdict` reads only `hotspots[0]`.
