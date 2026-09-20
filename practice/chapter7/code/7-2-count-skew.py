#!/usr/bin/env python3
"""7주차 7-2: 같은 날 민원 건수를 세 곳에서 따로 세면 — 훈련-서빙 스큐 재현.

읽는 것은 6주차 배치가 확정한 일별 산출물뿐이다.
    data/input/ch6_daily/{날짜}/quality_check.json
    data/input/ch6_daily/{날짜}/daily_summary.json

정제 단계를 어디까지 적용하느냐에 따라 "그날 민원 건수"가 몇으로 갈리는지,
그리고 그 차이가 오류 없이 지나가는지를 보인다.
난수를 쓰지 않고 외부 의존도 없다(표준 라이브러리만).

실행: python code/7-2-count-skew.py
"""

from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "data" / "input" / "ch6_daily"

DAYS = ["2026-07-01", "2026-07-02", "2026-07-03"]
FOCUS_DAY = "2026-07-02"


def load_day(day: str) -> tuple[dict, dict]:
    base = INPUT_DIR / day
    quality = json.loads((base / "quality_check.json").read_text(encoding="utf-8"))
    summary = json.loads((base / "daily_summary.json").read_text(encoding="utf-8"))
    return quality, summary


def main() -> int:
    days = {d: load_day(d) for d in DAYS}

    print(f"[1] 원천 — 6주차 일별 배치 산출물 {len(DAYS)}일치")
    print(f"    경로 practice/chapter7/data/input/ch6_daily/")
    print("    한 날짜마다 quality_check.json(정제 단계별 건수)과 "
          "daily_summary.json(지역구별 확정 집계)이 있음")

    print()
    print("[2] 어디까지 정제하고 세느냐에 따라 같은 날의 '민원 건수'가 갈림")
    print(f"    {'날짜':<12}{'물리 레코드':>10}{'중복제거 유효':>12}{'표준코드 확정':>12}")
    for day in DAYS:
        q, _ = days[day]
        print(f"    {day:<12}{q['physical']:>12}{q['valid']:>14}{q['mapped']:>14}")

    q, s = days[FOCUS_DAY]
    physical, valid, mapped = q["physical"], q["valid"], q["mapped"]
    print()
    print(f"[3] 세 팀이 각자 '{FOCUS_DAY} 민원 건수' 피처를 만들면")
    lines = [
        ("서빙 API", "운영 DB를 그대로 셈", physical),
        ("분석 부서", f"중복 {q['dup_removed']}건만 제거", valid),
        ("훈련 파이프라인", f"중복 + 미매핑 {q['unmapped']}건까지 제외", mapped),
    ]
    for who, how, cnt in lines:
        print(f"    {who:<10}{how:<30}{cnt:>4}")
    gap = physical - mapped
    print(f"    최댓값과 최솟값의 차 {gap}건 — 확정 집계 대비 {gap / mapped:.1%}")
    by_region = ", ".join("{} {}".format(r["region"], r["count"]) for r in s["by_region"])
    print(f"    셋 다 버그가 아님: 같은 날의 지역구별 확정 집계는 "
          f"{by_region} 합계 {s['mapped_total']}")

    print()
    print("[4] 모델이 확정 집계로 훈련되고 서빙은 물리 레코드를 세면")
    diffs = []
    for day in DAYS:
        qq, _ = days[day]
        d = qq["physical"] - qq["mapped"]
        diffs.append(d)
        print(f"    {day}  훈련 {qq['mapped']:>3}  서빙 {qq['physical']:>3}  차이 {d:+d}")
    print(f"    3일 모두 같은 방향 — 평균 차이 {sum(diffs) / len(diffs):+.2f}건")
    print("    한쪽으로만 치우친 편의라서 평균 보정으로 사라지지 않음")

    print()
    print("[5] 이 실행이 끝나는 방식")
    print("    예외 없음, 종료 코드 0 — 세 값이 어긋난 채로 정상 종료함")
    print("CH7_2_RUN_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
