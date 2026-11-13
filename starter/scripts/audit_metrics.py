"""Aggregate the audit (run from starter/: python -m scripts.audit_metrics).

Inputs (repo root):
  results/traces.jsonl                    automatic top-3 traces (python -m src.run evaluate)
  results/audit/coherence_labels.csv      manual coherence labels (10 positions x A,B; C has B's chunks)
  results/audit/grounding_labels.csv      manual grounding labels (test questions x A,B,C)
  results/audit/equivalent_evidence.csv   grader decisions on alternative evidence (accept/reject)
Outputs:
  results/audit/metadata_check.csv        per record: source/page/section/pep_type/python_version check
  results/audit/audit_summary.json        all numbers used in the report
  results/metrics_tables.md               tables pasted into the report

The metadata check is semi-automatic: source, page and filter fields are compared with the
source files/manifest; ``section`` is counted correct when it names the section that holds the
majority of the chunk's characters. Flagged rows were then read by hand (see report).
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "results" / "audit"
sys.path.insert(0, str(ROOT / "starter"))
from src.run import STRATEGIES, load_benchmark  # noqa: E402


def canon(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main() -> None:
    traces = [json.loads(l) for l in (ROOT / "results" / "traces.jsonl").read_text(encoding="utf-8").splitlines()]
    units = {}
    for line in (ROOT / "data" / "processed" / "units.jsonl").read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        units[(d["document_id"], d["page"])] = d
    manifest = {d["source_id"]: d for d in json.loads((ROOT / "data" / "manifest.json").read_text())["documents"]}
    questions = {q["id"]: q for q in load_benchmark()}
    out: dict = {}

    # ---------------------------------------------------------- metadata (test x top-3)
    meta_rows = []
    for t in traces:
        if t["split"] != "test":
            continue
        for h in t["top3"]:
            errs = []
            u = units.get((h["document_id"], h["page"]))
            if u is None:
                errs.append("unknown document/page")
            else:
                ut, ct = canon(u["text"]), canon(h["text"])
                pos = ut.find(ct)
                if pos < 0:
                    errs.append("chunk text not found in the stated unit (page wrong)")
                cover, off = {}, 0
                for p in u["metadata"]["paragraphs"]:
                    pt = canon(p["text"])
                    ov = max(0, min(off + len(pt), pos + len(ct)) - max(off, pos))
                    if ov:
                        cover[p["section"]] = cover.get(p["section"], 0) + ov
                    off += len(pt) + 1
                major = max(cover, key=cover.get) if cover else None
                if h["section"] != major:
                    errs.append(f"section '{h['section']}' but most of the text is in '{major}' {cover}")
            m = manifest[h["document_id"]]
            for field, expected in (("source", m["source_path_or_url"]), ("pep_type", m["pep_type"]),
                                    ("python_version", m["python_version"])):
                if h[field] != expected:
                    errs.append(f"{field} mismatch")
            meta_rows.append({"strategy": t["strategy"], "question_id": t["id"], "rank": h["rank"],
                              "chunk_id": h["chunk_id"], "source": h["source"], "page": h["page"],
                              "section": h["section"], "pep_type": h["pep_type"],
                              "python_version": h["python_version"],
                              "complete_and_correct": int(not errs), "errors": "; ".join(errs)})
    with (AUDIT / "metadata_check.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(meta_rows[0]))
        w.writeheader()
        w.writerows(meta_rows)
    out["metadata"] = {s: {"correct": sum(r["complete_and_correct"] for r in meta_rows if r["strategy"] == s),
                           "checked": sum(r["strategy"] == s for r in meta_rows)} for s in STRATEGIES}

    # ---------------------------------------------------------- filter compliance (all strategies)
    out["filter_compliance"] = {}
    for s in STRATEGIES:
        for split in ("dev", "test"):
            items = [t for t in traces if t["strategy"] == s and t["split"] == split and t["filter_in_question"]]
            ok = [t["id"] for t in items
                  if all(all(h[k] == v for k, v in t["filter_in_question"].items()) for h in t["top3"])]
            out["filter_compliance"][f"{s}/{split}"] = {
                "compliant": len(ok), "questions_with_filter": len(items), "filter_applied": STRATEGIES[s]["filter"],
                "non_compliant_ids": sorted(set(t["id"] for t in items) - set(ok))}

    # ---------------------------------------------------------- strict vs adjudicated hits
    accepted = {(r["question_id"], r["strategy"], int(r["rank"])) for r in read_csv(AUDIT / "equivalent_evidence.csv")
                if r["decision"] == "accept"}
    out["retrieval"] = {}
    for s in STRATEGIES:
        for split in ("dev", "test"):
            items = [t for t in traces if t["strategy"] == s and t["split"] == split]
            strict1 = sum(t["metrics"]["hit_at_1"] for t in items)
            strict3 = sum(t["metrics"]["hit_at_3"] for t in items)
            adj1 = sum(t["metrics"]["hit_at_1"] or (t["id"], s, 1) in accepted for t in items)
            adj3 = sum(t["metrics"]["hit_at_3"] or any((t["id"], s, r) in accepted for r in (1, 2, 3)) for t in items)
            out["retrieval"][f"{s}/{split}"] = {"N": len(items), "hit1_strict": strict1, "hit3_strict": strict3,
                                                "hit1_adjudicated": adj1, "hit3_adjudicated": adj3,
                                                "search_ms_mean": round(sum(t["search_ms"] for t in items) / len(items), 1)}

    # ---------------------------------------------------------- coherence & grounding
    coh = read_csv(AUDIT / "coherence_labels.csv")
    out["coherence"] = {}
    for s in ("A", "B"):
        scores = [int(r["score_0_2"]) for r in coh if r["strategy"] == s]
        out["coherence"][s] = {"n": len(scores), "mean": round(sum(scores) / len(scores), 2),
                               "dist_0_1_2": [scores.count(i) for i in range(3)]}
    out["coherence"]["C"] = dict(out["coherence"]["B"], note="C uses exactly the same chunks as B")
    gr = read_csv(AUDIT / "grounding_labels.csv")
    out["grounding"] = {}
    for s in STRATEGIES:
        scores = [int(r["score_0_2"]) for r in gr if r["strategy"] == s]
        out["grounding"][s] = {"n": len(scores), "dist_0_1_2": [scores.count(i) for i in range(3)],
                               "mean": round(sum(scores) / len(scores), 2)}
    assert all(q in questions for q in {r["question_id"] for r in gr})

    stats = json.loads((ROOT / "results" / "index_stats.json").read_text())
    (AUDIT / "audit_summary.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # ---------------------------------------------------------- markdown tables
    lines = ["| Strategy | Split | Hit@1 strict (n/N) | Evidence Hit@3 strict (n/N) | Hit@1 adjudicated | Hit@3 adjudicated | Chunk count | Embed time | Cost |",
             "|---|---|---|---|---|---|---|---|---|"]
    for s in STRATEGIES:
        st = stats["strategies"][s]
        for split in ("dev", "test"):
            r = out["retrieval"][f"{s}/{split}"]
            embed = f"{st['embed_seconds']} s" + (" (vectors of B reused)" if st["embeddings_reused_from_B"] else "")
            lines.append(f"| {s} | {split} | {r['hit1_strict']}/{r['N']} | {r['hit3_strict']}/{r['N']} | "
                         f"{r['hit1_adjudicated']}/{r['N']} | {r['hit3_adjudicated']}/{r['N']} | "
                         f"{st['chunk_length_chars']['count']} | {embed} | $0 |")
    lines += ["", "| Strategy | Coherence mean /2 (n) | Metadata complete & correct (n/N) | Filter compliant dev / test | Grounding 0/1/2 (questions) and mean /2 |",
              "|---|---|---|---|---|"]
    for s in STRATEGIES:
        c, m, g = out["coherence"][s], out["metadata"][s], out["grounding"][s]
        fd, ft = out["filter_compliance"][f"{s}/dev"], out["filter_compliance"][f"{s}/test"]
        tag = "" if STRATEGIES[s]["filter"] else " (filter not applied)"
        lines.append(f"| {s} | {c['mean']} ({c['n']}) | {m['correct']}/{m['checked']} | "
                     f"{fd['compliant']}/{fd['questions_with_filter']} / {ft['compliant']}/{ft['questions_with_filter']}{tag} | "
                     f"{'/'.join(map(str, g['dist_0_1_2']))} -> {g['mean']} |")
    (ROOT / "results" / "metrics_tables.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(json.dumps(out["filter_compliance"], indent=1))


if __name__ == "__main__":
    main()
