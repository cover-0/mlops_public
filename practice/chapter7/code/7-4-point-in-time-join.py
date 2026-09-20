#!/usr/bin/env python3
"""7주차 7-4: 시점 조인(point-in-time join)과 미래 누출.

6주차 확정 집계를 피처 행으로 편 뒤, 기준 시점이 다른 훈련 샘플에
  (1) 시점 조인 — 기준 시점 이전에 알려진 값 중 가장 최근 값, TTL 안쪽
  (2) 최신값 조인 — 지금 저장소에 있는 마지막 값
두 규칙을 각각 적용해 결과가 어떻게 갈리는지 보인다.

Feast 엔진 없이 조인 규칙만 구현한 것이며, 마지막에 7-1이 남긴
data/output/ch7_feature_report.json의 historical_join과 값을 대조한다.

실행: python code/7-4-point-in-time-join.py
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

# 훈련 샘플: (조인 키, 기준 시점). 09:00은 "오전 9시에 그날 인력 배치를 정한다"는
# 업무 시나리오에서 나온 값이며 코드에 고정한다.
SAMPLES = [
    ("11620", datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)),
    ("11680", datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)),
    ("11440", datetime(2026, 7, 3, 9, 0, tzinfo=timezone.utc)),
    ("11680", datetime(2026, 7, 4, 9, 0, tzinfo=timezone.utc)),
]
TTL_SAMPLE = ("11680", datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc))


def iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_feature_rows() -> list[dict]:
    rows = []
    for day in DAYS:
        base = INPUT_DIR / day
        summary = json.loads((base / "daily_summary.json").read_text(encoding="utf-8"))
        check = json.loads((base / "quality_check.json").read_text(encoding="utf-8"))
        known_at = datetime.fromisoformat(day + "T00:00:00+00:00") + timedelta(days=1)
        for r in summary["by_region"]:
            rows.append({
                "lawd_cd": r["lawd_cd"],
                "covers": day,
                "event_timestamp": known_at,
                "complaint_count": int(r["count"]),
                "day_unmapped_rate": round(float(check["unmapped_rate"]), 3),
            })
    rows.sort(key=lambda r: (r["event_timestamp"], r["lawd_cd"]))
    return rows


def point_in_time(rows: list[dict], cd: str, as_of: datetime):
    """기준 시점 이전에 알려진 값 중 가장 최근 값. TTL을 넘으면 붙이지 않는다."""
    cands = [r for r in rows if r["lawd_cd"] == cd and r["event_timestamp"] <= as_of]
    if not cands:
        return None, "확정된 값 없음"
    best = max(cands, key=lambda r: r["event_timestamp"])
    age = as_of - best["event_timestamp"]
    if age > TTL:
        return None, f"가장 최근 값이 {age.days}일 {age.seconds // 3600}시간 전 — TTL {TTL.days}일 초과"
    return best, f"간격 {age.days}일 {age.seconds // 3600}시간"


def latest_value(rows: list[dict], cd: str):
    cands = [r for r in rows if r["lawd_cd"] == cd]
    return max(cands, key=lambda r: r["event_timestamp"]) if cands else None


def main() -> int:
    rows = build_feature_rows()

    print(f"[1] 피처 원천 {len(rows)}행 — 타임스탬프는 '값이 알려진 시점'")
    print("    규약: 대상일의 집계는 그날이 끝나야 확정되므로 대상일 다음 날 00:00 UTC")
    print(f"    {'lawd_cd':<10}{'대상일':<14}{'알려진 시점':<24}{'건수':>6}{'미매핑율':>10}")
    for r in rows:
        print(f"    {r['lawd_cd']:<10}{r['covers']:<14}{iso(r['event_timestamp']):<24}"
              f"{r['complaint_count']:>6}{r['day_unmapped_rate']:>10.3f}")

    print()
    print(f"[2] 시점 조인 — 훈련 샘플 {len(SAMPLES)}행")
    joined, dropped = [], []
    for cd, as_of in SAMPLES:
        hit, why = point_in_time(rows, cd, as_of)
        if hit is None:
            dropped.append((cd, as_of, why))
            continue
        joined.append({"lawd_cd": cd, "as_of": as_of, "row": hit})
        print(f"    {cd}  as_of {iso(as_of)}  →  건수 {hit['complaint_count']}, "
              f"미매핑율 {hit['day_unmapped_rate']:.3f}")
        print(f"           쓴 피처: {hit['covers']}분, 알려진 시점 {iso(hit['event_timestamp'])} ({why})")
    print(f"    입력 {len(SAMPLES)}행 → 결과 {len(joined)}행 (탈락 {len(dropped)}행)")
    for cd, as_of, why in dropped:
        print(f"    탈락: {cd}  as_of {iso(as_of)}  — {why}")
    print("    탈락 행은 빈 값으로 남지 않고 결과에서 사라짐 — 오류도 경고도 없음")

    print()
    print("[3] 같은 입력에 최신값 조인을 하면 — 미래 누출")
    print(f"    {'lawd_cd':<10}{'as_of':<24}{'시점 조인':>10}{'최신값 조인':>12}")
    leaked = 0
    for cd, as_of in SAMPLES:
        hit, _ = point_in_time(rows, cd, as_of)
        last = latest_value(rows, cd)
        pit = "탈락" if hit is None else str(hit["complaint_count"])
        now = "-" if last is None else str(last["complaint_count"])
        if pit != now:
            leaked += 1
        print(f"    {cd:<10}{iso(as_of):<24}{pit:>10}{now:>12}")
    print(f"    4행 모두 값이 붙어 훈련 셋은 줄지 않지만, 어긋난 행 {leaked}개")
    print("    7/1 09:00 샘플에는 아직 확정되지 않은 값이 붙고,")
    print("    7/2 09:00 샘플에는 그날 이후에 확정될 값이 붙음")

    print()
    print("[4] TTL 하한 — 알려진 값이어도 오래되면 붙이지 않음")
    cd, as_of = TTL_SAMPLE
    hit, why = point_in_time(rows, cd, as_of)
    last = latest_value(rows, cd)
    print(f"    {cd}  as_of {iso(as_of)}")
    print(f"    as_of 이전 최신 = {iso(last['event_timestamp'])} (건수 {last['complaint_count']})")
    print(f"    결과: {'탈락' if hit is None else hit['complaint_count']} — {why}")
    print("    배치가 TTL보다 오래 멈추면 훈련 샘플이 이 방식으로 조용히 사라짐")

    print()
    print("[5] 7-1이 Feast로 남긴 산출물과 대조")
    ref_path = OUTPUT_DIR / "ch7_feature_report.json"
    matched = False
    if ref_path.exists():
        ref = json.loads(ref_path.read_text(encoding="utf-8"))
        ref_join = {
            (r["lawd_cd"], r["as_of"][:19]): (r["complaint_count"], r["day_unmapped_rate"])
            for r in ref["historical_join"]
        }
        mine = {
            (j["lawd_cd"], j["as_of"].strftime("%Y-%m-%dT%H:%M:%S")):
                (j["row"]["complaint_count"], j["row"]["day_unmapped_rate"])
            for j in joined
        }
        print(f"    ch7_feature_report.json: 입력 {ref['entity_rows_requested']}행, "
              f"조인 결과 {len(ref['historical_join'])}행, "
              f"탈락 {len(ref['historical_dropped_rows'])}행 "
              f"(feast {ref['feast_version']})")
        print(f"    이 실행:                 입력 {len(SAMPLES)}행, "
              f"조인 결과 {len(joined)}행, 탈락 {len(dropped)}행")
        print(f"    키·시점별 값 일치: {'예' if ref_join == mine else '아니오'} ({len(ref_join)}행)")
        print("    두 값이 같다 = 조인 규칙을 같게 구현했다는 뜻이지 "
              "엔진을 다시 돌렸다는 뜻이 아님")
        matched = ref_join == mine
    else:
        print(f"    {ref_path.name}이 없어 대조를 건너뜀")

    print("CH7_4_RUN_" + ("PASS" if (len(joined) == 3 and len(dropped) == 1 and matched) else "FAIL"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
