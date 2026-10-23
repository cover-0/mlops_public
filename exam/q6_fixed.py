"""
문제 6 (7주). 훈련 샘플에 붙인 피처 - 수정본
====================================
수정 사항:
1. 결함 원인 분석:
   - 결함 1 (L46-48, L54): 최신값 조인(latest_value) 결함.
     샘플의 기준 시점(as_of)을 무시하고 현재 시점의 가장 최신 피처를 무조건 결합하여,
     기준 시점 이전에는 아직 생성되지 않은 미래의 데이터가 과거 훈련 샘플에 결합되는
     미래 누출(data leakage / time-travel leak, 7건 발생)을 유발함.
   - 결함 2 (L9, L60): 유효 기간(TTL, 3일) 만료 피처 및 확정 전 피처의 무조건 결합.
     기준 시점 이전에 확정된 피처가 없는 샘플(2건)과 가장 최근 확정치로부터 TTL(3일)을 초과한
     오래된 피처(3건)를 걸러내지 않고 모두 조인시켜, "12행 전부에 피처가 붙었으니 정상"이라고 오판함.
2. 결함 수정:
   - 시점 조인(point-in-time / as-of join) 적용:
     ① 기준 시점(as_of) 이전에 확정(event_timestamp <= as_of)된 후보 중 가장 최근 값 탐색
     ② 후보가 없으면 탈락 (n_dropped_no_value)
     ③ 기준 시점과 피처 확정 시점의 차이가 TTL(3일)을 초과하면 탈락 (n_dropped_ttl)
   - 수정 전 최신값 조인 시 미래 값이 결합되었던 샘플 수(n_leaked_future) 계산 및
     시점 조인 후 남은 행 수(n_joined=7), 결합된 피처 건수 합계(sum_count=45) 출력.
"""

import json
from datetime import datetime, timedelta, timezone

from common import PRACTICE, key, parse_id, pick_choice, pick_int

sid = parse_id()
INPUT_DIR = PRACTICE / "chapter7" / "data" / "input" / "ch6_daily"
DAYS = ["2026-07-01", "2026-07-02", "2026-07-03"]
TTL = timedelta(days=3)
CDS = ["11440", "11620", "11680"]


def build_feature_rows():
    rows = []
    for day in DAYS:
        summary = json.loads((INPUT_DIR / day / "daily_summary.json").read_text(encoding="utf-8"))
        known_at = datetime.fromisoformat(day + "T00:00:00+00:00") + timedelta(days=1)
        for r in summary["by_region"]:
            rows.append({"lawd_cd": r["lawd_cd"], "covers": day, "event_timestamp": known_at,
                         "complaint_count": int(r["count"])})
    return rows


SAMPLES = []
for i in range(12):
    cd = pick_choice(sid, f"q6-cd-{i}", CDS)
    day = pick_int(sid, f"q6-day-{i}", 0, 9)
    SAMPLES.append((cd, datetime(2026, 7, 1 + day, 9, 0, tzinfo=timezone.utc)))
SAMPLES.sort(key=lambda s: (s[1], s[0]))


def latest_value(rows, cd):
    cands = [r for r in rows if r["lawd_cd"] == cd]
    return max(cands, key=lambda r: r["event_timestamp"]) if cands else None


def point_in_time(rows, cd, as_of):
    """기준 시점 이전에 알려진 값 중 가장 최근 값. TTL을 넘으면 붙이지 않는다."""
    cands = [r for r in rows if r["lawd_cd"] == cd and r["event_timestamp"] <= as_of]
    if not cands:
        return None, "no_value"
    best = max(cands, key=lambda r: r["event_timestamp"])
    age = as_of - best["event_timestamp"]
    if age > TTL:
        return None, "ttl"
    return best, "ok"


rows = build_feature_rows()

# [결함 1 분석] 수정 전 최신값 조인 시 미래 값이 결합될 뻔한 샘플 수 계산
n_leaked_future = 0
for cd, as_of in SAMPLES:
    lv = latest_value(rows, cd)
    if lv and lv["event_timestamp"] > as_of:
        n_leaked_future += 1

# [결함 1 & 2 수정] 시점 조인 수행
joined = []
n_dropped_no_value = 0
n_dropped_ttl = 0

for cd, as_of in SAMPLES:
    hit, status = point_in_time(rows, cd, as_of)
    if status == "no_value":
        n_dropped_no_value += 1
    elif status == "ttl":
        n_dropped_ttl += 1
    else:
        joined.append({"lawd_cd": cd, "as_of": as_of, "row": hit})

n_samples = len(SAMPLES)
n_joined = len(joined)
sum_count = sum(j["row"]["complaint_count"] for j in joined)

print(f"피처 원천 {len(rows)}행, 훈련 샘플 {n_samples}행")
print(f"[수정 전 결함] 미래 데이터 누출 샘플: {n_leaked_future}행")
print(f"[수정 후 시점 조인] 부착 성공: {n_joined}행, 탈락: {n_dropped_no_value + n_dropped_ttl}행 "
      f"(확정값 없음: {n_dropped_no_value}행, TTL 초과: {n_dropped_ttl}행)")
for j in joined:
    print(f"  {j['lawd_cd']}  기준 {j['as_of']:%m-%d %H:%M}  대상일 {j['row']['covers']}  건수 {j['row']['complaint_count']}")
print(f"조인 결과 {n_joined}행, 붙은 민원 건수 합계 {sum_count}")

key("n_samples", n_samples)
key("n_joined", n_joined)
key("n_dropped_no_value", n_dropped_no_value)
key("n_dropped_ttl", n_dropped_ttl)
key("n_leaked_future", n_leaked_future)
key("sum_count", sum_count)
