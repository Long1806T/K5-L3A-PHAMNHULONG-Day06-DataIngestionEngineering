"""Evaluate retrieved evidence and keep per-query traces.

A retrieved chunk is a *hit* when (a) its (document_id, page) is one of the gold
locations of the question and (b) its text contains the **whole** evidence quote
of that location (compared in canonical form: NFC, lowercase, collapsed
whitespace).  Alternative gold locations listed in the benchmark are accepted.
Human labels (coherence, grounding) are NOT inferred here.
"""
from __future__ import annotations

from typing import Any

from .ingestion import canonical


def gold_locations(question: dict[str, Any]) -> list[dict[str, Any]]:
    locs = [{"source_id": question["gold_source_id"], "page": int(question["gold_page"]),
             "evidence": question["evidence_quote"]}]
    for alt in question.get("alternative_gold", []):
        locs.append({"source_id": alt["source_id"], "page": int(alt["page"]), "evidence": alt["evidence_quote"]})
    return locs


def is_hit(question: dict[str, Any], hit: dict[str, Any]) -> tuple[bool, bool]:
    """Return (right_location, full_evidence_hit) for one retrieved chunk."""
    text = canonical(hit["text"])
    right_loc = False
    for loc in gold_locations(question):
        if hit["document_id"] == loc["source_id"] and int(hit["page"]) == loc["page"]:
            right_loc = True
            if canonical(loc["evidence"]) in text:
                return True, True
    return right_loc, False


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    flags = [is_hit(question, h) for h in hits]
    for h, (loc, ev) in zip(hits, flags):
        h["right_location"] = loc
        h["evidence_hit"] = ev
    loc_only = any(loc and not ev for loc, ev in flags)
    return {
        "hit_at_1": bool(flags and flags[0][1]),
        "hit_at_3": any(ev for _, ev in flags[:3]),
        "first_hit_rank": next((i + 1 for i, (_, ev) in enumerate(flags) if ev), None),
        # right document+unit retrieved but evidence not fully inside one chunk
        "location_without_full_evidence": loc_only and not any(ev for _, ev in flags),
    }


def summarize(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate Hit@1 and Evidence Hit@3 by strategy and split (with n/N)."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for t in traces:
        groups.setdefault((t["strategy"], t["split"]), []).append(t)
    rows = []
    for (strategy, split), items in sorted(groups.items()):
        n = len(items)
        h1 = sum(t["metrics"]["hit_at_1"] for t in items)
        h3 = sum(t["metrics"]["hit_at_3"] for t in items)
        filtered = [t for t in items if t["filter_applied"]]
        compliant = sum(t["filter_compliant_top3"] for t in filtered)
        rows.append({
            "strategy": strategy, "split": split, "N": n,
            "hit_at_1": h1, "hit_at_1_rate": round(h1 / n, 3),
            "evidence_hit_at_3": h3, "evidence_hit_at_3_rate": round(h3 / n, 3),
            "loc_without_full_evidence": sum(t["metrics"]["location_without_full_evidence"] for t in items),
            "filter_questions_applied": len(filtered),
            "filter_compliant": compliant if filtered else "N/A",
        })
    return rows
