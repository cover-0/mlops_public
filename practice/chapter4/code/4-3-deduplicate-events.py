#!/usr/bin/env python3
"""4-3: 중복 이벤트 주입과 제거 검증.

입력 데이터의 출처(정직성): `data/input/ch4_alo_duplicate_stream.jsonl`은
4장 실습 4.1의 시나리오 C(at-least-once + 커밋 전 크래시)가 실제 Kafka
브로커에서 남긴 처리 기록의 스냅샷이다(40건 = 크래시 전 10건 + 재시작 후
30건 재수신, 중복 10건). 즉 이 실습의 "중복 주입"은 시뮬레이터가 아니라
실제 브로커 장애 실험이 만든 중복이다.

검증 4단계 — 같은 스트림을 서로 다른 저장 전략으로 적재해 비교한다:
  A. naive INSERT        : 제약 없음 → 중복이 그대로 행이 된다
  B. UNIQUE + OR IGNORE  : 중복 행을 조용히 건너뛴다
  C. UPSERT(DO UPDATE)   : 중복을 "재관찰"로 기록한다(seen_count, last_seen_at)
  D. 전체 스트림 리플레이 : C 테이블에 40건을 한 번 더 재생 → 상태 안정성 확인

실행:
    python3 code/4-3-deduplicate-events.py
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_PATH = BASE_DIR / "data" / "input" / "ch4_alo_duplicate_stream.jsonl"
OUTPUT_DIR = BASE_DIR / "data" / "output"
DB_PATH = OUTPUT_DIR / "ch4_dedup.sqlite"
REPORT_PATH = OUTPUT_DIR / "ch4_dedup_report.json"


def load_stream() -> list[dict]:
    lines = INPUT_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def stage_a_naive(conn: sqlite3.Connection, events: list[dict]) -> dict:
    """A. 제약 없는 테이블에 그대로 INSERT — 중복이 행으로 쌓인다."""
    conn.execute("DROP TABLE IF EXISTS complaints_naive")
    conn.execute(
        "CREATE TABLE complaints_naive ("
        "event_id TEXT, partition INTEGER, offset INTEGER, consumed_at TEXT)"
    )
    conn.executemany(
        "INSERT INTO complaints_naive VALUES (?, ?, ?, ?)",
        [(e["event_id"], e["partition"], e["offset"], e["consumed_at"]) for e in events],
    )
    total = conn.execute("SELECT COUNT(*) FROM complaints_naive").fetchone()[0]
    distinct = conn.execute(
        "SELECT COUNT(DISTINCT event_id) FROM complaints_naive"
    ).fetchone()[0]
    return {"rows": total, "distinct_event_ids": distinct, "duplicate_rows": total - distinct}


def stage_b_unique_ignore(conn: sqlite3.Connection, events: list[dict]) -> dict:
    """B. 유니크 제약(PRIMARY KEY) + INSERT OR IGNORE — 중복을 건너뛴다."""
    conn.execute("DROP TABLE IF EXISTS complaints_unique")
    conn.execute(
        "CREATE TABLE complaints_unique ("
        "event_id TEXT PRIMARY KEY, partition INTEGER, offset INTEGER, consumed_at TEXT)"
    )
    ignored = 0
    for e in events:
        cur = conn.execute(
            "INSERT OR IGNORE INTO complaints_unique VALUES (?, ?, ?, ?)",
            (e["event_id"], e["partition"], e["offset"], e["consumed_at"]),
        )
        ignored += 1 - cur.rowcount  # rowcount 0 = 충돌로 무시됨
    rows = conn.execute("SELECT COUNT(*) FROM complaints_unique").fetchone()[0]
    return {"rows": rows, "ignored_duplicates": ignored}


def stage_c_upsert(conn: sqlite3.Connection, events: list[dict]) -> dict:
    """C. UPSERT — 중복을 버리지 않고 '재관찰 기록'으로 남긴다."""
    conn.execute("DROP TABLE IF EXISTS complaints_upsert")
    conn.execute(
        "CREATE TABLE complaints_upsert ("
        "event_id TEXT PRIMARY KEY, partition INTEGER, offset INTEGER, "
        "first_seen_at TEXT, last_seen_at TEXT, seen_count INTEGER)"
    )
    upsert_events(conn, events)
    return upsert_stats(conn)


def upsert_events(conn: sqlite3.Connection, events: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO complaints_upsert VALUES (?, ?, ?, ?, ?, 1) "
        "ON CONFLICT(event_id) DO UPDATE SET "
        "last_seen_at = excluded.last_seen_at, seen_count = seen_count + 1",
        [(e["event_id"], e["partition"], e["offset"], e["consumed_at"], e["consumed_at"])
         for e in events],
    )


def upsert_stats(conn: sqlite3.Connection) -> dict:
    """행 수·관찰 수와 함께 '업무 상태 지문'을 남긴다.

    seen_count·last_seen_at는 전달 관찰 메타데이터라 리플레이 시 의도적으로
    증가한다. 반면 업무 상태(event_id·partition·offset·first_seen_at)는
    리플레이에 불변이어야 하며, 그 불변성을 해시 지문으로 검증 가능하게 한다.
    """
    import hashlib

    rows = conn.execute("SELECT COUNT(*) FROM complaints_upsert").fetchone()[0]
    observations = conn.execute("SELECT SUM(seen_count) FROM complaints_upsert").fetchone()[0]
    reobserved = conn.execute(
        "SELECT COUNT(*) FROM complaints_upsert WHERE seen_count > 1"
    ).fetchone()[0]
    business_rows = conn.execute(
        "SELECT event_id, partition, offset, first_seen_at "
        "FROM complaints_upsert ORDER BY event_id"
    ).fetchall()
    fingerprint = hashlib.sha256(repr(business_rows).encode("utf-8")).hexdigest()[:16]
    return {
        "rows": rows,
        "total_observations": observations,
        "reobserved_events": reobserved,
        "business_state_fingerprint": fingerprint,
    }


def print_summary(report: dict, events: list[dict]) -> None:
    """사람이 읽는 요약을 stdout에 남긴다(보고서 JSON은 건드리지 않는다)."""
    from collections import Counter

    counts = Counter(e["event_id"] for e in events)
    repeated = sorted(eid for eid, c in counts.items() if c > 1)

    print(f"[1] 입력 — 처리 기록 {len(events)}건, 고유 event_id {len(counts)}개")
    print(f"    출처: {report['input']['path']}")
    print(f"    두 번 나타난 event_id {len(repeated)}개")
    print("    " + " ".join(repeated))
    if repeated:
        pair = [e for e in events if e["event_id"] == repeated[0]]
        t0 = datetime.fromisoformat(pair[0]["consumed_at"])
        t1 = datetime.fromisoformat(pair[-1]["consumed_at"])
        gap = (t1 - t0).total_seconds()
        print(f"    예) {repeated[0]}  partition {pair[0]['partition']} "
              f"offset {pair[0]['offset']} — 같은 위치가 두 번 처리됨")
        print(f"        1차 {pair[0]['consumed_at']}")
        print(f"        2차 {pair[-1]['consumed_at']}  (간격 {gap:.1f}초)")

    a, b = report["A_naive_insert"], report["B_unique_or_ignore"]
    c, d = report["C_upsert_do_update"], report["D_replay_full_stream"]
    print("\n[2] 저장 전략별 결과")
    print("    단계                        행 수  관찰 지표")
    print(f"    A 제약 없는 INSERT          {a['rows']:5d}  중복 행 {a['duplicate_rows']}")
    print(f"    B UNIQUE + OR IGNORE        {b['rows']:5d}  무시된 중복 {b['ignored_duplicates']}")
    print(f"    C UPSERT DO UPDATE          {c['rows']:5d}  총 관찰 {c['total_observations']} / "
          f"재관찰 이벤트 {c['reobserved_events']}")
    print(f"    D C에 같은 스트림 재투입    {d['rows']:5d}  총 관찰 {d['total_observations']} / "
          f"재관찰 이벤트 {d['reobserved_events']}")

    print("\n[3] 업무 상태 지문 — event_id·partition·offset·first_seen_at")
    print(f"    C  {c['business_state_fingerprint']}")
    print(f"    D  {d['business_state_fingerprint']}")
    same = c["business_state_fingerprint"] == d["business_state_fingerprint"]
    print(f"    일치: {'예' if same else '아니오'} — "
          f"총 관찰은 {c['total_observations']}에서 {d['total_observations']}으로 늘었지만 "
          f"행 수는 {c['rows']}으로 그대로임\n")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()  # 재실행 재현성

    events = load_stream()
    conn = sqlite3.connect(DB_PATH)
    with conn:
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "input": {
                "path": str(INPUT_PATH.relative_to(BASE_DIR)),
                "provenance": "4장 실습 4.1 시나리오 C(at-least-once 크래시)의 실측 처리 기록 스냅샷",
                "records": len(events),
                "distinct_event_ids": len({e["event_id"] for e in events}),
            },
            "A_naive_insert": stage_a_naive(conn, events),
            "B_unique_or_ignore": stage_b_unique_ignore(conn, events),
            "C_upsert_do_update": stage_c_upsert(conn, events),
        }
        # D. 전체 스트림을 한 번 더 리플레이 — 행 수는 불변, 관찰 수만 증가해야 한다
        upsert_events(conn, events)
        report["D_replay_full_stream"] = upsert_stats(conn)
    conn.close()

    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print_summary(report, events)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n[저장] {REPORT_PATH}")


if __name__ == "__main__":
    main()
