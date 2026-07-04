# Explanation: How Trigram Similarity Works

This document explains the concepts behind trigram-based binary comparison — what the metrics measure, why they complement each other, and where each one falls short on its own.

## What is a trigram?

A trigram is any sequence of three consecutive bytes. A file of N bytes contains exactly N − 2 trigrams (with repetition). For example, the four-byte sequence `\x55\x89\xe5\x83` contains two trigrams: `\x55\x89\xe5` and `\x89\xe5\x83`.

Unlike text analysis (where trigrams are three characters), binary trigrams treat every byte value equally. There are 2²⁴ = 16,777,216 possible trigrams.

The trigram index maps each trigram to all the byte offsets in the file where it appears. Low-entropy files (code sections, structured data) have many repeated trigrams. High-entropy files (compressed archives, encrypted payloads) have almost all unique trigrams — each of the 2²⁴ possible values appears roughly once.

## Why trigrams for binary similarity?

Format-agnostic: the approach works on any byte sequence regardless of file type, compression, or architecture. There is no need to parse PE headers, disassemble instructions, or decompress.

Robust to small mutations: a single byte change destroys at most three consecutive trigrams (the three windows that contain the changed byte) but leaves the rest of the file's trigram set intact. A 5 % mutation rate therefore reduces Jaccard by roughly 5 %, not 100 %.

Efficient: the index is built in O(N) time and the set intersection that drives Jaccard is O(min(|A|, |B|)) with Python's built-in set operations.

## The three scalar metrics

### Jaccard similarity

```
Jaccard = |keys_A ∩ keys_B| / |keys_A ∪ keys_B|
```

Jaccard measures overall overlap between the two files' trigram *vocabularies* (unique trigrams only). It ranges from 0 (no shared trigrams) to 1 (identical trigram sets).

Strengths: intuitive, symmetric, robust to repetition within a single file.

Limitations: ignores how many times each trigram appears. Two files with identical trigram sets but very different frequency distributions will score Jaccard = 1.0.

### Cosine similarity

```
Cosine = (Σ freq_A(t) × freq_B(t)) / (‖freq_A‖ × ‖freq_B‖)
```

Cosine treats each file as a vector of trigram frequencies and computes the angle between the two vectors. It rewards files that have the same trigrams in similar proportions.

Strengths: sensitive to frequency distribution, not just presence/absence.

Limitations: a single highly-repeated trigram (e.g. `\x00\x00\x00` in a null-padded binary) can dominate the dot product and inflate the score.

### Containment

```
Containment A→B = |keys_A ∩ keys_B| / |keys_A|
Containment B→A = |keys_A ∩ keys_B| / |keys_B|
```

Containment is asymmetric. A→B measures "what fraction of A's unique trigrams appear somewhere in B". A score near 1.0 on A→B means A is a subset of B — file A's content is largely contained within file B.

Strengths: detects embedding relationships that Jaccard misses. If A is a 1 KB payload hidden inside B which is 100 KB of unrelated data, Jaccard will be tiny (~0.01) but containment A→B can be near 1.0.

Limitations: sensitive to file size ratio. A small file with low-entropy content will have high containment in almost any larger file just by chance.

## Hotspots and coverage map

The scalar metrics summarize the whole file. The spatial analysis answers a different question: *where* in the two files do the shared trigrams cluster?

### Hotspots (local alignment)

For each shared trigram, every (offset_in_A, offset_in_B) pair is bucketed into a grid cell of size `window × window`. A dense cell means the same trigrams appear at similar relative positions in both files — a sign of copied or transplanted code.

Each cell counts *distinct A positions* that matched, not raw offset pairs. This matters for repeated content: if a string occurs twice in each file, every one of its trigrams produces four offset pairs, but each A position is still only counted once. Density is `count / window` and always falls in [0, 1]; the default threshold of 0.25 means at least one matched position per 4 bytes across the window.

High-frequency trigrams (more than 10,000 offset combinations) are skipped to prevent O(n²) blowup. This means very common byte patterns like `\x00\x00\x00` do not contribute to hotspots even if they are theoretically shared.

### Coverage map (file-A perspective)

The coverage map slides a window over file A and asks: "what fraction of the trigrams in this window appear anywhere in file B?" It is a coarser, one-dimensional view compared to hotspots. A final window is always placed flush with the end of file A, so the tail is examined even when the file size is not a multiple of the step.

Matching is multiset-based: each trigram occurrence in the window can match at most as many occurrences as exist in all of B. Without this rule, a single common trigram value — a null run in A matched against one incidental null trigram in B — would saturate the window and report a full-density "match" between dissimilar files.

The B-side position reported for each segment is an approximation: the median offset of all B-side occurrences of the shared trigrams. For an exactly aligned region this median converges to the true alignment offset; for scattered matches it is less precise.

Overlapping windows are merged into a single segment only when their B ranges are also consistent (within one window of each other). Adjacent A windows that match two distant regions of B stay separate segments — unioning their B ranges would fabricate a span covering everything in between.

## Verdict logic

The verdict is a convenience classification. The thresholds are heuristics tuned for typical malware analysis scenarios:

- **NEAR-IDENTICAL** / **HIGHLY SIMILAR**: global Jaccard dominates; the files are structurally the same.
- **EMBEDDED CONTENT LIKELY**: asymmetric containment signals that one file's content lives inside the other.
- **SHARED CODE REGION DETECTED**: Jaccard is low but the top hotspot has at least 64 matched positions covering at least a quarter of its window — a localized match in otherwise different files. The quarter-window requirement scales the check with `--window`, so a fixed 64 matches is not treated as significant inside a large window. Windows smaller than 256 bytes cannot trigger this verdict.
- **MODERATE / LOW / DISSIMILAR**: falling-through levels of the Jaccard scale.

Because verdicts are evaluated in order, a file pair can only receive one label even if multiple conditions are true. When building automated pipelines, inspect the raw metrics rather than relying solely on the verdict string.

## Limitations

**Encryption and compression**: high-entropy content produces near-unique trigrams. Two compressed archives of the same plaintext will score DISSIMILAR.

**Obfuscation by insertion**: inserting large amounts of new content between shared sections reduces Jaccard but the shared hotspots remain visible. Use hotspot density rather than Jaccard to detect this pattern.

**Very small files**: files under ~300 bytes have fewer than 256 trigrams total. The hotspot grid will have at most one populated cell regardless of content.

**Incidental trigram sharing**: some trigrams (especially null runs, common instruction prefixes) occur in almost every binary. The hotspot algorithm already skips the most degenerate cases; the rest contribute noise at low density levels.
