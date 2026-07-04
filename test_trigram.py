#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Bill Halpin
"""
Regression tests for the trigram_index engine.

Run with:
  python3 -m unittest test_trigram.py -v

Each test writes deterministic binary fixtures to a temporary directory, so
the suite needs no external test data and produces the same results on every
run.
"""

import random
import tempfile
import unittest
from pathlib import Path

from trigram_index import TrigramIndex


class TrigramTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.rng = random.Random(1234)

    def tearDown(self):
        self._tmp.cleanup()

    def _file(self, name: str, data: bytes) -> Path:
        p = self.dir / name
        p.write_bytes(data)
        return p

    def _rand(self, n: int) -> bytes:
        return self.rng.randbytes(n)

    def _compare(self, data_a: bytes, data_b: bytes, **kwargs):
        a = TrigramIndex(self._file("a.bin", data_a)).build()
        b = TrigramIndex(self._file("b.bin", data_b)).build()
        return a.compare(b, **kwargs)


class TestIdenticalFiles(TrigramTestCase):
    def test_metrics_and_verdict(self):
        data = self._rand(8192)
        r = self._compare(data, data)
        self.assertEqual(r.jaccard, 1.0)
        self.assertEqual(r.verdict, "NEAR-IDENTICAL")

    def test_coverage_reaches_end_of_file(self):
        # Bug regression: the last window used to be excluded, leaving the
        # tail of file A unexamined even for identical files.
        data = self._rand(8192)
        r = self._compare(data, data, coverage_window=1024)
        self.assertTrue(r.coverage_segments)
        self.assertEqual(max(s.end_a for s in r.coverage_segments), 8192)

    def test_coverage_reaches_end_with_unaligned_size(self):
        # File size not a multiple of the step: tail window must still exist.
        data = self._rand(8000)
        r = self._compare(data, data, coverage_window=1024)
        self.assertTrue(r.coverage_segments)
        self.assertEqual(max(s.end_a for s in r.coverage_segments), 8000)

    def test_size_equal_to_window_produces_coverage(self):
        # Bug regression: size == window used to yield an empty range and
        # zero coverage segments for identical files.
        data = self._rand(1024)
        r = self._compare(data, data, coverage_window=1024)
        self.assertTrue(r.coverage_segments)

    def test_densities_never_exceed_one(self):
        # Bug regression: coverage density used to reach 1.002 because
        # trigrams straddling the window edge were counted.
        data = self._rand(8192)
        r = self._compare(data, data, coverage_window=1024)
        for seg in r.coverage_segments:
            # Identical files: every window matches fully, exactly 1.0
            self.assertEqual(seg.density, 1.0)
        for hs in r.hotspots:
            self.assertLessEqual(hs.trigram_count / hs.length, 1.0)


class TestHotspotHonesty(TrigramTestCase):
    def test_repeated_string_does_not_inflate_count(self):
        # Bug regression: a substring repeated in both files used to multiply
        # into offset pairs (150 reported "trigrams" from 76 shared positions).
        shared = b"kernel32.dll\x00VirtualAlloc\x00LoadLibraryA\x00" * 2  # 78 bytes
        a = self._rand(4000) + shared + self._rand(4000)
        b = self._rand(4000) + shared + self._rand(4000)
        r = self._compare(a, b)
        if r.hotspots:
            top = r.hotspots[0]
            # 78 shared bytes contain at most 76 trigram positions
            self.assertLessEqual(top.trigram_count, 76)


class TestCoverageSaturation(TrigramTestCase):
    def test_single_common_trigram_cannot_saturate(self):
        # Bug regression: a null-padded region in A used to report density
        # ~1.0 against a file that merely contained the null trigram once.
        a = self._rand(4096) + bytes(4096)          # half random, half nulls
        b = self._rand(8189) + bytes(3)             # one null trigram in B
        r = self._compare(a, b, coverage_window=1024, coverage_min_density=0.15)
        for seg in r.coverage_segments:
            # The null half of A must not be reported as covered by B
            self.assertLess(seg.start_a, 4096)


class TestHighFrequencySampling(TrigramTestCase):
    def test_repetitive_shared_block_still_registers(self):
        # Bug regression: trigrams with >10,000 offset pairs used to be
        # skipped outright, so a large repeated shared block (tiled pattern,
        # padding run, jump table) produced no hotspot at all.
        pattern = self._rand(16) * 256  # 4 KB: ~16 trigram values x 256 occurrences
        a = self._rand(2048) + pattern + self._rand(2048)
        b = self._rand(2048) + pattern + self._rand(2048)
        r = self._compare(a, b)
        self.assertGreater(r.sampled_trigrams, 0)
        self.assertTrue(r.hotspots, "repetitive shared block must produce a hotspot")

    def test_sampling_is_deterministic(self):
        pattern = self._rand(16) * 256
        a = self._rand(2048) + pattern + self._rand(2048)
        b = self._rand(2048) + pattern + self._rand(2048)
        r1 = self._compare(a, b)
        r2 = self._compare(a, b)
        self.assertEqual(
            [(h.offset_a, h.offset_b, h.trigram_count) for h in r1.hotspots],
            [(h.offset_a, h.offset_b, h.trigram_count) for h in r2.hotspots],
        )


class TestGridEquivalence(TrigramTestCase):
    def test_counter_grid_matches_set_based_reference(self):
        # The counter-based grid must produce cell counts identical to the
        # brute-force approach of collecting distinct A positions per cell.
        window = 256
        shared_block = self._rand(600)
        a = self._rand(1500) + shared_block + self._rand(1000)
        b = self._rand(800) + shared_block + self._rand(1700)
        pa, pb = self._file("ga.bin", a), self._file("gb.bin", b)
        ia, ib = TrigramIndex(pa).build(), TrigramIndex(pb).build()

        shared = [k for k in ia.keys() if len(ib.offsets(k)) > 0]

        reference: dict = {}
        for k in shared:
            offs_a, offs_b = ia.offsets(k), ib.offsets(k)
            if len(offs_a) * len(offs_b) > 10_000:
                continue  # keep the reference simple: fixture stays below the budget
            for oa in offs_a:
                for ob in offs_b:
                    reference.setdefault((oa // window, ob // window), set()).add(oa)

        hotspots, _ = ia._find_hotspots(ib, shared, window, min_density=0.05)
        expected = {
            (ca, cb): len(s) for (ca, cb), s in reference.items()
            if len(s) / window >= 0.05
        }
        actual = {
            (h.offset_a // window, h.offset_b // window): h.trigram_count
            for h in hotspots
        }
        # hotspots list is capped at 50; compare on the cells it reports
        for cell, count in actual.items():
            self.assertEqual(count, expected[cell])
        self.assertGreater(len(actual), 0)


class TestSegmentMerging(TrigramTestCase):
    def test_distinct_b_regions_stay_separate(self):
        # Bug regression: merging used to union B ranges of any A-overlapping
        # segments, so two adjacent A regions matching distant regions of B
        # collapsed into one segment spanning most of B.
        x = self._rand(2048)
        y = self._rand(2048)
        a = x + y                                  # A: X then Y, contiguous
        b = x + self._rand(16384) + y              # B: X ... 16KB gap ... Y
        r = self._compare(a, b, coverage_window=1024, coverage_min_density=0.5)
        self.assertGreaterEqual(len(r.coverage_segments), 2)
        for seg in r.coverage_segments:
            # No segment may span from the X match to the Y match in B
            self.assertLessEqual(seg.size_b, 8192)


class TestEmbeddedPayload(TrigramTestCase):
    def test_embedded_chunk_still_detected(self):
        # Behaviour guard: the main use case must survive the fixes.
        base = bytes(self.rng.choice(b"\x55\x89\xe5\x83\xec\x10\x8b\x45")
                     for _ in range(8192))
        payload = base[1024:3072]
        host = bytearray(self._rand(8192))
        host[4000:4000 + len(payload)] = payload
        r = self._compare(base, bytes(host))
        self.assertIn(r.verdict, ("EMBEDDED CONTENT LIKELY", "SHARED CODE REGION DETECTED"))
        self.assertTrue(r.hotspots)


class TestValidation(TrigramTestCase):
    def test_window_below_trigram_width_raises(self):
        data = self._rand(1024)
        with self.assertRaises(ValueError):
            self._compare(data, data, hotspot_window=0)
        with self.assertRaises(ValueError):
            self._compare(data, data, coverage_window=2)

    def test_non_positive_threshold_raises(self):
        data = self._rand(1024)
        with self.assertRaises(ValueError):
            self._compare(data, data, hotspot_min_density=0)


class TestIndexAccessors(TrigramTestCase):
    def test_offsets_returns_sorted_positions(self):
        p = self._file("x.bin", b"ABCABCABe")
        idx = TrigramIndex(p).build()
        self.assertEqual(idx.offsets(b"ABC"), [0, 3])
        self.assertEqual(idx.offsets(b"BCA"), [1, 4])
        self.assertEqual(idx.offsets(b"ZZZ"), [])
        self.assertEqual(idx.total_trigrams, 7)
        self.assertIsInstance(idx.offsets(b"ABC"), list)

    def test_cosine_matches_direct_computation(self):
        # The optimised cosine (shared-keys dot product, per-side magnitudes)
        # must equal the naive full-union formula.
        a_data = self._rand(4096) + bytes(512)
        b_data = self._rand(2048) + a_data[:2048]
        pa = self._file("ca.bin", a_data)
        pb = self._file("cb.bin", b_data)
        ia, ib = TrigramIndex(pa).build(), TrigramIndex(pb).build()
        r = ia.compare(ib)

        all_keys = ia.keys() | ib.keys()
        dot = mag_a = mag_b = 0.0
        for k in all_keys:
            fa, fb = len(ia.offsets(k)), len(ib.offsets(k))
            dot += fa * fb
            mag_a += fa * fa
            mag_b += fb * fb
        expected = dot / ((mag_a ** 0.5) * (mag_b ** 0.5))
        self.assertAlmostEqual(r.cosine, expected, places=12)


class TestTinyFiles(TrigramTestCase):
    def test_file_smaller_than_trigram(self):
        r = self._compare(b"ab", b"ab")
        self.assertEqual(r.jaccard, 0.0)
        self.assertEqual(r.verdict, "DISSIMILAR")
        self.assertEqual(r.hotspots, [])
        self.assertEqual(r.coverage_segments, [])


if __name__ == "__main__":
    unittest.main()
