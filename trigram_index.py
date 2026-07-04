# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Bill Halpin

"""
trigram_index.py - Core trigram analysis engine for binary file comparison.
Detects embedded code, polymorphism, and structural similarity via 3-byte ngrams.
"""

from __future__ import annotations

import os
from array import array
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Hotspot:
    """A region where two files share a dense cluster of matching trigrams."""

    offset_a: int
    offset_b: int
    length: int         # approximate span in bytes
    trigram_count: int  # number of shared trigrams in this cluster

    def __repr__(self) -> str:
        return (
            f"Hotspot(A=0x{self.offset_a:08x}, B=0x{self.offset_b:08x}, "
            f"~{self.length}B, {self.trigram_count} trigrams)"
        )


@dataclass
class CoverageSegment:
    """A contiguous byte range in one file matched to a range in another."""

    start_a: int
    end_a: int
    start_b: int
    end_b: int
    density: float  # shared trigrams / possible trigrams in window

    @property
    def size_a(self) -> int:
        return self.end_a - self.start_a

    @property
    def size_b(self) -> int:
        return self.end_b - self.start_b


@dataclass
class SimilarityReport:
    """Complete similarity analysis between two binary files."""

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
    containment_a_in_b: float     # what fraction of A's trigrams appear in B
    containment_b_in_a: float     # what fraction of B's trigrams appear in A
    hotspots: list[Hotspot] = field(default_factory=list)
    coverage_segments: list[CoverageSegment] = field(default_factory=list)
    # Shared trigram values whose offsets were subsampled during hotspot
    # analysis because they exceeded the pair budget (see _find_hotspots)
    sampled_trigrams: int = 0

    @property
    def verdict(self) -> str:
        """Classify the comparison result as a human-readable verdict string.

        Thresholds are evaluated in order; the first match wins:
          jaccard >= 0.85  -> NEAR-IDENTICAL
          jaccard >= 0.50  -> HIGHLY SIMILAR
          containment >= 0.70 (either direction) -> EMBEDDED CONTENT LIKELY
          hotspots[0] has >= 64 matched positions covering >= 1/4 of its
            window -> SHARED CODE REGION DETECTED
          jaccard >= 0.15  -> MODERATE SIMILARITY
          jaccard >= 0.05  -> LOW SIMILARITY
          otherwise        -> DISSIMILAR

        The shared-code check scales with window size so that 64 matches in
        a 256-byte window and 256 matches in a 1024-byte window carry the
        same weight; windows smaller than 256 bytes cannot trigger it.
        """
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
            if top.trigram_count >= 64 and top.trigram_count * 4 >= top.length:
                return "SHARED CODE REGION DETECTED"
        if j >= 0.15:
            return "MODERATE SIMILARITY"
        if j >= 0.05:
            return "LOW SIMILARITY"
        return "DISSIMILAR"


# Hotspot analysis bounds the work done per shared trigram: values whose
# offset cross-product exceeds the budget are subsampled to CAP evenly-strided
# offsets per side (CAP² == budget, so sampled trigrams stay within it).
_HOTSPOT_PAIR_BUDGET = 10_000
_HOTSPOT_SAMPLE_CAP = 100


def _sample_offsets(offs: Sequence[int], cap: int = _HOTSPOT_SAMPLE_CAP) -> Sequence[int]:
    """Deterministically subsample *offs* to at most *cap* evenly-strided entries."""
    n = len(offs)
    if n <= cap:
        return offs
    stride = n / cap
    return [offs[int(i * stride)] for i in range(cap)]


class TrigramIndex:
    """
    Builds a trigram index for a binary file.

    The file is read fully into memory during build(). Internally stores
    dict[int, array('i')]: trigram (3 bytes packed as int) -> sorted byte
    offsets in a compact 4-byte-per-entry array. Using int keys is ~2x
    faster than bytes keys; array postings use ~9x less memory than lists
    of boxed ints. Files are limited to 2 GiB so offsets fit 32 bits.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.size: int = 0
        self._index: dict[int, array] = defaultdict(lambda: array("i"))
        self._built = False

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> TrigramIndex:
        """Scan the file and populate the trigram index.

        Raises:
            ValueError: If the file exceeds 2 GiB (offsets are stored as
                32-bit ints).
        """
        self.size = os.path.getsize(self.path)
        if self.size > 2**31 - 1:
            raise ValueError("files larger than 2 GiB are not supported")
        if self.size < 3:
            self._built = True
            return self

        with open(self.path, "rb") as fh:
            data = fh.read()

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
        """Total trigram count including duplicates; equals max(0, size - 2)."""
        return max(0, self.size - 2)

    @property
    def unique_trigrams(self) -> int:
        """Number of distinct 3-byte sequences observed in the file."""
        return len(self._index)

    def offsets(self, trigram: bytes | int) -> list[int]:
        """Return all byte offsets where *trigram* occurs.

        *trigram* may be a 3-byte ``bytes`` object or a pre-packed 24-bit int
        ``(b0 << 16) | (b1 << 8) | b2``.  Returns an empty list if the trigram
        is not present.
        """
        if isinstance(trigram, bytes):
            key = (trigram[0] << 16) | (trigram[1] << 8) | trigram[2]
        else:
            key = trigram
        return list(self._index.get(key, ()))

    def keys(self) -> set[int]:
        """Return the set of all unique trigrams in the file as packed 24-bit ints."""
        return set(self._index.keys())

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------

    def compare(
        self,
        other: TrigramIndex,
        hotspot_window: int = 256,
        hotspot_min_density: float = 0.25,
        coverage_window: int = 1024,
        coverage_min_density: float = 0.15,
    ) -> SimilarityReport:
        """Full comparison between this index and another. Returns a SimilarityReport.

        Raises:
            ValueError: If a window is smaller than 3 bytes (a trigram cannot
                fit) or a density threshold is not positive.
        """
        if hotspot_window < 3 or coverage_window < 3:
            raise ValueError("window sizes must be at least 3 bytes (trigram width)")
        if hotspot_min_density <= 0 or coverage_min_density <= 0:
            raise ValueError("density thresholds must be positive")

        if not self._built:
            self.build()
        if not other._built:
            other.build()

        # Dict views support set ops directly; the union is never
        # materialized (|A ∪ B| = |A| + |B| - |A ∩ B|)
        keys_a = self._index.keys()
        keys_b = other._index.keys()

        intersection = keys_a & keys_b

        shared = len(intersection)
        union_size = len(keys_a) + len(keys_b) - shared
        jaccard = shared / union_size if union_size else 0.0
        containment_ab = shared / len(keys_a) if keys_a else 0.0
        containment_ba = shared / len(keys_b) if keys_b else 0.0

        cosine = self._cosine_similarity(other, intersection)
        hotspots, sampled = self._find_hotspots(other, intersection, hotspot_window, hotspot_min_density)
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
            sampled_trigrams=sampled,
        )

    # ------------------------------------------------------------------
    # Internal metric helpers
    # ------------------------------------------------------------------

    def _cosine_similarity(self, other: TrigramIndex, shared_keys: set[int]) -> float:
        """Compute frequency-weighted cosine similarity over the full trigram vocabulary.

        Treats each file as a vector of trigram occurrence counts and returns
        the normalised dot product. Keys outside the intersection contribute
        zero to the dot product, so it is summed over *shared_keys* only;
        each magnitude iterates its own side once. Mathematically identical
        to iterating the full union, without materializing it. Returns 0.0
        when there are no shared trigrams or either file is empty.
        """
        if not shared_keys:
            return 0.0

        dot = 0.0
        for k in shared_keys:
            dot += len(self._index[k]) * len(other._index[k])

        mag_a = sum(len(v) ** 2 for v in self._index.values())
        mag_b = sum(len(v) ** 2 for v in other._index.values())

        denom = (mag_a ** 0.5) * (mag_b ** 0.5)
        return dot / denom if denom else 0.0

    def _find_hotspots(
        self,
        other: TrigramIndex,
        shared_keys: set[int],
        window: int,
        min_density: float,
    ) -> tuple[list[Hotspot], int]:
        """
        Bucket (offset_a, offset_b) pairs for each shared trigram into a grid
        of window-sized cells. Dense cells become Hotspot objects.

        Each cell counts *distinct A positions* matched to that B cell, so a
        substring repeated in both files cannot inflate the count beyond the
        number of bytes actually shared, and density stays in [0, 1].

        High-frequency trigrams whose offset cross-product exceeds the pair
        budget are subsampled (evenly strided, deterministic) rather than
        skipped, so heavily repeated shared content still registers in the
        grid — at reduced density. Returns (hotspots, sampled_count) where
        sampled_count is the number of trigram values that were subsampled.
        """
        if not shared_keys:
            return [], 0

        grid: dict[tuple[int, int], set[int]] = defaultdict(set)
        sampled = 0

        for k in shared_keys:
            offsets_a = self._index[k]
            offsets_b = other._index[k]
            # Bound the per-trigram work for high-frequency values
            # (e.g. 0x000000) to avoid O(n²) blowup
            if len(offsets_a) * len(offsets_b) > _HOTSPOT_PAIR_BUDGET:
                sampled += 1
                offsets_a = _sample_offsets(offsets_a)
                offsets_b = _sample_offsets(offsets_b)
            for oa in offsets_a:
                for ob in offsets_b:
                    grid[(oa // window, ob // window)].add(oa)

        hotspots: list[Hotspot] = []
        for (ca, cb), matched in grid.items():
            count = len(matched)
            if count / window >= min_density:
                hotspots.append(Hotspot(
                    offset_a=ca * window,
                    offset_b=cb * window,
                    length=window,
                    trigram_count=count,
                ))

        hotspots.sort(key=lambda h: h.trigram_count, reverse=True)
        return hotspots[:50], sampled

    def _build_coverage_map(
        self,
        other: TrigramIndex,
        shared_keys: set[int],
        window: int,
        min_density: float,
    ) -> list[CoverageSegment]:
        """
        Slide a window over file A and compute what fraction of its trigrams
        appear anywhere in file B. High-density windows become CoverageSegments.

        Matching is multiset-based: each trigram occurrence in the window can
        match at most as many occurrences as exist in all of B, so a single
        common trigram value (e.g. a null run) cannot saturate the window.
        Density is therefore always in [0, 1].

        Runs in time linear in file size: a per-offset key table is built
        once, so each window scans only its own byte range instead of every
        shared key's full offset list.
        """
        if not shared_keys or self.size < window:
            return []

        # Per-offset table of shared trigram keys (-1 = trigram not shared)
        # and B-side occurrence counts, built once up front. array('i') keeps
        # this at 4 bytes per file byte instead of an 8-byte pointer per slot.
        key_at = array("i", b"\xff\xff\xff\xff" * self.total_trigrams)
        for k in shared_keys:
            for o in self._index[k]:
                key_at[o] = k
        b_count = {k: len(other._index[k]) for k in shared_keys}

        segments: list[CoverageSegment] = []
        step = window // 2

        # Window starts at every `step`, plus a final window flush with EOF so
        # the tail of the file is always examined (size == window gives one
        # window at offset 0)
        last_start = self.size - window
        starts = list(range(0, last_start + 1, step))
        if starts[-1] != last_start:
            starts.append(last_start)

        for start_a in starts:
            end_a = start_a + window
            # Only positions whose full trigram fits inside the window
            trigram_end = end_a - 2

            counts: dict[int, int] = defaultdict(int)
            for o in range(start_a, trigram_end):
                k = key_at[o]
                if k >= 0:
                    counts[k] += 1

            if not counts:
                continue

            local_shared = sum(min(c, b_count[k]) for k, c in counts.items())
            total_in_window = max(1, window - 2)
            density = local_shared / total_in_window

            if density >= min_density:
                best_b_offsets: list[int] = []
                for k in counts:
                    best_b_offsets.extend(other._index[k])
                best_b_offsets.sort()
                mid_b = best_b_offsets[len(best_b_offsets) // 2]
                segments.append(CoverageSegment(
                    start_a=start_a,
                    end_a=end_a,
                    start_b=max(0, mid_b - window // 2),
                    end_b=min(other.size, mid_b + window // 2),
                    density=density,
                ))

        segments.sort(key=lambda s: s.start_a)
        merged = _merge_coverage_segments(segments, max_b_gap=window)
        merged.sort(key=lambda s: s.density, reverse=True)
        return merged[:20]


def _merge_coverage_segments(
    segs: list[CoverageSegment], max_b_gap: int
) -> list[CoverageSegment]:
    """Merge CoverageSegments that overlap in A *and* map to consistent B ranges.

    Segments whose B ranges are separated by more than *max_b_gap* bytes are
    kept apart even when their A ranges overlap: adjacent A windows matching
    two distant regions of B are two distinct matches, and unioning their B
    ranges would fabricate a span covering everything in between.

    Expects *segs* sorted by ``start_a``. Merged segments keep the highest
    density of their parts.
    """
    if not segs:
        return []
    result = [segs[0]]
    for s in segs[1:]:
        prev = result[-1]
        b_consistent = (
            s.start_b <= prev.end_b + max_b_gap
            and s.end_b >= prev.start_b - max_b_gap
        )
        if s.start_a <= prev.end_a and b_consistent:
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
