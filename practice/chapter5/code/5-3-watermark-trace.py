#!/usr/bin/env python3
"""5-3: watermark가 전진하는 과정과 지연 이벤트의 수용·폐기를 손으로 재현한다.

5-1(PySpark)과 같은 입력 파일을 같은 순서로 읽고, watermark 규칙만
표준 라이브러리로 다시 구현한다. 규칙은 두 줄이다.
  - 파일 하나를 처리할 때 적용되는 watermark = (직전까지 관측한 최대 이벤트 시각) - 지연 허용
  - 이벤트가 속한 창의 끝이 그 watermark 이하이면 폐기, 아니면 수용

산출물: data/output/ch5_watermark_trace.json (이 스크립트가 새로 만드는 파일)
5-1이 만든 ch5_late_event_report.json이 있으면 판정을 대조해 일치 여부를 출력한다.

실행:
    python3 code/5-3-watermark-trace.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STREAM_DIR = BASE_DIR / "data" / "input" / "stream"
OUTPUT_DIR = BASE_DIR / "data" / "output"
TRACE_PATH = OUTPUT_DIR / "ch5_watermark_trace.json"
ENGINE_REPORT = OUTPUT_DIR / "ch5_late_event_report.json"
FMT = "%Y-%m-%d %H:%M:%S"

WINDOW_MINUTES = 10
WATERMARK_DELAY_MINUTES = 10


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
        batches.append((path.name, rows))
    return batches


def window_of(t: datetime) -> tuple[datetime, datetime]:
    start = t.replace(minute=(t.minute // WINDOW_MINUTES) * WINDOW_MINUTES,
                      second=0, microsecond=0)
    return start, start + timedelta(minutes=WINDOW_MINUTES)


def main() -> None:
    batches = load_batches()
    delay = timedelta(minutes=WATERMARK_DELAY_MINUTES)

    counts: dict[tuple[datetime, str], int] = defaultdict(int)
    max_seen: datetime | None = None
    watermark: datetime | None = None
    dropped_total = 0
    trace: list[dict] = []
    late_events: list[dict] = []

    print(f"[1] 규칙 — 창 {WINDOW_MINUTES}분, 지연 허용 {WATERMARK_DELAY_MINUTES}분")
    print("    watermark = 관측된 최대 이벤트 시각 − 지연 허용 (시계가 아니라 데이터에서 계산)")

    for order, (name, rows) in enumerate(batches, start=1):
        wm_in_effect = watermark
        wm_text = f"{wm_in_effect:%H:%M}" if wm_in_effect else "없음(아직 관측한 이벤트 없음)"
        print(f"\n[{order + 1}] {name} 도착 — 이벤트 {len(rows)}건, 적용 watermark {wm_text}")

        accepted, dropped_here, updated = [], [], []
        for row in sorted(rows, key=lambda r: r["t"]):
            w_start, w_end = window_of(row["t"])
            late = wm_in_effect is not None and w_end <= wm_in_effect
            if late:
                dropped_here.append(row)
                dropped_total += 1
                continue
            before = counts[(w_start, row["district"])]
            counts[(w_start, row["district"])] = before + 1
            accepted.append(row)
            updated.append((w_start, row["district"], before, before + 1))
            if row["event_id"].startswith("LATE"):
                late_events.append({
                    "event_id": row["event_id"],
                    "event_time": f"{row['t']:%H:%M}",
                    "arrived_in": name,
                    "watermark_at_arrival": f"{wm_in_effect:%H:%M}" if wm_in_effect else None,
                    "window": f"{w_start:%H:%M}-{w_end:%H:%M}",
                    "decision": "수용",
                    "evidence": f"창 {w_start:%H:%M}-{w_end:%H:%M} {row['district']} "
                                f"count {before} → {before + 1}",
                })
        for row in dropped_here:
            w_start, w_end = window_of(row["t"])
            if row["event_id"].startswith("LATE"):
                late_events.append({
                    "event_id": row["event_id"],
                    "event_time": f"{row['t']:%H:%M}",
                    "arrived_in": name,
                    "watermark_at_arrival": f"{wm_in_effect:%H:%M}",
                    "window": f"{w_start:%H:%M}-{w_end:%H:%M}",
                    "decision": "폐기",
                    "evidence": f"폐기 누적 = {dropped_total}",
                })

        for w_start, district, before, after in updated:
            mark = "갱신" if before else "신규"
            print(f"    {mark}  창 {w_start:%H:%M}-{w_start + timedelta(minutes=WINDOW_MINUTES):%H:%M} "
                  f"{district}  {before} → {after}")
        for row in dropped_here:
            w_start, w_end = window_of(row["t"])
            print(f"    폐기  {row['event_id']} 발생 {row['t']:%H:%M} — 창 {w_start:%H:%M}-{w_end:%H:%M}의 "
                  f"끝이 watermark {wm_in_effect:%H:%M} 이하")
        print(f"    수용 {len(accepted)}건 / 폐기 {len(dropped_here)}건, 폐기 누적 {dropped_total}")

        batch_max = max(r["t"] for r in rows)
        max_seen = batch_max if max_seen is None else max(max_seen, batch_max)
        watermark = max_seen - delay
        print(f"    처리 후 관측 최대 {max_seen:%H:%M} → 다음 watermark {watermark:%H:%M} "
              f"(= {max_seen:%H:%M} − {WATERMARK_DELAY_MINUTES}분)")
        trace.append({
            "file": name,
            "events": len(rows),
            "watermark_in_effect": f"{wm_in_effect:%H:%M}" if wm_in_effect else None,
            "accepted": len(accepted),
            "dropped": len(dropped_here),
            "dropped_cumulative": dropped_total,
            "max_event_time_after": f"{max_seen:%H:%M}",
            "watermark_after": f"{watermark:%H:%M}",
        })

    print("\n[5] 지연 이벤트 판정")
    for ev in late_events:
        print(f"    {ev['event_id']:<10} 발생 {ev['event_time']}  도착 시점 watermark "
              f"{ev['watermark_at_arrival']}  창 {ev['window']}  → {ev['decision']}")
        print(f"               증거: {ev['evidence']}")

    # 가정 시나리오: 같은 이벤트가 한 파일 더 늦게 왔다면 판정이 뒤집히는가
    print("\n[6] 가정 시나리오 — LATE_OK가 마지막 파일 다음에 도착했다면 (입력에 없는 계산)")
    ok = next((e for e in late_events if e["event_id"] == "LATE_OK"), None)
    if ok and watermark is not None:
        w_start, w_end = window_of(datetime.strptime(f"2026-07-07 {ok['event_time']}:00", FMT))
        verdict = "폐기" if w_end <= watermark else "수용"
        print(f"    적용 watermark {watermark:%H:%M}, 창 {ok['window']}의 끝 {w_end:%H:%M} → {verdict}")
        print("    같은 이벤트인데 판정이 바뀜 — 기준은 '얼마나 늦었나'가 아니라 '엔진이 그사이 무엇을 봤나'다")

    print("\n[7] 5-1(Spark) 산출물과 대조")
    if ENGINE_REPORT.exists():
        engine = json.loads(ENGINE_REPORT.read_text(encoding="utf-8"))
        engine_decision = {e["event_id"]: e["decision"] for e in engine["late_events"]}
        mine = {e["event_id"]: e["decision"] for e in late_events}
        engine_dropped = list(engine["dropped_by_watermark_cumulative"].values())[-1]
        print(f"    엔진 판정 {engine_decision} / 이 스크립트 판정 {mine}")
        print(f"    엔진 폐기 누적 {engine_dropped} / 이 스크립트 폐기 누적 {dropped_total}")
        same = engine_decision == mine and engine_dropped == dropped_total
        print(f"    일치: {'예' if same else '아니오'} — 규칙을 손으로 적용한 결과와 엔진 결과가 "
              f"{'같음' if same else '다름'}")
    else:
        print(f"    {ENGINE_REPORT.name}이 없어 대조를 건너뜀 (5-1 실행 필요)")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TRACE_PATH.write_text(json.dumps({
        "window_size_minutes": WINDOW_MINUTES,
        "watermark_delay_minutes": WATERMARK_DELAY_MINUTES,
        "rule": "watermark = 관측된 최대 이벤트 시각 − 지연 허용, 창의 끝 <= watermark 이면 폐기",
        "input_note": "민원 이벤트는 시뮬레이션 입력. 판정은 입력 파일에서 계산한 값.",
        "per_file": trace,
        "late_events": late_events,
        "dropped_cumulative": dropped_total,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n[저장] {TRACE_PATH}")


if __name__ == "__main__":
    main()
