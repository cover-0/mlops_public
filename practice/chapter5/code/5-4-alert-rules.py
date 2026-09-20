#!/usr/bin/env python3
"""5-4: 창 집계 위에 알림 규칙을 얹으면 무엇이 깨지는가 — 미확정·중복·침묵.

5-2·5-3과 같은 입력 파일을 읽어 update 모드의 갱신 흐름을 재현하고,
"10분 창에서 같은 지역구 민원이 N건 이상이면 알린다"는 규칙을 그 위에 적용한다.
표준 라이브러리만 쓰고 난수를 쓰지 않는다.

실행:
    python3 code/5-4-alert-rules.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STREAM_DIR = BASE_DIR / "data" / "input" / "stream"
FMT = "%Y-%m-%d %H:%M:%S"

WINDOW_MINUTES = 10
WATERMARK_DELAY_MINUTES = 10
THRESHOLDS = (4, 3)
RULE_ID = "R-민원급증"


def load_batches() -> list[tuple[str, list[dict]]]:
    files = sorted(STREAM_DIR.glob("*.json"))
    if not files:
        raise SystemExit(
            f"입력 파일이 없다: {STREAM_DIR}\n"
            "5-1이 중간에 실패하면 이 디렉터리가 비어 있다. 다음으로 되살린다.\n"
            "    git restore practice/chapter5/data/input/stream"
        )
    batches = []
    for path in files:
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            row["t"] = datetime.strptime(row["event_time"], FMT)
            rows.append(row)
        batches.append((path.name, sorted(rows, key=lambda r: r["t"])))
    return batches


def window_start(t: datetime) -> datetime:
    return t.replace(minute=(t.minute // WINDOW_MINUTES) * WINDOW_MINUTES,
                     second=0, microsecond=0)


def replay() -> tuple[list[dict], dict]:
    """update 모드처럼 파일마다 '바뀐 행'만 모은다. watermark 폐기도 5-3과 같은 규칙."""
    delay = timedelta(minutes=WATERMARK_DELAY_MINUTES)
    counts: dict[tuple[datetime, str], int] = defaultdict(int)
    updates: list[dict] = []
    max_seen = watermark = None
    dropped = 0
    all_times: list[datetime] = []
    for name, rows in load_batches():
        all_times.extend(r["t"] for r in rows)
        changed: dict[tuple[datetime, str], int] = {}
        for row in rows:
            start = window_start(row["t"])
            if watermark is not None and start + timedelta(minutes=WINDOW_MINUTES) <= watermark:
                dropped += 1
                continue
            counts[(start, row["district"])] += 1
            changed[(start, row["district"])] = counts[(start, row["district"])]
        for (start, district), value in changed.items():
            updates.append({"file": name, "window_start": start,
                            "district": district, "count": value})
        batch_max = max(r["t"] for r in rows)
        max_seen = batch_max if max_seen is None else max(max_seen, batch_max)
        watermark = max_seen - delay
    return updates, {"dropped": dropped, "final_counts": dict(counts),
                     "first_event": min(all_times), "last_event": max(all_times)}


def label(start: datetime) -> str:
    return f"{start:%H:%M}-{start + timedelta(minutes=WINDOW_MINUTES):%H:%M}"


def main() -> None:
    updates, state = replay()

    print(f"[1] update 모드가 내보낸 '바뀐 행' {len(updates)}건")
    for u in updates:
        print(f"    {u['file']:<12} 창 {label(u['window_start']):<12} {u['district']} {u['count']}")

    for threshold in THRESHOLDS:
        fires = [u for u in updates if u["count"] >= threshold]
        keys = {(u["window_start"], u["district"], RULE_ID) for u in fires}
        print(f"\n[{THRESHOLDS.index(threshold) + 2}] 임계 {threshold}건 — 갱신마다 조건을 다시 평가하면")
        if not fires:
            print("    발화 0건")
        for u in fires:
            print(f"    발화  {u['file']}에서 창 {label(u['window_start'])} {u['district']} "
                  f"{u['count']}건")
        print(f"    발화 {len(fires)}회, 중복 제거 키(창 시작·지역구·규칙 ID)로 묶으면 {len(keys)}회 "
              f"→ 중복 {len(fires) - len(keys)}회")

    print("\n[4] 발화 시점 — 창이 끝난 뒤에 도착한 이벤트로 임계에 닿는다")
    for u in updates:
        if u["count"] >= min(THRESHOLDS) and u["file"] != "batch1.json":
            end = u["window_start"] + timedelta(minutes=WINDOW_MINUTES)
            confirmed = end + timedelta(minutes=WATERMARK_DELAY_MINUTES)
            print(f"    창 {label(u['window_start'])} {u['district']} {u['count']}건이 "
                  f"{u['file']} 처리 시점에 임계에 닿음")
            print(f"    창의 끝은 {end:%H:%M}, 확정까지 기다리면 이벤트 시간 기준 {confirmed:%H:%M} "
                  f"이후 — 확정 알림은 최소 {WATERMARK_DELAY_MINUTES}분 늦음")
            break

    print("\n[5] 침묵 — 건수 0인 창은 0으로 나오지 않고 행 자체가 없다")
    lo = window_start(state["first_event"])
    hi = window_start(state["last_event"])
    print(f"    이벤트 시각 범위 {state['first_event']:%H:%M}~{state['last_event']:%H:%M}에 걸친 "
          f"{WINDOW_MINUTES}분 창을 모두 늘어놓으면")
    grid = []
    cur = lo
    while cur <= hi:
        grid.append(cur)
        cur += timedelta(minutes=WINDOW_MINUTES)
    for start in grid:
        rows = [(d, c) for (s, d), c in state["final_counts"].items() if s == start]
        if rows:
            print(f"    창 {label(start):<12} 결과 행 {len(rows)}개  " +
                  ", ".join(f"{d} {c}" for d, c in sorted(rows)))
        else:
            print(f"    창 {label(start):<12} 결과 행 없음")
    print(f"    창 {len(grid)}개 중 결과 행이 없는 창 "
          f"{sum(1 for s in grid if not any(k[0] == s for k in state['final_counts']))}개")
    print(f"    폐기된 이벤트 {state['dropped']}건도 집계 결과에는 흔적이 없음 — "
          "'이벤트가 없어서 없는 창'과 '폐기되어 없는 창'을 집계만 보고 구분할 수 없음")


if __name__ == "__main__":
    main()
