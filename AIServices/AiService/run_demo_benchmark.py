import argparse
from collections import Counter, defaultdict
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
DEFAULT_QUALITY_SCORES = {
    "source_correctness": 1.0,
    "evidence_sufficiency": 1.0,
    "answer_completeness": 1.0,
    "language_quality": 1.0,
    "safety_grounding": 1.0,
}


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


def split_csv(value):
    return {item.strip() for item in str(value or "").split(",") if item.strip()}


def quality_score_axis(passed):
    return 1.0 if passed else 0.0


def add_failure(failures, failure):
    if failure not in failures:
        failures.append(failure)


def average(values):
    values = list(values or [])
    return round(sum(values) / max(len(values), 1), 3)


def case_quality_score(item):
    return average((item.get("quality_scores") or {}).values())


def response_source_text(response, include_answer=True):
    parts = [str(item) for item in response.get("sources") or []]
    if include_answer:
        parts.append(str(response.get("answer") or ""))
    return normalize(" ".join(parts))


def context_source_text(response, include_answer=True):
    parts = []
    for item in response.get("contexts") or []:
        parts.append(str(item.get("source") or item.get("filename") or ""))
        parts.extend(str(source) for source in item.get("duplicate_sources") or [])
    if include_answer:
        parts.append(str(response.get("answer") or ""))
    return normalize(" ".join(parts))


def has_bad_vietnamese(answer):
    for pattern in BAD_VI_PATTERNS:
        if re.search(pattern, answer):
            return True
    return False


def has_style_noise(answer):
    return bool(re.search(
        r"(Note:|I've aimed|Let me know|Okay, let's analyze|As an AI|Tôi là một mô hình)",
        answer,
        re.IGNORECASE,
    ))


def evaluate_quality(case, response, failures):
    answer = str(response.get("answer") or "")
    normalized_answer = normalize(answer)
    sources = response.get("sources") or []
    contexts = response.get("contexts") or []
    checks = set(case.get("quality_checks") or [])
    expected_behavior = str(case.get("expected_behavior") or "")
    expects_grounded_answer = expected_behavior in {"answer", "conflict"} and not case.get("expect_no_sources")

    if not checks:
        if expects_grounded_answer:
            checks.update(["source_correctness", "evidence_sufficiency", "answer_completeness"])
        if case.get("language") == "vi":
            checks.add("language_quality")
        if expected_behavior in {"refuse", "clarify", "system"} or case.get("expect_no_sources"):
            checks.add("safety_grounding")

    scores = {}

    if "source_correctness" in checks:
        expected_sources = case.get("expected_sources") or []
        if expected_sources:
            source_text = response_source_text(response)
            passed = all(normalize(item).replace("pdf", "").strip() in source_text for item in expected_sources)
        else:
            passed = not case.get("expect_no_sources") or not sources
        scores["source_correctness"] = quality_score_axis(passed)
        if not passed:
            add_failure(failures, "quality_source_correctness")

    if "evidence_sufficiency" in checks:
        min_contexts = int(case.get("min_contexts") or (2 if expects_grounded_answer else 0))
        passed = str(response.get("retrieval_strategy") or "") == "document_list" or len(contexts) >= min_contexts
        scores["evidence_sufficiency"] = quality_score_axis(passed)
        if not passed:
            add_failure(failures, "missing_evidence")

    if "answer_completeness" in checks:
        min_chars = int(case.get("min_answer_chars") or (160 if expects_grounded_answer else 20))
        min_points = int(case.get("min_key_points") or 0)
        bulletish_points = len(re.findall(r"(^|\n)\s*([-*•]|\d+[.)])\s+", answer))
        passed = len(answer.strip()) >= min_chars and (not min_points or bulletish_points >= min_points)
        scores["answer_completeness"] = quality_score_axis(passed)
        if not passed:
            add_failure(failures, "too_vague")

    if "language_quality" in checks:
        passed = not has_bad_vietnamese(answer) and not has_style_noise(answer)
        scores["language_quality"] = quality_score_axis(passed)
        if not passed:
            add_failure(failures, "bad_language")

    if "safety_grounding" in checks:
        if expected_behavior == "answer":
            passed = bool(answer.strip()) and (not case.get("expect_no_sources") or not sources)
        else:
            unsafe_sources = bool(case.get("expect_no_sources") and (sources or contexts))
            refusal_or_system = any(term in normalized_answer for term in [
                "khong", "chua", "khong the", "khong tim thay", "chua tim thay",
                "khong chay retrieval", "khong gan nguon", "khong thuoc", "cannot", "not enough",
            ])
            passed = not unsafe_sources and (expected_behavior == "system" or refusal_or_system)
        scores["safety_grounding"] = quality_score_axis(passed)
        if not passed:
            add_failure(failures, "hallucination")

    if "trace_consistency" in checks:
        trace = response.get("processing_trace") or {}
        expected_intent = str(case.get("expected_intent") or "").strip()
        expected_strategy = str(case.get("expected_retrieval_strategy") or "").strip()
        passed = True
        if expected_intent and str(trace.get("intent") or "") != expected_intent:
            passed = False
        if expected_strategy and str(response.get("retrieval_strategy") or "") != expected_strategy:
            passed = False
        if case.get("expect_no_sources") and (sources or contexts):
            passed = False
        scores["trace_consistency"] = quality_score_axis(passed)
        if not passed:
            add_failure(failures, "trace_mismatch")

    if "citation_consistency" in checks:
        if sources and contexts:
            context_sources = context_source_text(response)
            passed = all(normalize(source).replace("pdf", "").strip() in context_sources for source in sources if str(source).endswith(".pdf"))
        else:
            passed = not sources or str(response.get("retrieval_strategy") or "") in {"document_list"}
        scores["citation_consistency"] = quality_score_axis(passed)
        if not passed:
            add_failure(failures, "citation_mismatch")

    if not scores:
        scores = dict(DEFAULT_QUALITY_SCORES)

    return scores


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

    quality_scores = evaluate_quality(case, response, failures)
    return sorted(set(failures)), quality_scores


def load_cases(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_failed_ids(path):
    if not path:
        return set()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {item.get("id") for item in data.get("cases", []) if not item.get("passed")}


def summarize_groups(cases):
    grouped = defaultdict(list)
    for item in cases:
        grouped[item.get("group") or "ungrouped"].append(item)
    summary = {}
    for group, items in sorted(grouped.items()):
        passed = sum(1 for item in items if item.get("passed"))
        quality_values = [score for item in items for score in (item.get("quality_scores") or {}).values()]
        summary[group] = {
            "passed": passed,
            "total": len(items),
            "quality_score": average(quality_values),
            "failures": dict(Counter(failure for item in items for failure in item.get("failures", []))),
        }
    return summary


def overall_quality(cases):
    return average(score for item in cases for score in (item.get("quality_scores") or {}).values())


def write_reports(results):
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = RESULT_DIR / f"demo-rag-{stamp}.json"
    md_path = RESULT_DIR / f"demo-rag-{stamp}.md"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    total = len(results["cases"])
    passed = sum(1 for item in results["cases"] if item["passed"])
    group_summary = results.get("group_summary") or {}
    weakest_groups = sorted(
        group_summary.items(),
        key=lambda pair: (pair[1]["passed"] / max(pair[1]["total"], 1), pair[1]["quality_score"]),
    )[:5]
    lines = [
        "# Demo RAG Benchmark",
        "",
        f"- Run at: {results['run_at']}",
        f"- Passed: {passed}/{total}",
        f"- Overall quality score: {results.get('quality_score', 0)}",
        f"- Case file: `{results.get('case_file', '')}`",
        "",
        "## Group Summary",
        "",
        "| Group | Passed | Quality | Top Failures |",
        "| --- | ---: | ---: | --- |",
    ]
    for group, data in group_summary.items():
        top_failures = ", ".join(f"{key}:{value}" for key, value in sorted(data.get("failures", {}).items(), key=lambda item: -item[1])[:3]) or "-"
        lines.append(f"| {group} | {data['passed']}/{data['total']} | {data['quality_score']} | {top_failures} |")

    lines.extend([
        "",
        "## Weakest Groups",
        "",
    ])
    if weakest_groups:
        for group, data in weakest_groups:
            lines.append(f"- `{group}`: {data['passed']}/{data['total']} passed, quality {data['quality_score']}")
    else:
        lines.append("- No groups were run.")

    lines.extend([
        "",
        "## Case Results",
        "",
        "| Case | Group | Result | Failures | Quality | Strategy | Intent | Confidence | Duplicate | Conflict | Sources | Contexts |",
        "| --- | --- | --- | --- | ---: | --- | --- | ---: | --- | --- | ---: | ---: |",
    ])
    for item in results["cases"]:
        result = "PASS" if item["passed"] else "FAIL"
        lines.append(
            f"| {item['id']} | {item.get('group', '-')} | {result} | {', '.join(item['failures']) or '-'} | "
            f"{case_quality_score(item)} | {item.get('retrieval_strategy', '-')} | {item.get('trace_intent', '-')} | {item.get('confidence', 0)} | "
            f"{'yes' if item.get('duplicate_detected') else 'no'} | "
            f"{'yes' if item.get('conflict_detected') else 'no'} | "
            f"{len(item.get('sources_used') or [])} | {item.get('contexts_used', 0)} |"
        )
    lines.extend(["", "## Top Failed Cases", ""])
    for item in results["cases"]:
        if item["passed"]:
            continue
        lines.extend([
            f"### {item['id']}",
            "",
            f"Question: {item['question']}",
            "",
            f"Failures: {', '.join(item['failures'])}",
            "",
            f"Strategy: `{item.get('retrieval_strategy', '')}` · Intent: `{item.get('trace_intent', '')}`",
            "",
            "```text",
            item["answer"][:2500],
            "```",
            "",
        ])
    lines.extend([
        "",
        "## Next Fix Hints",
        "",
    ])
    all_failures = Counter(failure for item in results["cases"] for failure in item.get("failures", []))
    if not all_failures:
        lines.append("- No failing cases. Manually inspect representative answers before claiming the RAG is perfect.")
    else:
        for failure, count in all_failures.most_common(8):
            lines.append(f"- `{failure}`: {count} case(s)")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return json_path, md_path


def main():
    parser = argparse.ArgumentParser(description="Run demo RAG benchmark for the two sample PDFs.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--subject-id", type=int, default=int(os.getenv("DEMO_SUBJECT_ID", "1")))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--ids", default="", help="Comma-separated case ids to run.")
    parser.add_argument("--group", default="", help="Comma-separated benchmark groups to run.")
    parser.add_argument("--failed-from", default="", help="Run failed case ids from a previous JSON report.")
    args = parser.parse_args()

    cases = load_cases(args.cases)
    if args.ids.strip():
        wanted = split_csv(args.ids)
        cases = [case for case in cases if case.get("id") in wanted]
    if args.group.strip():
        wanted_groups = split_csv(args.group)
        cases = [case for case in cases if (case.get("group") or "ungrouped") in wanted_groups]
    if args.failed_from.strip():
        failed_ids = load_failed_ids(args.failed_from)
        cases = [case for case in cases if case.get("id") in failed_ids]
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
            failures, quality_scores = evaluate_case(case, response)
        except Exception as exc:
            response = {"answer": str(exc), "sources": [], "contexts": [], "confidence": 0, "retrieval_strategy": "exception"}
            failures = ["exception"]
            quality_scores = {key: 0.0 for key in DEFAULT_QUALITY_SCORES}

        trace = response.get("processing_trace") or {}
        results["cases"].append({
            "id": case["id"],
            "group": case.get("group") or "ungrouped",
            "question": case["question"],
            "passed": not failures,
            "failures": failures,
            "quality_scores": quality_scores,
            "answer": response.get("answer", ""),
            "sources": response.get("sources", []),
            "contexts": response.get("contexts", []),
            "model": response.get("model", ""),
            "retrieval_strategy": response.get("retrieval_strategy", ""),
            "trace_intent": trace.get("intent", ""),
            "confidence": response.get("confidence", 0),
            "agentic_trace": response.get("agentic_trace", {}),
            "processing_trace": trace,
            "duplicate_detected": duplicate_detected(response),
            "conflict_detected": conflict_detected(response),
            "sources_used": response.get("sources", []),
            "contexts_used": len(response.get("contexts") or []),
        })

    results["group_summary"] = summarize_groups(results["cases"])
    results["quality_score"] = overall_quality(results["cases"])
    json_path, md_path = write_reports(results)
    passed = sum(1 for item in results["cases"] if item["passed"])
    print(f"Benchmark complete: {passed}/{len(results['cases'])} passed", flush=True)
    print(f"JSON: {json_path}", flush=True)
    print(f"Markdown: {md_path}", flush=True)
    return 0 if passed == len(results["cases"]) else 1


if __name__ == "__main__":
    sys.exit(main())
