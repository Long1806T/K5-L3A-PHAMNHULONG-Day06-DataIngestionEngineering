"""Day 06 pipeline entry point.

Run from ``starter/``::

    python -m src.run ingest            # parse corpus -> units, manifest, ingestion log
    python -m src.run verify-benchmark  # check every evidence quote exists in its gold unit
    python -m src.run index             # chunk (A, B), embed, upsert A/B/C, re-ingest check
    python -m src.run evaluate          # top-3 for every question x strategy, traces + summary
    python -m src.run audit-samples     # sheets for manual coherence / metadata / grounding audit
    python -m src.run all               # everything above in order
"""
from __future__ import annotations

import csv
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .chunking import by_paragraph, fixed_size
from .embeddings import OnnxMiniLMEmbedder
from .evaluation import evaluate_query, summarize
from .ingestion import MIN_UNIT_CHARS, canonical, load_pep
from .models import Chunk, DocumentPage
from .store import PgVectorStore

ROOT = Path(__file__).resolve().parents[2]          # repository root
CORPUS_DIR = ROOT / "data" / "corpus" / "peps"
PROCESSED = ROOT / "data" / "processed"
BENCHMARK = ROOT / "benchmark" / "questions.json"
RESULTS = ROOT / "results"
SOURCE_COMMIT = "2a71e92663616ff5b2c3085ac8ed4f29d38e83d4"   # python/peps snapshot
ACCESSED_AT = "2026-11-14"

STRATEGIES = {
    "A": {"chunking": "fixed_size", "size": 500, "overlap": 50, "filter": False},
    "B": {"chunking": "by_paragraph", "max_size": 1000, "overlap": 0, "filter": False},
    "C": {"chunking": "by_paragraph", "max_size": 1000, "overlap": 0, "filter": True},
}


def _load_env() -> None:
    env = ROOT / "starter" / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _db_url() -> str:
    _load_env()
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL missing: copy starter/.env.example to starter/.env")
    return url


def _dump_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ------------------------------------------------------------------- ingest
def load_units() -> list[DocumentPage]:
    units: list[DocumentPage] = []
    for line in (PROCESSED / "units.jsonl").read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        units.append(DocumentPage(d["document_id"], d["source"], d["page"], d["text"], d["metadata"]))
    return units


def cmd_ingest() -> list[DocumentPage]:
    files = sorted(CORPUS_DIR.glob("pep-*.rst"))
    if not files:
        sys.exit(f"no corpus files in {CORPUS_DIR}")
    all_units: list[DocumentPage] = []
    manifest, log_rows = [], []
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        try:
            units, doc_meta, log = load_pep(path, rel)
        except Exception as exc:  # record and continue
            log_rows.append({"file": rel, "level": "ERROR", "message": repr(exc)})
            continue
        for msg in log:
            log_rows.append({"file": rel, "level": "INFO", "message": msg})
        short = [u.metadata["unit_id"] for u in units if u.metadata["n_chars"] < MIN_UNIT_CHARS]
        if short:
            log_rows.append({"file": rel, "level": "WARN", "message": f"units below {MIN_UNIT_CHARS} chars: {short}"})
        raw = path.read_text(encoding="utf-8")
        license_line = raw[raw.find("Copyright\n=========") + 20:].strip().split("\n\n")[0].replace("\n", " ")
        manifest.append({
            "source_id": doc_meta["document_id"],
            "title": doc_meta["title"],
            "source_path_or_url": rel,
            "upstream_url": f"https://github.com/python/peps/blob/{SOURCE_COMMIT}/peps/{path.name}",
            "snapshot": f"python/peps@{SOURCE_COMMIT}",
            "local_copy_changes": "author e-mail addresses in the header replaced by '<email redacted>' "
                                  "(header is not used as content); body unchanged",
            "license_or_permission": license_line,
            "accessed_at": ACCESSED_AT,
            "pep_type": doc_meta["pep_type"], "status": doc_meta["status"],
            "python_version": doc_meta["python_version"], "created": doc_meta["created"],
            "physical_pages": "N/A (reStructuredText, no pagination)",
            "raw_chars": len(raw),
            "units": [{"unit_id": u.metadata["unit_id"], "page": u.page, "n_chars": u.metadata["n_chars"],
                       "first_section": u.metadata["section"]} for u in units],
            "n_units": len(units),
            "normalized_chars": sum(u.metadata["n_chars"] for u in units),
        })
        all_units.extend(units)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    with (PROCESSED / "units.jsonl").open("w", encoding="utf-8") as fh:
        for u in all_units:
            fh.write(json.dumps({"document_id": u.document_id, "source": u.source, "page": u.page,
                                 "text": u.text, "metadata": u.metadata}, ensure_ascii=False) + "\n")
    counted = [u for u in all_units if u.metadata["n_chars"] >= MIN_UNIT_CHARS]
    _dump_json(ROOT / "data" / "manifest.json", {
        "corpus": "Python Enhancement Proposals (selected 10 PEPs)",
        "unit_rule": (f"No physical pages. Each PEP body (header, Copyright, Footnotes and References "
                      f"sections removed) is split in order into units of >= {MIN_UNIT_CHARS} normalized "
                      "characters, cut only at paragraph boundaries; a short tail is merged into the "
                      "previous unit. A unit is the 'page' (page = unit number within the document)."),
        "total_units": len(all_units), "units_counted_ge_1500_chars": len(counted),
        "total_normalized_chars": sum(u.metadata["n_chars"] for u in all_units),
        "documents": manifest,
    })
    with (ROOT / "data" / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["source_id", "title", "source_path_or_url", "license_or_permission", "accessed_at",
                    "snapshot", "pep_type", "python_version", "status", "n_units", "unit_ids", "normalized_chars"])
        for m in manifest:
            w.writerow([m["source_id"], m["title"], m["source_path_or_url"], m["license_or_permission"],
                        m["accessed_at"], m["snapshot"], m["pep_type"], m["python_version"], m["status"],
                        m["n_units"], " ".join(u["unit_id"] for u in m["units"]), m["normalized_chars"]])
    RESULTS.mkdir(exist_ok=True)
    with (RESULTS / "ingestion_log.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["file", "level", "message"])
        w.writeheader()
        w.writerows(log_rows)
    print(f"ingest: {len(files)} files -> {len(all_units)} units ({len(counted)} >= {MIN_UNIT_CHARS} chars)")
    return all_units


# --------------------------------------------------------- benchmark checks
def load_benchmark() -> list[dict]:
    return json.loads(BENCHMARK.read_text(encoding="utf-8"))["questions"]


def cmd_verify_benchmark() -> None:
    units = {(u.document_id, u.page): u for u in load_units()}
    questions = load_benchmark()
    problems = []
    for q in questions:
        locs = [(q["gold_source_id"], q["gold_page"], q["evidence_quote"])] + \
               [(a["source_id"], a["page"], a["evidence_quote"]) for a in q.get("alternative_gold", [])]
        for doc, page, ev in locs:
            unit = units.get((doc, int(page)))
            if unit is None:
                problems.append(f"{q['id']}: unknown location {doc} page {page}")
            elif canonical(ev) not in canonical(unit.text):
                problems.append(f"{q['id']}: evidence not found in {doc} page {page}")
        if q.get("filter"):
            for k, v in q["filter"].items():
                if not any(u.metadata.get(k) == v for u in units.values()):
                    problems.append(f"{q['id']}: filter value {k}={v} does not exist")
            gold_unit = units.get((q["gold_source_id"], int(q["gold_page"])))
            if gold_unit and any(gold_unit.metadata.get(k) != v for k, v in q["filter"].items()):
                problems.append(f"{q['id']}: gold unit does not satisfy its own filter")
    splits = {s: sum(q["split"] == s for q in questions) for s in ("dev", "test")}
    n_filter = {s: sum(bool(q.get("filter")) and q["split"] == s for q in questions) for s in ("dev", "test")}
    report = {"questions": len(questions), "splits": splits, "filter_questions": n_filter,
              "problems": problems, "ok": not problems}
    _dump_json(RESULTS / "benchmark_verification.json", report)
    print(json.dumps(report, indent=2))
    if problems:
        sys.exit(1)


# ------------------------------------------------------------------ index
def build_chunks(units: list[DocumentPage], name: str) -> list[Chunk]:
    cfg = STRATEGIES[name]
    out: list[Chunk] = []
    for u in units:
        if cfg["chunking"] == "fixed_size":
            out.extend(fixed_size(u, cfg["size"], cfg["overlap"]))
        else:
            out.extend(by_paragraph(u, cfg["max_size"]))
    if name == "C":  # identical chunks to B; IDs re-labelled so the strategy is self-describing
        for c in out:
            c.chunk_id = c.chunk_id.replace(":B", ":C")
    return out


def _length_stats(chunks: list[Chunk]) -> dict:
    lens = sorted(len(c.text) for c in chunks)
    q = statistics.quantiles(lens, n=4)
    return {"count": len(lens), "total_chars": sum(lens), "min": lens[0], "p25": round(q[0]),
            "median": round(q[1]), "p75": round(q[2]), "max": lens[-1], "mean": round(sum(lens) / len(lens), 1)}


def cmd_index() -> None:
    units = load_units()
    store = PgVectorStore(_db_url(), OnnxMiniLMEmbedder.dimensions)
    info = store.server_info()
    store.create_schema()
    embedder = OnnxMiniLMEmbedder()
    stats: dict = {"server": info, "embedding_model": embedder.model_name, "dimensions": embedder.dimensions,
                   "max_seq_length": embedder.max_length, "run_at": datetime.now(timezone.utc).isoformat(),
                   "cost_usd": 0.0, "strategies": {}}
    cache: dict[str, list[list[float]]] = {}
    for name in STRATEGIES:
        chunks = build_chunks(units, name)
        t0 = time.perf_counter()
        trunc_before = embedder.truncated_inputs
        key = "B" if name in ("B", "C") else name
        reused = key in cache
        if not reused:
            cache[key] = embedder.embed_documents([c.text for c in chunks])
        vectors = cache[key]
        t_embed = time.perf_counter() - t0
        t1 = time.perf_counter()
        first = store.upsert(name, chunks, vectors)
        t_store = time.perf_counter() - t1
        second = store.upsert(name, chunks, vectors)      # re-ingest same version
        counts = store.count(name)
        stats["strategies"][name] = {
            "config": STRATEGIES[name], "chunk_length_chars": _length_stats(chunks),
            "approx_tokens_total": None,
            "embed_seconds": round(t_embed, 2), "embeddings_reused_from_B": reused,
            "upsert_seconds": round(t_store, 2),
            "inputs_truncated_at_256_tokens": embedder.truncated_inputs - trunc_before,
            "first_upsert": first, "reingest_same_version": second, "rows_after_reingest": counts,
            "duplicates_after_reingest": counts["rows"] - counts["distinct_ids"],
        }
        stats["strategies"][name]["approx_tokens_total"] = sum(
            len(embedder.tokenizer.encode(c.text)[0]) for c in chunks)
        print(f"index {name}: {len(chunks)} chunks, embed {t_embed:.1f}s, upsert {t_store:.1f}s, "
              f"re-ingest {second}, rows {counts}")
    stats["changed_document_check"] = _changed_document_check(store, units, embedder)
    _dump_json(RESULTS / "index_stats.json", stats)


def _changed_document_check(store: PgVectorStore, units: list[DocumentPage], embedder) -> dict:
    """Simulate an edited source document in a scratch strategy and verify cleanup."""
    doc = [u for u in units if u.document_id == "pep-0604"]
    chunks = [c for u in doc for c in by_paragraph(u, 1000)]
    store.upsert("_reingest_test", chunks, embedder.embed_documents([c.text for c in chunks]))
    before = store.count("_reingest_test")
    edited = chunks[:-2]                                    # document got shorter
    edited[0] = Chunk(edited[0].chunk_id, edited[0].document_id, edited[0].source, edited[0].page,
                      edited[0].text + " (edited)", edited[0].metadata)
    result = store.upsert("_reingest_test", edited, embedder.embed_documents([c.text for c in edited]))
    after = store.count("_reingest_test")
    store._run("DELETE FROM chunks WHERE strategy = '_reingest_test';")
    return {"document": "pep-0604", "rows_before": before["rows"], "edit": "first chunk text changed, last 2 chunks removed",
            "upsert_result": result, "rows_after": after["rows"],
            "ok": result["deleted"] == 2 and result["updated"] == 1 and after["rows"] == before["rows"] - 2}


# --------------------------------------------------------------- evaluate
def cmd_evaluate() -> None:
    questions = load_benchmark()
    store = PgVectorStore(_db_url(), OnnxMiniLMEmbedder.dimensions)
    embedder = OnnxMiniLMEmbedder()
    traces = []
    t0 = time.perf_counter()
    for q in questions:
        qvec = embedder.embed_query(q["question"])
        for name, cfg in STRATEGIES.items():
            flt = q.get("filter") if cfg["filter"] else None
            t = time.perf_counter()
            hits = store.search(name, qvec, top_k=3, filters=flt)
            latency = time.perf_counter() - t
            metrics = evaluate_query(q, hits)
            compliant = all(all(h.get(k) == v for k, v in flt.items()) for h in hits) if flt else None
            traces.append({
                "strategy": name, "id": q["id"], "split": q["split"], "type": q.get("type"),
                "question": q["question"], "filter_in_question": q.get("filter"),
                "filter_applied": bool(flt), "filter_compliant_top3": compliant,
                "gold": {"source_id": q["gold_source_id"], "page": q["gold_page"],
                         "evidence_quote": q["evidence_quote"],
                         "alternatives": q.get("alternative_gold", [])},
                "expected_answer": q["expected_answer"], "metrics": metrics,
                "search_ms": round(latency * 1000, 1), "top3": hits,
            })
    total = time.perf_counter() - t0
    with (RESULTS / "traces.jsonl").open("w", encoding="utf-8") as fh:
        for t in traces:
            fh.write(json.dumps(t, ensure_ascii=False) + "\n")
    summary = summarize(traces)
    _dump_json(RESULTS / "retrieval_summary.json", {"embedding_model": embedder.model_name, "top_k": 3,
                                                    "eval_seconds_total": round(total, 2), "rows": summary})
    with (RESULTS / "per_question.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "split", "type", "filter", "strategy", "hit_at_1", "hit_at_3", "first_hit_rank",
                    "loc_without_full_evidence", "top1_unit", "top2_unit", "top3_unit"])
        for t in traces:
            units = [h["unit_id"] for h in t["top3"]] + ["", "", ""]
            w.writerow([t["id"], t["split"], t["type"], json.dumps(t["filter_in_question"]) if t["filter_in_question"] else "",
                        t["strategy"], int(t["metrics"]["hit_at_1"]), int(t["metrics"]["hit_at_3"]),
                        t["metrics"]["first_hit_rank"] or "", int(t["metrics"]["location_without_full_evidence"]),
                        *units[:3]])
    for r in summary:
        print(f"{r['strategy']} {r['split']:4s} Hit@1 {r['hit_at_1']}/{r['N']}  EvHit@3 {r['evidence_hit_at_3']}/{r['N']}"
              f"  filter {r['filter_compliant']}/{r['filter_questions_applied']}")


# ----------------------------------------------------------- audit sheets
COHERENCE_DOCS = ["pep-0008", "pep-0257", "pep-0498", "pep-0557", "pep-0572",
                  "pep-0585", "pep-0604", "pep-0618", "pep-0634", "pep-0636"]


def cmd_audit_samples() -> None:
    """Coherence positions are fixed in advance: midpoint character of unit u02 of each document."""
    units = {(u.document_id, u.page): u for u in load_units()}
    rows = []
    for doc in COHERENCE_DOCS:
        u = units[(doc, 2)]
        offset = len(u.text) // 2
        for name in ("A", "B"):
            chunks = build_chunks([u], name)
            if name == "A":
                cands = [c for c in chunks if c.metadata["char_start"] <= offset < c.metadata["char_end"]]
                chosen = cands[0]
            else:
                pos, chosen = 0, chunks[-1]
                for c in chunks:  # locate by searching the chunk text in the unit text
                    idx = u.text.find(c.text[:80], pos)
                    if idx != -1:
                        pos = idx
                        if idx <= offset < idx + len(c.text) + 2:
                            chosen = c
                            break
            rows.append({"position_id": f"{doc}#u02@{offset}", "strategy": name, "chunk_id": chosen.chunk_id,
                         "section": chosen.metadata.get("section"), "chunk_chars": len(chosen.text),
                         "chunk_text": chosen.text, "score_0_2": "", "reason": ""})
    _dump_json(RESULTS / "audit" / "coherence_sample.json", rows)
    print(f"audit-samples: {len(rows)} coherence rows written")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    steps = {"ingest": cmd_ingest, "verify-benchmark": cmd_verify_benchmark, "index": cmd_index,
             "evaluate": cmd_evaluate, "audit-samples": cmd_audit_samples}
    if cmd == "all":
        for name in ("ingest", "verify-benchmark", "index", "evaluate", "audit-samples"):
            steps[name]()
    elif cmd in steps:
        steps[cmd]()
    else:
        sys.exit(f"unknown command {cmd}; choose from {', '.join(steps)} or all")


if __name__ == "__main__":
    main()
