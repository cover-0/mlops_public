#!/usr/bin/env python3
"""중간 미니 프로젝트 m-2 (B2): 이벤트 회계 — 중복·지연·창 집계.

입력: data/input/b2/batch1.jsonl ~ batch3.jsonl (m-0이 학번으로 만든 파일)
산출: data/output/b2_accounting.json

처리 규칙 (4주차 중복 제거 + 5주차 5-3 watermark 규칙)
  1. 배치를 파일 이름 순서(batch1 → batch2 → batch3)로 처리한다.
  2. 한 배치 안에서는 (event_time, event_id) 순서로 정렬해 한 건씩 본다.
  3. 이미 본 event_id면 '중복'으로 세고 건너뛴다. 처음 본 건이 수용됐든 폐기됐든 같다.
  4. 배치에 적용하는 watermark = (직전 배치까지 관측한 최대 event_time) − 지연 허용.
     첫 배치에는 watermark가 없다.
  5. 이벤트가 속한 10분 창의 끝이 watermark 이하이면 '지연 폐기', 아니면 '수용'해 (창, 지역구)에 1을 더한다.
  6. 배치를 다 처리한 뒤 최대 event_time을 갱신한다(중복 건 포함, 이 배치의 모든 행).
지연 허용 5분과 15분으로 각각 한 번씩 돌린다.

실행:
    python code/m-2-event-accounting.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_PATH = BASE_DIR / "data" / "output" / "b2_accounting.json"
FMT = "%Y-%m-%d %H:%M:%S"

WINDOW_MINUTES = 10
DELAYS = [5, 15]


def load_batches(input_dir: Path) -> list[tuple[str, list[dict]]]:
    batches = []
    for path in sorted((input_dir / "b2").glob("batch*.jsonl")):
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for r in rows:
            r["t"] = datetime.strptime(r["event_time"], FMT)
        batches.append((path.name, rows))
    return batches


def window_of(t: datetime) -> tuple[datetime, datetime]:
    start = t.replace(minute=(t.minute // WINDOW_MINUTES) * WINDOW_MINUTES, second=0, microsecond=0)
    return start, start + timedelta(minutes=WINDOW_MINUTES)


def run(batches: list[tuple[str, list[dict]]], delay_minutes: int) -> dict:
    delay = timedelta(minutes=delay_minutes)
    seen: set[str] = set()
    counts: dict[tuple[datetime, str], int] = defaultdict(int)
    max_seen: datetime | None = None
    received = duplicates = accepted = 0
    dropped: list[str] = []
    per_batch = []

    for name, rows in batches:
        # TODO 1 — 이 배치에 적용할 watermark를 정한다(규칙 4). 첫 배치는 None이다.
        watermark = None
        b_dup = b_acc = b_drop = 0
        for row in sorted(rows, key=lambda r: (r["t"], r["event_id"])):
            received += 1
            # TODO 2 — 이미 본 event_id면 duplicates·b_dup을 1 늘리고 다음 행으로 넘어간다(규칙 3).
            #          처음 본 event_id는 seen에 넣는다.
            # TODO 3 — window_of(row["t"])로 창을 구하고, 창의 끝이 watermark 이하이면
            #          dropped에 event_id를 넣고 b_drop을 1 늘린 뒤 다음 행으로 넘어간다(규칙 5).
            # TODO 4 — 나머지는 counts[(창 시작, 지역구)]에 1을 더하고 accepted·b_acc를 1 늘린다.
            raise NotImplementedError("run의 TODO 2~4를 완성한다")
        # TODO 5 — 이 배치의 최대 event_time으로 max_seen을 갱신한다(규칙 6).
        per_batch.append({
            "batch": name,
            "watermark": None if watermark is None else f"{watermark:%H:%M:%S}",
            "received": len(rows), "duplicates": b_dup, "accepted": b_acc, "dropped_late": b_drop,
        })

    return {
        "watermark_delay_minutes": delay_minutes,
        "received": received,
        "duplicates": duplicates,
        "accepted": accepted,
        "dropped_late": len(dropped),
        "dropped_event_ids": sorted(dropped),
        "per_batch": per_batch,
        "window_counts": [
            {"window_start": f"{w:%H:%M}", "district": d, "count": c}
            for (w, d), c in sorted(counts.items())
        ],
    }


def compute(input_dir: Path) -> dict:
    batches = load_batches(input_dir)
    return {"window_minutes": WINDOW_MINUTES, "runs": [run(batches, d) for d in DELAYS]}


def main() -> int:
    result = compute(INPUT_DIR)
    for k, r in enumerate(result["runs"], start=1):
        print(f"[{k}] 지연 허용 {r['watermark_delay_minutes']}분")
        for b in r["per_batch"]:
            print(f"    {b['batch']}  watermark {b['watermark'] or '없음'}  받음 {b['received']}  "
                  f"중복 {b['duplicates']}  수용 {b['accepted']}  폐기 {b['dropped_late']}")
        ok = r["received"] == r["duplicates"] + r["accepted"] + r["dropped_late"]
        print(f"    합계  받음 {r['received']} = 중복 {r['duplicates']} + 수용 {r['accepted']} + "
              f"지연 폐기 {r['dropped_late']}  → 등식 {'성립' if ok else '불성립'}")
        print(f"    폐기된 event_id: {', '.join(r['dropped_event_ids']) or '없음'}")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[3] 산출물 → {OUTPUT_PATH.relative_to(BASE_DIR.parent.parent).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
