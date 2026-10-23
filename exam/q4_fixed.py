"""
문제 4 (5주). 늦게 도착한 이벤트는 집계에 들어갔는가 - 수정본
=====================================================
수정 사항:
1. 결함 1 (L55-57): 워터마크 계산 시점 오류.
   Spark Structured Streaming 및 5주차 규칙에 따르면, 각 배치 파일 처리 시 적용되는 워터마크는
   "그 파일 직전까지 관측한 최대 이벤트 시각 - 지연 허용"이어야 합니다.
   기존 코드는 현재 배치의 최댓값을 먼저 반영하여 워터마크를 성급하게 전진시킨 뒤 현재 배치를 필터링함으로써
   batch2의 LATE_OK가 부당하게 폐기되었습니다.
   -> 배치 행들을 처리할 때는 직전까지의 watermark를 적용하고, 워터마크 갱신은 배치 처리가 끝난 뒤 수행하도록 수정.
2. 결함 2 (L60): 폐기(drop)된 지연 이벤트의 집계 및 보고 누락.
   운영 보고서는 "14건 모두 정상 집계"라고 하였으나, 실제 폐기된 이벤트를 카운트(dropped)하고
   LATE_OK와 LATE_DROP의 판정 결과를 명시적으로 기록/출력하도록 보완.
"""

import json
from collections import defaultdict
from datetime import datetime, timedelta

from common import PRACTICE, key, parse_id, pick_choice

sid = parse_id()
STREAM_DIR = PRACTICE / "chapter5" / "data" / "input" / "stream"
FMT = "%Y-%m-%d %H:%M:%S"
WINDOW_MIN = pick_choice(sid, "q4-window", [5, 10])
DELAY_MIN = pick_choice(sid, "q4-delay", [2, 3, 4, 5, 6, 8, 12, 29, 30, 35])


def load_batches():
    batches = []
    for path in sorted(STREAM_DIR.glob("*.json")):
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                row["t"] = datetime.strptime(row["event_time"], FMT)
                rows.append(row)
        batches.append((path.name, rows))
    return batches


def window_of(t):
    start = t.replace(minute=(t.minute // WINDOW_MIN) * WINDOW_MIN, second=0, microsecond=0)
    return start, start + timedelta(minutes=WINDOW_MIN)


batches = load_batches()
delay = timedelta(minutes=DELAY_MIN)
counts = defaultdict(int)
max_seen = None
watermark = None

accepted = 0
dropped = 0
decisions = {}

print(f"창 {WINDOW_MIN}분, 지연 허용 {DELAY_MIN}분")

for name, rows in batches:
    # [결함 1 수정] 직전 배치까지 관측된 최대 시각으로 계산된 watermark를 이번 배치에 적용
    wm_in_effect = watermark
    wm_text = f"{wm_in_effect:%H:%M}" if wm_in_effect else "없음(초기)"
    print(f"\n{name}: 이벤트 {len(rows)}건 처리 (적용 watermark: {wm_text})")

    for r in rows:
        w_start, w_end = window_of(r["t"])
        # 창 끝(w_end)이 적용 워터마크 이하이면 지연 폐기
        is_late = (wm_in_effect is not None) and (w_end <= wm_in_effect)
        if is_late:
            dropped += 1
            decisions[r["event_id"]] = "폐기"
            print(f"  [폐기] {r['event_id']} (발생: {r['t']:%H:%M}, 창끝: {w_end:%H:%M} <= wm: {wm_text})")
            continue

        accepted += 1
        counts[(w_start, r["district"])] += 1
        decisions[r["event_id"]] = "수용"
        print(f"  [수용] {r['event_id']} (발생: {r['t']:%H:%M}, 창: {w_start:%H:%M}~{w_end:%H:%M})")

    # [결함 1 수정] 배치의 처리가 완료된 후 다음 배치를 위한 watermark 갱신
    batch_max = max(r["t"] for r in rows)
    max_seen = batch_max if max_seen is None else max(max_seen, batch_max)
    watermark = max_seen - delay
    print(f"  -> 배치 처리 후 관측 최대 시각: {max_seen:%H:%M}, 다음 배치용 watermark: {watermark:%H:%M}")

late_ok_decision = decisions.get("LATE_OK", "미도착")
late_drop_decision = decisions.get("LATE_DROP", "미도착")

print(f"\n집계 완료: 창-구 {len(counts)}행, 이벤트 {accepted}건 반영, 폐기 {dropped}건")
print(f"판정 결과: LATE_OK={late_ok_decision}, LATE_DROP={late_drop_decision}")

key("window_min", WINDOW_MIN)
key("delay_min", DELAY_MIN)
key("accepted", accepted)
key("dropped", dropped)
key("n_rows", len(counts))
key("late_ok", late_ok_decision)
key("late_drop", late_drop_decision)
