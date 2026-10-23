"""
문제 2 (3주). 같은 집계를 두 계층에 두었다 - 수정본
===========================================
수정 사항:
1. 결함 원인 분석: 배치 계층은 지연 허용(GRACE_BATCH)이 15분인 반면, 
   스피드 계층은 GRACE_SPEED(8분)로 서로 다르게 설정되어 있어,
   72분 지연된 이벤트 20건(각 창당 10건)이 스피드 계층에서만 탈락하는 Lambda skew 발생.
2. 결함 수정: 스피드 계층의 집계 규칙(지연 허용 시간)을 배치 계층과 동일하게 15분으로 통일(또는 단일 규칙 사용).
3. 수정 전 스피드 계층 결과와 비교하여 n_diff_before, missing_events_before, max_mean_gap_before 산출 및
   수정 후 sha_batch, sha_speed, sha_equal 출력.
"""

import hashlib
import json
from datetime import datetime, timedelta

from common import PRACTICE, key, parse_id, pick_choice, pick_int

sid = parse_id()
INPUT_DIR = PRACTICE / "chapter3" / "data" / "input"
FILES = ["airquality_seoul_2200.json", "airquality_seoul_current.json"]
WINDOW_MIN = 60
GRACE_BATCH = 15                                   # 배치 계층의 지연 허용(분)
GRACE_SPEED = pick_choice(sid, "q2-grace", [5, 8, 10, 12])   # 수정 전 스피드 계층의 지연 허용(분)
LATE_PERIOD = pick_int(sid, "q2-period", 4, 7)     # 정렬 순번이 이 값의 배수인 이벤트가 72분 늦게 도착


def load_events():
    rows = []
    for name in FILES:
        body = json.loads((INPUT_DIR / name).read_text(encoding="utf-8"))["response"]["body"]
        for item in body["items"]:
            if item.get("pm10Value") in (None, "-", ""):
                continue
            rows.append({
                "station": item["stationName"],
                "event_time": datetime.strptime(item["dataTime"], "%Y-%m-%d %H:%M"),
                "pm10": int(item["pm10Value"]),
            })
    rows.sort(key=lambda r: (r["event_time"], r["station"]))
    for i, row in enumerate(rows):
        delay = 72 if (i + 1) % LATE_PERIOD == 0 else 3
        row["arrival_time"] = row["event_time"] + timedelta(minutes=delay)
    return rows


def window_of(t):
    return t.replace(minute=0, second=0, microsecond=0)


def aggregate(rows, grace_min):
    """지연 허용 시간(grace_min)을 인자로 받아 창별 건수와 PM10 평균을 집계하는 단일 공통 함수"""
    buckets = {}
    for row in rows:
        win = window_of(row["event_time"])
        if row["arrival_time"] >= win + timedelta(minutes=WINDOW_MIN + grace_min):
            continue
        buckets.setdefault(win, []).append(row["pm10"])
    return {w.strftime("%Y-%m-%d %H:%M"): {"count": len(v), "pm10_mean": round(sum(v) / len(v), 2)}
            for w, v in sorted(buckets.items())}


def sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


events = load_events()

# 배치 계층 집계 (15분 허용)
batch = aggregate(events, GRACE_BATCH)

# 수정 전 스피드 계층 집계 (학번별 GRACE_SPEED)
speed_before = aggregate(events, GRACE_SPEED)

# 수정 전 두 계층 차이 계산
diff_windows = []
missing_events_before = 0
mean_gaps = []

for win in sorted(set(batch) | set(speed_before)):
    b = batch.get(win, {"count": 0, "pm10_mean": 0.0})
    s = speed_before.get(win, {"count": 0, "pm10_mean": 0.0})
    if b != s:
        diff_windows.append(win)
    missing_events_before += (b["count"] - s["count"])
    mean_gaps.append(abs(round(b["pm10_mean"] - s["pm10_mean"], 2)))

n_diff_before = len(diff_windows)
max_mean_gap_before = max(mean_gaps) if mean_gaps else 0.0

# [결함 수정] 스피드 계층의 지연 허용을 배치와 동일하게 15분으로 일치
speed_after = aggregate(events, GRACE_BATCH)

sha_b = sha(batch)
sha_s = sha(speed_after)
sha_equal = 1 if sha_b == sha_s else 0

print(f"이벤트 {len(events)}건, 창 길이 {WINDOW_MIN}분")
print(f"[수정 전] 어긋난 창 {n_diff_before}개, 누락 이벤트 {missing_events_before}건, 최대 평균 차이 {max_mean_gap_before}")
print(f"[수정 후] 배치 sha: {sha_b}, 스피드 sha: {sha_s}, 일치 여부: {sha_equal}")
print(f"{'창':<18}{'배치 건수':>10}{'배치 평균':>11}{'스피드 건수':>12}{'스피드 평균':>12}")
for win in sorted(set(batch) | set(speed_after)):
    b = batch.get(win, {"count": 0, "pm10_mean": 0.0})
    s = speed_after.get(win, {"count": 0, "pm10_mean": 0.0})
    print(f"{win:<18}{b['count']:>10}{b['pm10_mean']:>11.2f}{s['count']:>12}{s['pm10_mean']:>12.2f}")

key("n_diff_before", n_diff_before)
key("missing_events_before", missing_events_before)
key("max_mean_gap_before", max_mean_gap_before)
key("sha_batch", sha_b)
key("sha_speed", sha_s)
key("sha_equal", sha_equal)
