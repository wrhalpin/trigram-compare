# How-to: Tune Detection Sensitivity

Sensitivity is controlled by two parameters: `--window` and `--threshold`. This guide shows how to adjust them for specific detection scenarios.

## Detect small embedded payloads

The default window (256 bytes) works well for payloads of several kilobytes. For shellcode stubs or small loaders (under 512 bytes), shrink the window so the grid cells capture the dense region:

```bash
python3 trigram_compare.py --window 64 --threshold 0.15 host.bin payload.bin
```

A smaller window increases resolution but also increases noise — lower `--threshold` compensates.

## Reduce false positives on compressed or encrypted data

Compressed and encrypted regions share trigrams by chance at a low rate. Raise both parameters to require stronger evidence:

```bash
python3 trigram_compare.py --window 512 --threshold 0.5 file_a.bin file_b.bin
```

## Compare very large files

For files over 100 MB, the inner loop in `_find_hotspots` can be slow if many low-entropy trigrams (e.g. `0x000000`) appear at thousands of offsets each. The implementation already skips trigrams whose cross-product exceeds 10,000 pairs. You can additionally raise `--window` to reduce grid resolution:

```bash
python3 trigram_compare.py --window 1024 firmware_a.bin firmware_b.bin
```

The coverage window is automatically set to `4 × --window`, so raising `--window` also coarsens coverage segments.

## Suppress the coverage map for faster output

Coverage map computation slides a window over the entire file A. Disable it when you only need the scalar metrics and hotspots:

```bash
python3 trigram_compare.py --no-coverage file_a.bin file_b.bin
```

## Use trigram-compare programmatically

Import `TrigramIndex` directly to avoid subprocess overhead in batch workflows:

```python
from trigram_index import TrigramIndex

idx_a = TrigramIndex("sample_a.bin").build()
idx_b = TrigramIndex("sample_b.bin").build()

report = idx_a.compare(
    idx_b,
    hotspot_window=128,
    hotspot_min_density=0.3,
    coverage_window=512,
    coverage_min_density=0.18,
)

print(report.verdict, report.jaccard)
for hs in report.hotspots[:5]:
    print(hs)
```

The `build()` step is the expensive one (linear in file size). Cache the `TrigramIndex` object if you are comparing one reference file against many candidates.

## Interpret the verdict programmatically

`SimilarityReport.verdict` is a plain string. For branching logic use the underlying metrics directly:

```python
if report.jaccard >= 0.5:
    # strong overall match
    ...
elif report.containment_a_in_b >= 0.7:
    # most of file A is inside file B
    ...
elif report.hotspots and report.hotspots[0].trigram_count >= 64:
    # a localized match region exists
    ...
```

See [Explanation: similarity metrics](explanation-similarity-metrics.md) for the meaning of each field.
