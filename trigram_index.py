“””
trigram_index.py — Core trigram analysis engine for binary file comparison.
Detects embedded code, polymorphism, and structural similarity via 3-byte ngrams.
“””

from **future** import annotations
import mmap
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator

# —————————————————————————

# Data structures

# —————————————————————————

@dataclass
class Hotspot:
“”“A region where two files share a dense cluster of matching trigrams.”””
offset_a: int
offset_b: int
length: int          # approximate span in bytes
trigram_count: int   # number of shared trigrams in this cluster

```
def __repr__(self) -> str:
    return (
        f"Hotspot(A=0x{self.offset_a:08x}, B=0x{self.offset_b:08x}, "
        f"~{self.length}B, {self.trigram_count} trigrams)"
    )
```

@dataclass
class CoverageSegment:
“”“A contiguous byte range in one file matched to a range in another.”””
start_a: int
end_a: int
start_b: int
end_b: int
density: float   # shared trigrams / possible trigrams in window

```
@property
def size_a(self) -> int:
    return self.end_a - self.start_a

@property
def size_b(self) -> int:
    return self.end_b - self.start_b
```

@dataclass
class SimilarityReport:
path_a: str
path_b: str
size_a: int
size_b: int
total_trigrams_a: int
total_trigrams_b: int
unique_trigrams_a: int
unique_trigrams_b: int
shared_trigrams: int          # unique trigrams present in both
jaccard: float                # |A ∩ B| / |A ∪ B|  (set-based)
cosine: float                 # frequency-weighted similarity
containment_a_in_b: float     # what fraction of A’s trigrams appear in B
containment_b_in_a: float     # what fraction of B’s trigrams appear in A
hotspots: list[Hotspot] = field(default_factory=list)
coverage_segments: list[CoverageSegment] = field(default_factory=list)

```
# Derived verdict
@property
def verdict(self) -> str:
    j = self.jaccard
    ca = self.containment_a_in_b
    cb = self.containment_b_in_a
    if j >= 0.85:
        return "NEAR-IDENTICAL"
    if j >= 0.50:
        return "HIGHLY SIMILAR"
    if ca >= 0.70 or cb >= 0.70:
        return "EMBEDDED CONTENT LIKELY"
    if self.hotspots:
        top = self.hotspots[0]
        if top.trigram_count >= 64:
            return "SHARED CODE REGION DETECTED"
    if j >= 0.15:
        return "MODERATE SIMILARITY"
    if j >= 0.05:
        return "LOW SIMILARITY"
    return "DISSIMILAR"
```

# —————————————————————————

# Index builder

# —————————————————————————

class TrigramIndex:
“””
Builds a trigram index for a binary file using memory-mapped I/O.
index: dict[bytes, list[int]]  — trigram -> sorted list of byte offsets
“””

```
def __init__(self, path: str | Path) -> None:
    self.path = Path(path)
    self.size: int = 0
    # trigram (3 bytes as int for speed) -> offsets
    self._index: dict[int, list[int]] = defaultdict(list)
    self._built = False

# ------------------------------------------------------------------
# Build
# ------------------------------------------------------------------

def build(self) -> TrigramIndex:
    """Scan the file and populate the trigram index."""
    self.size = os.path.getsize(self.path)
    if self.size < 3:
        self._built = True
        return self

    with open(self.path, "rb") as fh:
        with mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            data = mm[:]   # read all bytes into memory as bytes object

    # Sliding window — convert each 3-byte window to a single int key
    # for ~2x speed vs storing bytes objects as keys
    for i in range(len(data) - 2):
        key = (data[i] << 16) | (data[i + 1] << 8) | data[i + 2]
        self._index[key].append(i)

    self._built = True
    return self

# ------------------------------------------------------------------
# Accessors
# ------------------------------------------------------------------

@property
def total_trigrams(self) -> int:
    return max(0, self.size - 2)

@property
def unique_trigrams(self) -> int:
    return len(self._index)

def offsets(self, trigram: bytes | int) -> list[int]:
    if isinstance(trigram, bytes):
        key = (trigram[0] << 16) | (trigram[1] << 8) | trigram[2]
    else:
        key = trigram
    return self._index.get(key, [])

def keys(self) -> set[int]:
    return set(self._index.keys())

# ------------------------------------------------------------------
# Comparison
# ------------------------------------------------------------------

def compare(self, other: TrigramIndex,
            hotspot_window: int = 256,
            hotspot_min_density: float = 0.25,
            coverage_window: int = 1024,
            coverage_min_density: float = 0.15) -> SimilarityReport:
    """
    Full comparison between this index and another.
    Returns a SimilarityReport with all metrics.
    """
    if not self._built:
        self.build()
    if not other._built:
        other.build()

    keys_a = self.keys()
    keys_b = other.keys()

    intersection = keys_a & keys_b
    union = keys_a | keys_b

    shared = len(intersection)
    jaccard = shared / len(union) if union else 0.0
    containment_ab = shared / len(keys_a) if keys_a else 0.0
    containment_ba = shared / len(keys_b) if keys_b else 0.0

    # Cosine similarity using frequency vectors
    cosine = self._cosine_similarity(other, intersection)

    hotspots = self._find_hotspots(other, intersection, hotspot_window, hotspot_min_density)
    coverage = self._build_coverage_map(other, intersection, coverage_window, coverage_min_density)

    return SimilarityReport(
        path_a=str(self.path),
        path_b=str(other.path),
        size_a=self.size,
        size_b=other.size,
        total_trigrams_a=self.total_trigrams,
        total_trigrams_b=other.total_trigrams,
        unique_trigrams_a=len(keys_a),
        unique_trigrams_b=len(keys_b),
        shared_trigrams=shared,
        jaccard=jaccard,
        cosine=cosine,
        containment_a_in_b=containment_ab,
        containment_b_in_a=containment_ba,
        hotspots=hotspots,
        coverage_segments=coverage,
    )

# ------------------------------------------------------------------
# Internal metric helpers
# ------------------------------------------------------------------

def _cosine_similarity(self, other: TrigramIndex, shared_keys: set[int]) -> float:
    if not shared_keys:
        return 0.0

    dot = 0.0
    mag_a = 0.0
    mag_b = 0.0

    all_keys = self.keys() | other.keys()
    for k in all_keys:
        fa = len(self._index.get(k, []))
        fb = len(other._index.get(k, []))
        dot += fa * fb
        mag_a += fa * fa
        mag_b += fb * fb

    denom = (mag_a ** 0.5) * (mag_b ** 0.5)
    return dot / denom if denom else 0.0

def _find_hotspots(self, other: TrigramIndex, shared_keys: set[int],
                   window: int, min_density: float) -> list[Hotspot]:
    """
    For each shared trigram, pair offsets from A and B and bucket them
    into (offset_a // window, offset_b // window) grid cells.
    Dense cells are reported as hotspots.
    """
    if not shared_keys:
        return []

    grid: dict[tuple[int, int], int] = defaultdict(int)

    for k in shared_keys:
        offsets_a = self._index[k]
        offsets_b = other._index[k]
        # To avoid O(n²), sample if too many matches (common bytes like 0x00)
        if len(offsets_a) * len(offsets_b) > 10_000:
            continue
        for oa in offsets_a:
            for ob in offsets_b:
                cell = (oa // window, ob // window)
                grid[cell] += 1

    # Convert to Hotspot objects; filter by density
    hotspots: list[Hotspot] = []
    for (ca, cb), count in grid.items():
        density = count / window
        if density >= min_density:
            hotspots.append(Hotspot(
                offset_a=ca * window,
                offset_b=cb * window,
                length=window,
                trigram_count=count,
            ))

    hotspots.sort(key=lambda h: h.trigram_count, reverse=True)
    return hotspots[:50]  # cap output

def _build_coverage_map(self, other: TrigramIndex, shared_keys: set[int],
                        window: int, min_density: float) -> list[CoverageSegment]:
    """
    Slide a window over file A and compute what fraction of its trigrams
    appear anywhere in file B. High-density windows become segments.
    """
    if not shared_keys or self.size < window:
        return []

    segments: list[CoverageSegment] = []
    step = window // 2

    for start_a in range(0, self.size - window, step):
        end_a = start_a + window
        # Collect trigrams in this window of A
        window_keys = set()
        for i in range(start_a, min(end_a - 2, self.size - 2)):
            d = self._index
            # find keys that start in this window
            pass

        # Faster approach: check shared keys whose offsets fall in window
        local_shared = 0
        local_total = 0
        best_b_offsets: list[int] = []

        for k in shared_keys:
            a_offs = [o for o in self._index.get(k, []) if start_a <= o < end_a]
            if a_offs:
                local_shared += len(a_offs)
                best_b_offsets.extend(other._index.get(k, []))
            local_total += len([o for o in self._index.get(k, []) if start_a <= o < end_a])

        # Count total trigrams in window
        total_in_window = max(1, end_a - start_a - 2)
        density = local_shared / total_in_window

        if density >= min_density and best_b_offsets:
            best_b_offsets.sort()
            mid_b = best_b_offsets[len(best_b_offsets) // 2]
            segments.append(CoverageSegment(
                start_a=start_a,
                end_a=end_a,
                start_b=max(0, mid_b - window // 2),
                end_b=min(other.size, mid_b + window // 2),
                density=density,
            ))

    # Merge overlapping segments
    segments.sort(key=lambda s: s.start_a)
    merged = _merge_coverage_segments(segments)
    merged.sort(key=lambda s: s.density, reverse=True)
    return merged[:20]
```

def _merge_coverage_segments(segs: list[CoverageSegment]) -> list[CoverageSegment]:
if not segs:
return []
result = [segs[0]]
for s in segs[1:]:
prev = result[-1]
if s.start_a <= prev.end_a:
# merge
result[-1] = CoverageSegment(
start_a=prev.start_a,
end_a=max(prev.end_a, s.end_a),
start_b=min(prev.start_b, s.start_b),
end_b=max(prev.end_b, s.end_b),
density=max(prev.density, s.density),
)
else:
result.append(s)
return result