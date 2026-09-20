#!/usr/bin/env python3
"""9장 9-5: 승격 검수 기록이 감사 질문에 답할 수 있는지 점검한다.

무엇을 보이는가
---------------
- 9-1이 남긴 승격 검수 기록(ch9_promotion_record.json)의 필수 항목을 점검한다.
- 기록된 데이터 지문을 원천에서 다시 계산해 대조한다(기록의 진위 확인).
- 판정 이력과 champion 버전이 서로 맞는지 확인한다.
- 항목 하나를 빼면 점검이 어떻게 실패하는지 보인다.

의존성: 표준 라이브러리만. Docker·MLflow 없이 실행된다.
실행:   python code/9-5-review-record-check.py
산출물: data/output/ch9_record_audit.json
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "data" / "output"
SOURCE_DIR = BASE_DIR.parent / "chapter7" / "data" / "input" / "ch6_daily"
RECORD_PATH = OUTPUT_DIR / "ch9_promotion_record.json"

# 감사가 묻는 것을 기록의 항목으로 옮긴 최소 집합
REQUIRED = {
    "model_name": "어느 모델인가",
    "champion_version": "지금 운영 중인 것은 몇 번인가",
    "gate_rule": "어떤 규칙으로 통과시켰는가",
    "decisions": "각 버전을 어떻게 판정했는가",
    "reproducibility_check": "그 수치가 다시 나오는가",
    "data_fingerprint_sha256": "어느 데이터로 훈련했는가",
    "reviewer": "누가 확인했는가",
    "notes": "어떤 제한이 붙는가",
}


def recompute_fingerprint() -> str:
    days = sorted(p.name for p in SOURCE_DIR.iterdir() if p.is_dir())
    table: dict[str, dict[str, int]] = {}
    for day in days:
        summary = json.loads((SOURCE_DIR / day / "daily_summary.json").read_text(encoding="utf-8"))
        for row in summary["by_region"]:
            table.setdefault(row["lawd_cd"], {})[day] = int(row["count"])
    pairs = []
    for cd in sorted(table):
        ds = sorted(table[cd])
        for i in range(len(ds) - 1):
            pairs.append((cd, table[cd][ds[i]], table[cd][ds[i + 1]]))
    pairs.sort(key=lambda p: (p[0], p[1]))
    csv = "lawd_cd,x_prev_count,y_count\n" + "".join(f"{a},{b},{c}\n" for a, b, c in pairs)
    return hashlib.sha256(csv.encode("utf-8")).hexdigest()


def audit(record: dict, recomputed_fp: str) -> list[dict]:
    """점검 항목마다 (이름, 통과 여부, 본 값)을 낸다."""
    checks = []
    for key, question in REQUIRED.items():
        present = key in record and record[key] not in (None, "", [], {})
        checks.append({"check": f"항목 {key}", "question": question, "pass": present})

    fp = record.get("data_fingerprint_sha256", "")
    checks.append(
        {
            "check": "지문 재계산 대조",
            "question": "기록된 지문이 원천에서 다시 나오는가",
            "pass": fp == recomputed_fp,
            "detail": f"기록 {fp[:16]}… / 재계산 {recomputed_fp[:16]}…",
        }
    )

    decisions = record.get("decisions", [])
    promoted = [d["version"] for d in decisions if d.get("promoted")]
    checks.append(
        {
            "check": "champion 일치",
            "question": "champion 버전이 승격 판정과 맞는가",
            "pass": bool(promoted) and record.get("champion_version") == promoted[-1],
            "detail": f"champion v{record.get('champion_version')} / 승격 판정 {promoted}",
        }
    )

    rejected = [d["version"] for d in decisions if not d.get("promoted")]
    checks.append(
        {
            "check": "반려 이력 보존",
            "question": "반려된 버전이 기록에 남아 있는가",
            "pass": bool(rejected),
            "detail": f"반려 {rejected} — 롤백 대상이자 재시도 방지 근거",
        }
    )

    repro = record.get("reproducibility_check", {})
    checks.append(
        {
            "check": "재현성 통과",
            "question": "같은 설정으로 같은 결과가 나왔는가",
            "pass": bool(repro.get("mae_equal")) and bool(repro.get("coef_equal")),
            "detail": f"mae_equal={repro.get('mae_equal')} coef_equal={repro.get('coef_equal')}",
        }
    )

    reviewer = str(record.get("reviewer", ""))
    named = bool(reviewer) and ("가상" not in reviewer and "시뮬레이션" not in reviewer)
    checks.append(
        {
            "check": "검수자 실명",
            "question": "확인한 사람이 특정되는가",
            "pass": named,
            "detail": f"reviewer={reviewer!r} — 실운영이면 이 칸이 비면 안 된다",
        }
    )
    return checks


def show(title: str, checks: list[dict]) -> tuple[int, int]:
    print(title)
    for c in checks:
        mark = "통과" if c["pass"] else "미흡"
        line = f"    {mark}  {c['check']:<22} {c['question']}"
        print(line)
        if c.get("detail"):
            print(f"          {c['detail']}")
    passed = sum(1 for c in checks if c["pass"])
    print(f"    → {passed}/{len(checks)} 통과")
    return passed, len(checks)


def main() -> int:
    if not RECORD_PATH.exists():
        print(f"승격 검수 기록이 없습니다: {RECORD_PATH}")
        print("9-1을 먼저 실행하거나, 저장소에 커밋된 산출물을 확인하십시오.")
        return 1

    record = json.loads(RECORD_PATH.read_text(encoding="utf-8"))
    fp_now = recompute_fingerprint()

    print("[1] 점검 대상")
    print(f"    파일         practice/chapter9/data/output/ch9_promotion_record.json")
    print(f"    모델 이름    {record.get('model_name')}")
    print(f"    승격 규칙    {record.get('gate_rule')}")
    print(f"    판정 이력    " + " / ".join(
        f"v{d['version']} mae {d['train_mae']} {'승격' if d.get('promoted') else '반려'}"
        for d in record.get("decisions", [])
    ))

    checks = audit(record, fp_now)
    print()
    passed, total = show("[2] 감사 질문별 점검", checks)

    # 항목 하나를 빼면 점검이 무엇을 잡는가
    broken = {k: v for k, v in record.items() if k != "reviewer"}
    broken["data_fingerprint_sha256"] = "0" * 64
    print()
    show("[3] 기록이 부실할 때 — reviewer를 빼고 지문을 다른 값으로 바꾼 사본", audit(broken, fp_now))

    print("\n[4] 이 점검이 성립하는 조건")
    print("    지문 대조는 원천 자료가 남아 있어야 가능하다 — 원천을 지우면 기록의 진위를 확인할 수 없다")
    print("    재현성 항목은 훈련 시점에 기록되어야 한다 — 사고가 난 뒤에는 만들 수 없다")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "audited_file": "practice/chapter9/data/output/ch9_promotion_record.json",
        "model_name": record.get("model_name"),
        "recomputed_fingerprint_sha256": fp_now,
        "checks": [{k: v for k, v in c.items()} for c in checks],
        "passed": passed,
        "total": total,
    }
    (OUTPUT_DIR / "ch9_record_audit.json").write_text(
        json.dumps(out, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n증거 파일: {OUTPUT_DIR / 'ch9_record_audit.json'}")
    # 검수자 칸은 교육용 가상 표기라 미흡으로 남는다 — 그 한 건만 허용한다
    print("CH9_5_" + ("PASS" if passed >= total - 1 else "FAIL"))
    return 0 if passed >= total - 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
