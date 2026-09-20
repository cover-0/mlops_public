#!/usr/bin/env python3
"""6주차 실습 6-4: 태스크 그래프의 순서, 실패 전파, 품질 게이트.

6-1의 Airflow DAG와 같은 그래프(검증 → 정제 → [집계 ∥ 품질] → 보고서)를
표준 라이브러리만으로 만든 작은 실행기로 돌린다. Airflow를 설치할 수 없는 환경
에서도 세 가지를 눈으로 확인하려는 목적이다.

  (1) 선언한 의존성만 순서를 보장한다 — 집계와 품질 점검 사이에는 순서가 없다.
  (2) 상류가 실패하면 하류는 실행되지 않고(upstream_failed) 산출물도 남지 않는다.
  (3) 총계 보존식이 깨지면 품질 게이트가 막아 보고서가 아예 만들어지지 않는다.

산출물은 임시 폴더에 쓰고 실행이 끝나면 지운다 — 저장소의 기존 산출물을 건드리지
않는다. 입력은 6주차 원천(data/input/)뿐이다.

실행:
    python code/6-4-dag-order.py
"""

from __future__ import annotations

import csv
import json
import tempfile
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "data" / "input"
ALIASES = {"강남": "강남구", "마포": "마포구", "관악": "관악구"}

# 의존성 선언 — 6-1 DAG의 `t_validate >> t_clean >> [t_aggregate, t_quality] >> t_report`
# 와 같은 그래프다. 값은 "이 태스크가 기다리는 상류 태스크" 목록이다.
DEPENDS_ON: dict[str, list[str]] = {
    "validate_input": [],
    "clean_and_map": ["validate_input"],
    "aggregate_daily": ["clean_and_map"],
    "check_quality": ["clean_and_map"],
    "write_report": ["aggregate_daily", "check_quality"],
}


# ── 그래프 유틸 ──────────────────────────────────────────────────
def topological_order(deps: dict[str, list[str]]) -> list[str]:
    """실행 가능한 순서 하나를 만든다. 동순위는 이름순으로 골라 결정적으로 만든다."""
    remaining = {t: set(ups) for t, ups in deps.items()}
    order: list[str] = []
    while remaining:
        ready = sorted(t for t, ups in remaining.items() if not ups)
        if not ready:
            raise ValueError("순환 의존 — 비순환 그래프가 아니다")
        pick = ready[0]
        order.append(pick)
        del remaining[pick]
        for ups in remaining.values():
            ups.discard(pick)
    return order


def reaches(deps: dict[str, list[str]], src: str, dst: str) -> bool:
    """src 가 dst 의 상류인가(경로가 있는가)."""
    stack = list(deps[dst])
    while stack:
        node = stack.pop()
        if node == src:
            return True
        stack.extend(deps[node])
    return False


# ── 태스크 본체 ──────────────────────────────────────────────────
def load_mapping() -> dict[str, str]:
    with open(INPUT_DIR / "lawd_cd_seoul.csv", encoding="utf-8") as f:
        return {row["region_std"]: row["lawd_cd"] for row in csv.DictReader(f)}


def t_validate_input(ds: str, out: Path, **_) -> None:
    path = INPUT_DIR / "complaints" / f"{ds}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"입력 파일 없음: {path.name}")
    with open(path, encoding="utf-8") as f:
        n = sum(1 for line in f if line.strip())
    (out / "validated.json").write_text(json.dumps({"rows": n}), encoding="utf-8")


def t_clean_and_map(ds: str, out: Path, drop_silently: bool = False, **_) -> None:
    mapping = load_mapping()
    with open(INPUT_DIR / "complaints" / f"{ds}.jsonl", encoding="utf-8") as f:
        recs = [json.loads(line) for line in f if line.strip()]

    seen: set[str] = set()
    dup = 0
    valid = []
    for rec in recs:
        if rec["complaint_id"] in seen:
            dup += 1
            continue
        seen.add(rec["complaint_id"])
        valid.append(rec)

    mapped, missing, unmapped = [], 0, 0
    for rec in valid:
        name = (rec.get("region_raw") or "").strip()
        if not name:
            missing += 1
            continue
        name = ALIASES.get(name, name)
        if name in mapping:
            mapped.append({**rec, "region_std": name, "lawd_cd": mapping[name]})
        else:
            unmapped += 1

    if drop_silently:
        # 주입한 결함: 매핑 실패를 세지 않고 버린다(조용한 누락).
        unmapped = 0

    with open(out / "cleaned.jsonl", "w", encoding="utf-8") as f:
        for rec in mapped:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    quality = {
        "date": ds, "physical": len(recs), "dup_removed": dup, "valid": len(valid),
        "mapped": len(mapped), "missing": missing, "unmapped": unmapped,
        "preservation_ok": len(recs) == len(mapped) + missing + unmapped + dup,
    }
    (out / "quality.json").write_text(json.dumps(quality, ensure_ascii=False), encoding="utf-8")


def t_aggregate_daily(ds: str, out: Path, **_) -> None:
    with open(out / "cleaned.jsonl", encoding="utf-8") as f:
        mapped = [json.loads(line) for line in f]
    by_region = Counter((r["lawd_cd"], r["region_std"]) for r in mapped)
    summary = {
        "date": ds,
        "mapped_total": len(mapped),
        "by_region": [{"lawd_cd": c, "region": n, "count": v}
                      for (c, n), v in sorted(by_region.items())],
    }
    (out / "daily_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def t_check_quality(ds: str, out: Path, **_) -> None:
    quality = json.loads((out / "quality.json").read_text(encoding="utf-8"))
    if not quality["preservation_ok"]:
        raise ValueError(
            f"총계 보존 실패: {quality['physical']} ≠ {quality['mapped']} + "
            f"{quality['missing']} + {quality['unmapped']} + {quality['dup_removed']}"
        )
    (out / "quality_check.json").write_text(
        json.dumps({**quality, "gate": "PASS"}, ensure_ascii=False), encoding="utf-8")


def t_write_report(ds: str, out: Path, **_) -> None:
    summary = json.loads((out / "daily_summary.json").read_text(encoding="utf-8"))
    check = json.loads((out / "quality_check.json").read_text(encoding="utf-8"))
    lines = [f"# 일별 민원 요약 보고서 — {ds}", "",
             f"- 원천 접수: {check['physical']}건, 매핑 {check['mapped']}건"]
    for row in summary["by_region"]:
        lines.append(f"| {row['lawd_cd']} | {row['region']} | {row['count']} |")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


CALLABLES = {
    "validate_input": t_validate_input,
    "clean_and_map": t_clean_and_map,
    "aggregate_daily": t_aggregate_daily,
    "check_quality": t_check_quality,
    "write_report": t_write_report,
}
ARTIFACTS = ("validated.json", "cleaned.jsonl", "quality.json",
             "daily_summary.json", "quality_check.json", "report.md")


def run_dag(ds: str, out: Path, **kw) -> tuple[str, list[tuple[str, str, str]]]:
    """태스크를 순서대로 돌린다. 상류가 실패하면 하류는 실행하지 않는다."""
    states: dict[str, str] = {}
    log: list[tuple[str, str, str]] = []
    for task in topological_order(DEPENDS_ON):
        bad = [u for u in DEPENDS_ON[task] if states[u] != "success"]
        if bad:
            states[task] = "upstream_failed"
            log.append((task, "upstream_failed", f"{bad[0]} 이(가) 끝나지 않음"))
            continue
        try:
            CALLABLES[task](ds=ds, out=out, **kw)
            states[task] = "success"
            log.append((task, "success", ""))
        except Exception as exc:  # 태스크 실패는 상태로 남긴다
            states[task] = "failed"
            log.append((task, "failed", f"{type(exc).__name__}: {exc}"))
    run_state = "success" if all(s == "success" for s in states.values()) else "failed"
    return run_state, log


def show(title: str, ds: str, out: Path, **kw) -> None:
    out.mkdir(parents=True, exist_ok=True)
    state, log = run_dag(ds, out, **kw)
    print(f"{title}  dagrun={state}")
    for task, st, note in log:
        print(f"    {task:<16} {st:<16} {note}")
    made = [name for name in ARTIFACTS if (out / name).exists()]
    print(f"    남은 산출물 {len(made)}개: {', '.join(made) if made else '없음'}")


def main() -> int:
    order = topological_order(DEPENDS_ON)
    print("[1] 의존성 선언에서 나오는 실행 순서")
    print("    " + " → ".join(order))
    pairs = [(a, b) for a in DEPENDS_ON for b in DEPENDS_ON if a < b]
    fixed = [(a, b) for a, b in pairs if reaches(DEPENDS_ON, a, b) or reaches(DEPENDS_ON, b, a)]
    free = [(a, b) for a, b in pairs if (a, b) not in fixed]
    print(f"    순서가 정해진 쌍 {len(fixed)}개 / 정해지지 않은 쌍 {len(free)}개")
    for a, b in free:
        print(f"    순서 없음: {a} 와 {b} — 실행마다 선후가 달라질 수 있음")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print("\n[2] 2026-07-01 — 입력이 있는 날")
        show("   ", "2026-07-01", tmp / "ok" / "2026-07-01")

        print("\n[3] 2026-07-04 — 입력 파일이 없는 날")
        show("   ", "2026-07-04", tmp / "ok" / "2026-07-04")

        print("\n[4] 정제에 누락 결함을 심은 2026-07-01 — 품질 게이트가 막는가")
        print("    주입한 결함: 매핑 실패 건수를 세지 않고 버린다(drop_silently=True)")
        show("   ", "2026-07-01", tmp / "broken" / "2026-07-01", drop_silently=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
