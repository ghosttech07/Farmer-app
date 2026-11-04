"""Check every knowledge-base treatment against the official CIB&RC rows in pesticides.db.

For each entry: the product must be registered for at least one of its crops against its pest, the dose per litre must
fall inside an official row's range, and the waiting period must not be shorter than that row's. Problems are listed;
`python audit_kb.py` prints the report, and the test suite fails on any problem.
"""
import re
import sys

import matcher
import registry


def _num(s):
    m = re.search(r"\d+(?:\.\d+)?", s or "")
    return float(m.group()) if m else None


def audit(kb=None):
    kb = kb or matcher.load_kb()
    report = []
    for e in kb["entries"]:
        t = e["treatment"]
        dose = _num(t["dose_per_litre"])
        rows = [r for c in e["crops"] for r in registry.uses(c, e.get("pest_terms", []))
                if registry.same_product(r["product"], t["product"])]
        if not rows:
            report.append((e["id"], "NOT FOUND", f"{t['product']} not registered for {e['crops']} / {e.get('pest_terms')}"))
            continue
        ok_dose = [r for r in rows if (pl := registry.per_litre(r)) and pl[0] * 0.95 <= dose <= pl[1] * 1.05]
        if not ok_dose:
            ranges = sorted({registry.fmt(pl) for r in rows if (pl := registry.per_litre(r))})
            # rows whose per-litre dose the PDF does not state plainly are left to the expert check
            report.append((e["id"], "DOSE" if ranges else "DOSE NOT PLAIN",
                           f"{t['dose_per_litre']} vs official {ranges or [r['formulation_per_ha'] + ' in ' + r['water_l_per_ha'] for r in rows]}"))
        waits = [r["waiting_days"] for r in (ok_dose or rows) if r["waiting_days"] is not None]
        kb_wait = min([e["waiting_days"], *e.get("waiting_by_crop", {}).values()])
        if waits and kb_wait < min(waits):
            report.append((e["id"], "WAIT", f"{kb_wait} days vs official {min(waits)}"))
    return report


if __name__ == "__main__":
    rep = audit()
    for r in rep:
        print(" | ".join(r))
    print(f"{len(rep)} problem(s)")
    sys.exit(1 if rep else 0)
