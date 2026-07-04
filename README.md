# trigram-compare

Binary file similarity analysis using 3-byte n-gram (trigram) indexing. Detects polymorphic variants, embedded payloads, and shared code regions between binary files — no format-specific parsing required.

## Quick start

```bash
python3 trigram_compare.py file_a.bin file_b.bin
```

No installation or dependencies beyond Python 3.10+.

## What it does

trigram-compare builds a trigram index for each file (every 3-byte sliding window and its byte offsets), then computes:

- **Jaccard similarity** — set overlap of unique trigrams
- **Cosine similarity** — frequency-weighted similarity
- **Containment** — asymmetric measure; detects when one file's content lives inside another
- **Hotspots** — specific byte ranges where the two files align most densely
- **Coverage map** — sliding-window view of match density across file A

A human-readable verdict summarizes the result: `NEAR-IDENTICAL`, `HIGHLY SIMILAR`, `EMBEDDED CONTENT LIKELY`, `SHARED CODE REGION DETECTED`, `MODERATE SIMILARITY`, `LOW SIMILARITY`, or `DISSIMILAR`.

## Usage

```
python3 trigram_compare.py <file_a> <file_b> [options]

Options:
  --json              Output raw JSON instead of formatted report
  --hotspots N        Show top N hotspots (default: 10)
  --no-coverage       Hide the coverage map section
  --window SIZE       Analysis window size in bytes (default: 256)
  --threshold FLOAT   Minimum hotspot density (default: 0.25)
  --no-color          Disable ANSI colors
```

### Examples

```bash
# Compare two firmware images
python3 trigram_compare.py fw_v1.bin fw_v2.bin

# Machine-readable output for scripting
python3 trigram_compare.py --json sample_a.bin sample_b.bin | jq '.verdict'

# Higher sensitivity for small embedded payloads
python3 trigram_compare.py --window 64 --threshold 0.15 host.bin shellcode.bin
```

### Python API

```python
from trigram_index import TrigramIndex

idx_a = TrigramIndex("sample_a.bin").build()
idx_b = TrigramIndex("sample_b.bin").build()

report = idx_a.compare(idx_b)
print(report.verdict, report.jaccard)
for hs in report.hotspots[:5]:
    print(hs)
```

## Test data

Generate synthetic binaries covering the main detection scenarios:

```bash
python3 gen_testdata.py
# Creates testdata/base.bin, similar.bin, embedded.bin, unrelated.bin
```

Run the regression tests (stdlib `unittest`, no test data required):

```bash
python3 -m unittest test_trigram.py -v
```

## Documentation

| Document | Description |
|---|---|
| [Tutorial: first comparison](docs/tutorial-first-comparison.md) | Hands-on walkthrough of all three similarity scenarios |
| [How-to: tune sensitivity](docs/how-to-tune-sensitivity.md) | Recipes for small payloads, large files, programmatic use |
| [Reference: CLI and API](docs/reference-cli.md) | All options, JSON schema, and Python API |
| [Explanation: how it works](docs/explanation-similarity-metrics.md) | Concepts behind trigrams, Jaccard, cosine, containment, and hotspots |

## License

Apache 2.0 — see [LICENSE](LICENSE).
