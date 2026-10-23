"""
문제 4 (5주). 늦게 도착한 이벤트는 집계에 들어갔는가
=====================================================
구 단위 민원 이벤트를 시간 창으로 세는 스트리밍 집계다. 이벤트 14건이 파일 3개(batch1~3)로 나뉘어
차례로 도착한다. 자료는 5주차 실습의 실제 입력이다. 이 중 2건(LATE_OK, LATE_DROP)은 발생 시각보다
한참 늦게 도착한다. 학번마다 창 길이와 watermark 지연 허용 시간이 다르다.

적용 규칙(5주차): 파일 하나를 처리할 때 쓰는 watermark는 "그 파일 직전까지 관측한 최대 이벤트 시각 - 지연 허용"이다.
이벤트가 속한 창의 끝이 그 watermark 이하이면 폐기하고, 아니면 집계에 넣는다.

운영 보고: "이벤트 14건이 도착했고 모두 정상 집계되었다."

실행: python exam/q4.py --id 학번
수정본은 q4_fixed.py 로 저장해 같은 방식으로 실행한다.
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

print(f"창 {WINDOW_MIN}분, 지연 허용 {DELAY_MIN}분")
for name, rows in batches:
    batch_max = max(r["t"] for r in rows)
    max_seen = batch_max if max_seen is None else max(max_seen, batch_max)
    watermark = max_seen - delay
    for r in rows:
        w_start, w_end = window_of(r["t"])
        if w_end <= watermark:
            continue
        counts[(w_start, r["district"])] += 1
    print(f"{name}: 이벤트 {len(rows)}건 처리, watermark {watermark:%H:%M}")

accepted = sum(counts.values())
print(f"집계 완료: 창-구 {len(counts)}행, 이벤트 {accepted}건 반영")
key("window_min", WINDOW_MIN)
key("delay_min", DELAY_MIN)
key("accepted", accepted)
key("n_rows", len(counts))
