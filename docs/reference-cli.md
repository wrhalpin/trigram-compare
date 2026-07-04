# Reference: CLI and Python API

## Command-line interface

```
python3 trigram_compare.py <file_a> <file_b> [options]
```

### Positional arguments

| Argument | Description |
|---|---|
| `file_a` | Path to the first binary file |
| `file_b` | Path to the second binary file |

### Options

| Option | Default | Description |
|---|---|---|
| `--json` | off | Print a JSON object to stdout instead of the formatted report |
| `--hotspots N` | 10 | Maximum number of hotspot rows to show in the table |
| `--coverage` / `--no-coverage` | on | Show or hide the coverage map section |
| `--window SIZE` | 256 | Window size in bytes used for both hotspot grid cells and the coverage map base unit. Coverage window is `4 × SIZE`. Must be at least 3. |
| `--threshold FLOAT` | 0.25 | Minimum trigram density (`count / window`) for a cell to become a hotspot. Coverage threshold is `0.6 × FLOAT`. Must be positive. |
| `--no-color` | off | Disable ANSI escape codes. Also disabled automatically when stdout is not a TTY. |

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Analysis completed (any verdict) |
| 1 | One or both input files not found |
| 2 | Invalid arguments (e.g. `--window` below 3, non-positive `--threshold`) |

### JSON output schema

```json
{
  "files": {
    "a": { "path": "string", "size": int, "total_trigrams": int, "unique_trigrams": int },
    "b": { "path": "string", "size": int, "total_trigrams": int, "unique_trigrams": int }
  },
  "metrics": {
    "jaccard": float,
    "cosine": float,
    "containment_a_in_b": float,
    "containment_b_in_a": float,
    "shared_trigrams": int,
    "unique_to_a": int,
    "unique_to_b": int
  },
  "verdict": "string",
  "sampled_trigrams": int,
  "hotspots": [
    { "offset_a": int, "offset_b": int, "length": int, "trigram_count": int, "density": float }
  ],
  "coverage_segments": [
    { "start_a": int, "end_a": int, "start_b": int, "end_b": int, "density": float }
  ],
  "elapsed_seconds": float
}
```

All float values are rounded to 6 decimal places (4 for per-hotspot density).

---

## Python API (`trigram_index` module)

### `TrigramIndex`

```python
TrigramIndex(path: str | Path)
```

**Methods**

`build() -> TrigramIndex`  
Reads the entire file into memory and builds the internal trigram index. Must be called before `compare()`. Returns `self` for chaining: `TrigramIndex(path).build()`.

`compare(other, hotspot_window=256, hotspot_min_density=0.25, coverage_window=1024, coverage_min_density=0.15) -> SimilarityReport`  
Compares this index to `other`. Calls `build()` on either index if not yet built. Raises `ValueError` if a window is smaller than 3 bytes or a density threshold is not positive.

`offsets(trigram: bytes | int) -> list[int]`  
Returns the sorted list of byte offsets where `trigram` occurs in the file. Accepts a 3-byte `bytes` object or a pre-packed `int`.

`keys() -> set[int]`  
Returns the set of all unique trigrams (as packed ints) in the file.

**Properties**

| Property | Type | Description |
|---|---|---|
| `path` | `Path` | Resolved file path |
| `size` | `int` | File size in bytes (set during `build()`) |
| `total_trigrams` | `int` | `max(0, size - 2)` — total number of trigrams including duplicates |
| `unique_trigrams` | `int` | Number of distinct trigrams |

---

### `SimilarityReport`

Dataclass returned by `TrigramIndex.compare()`.

| Field | Type | Description |
|---|---|---|
| `path_a`, `path_b` | `str` | Stringified file paths |
| `size_a`, `size_b` | `int` | File sizes in bytes |
| `total_trigrams_a/b` | `int` | Total (non-unique) trigram counts |
| `unique_trigrams_a/b` | `int` | Unique trigram counts |
| `shared_trigrams` | `int` | `\|keys_a ∩ keys_b\|` |
| `jaccard` | `float` | Set-based Jaccard similarity |
| `cosine` | `float` | Frequency-weighted cosine similarity |
| `containment_a_in_b` | `float` | `shared / unique_a` |
| `containment_b_in_a` | `float` | `shared / unique_b` |
| `hotspots` | `list[Hotspot]` | Sorted by `trigram_count` descending, capped at 50 |
| `coverage_segments` | `list[CoverageSegment]` | Sorted by `density` descending, capped at 20 |
| `sampled_trigrams` | `int` | Number of shared trigram values subsampled during hotspot analysis because their offset cross-product exceeded 10,000 pairs |
| `verdict` | `str` (property) | Classification string (see below) |

**Verdict thresholds** (evaluated in order):

| Condition | Verdict |
|---|---|
| `jaccard >= 0.85` | `NEAR-IDENTICAL` |
| `jaccard >= 0.50` | `HIGHLY SIMILAR` |
| `containment_a_in_b >= 0.70` or `containment_b_in_a >= 0.70` | `EMBEDDED CONTENT LIKELY` |
| `hotspots[0].trigram_count >= 64` and `trigram_count × 4 >= length` | `SHARED CODE REGION DETECTED` |
| `jaccard >= 0.15` | `MODERATE SIMILARITY` |
| `jaccard >= 0.05` | `LOW SIMILARITY` |
| otherwise | `DISSIMILAR` |

---

### `Hotspot`

| Field | Type | Description |
|---|---|---|
| `offset_a` | `int` | Start of the matching window in file A |
| `offset_b` | `int` | Start of the matching window in file B |
| `length` | `int` | Window size in bytes (equals `hotspot_window`) |
| `trigram_count` | `int` | Number of *distinct positions* in this A window whose trigram also occurs in the corresponding B window |

Density = `trigram_count / length`, always in `[0, 1]`. Repeated substrings do not inflate the count: each A position is counted once per cell regardless of how many B occurrences it matches.

Trigram values with more than 10,000 offset pairs are deterministically subsampled to 100 evenly-strided offsets per side, so heavily repeated shared content still registers — at reduced density. The number of subsampled values is reported in `sampled_trigrams`.

---

### `CoverageSegment`

| Field | Type | Description |
|---|---|---|
| `start_a`, `end_a` | `int` | Byte range in file A |
| `start_b`, `end_b` | `int` | Corresponding byte range in file B (median-anchored approximation) |
| `density` | `float` | Peak density within the merged segment, in `[0, 1]`. Multiset-based: each trigram occurrence in the A window matches at most as many occurrences as exist in B, so one common trigram value cannot saturate a window. |
| `size_a` | `int` (property) | `end_a - start_a` |
| `size_b` | `int` (property) | `end_b - start_b` |
