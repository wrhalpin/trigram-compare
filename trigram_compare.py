#!/usr/bin/env python3
"""
trigram_compare.py - CLI for binary file trigram similarity analysis.

Usage:
  python trigram_compare.py file_a file_b [options]

Options:
  --json              Output raw JSON report
  --hotspots N        Show top N hotspots (default: 10)
  --coverage          Show coverage map segments (default: on)
  --no-coverage       Hide coverage map
  --window SIZE       Hotspot/coverage window size in bytes (default: 256)
  --threshold FLOAT   Min density for hotspot detection (default: 0.25)
  --no-color          Disable ANSI colors
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from trigram_index import CoverageSegment, Hotspot, SimilarityReport, TrigramIndex

# ---------------------------------------------------------------------------
# ANSI color helpers
# ---------------------------------------------------------------------------

USE_COLOR = True


def _c(code: str, text: str) -> str:
    if not USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def red(t: str) -> str:     return _c("91", t)
def yellow(t: str) -> str:  return _c("93", t)
def green(t: str) -> str:   return _c("92", t)
def cyan(t: str) -> str:    return _c("96", t)
def bold(t: str) -> str:    return _c("1", t)
def dim(t: str) -> str:     return _c("2", t)
def magenta(t: str) -> str: return _c("95", t)
def blue(t: str) -> str:    return _c("94", t)

# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _bar(value: float, width: int = 40, color_fn=None) -> str:
    filled = round(value * width)
    bar = "█" * filled + "░" * (width - filled)
    pct = f" {value * 100:5.1f}%"
    if color_fn:
        bar = color_fn(bar)
    return f"[{bar}]{pct}"


def _verdict_color(verdict: str) -> str:
    if "IDENTICAL" in verdict or "HIGHLY" in verdict or "EMBEDDED" in verdict:
        return red(verdict)
    if "SHARED CODE" in verdict or "MODERATE" in verdict:
        return yellow(verdict)
    if "LOW" in verdict:
        return green(verdict)
    return dim(verdict)


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def render_report(
    report: SimilarityReport,
    show_hotspots: int = 10,
    show_coverage: bool = True,
) -> None:
    w = 70
    line = "─" * w

    print()
    print(bold(cyan("╔" + "═" * (w - 2) + "╗")))
    print(bold(cyan("║")) + bold(" TRIGRAM BINARY SIMILARITY REPORT").center(w - 2) + bold(cyan("║")))
    print(bold(cyan("╚" + "═" * (w - 2) + "╝")))
    print()

    print(bold("FILES"))
    print(f"  A  {cyan(report.path_a)}")
    print(
        f"     {dim(_human_size(report.size_a))}  •  "
        f"{dim(str(report.total_trigrams_a))} trigrams  •  "
        f"{dim(str(report.unique_trigrams_a))} unique"
    )
    print(f"  B  {cyan(report.path_b)}")
    print(
        f"     {dim(_human_size(report.size_b))}  •  "
        f"{dim(str(report.total_trigrams_b))} trigrams  •  "
        f"{dim(str(report.unique_trigrams_b))} unique"
    )
    print()
    print(line)

    print()
    print(f"  VERDICT  {_verdict_color(bold(report.verdict))}")
    print()
    print(line)

    print()
    print(bold("SIMILARITY METRICS"))
    print()

    def bar_color(v: float):
        if v >= 0.7:
            return red
        if v >= 0.4:
            return yellow
        return green

    print(f"  Jaccard (set overlap)    {_bar(report.jaccard, 38, bar_color(report.jaccard))}")
    print(f"  Cosine  (freq-weighted)  {_bar(report.cosine, 38, bar_color(report.cosine))}")
    print()
    print(f"  Containment A\u2192B          {_bar(report.containment_a_in_b, 38, bar_color(report.containment_a_in_b))}")
    print(f"  Containment B\u2192A          {_bar(report.containment_b_in_a, 38, bar_color(report.containment_b_in_a))}")
    print()
    print(f"  Shared unique trigrams:  {bold(str(report.shared_trigrams)):>8}")
    print(f"  Only in A:               {str(report.unique_trigrams_a - report.shared_trigrams):>8}")
    print(f"  Only in B:               {str(report.unique_trigrams_b - report.shared_trigrams):>8}")
    print()
    print(line)

    if report.hotspots and show_hotspots > 0:
        print()
        print(bold("HOTSPOTS") + dim(f"  (top {min(show_hotspots, len(report.hotspots))} dense matching regions)"))
        print()
        print(f"  {'#':>3}  {'Offset A':>10}  {'Offset B':>10}  {'~Size':>8}  {'Trigrams':>9}  {'Density':>8}")
        print(f"  {'─'*3}  {'─'*10}  {'─'*10}  {'─'*8}  {'─'*9}  {'─'*8}")
        for i, hs in enumerate(report.hotspots[:show_hotspots], 1):
            density = hs.trigram_count / hs.length
            dcol = red if density >= 0.5 else yellow if density >= 0.25 else dim
            print(
                f"  {i:>3}  "
                f"0x{hs.offset_a:08x}  "
                f"0x{hs.offset_b:08x}  "
                f"{_human_size(hs.length):>8}  "
                f"{hs.trigram_count:>9}  "
                f"{dcol(f'{density:.3f}'):>8}"
            )
        print()
        print(line)

    if report.coverage_segments and show_coverage:
        print()
        print(bold("COVERAGE MAP") + dim("  (matching regions between files)"))
        print()
        print(f"  {'#':>3}  {'A start':>10}  {'A end':>10}  {'B start':>10}  {'B end':>10}  {'Density':>8}")
        print(f"  {'─'*3}  {'─'*10}  {'─'*10}  {'─'*10}  {'─'*10}  {'─'*8}")
        for i, seg in enumerate(report.coverage_segments[:20], 1):
            dcol = red if seg.density >= 0.5 else yellow if seg.density >= 0.25 else dim
            print(
                f"  {i:>3}  "
                f"0x{seg.start_a:08x}  "
                f"0x{seg.end_a:08x}  "
                f"0x{seg.start_b:08x}  "
                f"0x{seg.end_b:08x}  "
                f"{dcol(f'{seg.density:.3f}'):>8}"
            )
        print()
        print(line)

    print()


def report_to_dict(report: SimilarityReport) -> dict:
    return {
        "files": {
            "a": {
                "path": report.path_a,
                "size": report.size_a,
                "total_trigrams": report.total_trigrams_a,
                "unique_trigrams": report.unique_trigrams_a,
            },
            "b": {
                "path": report.path_b,
                "size": report.size_b,
                "total_trigrams": report.total_trigrams_b,
                "unique_trigrams": report.unique_trigrams_b,
            },
        },
        "metrics": {
            "jaccard": round(report.jaccard, 6),
            "cosine": round(report.cosine, 6),
            "containment_a_in_b": round(report.containment_a_in_b, 6),
            "containment_b_in_a": round(report.containment_b_in_a, 6),
            "shared_trigrams": report.shared_trigrams,
            "unique_to_a": report.unique_trigrams_a - report.shared_trigrams,
            "unique_to_b": report.unique_trigrams_b - report.shared_trigrams,
        },
        "verdict": report.verdict,
        "hotspots": [
            {
                "offset_a": h.offset_a,
                "offset_b": h.offset_b,
                "length": h.length,
                "trigram_count": h.trigram_count,
                "density": round(h.trigram_count / h.length, 4),
            }
            for h in report.hotspots
        ],
        "coverage_segments": [
            {
                "start_a": s.start_a,
                "end_a": s.end_a,
                "start_b": s.start_b,
                "end_b": s.end_b,
                "density": round(s.density, 4),
            }
            for s in report.coverage_segments
        ],
    }

# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Binary file trigram similarity analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("file_a", help="First binary file")
    parser.add_argument("file_b", help="Second binary file")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument(
        "--hotspots", type=int, default=10, metavar="N",
        help="Number of hotspots to display (default: 10)",
    )
    parser.add_argument(
        "--coverage", action="store_true", default=True,
        help="Show coverage map (default: on)",
    )
    parser.add_argument("--no-coverage", dest="coverage", action="store_false")
    parser.add_argument(
        "--window", type=int, default=256, metavar="SIZE",
        help="Analysis window size in bytes (default: 256)",
    )
    parser.add_argument(
        "--threshold", type=float, default=0.25, metavar="FLOAT",
        help="Min density for hotspot (default: 0.25)",
    )
    parser.add_argument("--no-color", action="store_true", help="Disable colors")

    args = parser.parse_args()

    global USE_COLOR
    if args.no_color or not sys.stdout.isatty():
        USE_COLOR = False

    path_a = Path(args.file_a)
    path_b = Path(args.file_b)

    for p in (path_a, path_b):
        if not p.exists():
            print(red(f"Error: file not found: {p}"), file=sys.stderr)
            sys.exit(1)

    if not args.json:
        print(dim(f"  Indexing {path_a.name} ..."), end="\r")
    t0 = time.perf_counter()

    idx_a = TrigramIndex(path_a).build()

    if not args.json:
        print(dim(f"  Indexing {path_b.name} ..."), end="\r")

    idx_b = TrigramIndex(path_b).build()

    if not args.json:
        print(dim(f"  Comparing ...          "), end="\r")

    report = idx_a.compare(
        idx_b,
        hotspot_window=args.window,
        hotspot_min_density=args.threshold,
        coverage_window=args.window * 4,
        coverage_min_density=args.threshold * 0.6,
    )
    elapsed = time.perf_counter() - t0

    if args.json:
        d = report_to_dict(report)
        d["elapsed_seconds"] = round(elapsed, 3)
        print(json.dumps(d, indent=2))
    else:
        print(" " * 50, end="\r")
        render_report(report, show_hotspots=args.hotspots, show_coverage=args.coverage)
        print(dim(f"  Analysis completed in {elapsed:.3f}s"))
        print()


if __name__ == "__main__":
    main()
