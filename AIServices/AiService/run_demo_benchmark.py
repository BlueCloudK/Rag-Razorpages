import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from services.rag_service import RagService

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SERVICE_ROOT = Path(__file__).resolve().parent
DEFAULT_CASES = SERVICE_ROOT / "data" / "demo_benchmark_cases.json"
RESULT_DIR = SERVICE_ROOT / "data" / "benchmark_results"


BAD_VI_PATTERNS = [
    r"\bMinh\b",
    r"\bChuong\b",
    r"\bTai lieu\b",
    r"\bNguon\b",
    r"\bKhong\b",
    r"\bCau nay\b",
    r"\bHien mon\b",
]


def normalize(value):
    import unicodedata

    text = str(value or "").lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def context_chapters(response):
    chapters = set()
    for item in response.get("contexts") or []:
        try:
            chapter = int(item.get("chapter_number") or 0)
        except Exception:
            chapter = 0
        if chapter:
            chapters.add(chapter)
    return sorted(chapters)


def context_variants(response):
    variants = set()
    for item in response.get("contexts") or []:
        variant = str(item.get("source_variant") or "").strip()
        if variant:
            variants.add(variant)
    return sorted(variants)


def duplicate_detected(response):
    for item in response.get("contexts") or []:
        try:
            if int(item.get("duplicate_count") or 1) > 1:
                return True
        except Exception:
            pass
        if len(item.get("duplicate_sources") or []) > 1:
            return True
    answer_norm = normalize(response.get("answer") or "")
    return "trung noi dung" in answer_norm or "giong nhau" in answer_norm


def conflict_detected(response):
    trace = response.get("processing_trace") or {}
    answer_norm = normalize(response.get("answer") or "")
    return (
        str(trace.get("intent") or "") == "conflict"
        or str(response.get("retrieval_strategy") or "") == "source_conflict_metadata"
        or "mau thuan" in answer_norm
        or "conflict" in answer_norm
    )


def evaluate_case(case, response):
    answer = str(response.get("answer") or "")
    normalized_answer = normalize(answer)
    sources = response.get("sources") or []
    source_text = " ".join(str(item) for item in sources)
    source_norm = normalize(source_text + " " + answer)
    trace = response.get("processing_trace") or {}
    trace_intent = str(trace.get("intent") or "")
    failures = []

    expected_intent = str(case.get("expected_intent") or "").strip()
    if expected_intent and trace_intent != expected_intent:
        failures.append("wrong_intent")

    expected_strategy = str(case.get("expected_retrieval_strategy") or "").strip()
    if expected_strategy and str(response.get("retrieval_strategy") or "") != expected_strategy:
        failures.append("wrong_strategy")

    if case.get("expect_no_sources"):
        if sources:
            failures.append("unexpected_source")
        if response.get("contexts"):
            failures.append("unexpected_context")

    for expected_source in case.get("expected_sources") or []:
        if normalize(expected_source).replace("pdf", "").strip() not in source_norm:
            failures.append("wrong_source")
            break

    expected_variants = [str(variant) for variant in case.get("expected_variants") or []]
    if expected_variants:
        variants = set(context_variants(response))
        answer_variant_text = normalize(answer)
        for variant in expected_variants:
            if variant not in variants and normalize(variant) not in answer_variant_text:
                failures.append("wrong_variant")
                break

    expected_chapters = [int(chapter) for chapter in case.get("expected_chapters") or []]
    if expected_chapters:
        chapters = context_chapters(response)
        answer_has_chapter = all(f"chapter {number}" in normalized_answer or f"chuong {number}" in normalized_answer for number in expected_chapters)
        context_has_chapter = all(number in chapters for number in expected_chapters)
        if not (answer_has_chapter or context_has_chapter):
            failures.append("wrong_chapter")

    for text in case.get("must_include") or []:
        if normalize(text) not in normalized_answer:
            failures.append("missing_expected_text")
            break

    for text in case.get("must_not_include") or []:
        raw_text = str(text or "")
        if raw_text in {"Minh", "Chuong", "Tai lieu", "Nguon", "Khong"}:
            if re.search(rf"\b{re.escape(raw_text)}\b", answer):
                failures.append("forbidden_text")
                break
            continue
        if normalize(text) and normalize(text) in normalized_answer:
            failures.append("forbidden_text")
            break

    if case.get("language") == "vi":
        for pattern in BAD_VI_PATTERNS:
            if re.search(pattern, answer):
                failures.append("bad_language")
                break

    if case.get("expected_behavior") == "refuse":
        if not any(term in normalized_answer for term in ["khong", "khong thay", "khong chua", "do not", "does not", "chua thay"]):
            failures.append("hallucination")

    if case.get("expected_behavior") == "clarify":
        clarify_terms = ["chua tim thay dinh nghia truc tiep", "viet day du", "file chuong nao", "specify", "full term"]
        if not any(term in normalized_answer for term in clarify_terms):
            failures.append("missing_clarification")
        if sources:
            failures.append("unexpected_source")
        if response.get("contexts"):
            failures.append("unexpected_context")
        strategy = str(response.get("retrieval_strategy") or "")
        if strategy and strategy != "ambiguous_acronym_guard":
            failures.append("wrong_strategy")

    if case.get("expected_behavior") == "conflict":
        if not any(term in normalized_answer for term in ["mau thuan", "conflict"]):
            failures.append("missing_conflict_notice")
        if any(term in normalized_answer for term in ["dung hon", "correct source", "official source"]):
            failures.append("over_decided_conflict")

    if case.get("expected_duplicate"):
        if not duplicate_detected(response):
            failures.append("missing_duplicate_detection")
        if conflict_detected(response):
            failures.append("false_conflict_for_duplicate")

    if len(answer.strip()) < 20 and case.get("expected_behavior") == "answer":
        failures.append("too_vague")

    return sorted(set(failures))


def load_cases(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_reports(results):
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = RESULT_DIR / f"demo-rag-{stamp}.json"
    md_path = RESULT_DIR / f"demo-rag-{stamp}.md"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    total = len(results["cases"])
    passed = sum(1 for item in results["cases"] if item["passed"])
    lines = [
        "# Demo RAG Benchmark",
        "",
        f"- Run at: {results['run_at']}",
        f"- Passed: {passed}/{total}",
        "",
        "| Case | Result | Failures | Strategy | Confidence | Duplicate | Conflict | Sources | Contexts |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in results["cases"]:
        result = "PASS" if item["passed"] else "FAIL"
        lines.append(
            f"| {item['id']} | {result} | {', '.join(item['failures']) or '-'} | "
            f"{item.get('retrieval_strategy', '-')} | {item.get('confidence', 0)} | "
            f"{'yes' if item.get('duplicate_detected') else 'no'} | "
            f"{'yes' if item.get('conflict_detected') else 'no'} | "
            f"{len(item.get('sources_used') or [])} | {item.get('contexts_used', 0)} |"
        )
    lines.extend(["", "## Failed Answers", ""])
    for item in results["cases"]:
        if item["passed"]:
            continue
        lines.extend([
            f"### {item['id']}",
            "",
            f"Question: {item['question']}",
            "",
            "```text",
            item["answer"][:2500],
            "```",
            "",
        ])
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return json_path, md_path


def main():
    parser = argparse.ArgumentParser(description="Run demo RAG benchmark for the two sample PDFs.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--subject-id", type=int, default=int(os.getenv("DEMO_SUBJECT_ID", "1")))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--ids", default="", help="Comma-separated case ids to run.")
    args = parser.parse_args()

    cases = load_cases(args.cases)
    if args.ids.strip():
        wanted = {item.strip() for item in args.ids.split(",") if item.strip()}
        cases = [case for case in cases if case.get("id") in wanted]
    if args.limit:
        cases = cases[: args.limit]

    rag = RagService()
    results = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "subject_id": args.subject_id,
        "case_file": str(Path(args.cases).resolve()),
        "cases": [],
    }

    for index, case in enumerate(cases, 1):
        print(f"[{index}/{len(cases)}] {case['id']}: {case['question']}", flush=True)
        try:
            response = rag.generate_answer(
                case["question"],
                subject_id=args.subject_id,
                history=case.get("history") or [],
                document_ids=None,
            )
            failures = evaluate_case(case, response)
        except Exception as exc:
            response = {"answer": str(exc), "sources": [], "contexts": [], "confidence": 0, "retrieval_strategy": "exception"}
            failures = ["exception"]

        results["cases"].append({
            "id": case["id"],
            "question": case["question"],
            "passed": not failures,
            "failures": failures,
            "answer": response.get("answer", ""),
            "sources": response.get("sources", []),
            "contexts": response.get("contexts", []),
            "model": response.get("model", ""),
            "retrieval_strategy": response.get("retrieval_strategy", ""),
            "confidence": response.get("confidence", 0),
            "agentic_trace": response.get("agentic_trace", {}),
            "duplicate_detected": duplicate_detected(response),
            "conflict_detected": conflict_detected(response),
            "sources_used": response.get("sources", []),
            "contexts_used": len(response.get("contexts") or []),
        })

    json_path, md_path = write_reports(results)
    passed = sum(1 for item in results["cases"] if item["passed"])
    print(f"Benchmark complete: {passed}/{len(results['cases'])} passed", flush=True)
    print(f"JSON: {json_path}", flush=True)
    print(f"Markdown: {md_path}", flush=True)
    return 0 if passed == len(results["cases"]) else 1


if __name__ == "__main__":
    sys.exit(main())
