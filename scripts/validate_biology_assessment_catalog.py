"""Cross-check the final pipeline artifacts before they are called complete.

Mirrors the checks recorded in the shared math package's
``math_assessment_catalog_validation_v2.json``: every JSONL parses, the source
row count matches the collected corpus, keys are unique, each layer is a
subset of the layer it was derived from, and the coverage matrix reconciles
with the roster and the catalogue.  The report is written even when a check
fails so the failing check is on record; the exit code is non-zero on failure.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_school_subject_assessment_catalog import (  # noqa: E402
    SUBJECTS,
    school_key,
    source_key,
)
from scripts.build_strict_biology_shortlist import key as evidence_key  # noqa: E402

COVERAGE_STATUSES = {
    "found",
    "found_curriculum_ambiguous",
    "extraction_failed",
    "not_found_in_collected_plans",
    "offering_unknown",
}


def read_jsonl(path: Path) -> tuple[list[dict], int]:
    rows: list[dict] = []
    bad = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            if isinstance(value, dict):
                rows.append(value)
            else:
                bad += 1
    return rows, bad


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--schools", type=Path, required=True)
    parser.add_argument("--source-index", type=Path, required=True)
    parser.add_argument("--evidence-index", type=Path, required=True)
    parser.add_argument("--strict-index", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-source-rows", type=int, required=True)
    args = parser.parse_args()

    checks: dict[str, bool] = {}
    counts: dict[str, object] = {}

    with args.schools.open("r", encoding="utf-8-sig", newline="") as handle:
        roster = {
            str(row.get("school_code") or row.get("school_name") or "")
            for row in csv.DictReader(handle)
        }
    roster.discard("")
    counts["schools"] = len(roster)

    # Source rows are streamed: the file is several GB and only its keys and
    # statuses are needed here.
    source_keys: list[str] = []
    source_status: collections.Counter[str] = collections.Counter()
    source_bad = 0
    with args.source_index.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                source_bad += 1
                continue
            source_keys.append(source_key(record.get("source") or {}))
            source_status[str(record.get("extract_status") or "missing")] += 1
    unique_sources = {key for key in source_keys if key}
    checks["source_json_valid"] = source_bad == 0
    checks["source_count_matches_expected"] = len(source_keys) == args.expected_source_rows
    checks["source_keys_unique_and_nonempty"] = (
        len(unique_sources) == len(source_keys) and all(source_keys)
    )
    counts.update({
        "source_rows": len(source_keys),
        "source_unique_keys": len(unique_sources),
        "source_bad_json": source_bad,
        "source_extract_status": dict(source_status),
    })

    evidence, evidence_bad = read_jsonl(args.evidence_index)
    evidence_keys = [evidence_key(row) for row in evidence]
    checks["evidence_json_valid"] = evidence_bad == 0
    checks["evidence_keys_unique"] = len(set(evidence_keys)) == len(evidence_keys)
    checks["evidence_sources_exist"] = all(
        source_key(row.get("source") or {}) in unique_sources for row in evidence
    )
    counts.update({"evidence_rows": len(evidence), "evidence_bad_json": evidence_bad})

    strict, strict_bad = read_jsonl(args.strict_index)
    strict_keys = [evidence_key(row) for row in strict]
    checks["strict_json_valid"] = strict_bad == 0
    checks["strict_keys_unique"] = len(set(strict_keys)) == len(strict_keys)
    checks["strict_is_subset_of_evidence"] = set(strict_keys) <= set(evidence_keys)
    counts.update({"strict_rows": len(strict), "strict_bad_json": strict_bad})

    catalog, catalog_bad = read_jsonl(args.catalog)
    checks["catalog_json_valid"] = catalog_bad == 0
    checks["catalog_matches_strict_row_count"] = len(catalog) == len(strict)
    counts.update({"catalog_rows": len(catalog), "catalog_bad_json": catalog_bad})

    with args.coverage.open("r", encoding="utf-8-sig", newline="") as handle:
        coverage = list(csv.DictReader(handle))
    subject_slots = sum(len(values) for values in SUBJECTS.values())
    expected_coverage = len(roster) * subject_slots
    coverage_keys = [
        (row.get("school_code", ""), row.get("curriculum", ""), row.get("subject", ""))
        for row in coverage
    ]
    status_counts = collections.Counter(row.get("coverage_status", "") for row in coverage)
    checks["coverage_row_count"] = len(coverage) == expected_coverage
    checks["coverage_keys_unique"] = len(set(coverage_keys)) == len(coverage_keys)
    checks["coverage_school_roster_matches"] = {key[0] for key in coverage_keys} == roster
    checks["coverage_statuses_valid"] = set(status_counts) <= COVERAGE_STATUSES
    # Every catalogue row with a resolved curriculum must appear as a found
    # slot, and every found slot must be backed by at least one catalogue row.
    found_slots = {
        key for key, row in zip(coverage_keys, coverage, strict=True)
        if row.get("coverage_status") == "found"
    }
    catalog_slots = {
        (school_key(row.get("source") or {}), str(row.get("resolved_curriculum") or ""),
         str(row.get("subject") or ""))
        for row in catalog
        if str(row.get("resolved_curriculum") or "") in SUBJECTS
    }
    checks["coverage_statuses_reconcile"] = found_slots == catalog_slots
    counts.update({
        "coverage_rows": len(coverage),
        "expected_coverage_rows": expected_coverage,
        "coverage_status": dict(status_counts),
    })

    report = {"passed": all(checks.values()), "checks": checks, "counts": counts}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    failed = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"passed": report["passed"], "failed_checks": failed}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
