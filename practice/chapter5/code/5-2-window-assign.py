#!/usr/bin/env python3
"""5-2: 이벤트를 시간 창에 배정한다 — tumbling과 sliding 비교.

5-1(PySpark)과 같은 입력 파일(data/input/stream/batch*.json)을 읽어,
창 배정 규칙만 표준 라이브러리로 다시 구현한다. Java도 Spark도 필요 없다.
난수를 쓰지 않으므로 몇 번 실행해도 같은 값이 나온다.

실행:
    python3 code/5-2-window-assign.py
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STREAM_DIR = BASE_DIR / "data" / "input" / "stream"
FMT = "%Y-%m-%d %H:%M:%S"

WINDOW_MINUTES = 10
SLIDE_MINUTES = 5
FOCUS_DISTRICT = "강남구"

# 경계 규칙을 확인하려고 스크립트가 구성한 시각. 입력 파일에는 없다.
BOUNDARY_PROBES = ["2026-07-07 22:09:59", "2026-07-07 22:10:00", "2026-07-07 22:10:01"]


def load_events() -> list[dict]:
    files = sorted(STREAM_DIR.glob("*.json"))
    if not files:
        raise SystemExit(
            f"입력 파일이 없다: {STREAM_DIR}\n"
            "5-1이 중간에 실패하면 이 디렉터리가 비어 있다. 다음으로 되살린다.\n"
            "    git restore practice/chapter5/data/input/stream"
        )
    events: list[dict] = []
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            row["source_file"] = path.name
            row["t"] = datetime.strptime(row["event_time"], FMT)
            events.append(row)
    return events


def tumbling_start(t: datetime, minutes: int) -> datetime:
    return t.replace(minute=(t.minute // minutes) * minutes, second=0, microsecond=0)


def sliding_starts(t: datetime, size: int, slide: int) -> list[datetime]:
    base = t.replace(minute=(t.minute // slide) * slide, second=0, microsecond=0)
    starts = [base - timedelta(minutes=slide * k) for k in range(size // slide)]
    return sorted(s for s in starts if s <= t < s + timedelta(minutes=size))


def label(start: datetime, size: int) -> str:
    return f"{start:%H:%M}-{start + timedelta(minutes=size):%H:%M}"


def main() -> None:
    events = load_events()
    files = sorted({e["source_file"] for e in events})
    times = sorted(e["t"] for e in events)

    print(f"[1] 입력 — 이벤트 {len(events)}건, 파일 {len(files)}개, 지역구 "
          f"{len({e['district'] for e in events})}개")
    print(f"    이벤트 시각 범위 {times[0]:%H:%M} ~ {times[-1]:%H:%M}")
    print(f"    창 크기 {WINDOW_MINUTES}분, 슬라이드 {SLIDE_MINUTES}분, 기준 시각은 발생 시각(이벤트 시간)")

    print(f"\n[2] tumbling {WINDOW_MINUTES}분 — 창끼리 겹치지 않음")
    tumbling: Counter = Counter()
    for e in events:
        tumbling[(tumbling_start(e["t"], WINDOW_MINUTES), e["district"])] += 1
    for start in sorted({k[0] for k in tumbling}):
        cells = [f"{d} {tumbling[(start, d)]}"
                 for d in ("강남구", "마포구", "관악구") if (start, d) in tumbling]
        print(f"    {label(start, WINDOW_MINUTES):<12} " + ", ".join(cells))

    focus = [e for e in events if e["district"] == FOCUS_DISTRICT]
    focus_times = ", ".join(f"{e['t']:%H:%M}" for e in sorted(focus, key=lambda e: e["t"]))
    t_counts = {label(s, WINDOW_MINUTES): tumbling[(s, FOCUS_DISTRICT)]
                for s in sorted({k[0] for k in tumbling}) if (s, FOCUS_DISTRICT) in tumbling}

    print(f"\n[3] {FOCUS_DISTRICT} {len(focus)}건을 두 방식으로 셈 (발생 {focus_times})")
    print("    tumbling  " + ", ".join(f"{w} → {c}" for w, c in t_counts.items()))
    print(f"    건수 합 {sum(t_counts.values())}")

    sliding: Counter = Counter()
    for e in focus:
        for s in sliding_starts(e["t"], WINDOW_MINUTES, SLIDE_MINUTES):
            sliding[s] += 1
    s_counts = {label(s, WINDOW_MINUTES): sliding[s] for s in sorted(sliding)}
    print("    sliding   " + ", ".join(f"{w} → {c}" for w, c in s_counts.items()))
    print(f"    건수 합 {sum(s_counts.values())}")
    print(f"    이벤트 수 {len(focus)}건 대비 tumbling 합 {sum(t_counts.values())}, "
          f"sliding 합 {sum(s_counts.values())} — "
          f"{sum(s_counts.values()) // len(focus)}배로 세어짐 "
          f"(창 크기 ÷ 슬라이드 = {WINDOW_MINUTES // SLIDE_MINUTES})")

    print("\n[4] 경계 판정 — 창은 [시작, 끝)이다 (아래 세 시각은 입력에 없는 구성값)")
    for raw in BOUNDARY_PROBES:
        t = datetime.strptime(raw, FMT)
        print(f"    {t:%H:%M:%S} → tumbling {label(tumbling_start(t, WINDOW_MINUTES), WINDOW_MINUTES)}")


if __name__ == "__main__":
    main()
