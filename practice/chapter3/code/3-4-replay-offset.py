#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3-4-replay-offset.py
제3장 — 오프셋을 되감아 같은 결과를 다시 만들 수 있는가

Kappa 아키텍처는 배치 레이어 없이 로그를 되감아 재처리한다(리플레이).
이 코드는 이벤트마다 오프셋을 붙여 로그에 적재한 뒤 세 가지를 확인한다.
  - 오프셋 0부터 다시 읽으면 처음과 같은 결과가 나오는가(결과 해시 대조)
  - 집계 규칙을 고친 뒤 되감으면 새 확정치가 나오는가
  - 보존 기간이 지난 구간은 되감을 수 있는가

입력: data/input/airquality_seoul_*.json (3-3과 같은 자료)

실행:
    cd practice/chapter3
    python3 code/3-4-replay-offset.py
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = PROJECT_ROOT / "data" / "input"
INPUT_FILES = ["airquality_seoul_2200.json", "airquality_seoul_current.json"]
OUTPUT_PATH = PROJECT_ROOT / "data" / "output" / "ch3_replay_report.json"

# 로그 보존 설정. 이 오프셋보다 앞은 보존 기간이 지나 삭제된 것으로 본다.
# 22시 창 40건이 보존 기간 밖이고, 23시 창 40건만 되감을 수 있다.
RETENTION_START_OFFSET = 40

# 창의 대표값을 무엇으로 낼 것인가. 규칙을 고치기 전은 산술평균,
# 고친 뒤는 측정소 하나의 튀는 값에 덜 흔들리는 중앙값이다.
STAT_BEFORE = "mean"
STAT_AFTER = "median"


def load_log() -> list[dict[str, Any]]:
    """원자료를 읽어 오프셋을 붙인 이벤트 로그로 만든다."""
    rows: list[dict[str, Any]] = []
    for name in INPUT_FILES:
        path = INPUT_DIR / name
        if not path.exists():
            raise FileNotFoundError(f"입력 자료가 없습니다: {path}")
        body = json.loads(path.read_text(encoding="utf-8"))["response"]["body"]
        for item in body["items"]:
            if item.get("pm10Value") in (None, "-", ""):
                continue
            rows.append({
                "station": item["stationName"],
                "event_time": item["dataTime"],
                "pm10": int(item["pm10Value"]),
            })
    rows.sort(key=lambda r: (r["event_time"], r["station"]))
    for offset, row in enumerate(rows):
        row["offset"] = offset
    return rows


def representative(values: list[int], stat: str) -> float:
    """창의 대표값. 규칙 변경 전후로 이 함수만 다르게 호출한다."""
    ordered = sorted(values)
    n = len(ordered)
    if stat == "median":
        mid = n // 2
        value = ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    else:
        value = sum(ordered) / n
    return round(value, 2)


def consume(log: list[dict[str, Any]], from_offset: int, stat: str) -> dict[str, Any]:
    """오프셋 from_offset부터 끝까지 읽어 창별로 집계한다."""
    available = [r for r in log if r["offset"] >= max(from_offset, RETENTION_START_OFFSET)]
    skipped = max(0, min(RETENTION_START_OFFSET, len(log)) - from_offset)

    buckets: dict[str, list[int]] = {}
    for row in available:
        win = row["event_time"][:13] + ":00"
        buckets.setdefault(win, []).append(row["pm10"])

    windows = {
        win: {
            "count": len(vals),
            "pm10_stat": representative(vals, stat),
            "pm10_min": min(vals),
            "pm10_max": max(vals),
        }
        for win, vals in sorted(buckets.items())
    }
    return {
        "from_offset": from_offset,
        "stat": stat,
        "consumed": len(available),
        "unavailable": skipped,
        "windows": windows,
    }


def result_hash(result: dict[str, Any]) -> str:
    """집계 결과의 지문. 창별 수치만 넣는다(읽기 시작한 오프셋은 제외)."""
    payload = json.dumps(result["windows"], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def show(label: str, result: dict[str, Any]) -> str:
    digest = result_hash(result)
    print(f"    {label}")
    print(f"      읽은 오프셋 {result['from_offset']}~ / 소비 {result['consumed']}건"
          f" / 보존 기간 밖 {result['unavailable']}건")
    for win, w in result["windows"].items():
        print(f"      {win}  건수 {w['count']:>3}  대표값({result['stat']}) {w['pm10_stat']:>6}"
              f"  최소 {w['pm10_min']:>3}  최대 {w['pm10_max']:>3}")
    print(f"      결과 해시 {digest[:16]}…")
    return digest


def main() -> int:
    log = load_log()
    print(f"[1] 이벤트 로그 — {len(log)}건, 오프셋 0~{len(log) - 1}")
    print(f"    보존 기간이 지난 구간: 오프셋 0~{RETENTION_START_OFFSET - 1}"
          f" ({RETENTION_START_OFFSET}건)")
    print(f"    되감을 수 있는 구간: 오프셋 {RETENTION_START_OFFSET}~{len(log) - 1}")

    print(f"\n[2] 최초 집계 (대표값 {STAT_BEFORE})")
    first = consume(log, RETENTION_START_OFFSET, STAT_BEFORE)
    h_first = show("처음 실행", first)

    print("\n[3] 오프셋을 되감아 같은 코드로 다시 읽기")
    replayed = consume(log, RETENTION_START_OFFSET, STAT_BEFORE)
    h_replay = show("리플레이", replayed)
    same = h_first == h_replay
    print(f"      해시 일치: {'예' if same else '아니오'}"
          f" — {'그 시점 자료로 그 계산을 다시 만들었음' if same else '재현 실패'}")

    print(f"\n[4] 집계 규칙을 고친 뒤 되감기 (대표값 {STAT_BEFORE} → {STAT_AFTER})")
    fixed = consume(log, RETENTION_START_OFFSET, STAT_AFTER)
    h_fixed = show("규칙 변경 후 리플레이", fixed)
    print(f"      해시 변경: {'예' if h_fixed != h_first else '아니오'}"
          " — 로직 한 벌만 고쳐 확정치를 다시 냈음")

    print("\n[5] 보존 기간 밖을 요청하면")
    past = consume(log, 0, STAT_BEFORE)
    print(f"      오프셋 0부터 요청했으나 {past['unavailable']}건은 남아 있지 않음")
    print(f"      실제로 읽은 건수 {past['consumed']}건 — 요청한 {len(log)}건에 못 미침")
    print("      감사 질의가 이 구간을 향하면 재현해 보일 수 없음")

    report = {
        "input_files": INPUT_FILES,
        "log_size": len(log),
        "retention_start_offset": RETENTION_START_OFFSET,
        "first_run": {"result": first, "hash": h_first},
        "replay": {"result": replayed, "hash": h_replay, "hash_matches_first": same},
        "replay_after_rule_change": {
            "result": fixed, "hash": h_fixed,
            "stat_before": STAT_BEFORE,
            "stat_after": STAT_AFTER,
        },
        "beyond_retention": {
            "requested_from_offset": 0,
            "unavailable": past["unavailable"],
            "consumed": past["consumed"],
        },
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\noutput={OUTPUT_PATH} replay_hash_match={same}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
