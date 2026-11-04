"""Summarise the pilot log for your write-up.

    python pilot_report.py                  # reads PILOT_LOG_PATH or pilot_log.jsonl
    python pilot_report.py path/to/log.jsonl
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path


def load(path: Path) -> list:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def pct(part: int, whole: int) -> str:
    return f"{part} ({part / whole:.0%})" if whole else "0"


def main():
    default = os.getenv("PILOT_LOG_PATH", str(Path(__file__).parent / "pilot_log.jsonl"))
    path = Path(sys.argv[1] if len(sys.argv) > 1 else default)
    if not path.exists():
        print(f"No pilot log at {path} yet.")
        return
    rows = load(path)
    asks = [r for r in rows if r.get("event") in ("advise", "confirm")]
    ratings = [r for r in rows if r.get("event") == "feedback" and r.get("useful") is not None]
    n = len(asks)

    print(f"Pilot log: {path}")
    print(f"Consultations: {n}")
    if n:
        print(f"Dates: {asks[0].get('ts', '?')[:10]} to {asks[-1].get('ts', '?')[:10]}")
        outcomes = Counter(r.get("outcome") or r.get("status") for r in asks)
        print("\nOutcome")
        for k, v in outcomes.most_common():
            print(f"  {k}: {pct(v, n)}")
        print("\nLanguage")
        for k, v in Counter(r.get("language", "unknown") for r in asks).most_common():
            print(f"  {k}: {pct(v, n)}")
        print("\nAsked by")
        for k, v in Counter(r.get("input", "unknown") for r in asks).most_common():
            print(f"  {k}: {pct(v, n)}")
        print("\nProblems identified")
        for k, v in Counter(r.get("problem") for r in asks if r.get("problem")).most_common():
            print(f"  {k}: {v}")
    helpful = sum(1 for r in ratings if r.get("useful") is True)
    print(f"\nRatings: {len(ratings)}, helpful {pct(helpful, len(ratings))}")
    next_steps = [r for r in rows if r.get("event") == "feedback" and r.get("next_action")]
    if next_steps:
        print("\nWhat farmers did next")
        for r in next_steps:
            print(f"  {r.get('ref', '')} {r['next_action']}")


if __name__ == "__main__":
    main()
