"""
문제 3 (4주). 소비자 장애 뒤에 적재된 행 수 - 수정본
============================================
수정 사항:
1. 결함 원인 분석:
   - 결함 1 (L71): "적재 행 수 >= 원천 건수"를 근거로 exactly-once라고 잘못 판정. 실제로는 A 규칙(처리 후 커밋)에서
     커밋되지 않은 2건이 재시작 후 중복 적재되어 32행이 적재된 at-least-once 상태임.
   - 결함 2: At-least-once 파이프라인에서 중복을 걸러내는 사후 중복 제거(deduplication) 로직이 누락됨.
2. 결함 수정:
   - 고유 식별자(event_id) 기반의 중복 제거를 수행하여 중복 건수와 정제 후 행 수 산출.
   - B 규칙(읽은 직후 커밋)을 함께 시뮬레이션하여 유실된 고유 이벤트 수(lost_rule_b) 집계.
"""

import json

from common import PRACTICE, key, parse_id, pick_choice, pick_int

sid = parse_id()
STREAM = PRACTICE / "chapter4" / "data" / "input" / "ch4_alo_duplicate_stream.jsonl"

ids = []
for line in STREAM.read_text(encoding="utf-8").splitlines():
    event_id = json.loads(line)["event_id"]
    if event_id not in ids:
        ids.append(event_id)
N = len(ids)                                              # 원천 이벤트 수 (30)

COMMIT_EVERY = pick_choice(sid, "q3-commit", [3, 4, 5, 6, 8])
_base = pick_int(sid, "q3-crash", 14, 24) // COMMIT_EVERY * COMMIT_EVERY
CRASH_AT = _base + 2 + pick_int(sid, "q3-rest", 0, COMMIT_EVERY - 3)   # 이 개수만큼 처리한 직후 장애
if CRASH_AT > N - 2:
    CRASH_AT -= COMMIT_EVERY


def run_rule_a():
    """A. 처리한 뒤 커밋 (At-Least-Once). 장애 뒤에는 마지막 커밋 위치부터 다시 읽는다."""
    rows, committed = [], 0
    for off in range(CRASH_AT):                           # 장애 전까지
        rows.append((off, ids[off]))
        if (off + 1) % COMMIT_EVERY == 0:
            committed = off + 1
    for off in range(committed, N):                       # 재시작 뒤
        rows.append((off, ids[off]))
    return rows


def run_rule_b():
    """B. 읽은 직후 커밋 (At-Most-Once). 장애 뒤에는 커밋된 위치부터 읽는다."""
    rows, processed, off, crashed = [], 0, 0, False
    while off < N:
        end = min(off + COMMIT_EVERY, N)
        committed = end                                   # 묶음을 읽자마자 커밋
        for o in range(off, end):
            if not crashed and processed == CRASH_AT:
                crashed = True
                break                                     # 장애: 이 묶음의 나머지는 유실됨
            rows.append((o, ids[o]))
            processed += 1
        off = committed                                   # 재시작은 커밋된 위치부터
    return rows


# A 규칙 실행 및 중복 제거
rows_a = run_rule_a()
rows_raw = len(rows_a)

unique_events_a = set()
dedup_rows = []
for off, eid in rows_a:
    if eid not in unique_events_a:
        unique_events_a.add(eid)
        dedup_rows.append((off, eid))

rows_after_dedup = len(dedup_rows)
duplicates = rows_raw - rows_after_dedup

# B 규칙 실행 및 유실 건수 계산
rows_b = run_rule_b()
unique_events_b = set(eid for off, eid in rows_b)
lost_rule_b = N - len(unique_events_b)

print(f"원천 {N}건, 커밋 주기 {COMMIT_EVERY}, 장애 시점 {CRASH_AT}건 처리 직후")
print(f"A 규칙(처리 후 커밋): 적재 {rows_raw}행, 중복 {duplicates}행, 중복 제거 후 {rows_after_dedup}행 (전달 보장: at-least-once)")
print(f"B 규칙(읽은 후 커밋): 적재 {len(rows_b)}행, 유실 {lost_rule_b}건 (전달 보장: at-most-once)")

key("commit_every", COMMIT_EVERY)
key("crash_at", CRASH_AT)
key("rows_raw", rows_raw)
key("duplicates", duplicates)
key("rows_after_dedup", rows_after_dedup)
key("lost_rule_b", lost_rule_b)
