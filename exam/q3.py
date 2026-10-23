"""
문제 3 (4주). 소비자 장애 뒤에 적재된 행 수
============================================
Kafka 소비자가 민원 이벤트 30건을 읽어 저장소에 적재하다가 도중에 멈췄고, 재시작해서 끝까지 읽었다.
이벤트 ID는 4주차 실습에서 실제 브로커가 남긴 처리 기록(ch4_alo_duplicate_stream.jsonl)의 30개 고유 ID다.
소비자 동작은 4주차 규칙대로 구현한 시뮬레이션이다(브로커를 띄우지 않는다).
학번마다 커밋 주기와 장애가 난 시점이 다르다.

소비자가 따르는 규칙은 둘 중 하나다.
  A. 처리한 뒤 커밋한다  (커밋 주기마다 지금까지 처리한 위치를 커밋)
  B. 읽은 직후 커밋한다  (한 묶음을 읽자마자 커밋하고 그 묶음을 처리)

팀의 보고: "A 규칙으로 운영했다. 적재 행 수가 원천 건수 이상이므로 유실이 없고, 전달 보장은 exactly-once다."

실행: python exam/q3.py --id 학번
수정본은 q3_fixed.py 로 저장해 같은 방식으로 실행한다.
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
    """A. 처리한 뒤 커밋. 장애 뒤에는 마지막 커밋 위치부터 다시 읽는다. 적재한 (오프셋, ID) 행을 돌려준다."""
    rows, committed = [], 0
    for off in range(CRASH_AT):                           # 장애 전까지
        rows.append((off, ids[off]))
        if (off + 1) % COMMIT_EVERY == 0:
            committed = off + 1
    for off in range(committed, N):                       # 재시작 뒤
        rows.append((off, ids[off]))
    return rows


def run_rule_b():
    """B. 읽은 직후 커밋. 장애 뒤에는 커밋된 위치부터 읽는다. 적재한 (오프셋, ID) 행을 돌려준다."""
    rows, processed, off, crashed = [], 0, 0, False
    while off < N:
        end = min(off + COMMIT_EVERY, N)
        committed = end                                   # 묶음을 읽자마자 커밋
        for o in range(off, end):
            if not crashed and processed == CRASH_AT:
                crashed = True
                break                                     # 장애: 이 묶음의 나머지는 처리되지 않았다
            rows.append((o, ids[o]))
            processed += 1
        off = committed                                   # 재시작은 커밋된 위치부터
    return rows


rows = run_rule_a()
print(f"원천 {N}건, 커밋 주기 {COMMIT_EVERY}, 장애 시점 {CRASH_AT}건 처리 직후")
print(f"A 규칙 적재 행 수 {len(rows)}행")
print(f"검증: 적재 {len(rows)} >= 원천 {N} -> 유실 없음, exactly-once 달성")
key("commit_every", COMMIT_EVERY)
key("crash_at", CRASH_AT)
key("rows_raw", len(rows))
