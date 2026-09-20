#!/usr/bin/env python3
"""6주차 실습 6-2: 배치의 마감은 달력이 정하고, 배치는 구간 전량을 한 번에 본다.

스트리밍(5주차)은 데이터가 마감을 정했다 — 워터마크를 넘겨 도착한 이벤트는 폐기됐다.
배치는 달력이 마감을 정한다 — "7월 1일분"은 그 날짜 파일 전체이며, 파일이 손에
들어온 뒤에 계산하므로 늦게 도착한 것도 같은 구간에 들어간다.

이 스크립트는 6주차 원천 입력(data/input/complaints/*.jsonl)만 읽는다.
표준 라이브러리만 쓰며 Airflow·Docker·네트워크가 필요 없다.

실행:
    python code/6-2-cutoff-scope.py
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter, defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "data" / "input" / "complaints"
DATES = ("2026-07-01", "2026-07-02", "2026-07-03")

# 5주차 스트리밍 실습이 쓴 창 길이(분). practice/chapter5/data/output/ch5_late_event_report.json
# 의 window_size = "10 minutes"와 같은 값이다.
STREAM_WINDOW_MIN = 10


def read_day(ds: str) -> list[dict]:
    path = INPUT_DIR / f"{ds}.jsonl"
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def minutes(iso: str) -> dt.datetime:
    return dt.datetime.fromisoformat(iso)


def main() -> int:
    days = {ds: read_day(ds) for ds in DATES}

    print("[1] 입력 — 날짜 하나가 파일 하나다")
    total = 0
    for ds, recs in days.items():
        times = sorted(minutes(r["created_at"]) for r in recs)
        total += len(recs)
        print(
            f"    {ds}.jsonl  물리 레코드 {len(recs):>2}건  "
            f"첫 접수 {times[0]:%H:%M}  마지막 접수 {times[-1]:%H:%M}"
        )
    print(f"    사흘 합계 {total}건")

    print("\n[2] 달력 마감 — 파일 안의 레코드가 모두 그 날짜인가")
    for ds, recs in days.items():
        off = [r["complaint_id"] for r in recs if minutes(r["created_at"]).date().isoformat() != ds]
        verdict = "전부 같은 날짜" if not off else f"다른 날짜 {len(off)}건: {off}"
        print(f"    {ds}: {verdict}")
    print("    → 구간의 경계를 데이터가 아니라 달력이 정함. 마감 시각까지 도착한 것은 늦어도 이 구간에 들어감")

    print("\n[3] 전체 조망 — 하루치를 통째로 쥐면 전수 중복 검사가 성립한다")
    found = False
    for ds, recs in days.items():
        seen: dict[str, dt.datetime] = {}
        for r in recs:
            cid, t = r["complaint_id"], minutes(r["created_at"])
            if cid in seen:
                found = True
                gap = int((t - seen[cid]).total_seconds() // 60)
                print(f"    {ds}: {cid} 가 두 번 — {seen[cid]:%H:%M} 과 {t:%H:%M}, 간격 {gap}분")
                print(f"           5주차 창 길이 {STREAM_WINDOW_MIN}분 기준으로 "
                      f"같은 창에서 만나는가: {'예' if gap < STREAM_WINDOW_MIN else '아니오'}")
            else:
                seen[cid] = t
    if not found:
        print("    중복 없음")
    print("    → 창 하나만 보는 처리는 이 쌍을 같은 창에서 만나지 못해 중복을 못 지움")

    print("\n[4] 하루 안에서의 접수 분포 — 배치가 한 번에 보는 범위")
    for ds, recs in days.items():
        by_hour: Counter = Counter(minutes(r["created_at"]).hour for r in recs)
        span = f"{min(by_hour)}시~{max(by_hour)}시"
        print(f"    {ds}: 접수 시각대 {span}, 시각대 {len(by_hour)}개에 걸침")
    print(f"    → 한 구간이 {STREAM_WINDOW_MIN}분 창 여러 개에 흩어져 있어도 배치는 한 번에 셈")

    print("\n[5] 지역 표기의 원문 — 정제 전에는 이렇게 들어와 있다")
    raw_count: dict[str, int] = defaultdict(int)
    for recs in days.values():
        for r in recs:
            raw_count[repr(r["region_raw"])] += 1
    for raw, cnt in sorted(raw_count.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {raw:<12} {cnt:>2}건")
    print(f"    원문 표기 {len(raw_count)}가지 — 정제는 6-3에서 이어감")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
