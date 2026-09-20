#!/usr/bin/env python3
"""7주차 7-3: offline store와 online store, 그리고 적재(materialize)의 침묵 실패.

6주차 확정 집계를 (키, 알려진 시점, 값) 행으로 편 뒤
    offline store = 이력 전체
    online store  = 키별 최신 1행
두 저장소를 파이썬 자료구조로 만들고, 적재 창을 바꿔 가며
'아무것도 적재되지 않아도 오류가 나지 않는' 상황을 재현한다.

Feast 엔진 없이 같은 규칙만 구현한 것이며, 마지막에 7-1이 남긴
data/output/ch7_consistency_report.json과 값을 대조한다.

실행: python code/7-3-materialize-consistency.py
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "data" / "input" / "ch6_daily"
OUTPUT_DIR = BASE_DIR / "data" / "output"

DAYS = ["2026-07-01", "2026-07-02", "2026-07-03"]
TTL = timedelta(days=3)

# 구성값 — 증분 적재의 기본 시작점("현재 시각 − TTL")을 재현하려고 코드에 고정한다.
# 실제 시계를 쓰면 실행할 때마다 창이 달라져 로그를 대조할 수 없다.
RUN_AS_OF = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)


def iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_offline_rows() -> list[dict]:
    """일별 집계 → 피처 행. 타임스탬프는 '값이 알려진 시점'(대상일 다음 날 00:00 UTC)."""
    rows = []
    for day in DAYS:
        base = INPUT_DIR / day
        summary = json.loads((base / "daily_summary.json").read_text(encoding="utf-8"))
        check = json.loads((base / "quality_check.json").read_text(encoding="utf-8"))
        known_at = datetime.fromisoformat(day + "T00:00:00+00:00") + timedelta(days=1)
        for r in summary["by_region"]:
            rows.append({
                "lawd_cd": r["lawd_cd"],
                "region": r["region"],
                "event_timestamp": known_at,
                "complaint_count": int(r["count"]),
                "day_unmapped_rate": float(check["unmapped_rate"]),
            })
    rows.sort(key=lambda r: (r["event_timestamp"], r["lawd_cd"]))
    return rows


def materialize(rows: list[dict], start: datetime, end: datetime) -> tuple[dict, int]:
    """창 [start, end] 안의 행만 골라 키별 최신 1행을 online store에 남긴다."""
    picked = [r for r in rows if start <= r["event_timestamp"] <= end]
    online: dict[str, dict] = {}
    for r in picked:
        cur = online.get(r["lawd_cd"])
        if cur is None or r["event_timestamp"] > cur["event_timestamp"]:
            online[r["lawd_cd"]] = r
    return online, len(picked)


def offline_latest(rows: list[dict]) -> dict:
    latest: dict[str, dict] = {}
    for r in rows:
        cur = latest.get(r["lawd_cd"])
        if cur is None or r["event_timestamp"] > cur["event_timestamp"]:
            latest[r["lawd_cd"]] = r
    return latest


def consistency(latest: dict, online: dict) -> dict:
    checks = []
    for cd in sorted(latest):
        off = latest[cd]
        on = online.get(cd)
        checks.append({
            "lawd_cd": cd,
            "offline": (off["complaint_count"], round(off["day_unmapped_rate"], 3)),
            "online": None if on is None else (on["complaint_count"], round(on["day_unmapped_rate"], 3)),
        })
        checks[-1]["consistent"] = checks[-1]["offline"] == checks[-1]["online"]
    return {
        "checked_keys": len(checks),
        "all_consistent": all(c["consistent"] for c in checks),
        "rows": checks,
    }


def print_consistency(report: dict) -> None:
    print(f"    {'키':<8}{'오프라인 최신':<18}{'온라인 조회':<18}일치")
    for c in report["rows"]:
        off = "{} / {}".format(*c["offline"])
        on = "없음(None)" if c["online"] is None else "{} / {}".format(*c["online"])
        print(f"    {c['lawd_cd']:<8}{off:<20}{on:<20}{'예' if c['consistent'] else '아니오'}")
    print(f"    checked_keys {report['checked_keys']}, "
          f"all_consistent {report['all_consistent']}")


def main() -> int:
    rows = build_offline_rows()

    print(f"[1] offline store — 피처 이력 전체 {len(rows)}행 "
          f"({len(DAYS)}일 × 지역구 {len(rows) // len(DAYS)}개)")
    print(f"    {'lawd_cd':<10}{'지역':<8}{'알려진 시점':<24}{'건수':>6}{'미매핑율':>10}")
    for r in rows:
        print(f"    {r['lawd_cd']:<10}{r['region']:<8}{iso(r['event_timestamp']):<24}"
              f"{r['complaint_count']:>6}{r['day_unmapped_rate']:>10.3f}")

    start, end = datetime(2026, 7, 1, tzinfo=timezone.utc), RUN_AS_OF
    online, picked = materialize(rows, start, end)
    print()
    print(f"[2] materialize — 적재 창을 명시해서 호출")
    print(f"    창 [{iso(start)}, {iso(end)}]")
    print(f"    창 안의 원천 {picked}행 → online store {len(online)}행(키별 최신 1행)")
    for cd in sorted(online):
        r = online[cd]
        print(f"    {cd}  {r['region']:<6}{r['complaint_count']:>4}  "
              f"{r['day_unmapped_rate']:.3f}  @{iso(r['event_timestamp'])}")

    latest = offline_latest(rows)
    ok_report = consistency(latest, online)
    print()
    print("[3] 훈련-서빙 일관성 점검 — 오프라인 최신값 대 온라인 조회값")
    print_consistency(ok_report)

    inc_start = RUN_AS_OF - TTL
    inc_online, inc_picked = materialize(rows, inc_start, RUN_AS_OF)
    print()
    print("[4] 같은 적재를 증분 호출로 하면 — 시작점이 '기준 시각 − TTL'")
    print(f"    기준 시각 {iso(RUN_AS_OF)}(구성값), TTL {TTL.days}일")
    print(f"    창 [{iso(inc_start)}, {iso(RUN_AS_OF)}]")
    print(f"    창 안의 원천 {inc_picked}행 → online store {len(inc_online)}행")
    print("    예외 없음, 오류 로그 없음 — 적재 작업은 성공으로 끝남")
    bad_report = consistency(latest, inc_online)
    print("    이 상태에서 온라인을 조회하면")
    print_consistency(bad_report)

    print()
    print("[5] 7-1이 Feast로 남긴 산출물과 대조")
    ref_path = OUTPUT_DIR / "ch7_consistency_report.json"
    if ref_path.exists():
        ref = json.loads(ref_path.read_text(encoding="utf-8"))
        same_keys = ref["checked_keys"] == ok_report["checked_keys"]
        same_flag = ref["all_consistent"] == ok_report["all_consistent"]
        ref_vals = {
            r["lawd_cd"]: (r["online"]["complaint_count"], r["online"]["day_unmapped_rate"])
            for r in ref["rows"]
        }
        mine = {c["lawd_cd"]: c["online"] for c in ok_report["rows"]}
        print(f"    ch7_consistency_report.json: checked_keys {ref['checked_keys']}, "
              f"all_consistent {ref['all_consistent']}")
        print(f"    이 실행:                     checked_keys {ok_report['checked_keys']}, "
              f"all_consistent {ok_report['all_consistent']}")
        print(f"    키별 온라인 값 일치: {'예' if ref_vals == mine else '아니오'} "
              f"({len(ref_vals)}개 키)")
        print(f"    두 값이 같다 = 규칙을 같게 구현했다는 뜻이지 "
              f"엔진을 다시 돌렸다는 뜻이 아님")
        matched = same_keys and same_flag and ref_vals == mine
    else:
        print(f"    {ref_path.name}이 없어 대조를 건너뜀")
        matched = False

    print("CH7_3_RUN_" + ("PASS" if (ok_report["all_consistent"] and not bad_report["all_consistent"] and matched) else "FAIL"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
