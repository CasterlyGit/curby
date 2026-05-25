"""curby stats — compute and display P50/P95 latency from curby.log.

Reads ~/.curby/curby.log (structured JSONL), computes per-session and
overall statistics, prints a formatted table, and appends one summary
row to ~/.curby/stats.jsonl.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOG_PATH = Path.home() / ".curby" / "curby.log"
STATS_PATH = Path.home() / ".curby" / "stats.jsonl"

LOOKBACK_DAYS = 30


def _percentile(data: list[float], p: int) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = max(0, math.ceil(len(s) * p / 100) - 1)
    return s[idx]


def _load_events(log_path: Path = LOG_PATH, days: int = LOOKBACK_DAYS) -> list[dict]:
    """Load quick_ask events from the JSONL log within the lookback window."""
    if not log_path.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    events = []
    try:
        with log_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("event") != "quick_ask":
                    continue
                try:
                    ts_str = entry.get("ts", "")
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                except Exception:
                    pass  # include entry if timestamp can't be parsed
                events.append(entry)
    except Exception as e:
        print(f"[curby stats] log read error: {e}", file=sys.stderr)
    return events


def compute_stats(events: list[dict], days: int = LOOKBACK_DAYS) -> dict:
    """Compute stats dict from a list of quick_ask events."""
    if not events:
        return {
            "days": days,
            "sessions": 0,
            "quick_asks": 0,
            "ttft_p50": None,
            "ttft_p95": None,
            "wall_clock_p50": None,
            "wall_clock_p95": None,
            "backend_counts": {},
            "avg_followups": 0.0,
        }

    ttft_samples = [e["ttft_ms"] for e in events if e.get("ttft_ms") is not None]
    wall_samples = [e["total_ms"] for e in events if e.get("total_ms") is not None]

    # Session count = unique calendar days with at least one quick_ask
    session_days: set[str] = set()
    for e in events:
        try:
            ts_str = e.get("ts", "")
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            session_days.add(ts.date().isoformat())
        except Exception:
            pass

    # Backend breakdown
    backend_counts: Counter = Counter()
    for e in events:
        b = e.get("backend", "unknown")
        backend_counts[b] += 1

    # Avg follow-ups per session: ratio of followup calls to non-followup (new) calls
    followup_count = sum(1 for e in events if e.get("was_followup"))
    non_followup = len(events) - followup_count
    avg_followups = (followup_count / non_followup) if non_followup > 0 else 0.0

    return {
        "days": days,
        "sessions": len(session_days),
        "quick_asks": len(events),
        "ttft_p50": int(_percentile(ttft_samples, 50)) if ttft_samples else None,
        "ttft_p95": int(_percentile(ttft_samples, 95)) if ttft_samples else None,
        "wall_clock_p50": int(_percentile(wall_samples, 50)) if wall_samples else None,
        "wall_clock_p95": int(_percentile(wall_samples, 95)) if wall_samples else None,
        "backend_counts": dict(backend_counts),
        "avg_followups": round(avg_followups, 1),
    }


def _backend_breakdown_str(counts: dict) -> str:
    total = sum(counts.values())
    if not total:
        return "—"
    parts = []
    for backend, n in sorted(counts.items(), key=lambda x: -x[1]):
        pct = int(round(100 * n / total))
        parts.append(f"{backend} {pct}%")
    return ", ".join(parts)


def print_stats(stats: dict) -> None:
    """Print a formatted stats table to stdout."""
    days = stats["days"]
    print(f"\ncurby stats (last {days} days)")
    print("─" * 41)

    def row(label: str, value: str) -> None:
        print(f" {label:<22} {value}")

    row("sessions", str(stats["sessions"]) if stats["sessions"] else "0")
    row("quick-asks", str(stats["quick_asks"]) if stats["quick_asks"] else "0")

    row("TTFT p50", f"{stats['ttft_p50']}ms" if stats["ttft_p50"] is not None else "—")
    row("TTFT p95", f"{stats['ttft_p95']}ms" if stats["ttft_p95"] is not None else "—")
    row("wall-clock p50", f"{stats['wall_clock_p50']}ms" if stats["wall_clock_p50"] is not None else "—")
    row("wall-clock p95", f"{stats['wall_clock_p95']}ms" if stats["wall_clock_p95"] is not None else "—")
    row("backend", _backend_breakdown_str(stats["backend_counts"]))
    row("avg follow-ups", f"{stats['avg_followups']} per session")
    print()


def save_summary(stats: dict, stats_path: Path = STATS_PATH) -> None:
    """Append one summary row to stats.jsonl. Never raises."""
    try:
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            **stats,
        }
        with stats_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"[curby stats] stats write failed: {e}", file=sys.stderr)


def run(args: list[str] | None = None) -> None:
    """Entry point for `curby stats`."""
    days = LOOKBACK_DAYS
    if args:
        for i, a in enumerate(args):
            if a == "--days" and i + 1 < len(args):
                try:
                    days = int(args[i + 1])
                except ValueError:
                    pass

    events = _load_events(days=days)
    stats = compute_stats(events, days=days)
    print_stats(stats)
    save_summary(stats)
