#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3-3-lambda-skew.py
제3장 — 같은 집계를 두 벌 유지하면 무슨 일이 생기는가

Lambda 아키텍처는 배치 레이어와 스피드 레이어에 같은 집계 로직을 두 벌 둔다.
이 코드는 두 로직에 같은 입력을 넣고, 한쪽의 지연 허용 시간만 바꾼 뒤
두 수치가 어긋나는지, 그때 프로그램이 오류를 내는지 확인한다.

입력: data/input/airquality_seoul_*.json
      서울 대기질 측정소 자료 두 시점(22시 40건, 23시 40건). 실제 공공 API 응답이다.

주의: 원자료에는 "언제 도착했는가"가 없다. 지연 도착을 재현하기 위해
      도착 시각을 아래 ARRIVAL_RULE로 구성한다. 난수를 쓰지 않으므로
      몇 번을 실행해도 같은 값이 나온다. 측정값(pm10)은 원자료 그대로다.

실행:
    cd practice/chapter3
    python3 code/3-3-lambda-skew.py
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = PROJECT_ROOT / "data" / "input"
INPUT_FILES = ["airquality_seoul_2200.json", "airquality_seoul_current.json"]
OUTPUT_PATH = PROJECT_ROOT / "data" / "output" / "ch3_lambda_skew.json"

# 도착 시각을 만드는 규칙(구성값). 정렬 순번이 5의 배수인 이벤트는 통신 장애로
# 72분 늦게 도착하고, 나머지는 3분 뒤에 도착한다.
ARRIVAL_RULE = {"기본_지연_분": 3, "지연_이벤트_지연_분": 72, "지연_주기": 5}

WINDOW_MINUTES = 60
GRACE_BEFORE = 15   # 처음 두 로직이 공유하는 지연 허용 시간(분)
GRACE_AFTER = 10    # 스피드 레이어만 줄인 뒤의 지연 허용 시간(분)


def load_events() -> list[dict[str, Any]]:
    """원자료를 읽어 이벤트 목록으로 만든다. 측정값은 그대로 쓴다."""
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
                "event_time": datetime.strptime(item["dataTime"], "%Y-%m-%d %H:%M"),
                "pm10": int(item["pm10Value"]),
            })
    rows.sort(key=lambda r: (r["event_time"], r["station"]))
    return rows


def attach_arrival(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """이벤트마다 도착 시각을 붙인다. 규칙은 ARRIVAL_RULE에 고정되어 있다."""
    for i, row in enumerate(rows):
        late = (i + 1) % ARRIVAL_RULE["지연_주기"] == 0
        delay = ARRIVAL_RULE["지연_이벤트_지연_분"] if late else ARRIVAL_RULE["기본_지연_분"]
        row["arrival_time"] = row["event_time"] + timedelta(minutes=delay)
        row["delay_min"] = delay
    return rows


def window_of(t: datetime) -> datetime:
    return t.replace(minute=0, second=0, microsecond=0)


def aggregate(rows: list[dict[str, Any]], grace_min: int | None) -> dict[str, dict[str, Any]]:
    """창별로 측정소 수와 평균 pm10을 집계한다.

    grace_min이 None이면 도착 시각을 보지 않고 전부 집계한다(배치 레이어).
    값이 있으면 창 마감(창 끝 + grace) 전에 도착한 것만 집계한다(스피드 레이어).
    """
    buckets: dict[datetime, list[dict[str, Any]]] = {}
    for row in rows:
        win = window_of(row["event_time"])
        if grace_min is not None:
            deadline = win + timedelta(minutes=WINDOW_MINUTES + grace_min)
            if row["arrival_time"] >= deadline:
                continue
        buckets.setdefault(win, []).append(row)

    out: dict[str, dict[str, Any]] = {}
    for win in sorted(buckets):
        vals = [r["pm10"] for r in buckets[win]]
        out[win.strftime("%Y-%m-%d %H:%M")] = {
            "count": len(vals),
            "pm10_mean": round(sum(vals) / len(vals), 2),
        }
    return out


def compare(batch: dict[str, Any], speed: dict[str, Any]) -> list[dict[str, Any]]:
    diffs = []
    for win in sorted(set(batch) | set(speed)):
        b = batch.get(win, {"count": 0, "pm10_mean": None})
        s = speed.get(win, {"count": 0, "pm10_mean": None})
        if b != s:
            diffs.append({
                "window": win,
                "batch_count": b["count"], "speed_count": s["count"],
                "batch_mean": b["pm10_mean"], "speed_mean": s["pm10_mean"],
                "missing": b["count"] - s["count"],
            })
    return diffs


def show(title: str, batch: dict[str, Any], speed: dict[str, Any]) -> list[dict[str, Any]]:
    print(title)
    print(f"    {'창':<17} {'배치 건수':>8} {'스피드 건수':>10} {'배치 평균':>9} {'스피드 평균':>11}")
    for win in sorted(set(batch) | set(speed)):
        b = batch.get(win, {"count": 0, "pm10_mean": 0})
        s = speed.get(win, {"count": 0, "pm10_mean": 0})
        print(f"    {win:<17} {b['count']:>8} {s['count']:>10} {b['pm10_mean']:>9} {s['pm10_mean']:>11}")
    diffs = compare(batch, speed)
    print(f"    → 어긋난 창 {len(diffs)}개")
    return diffs


def main() -> int:
    rows = attach_arrival(load_events())
    late = [r for r in rows if r["delay_min"] == ARRIVAL_RULE["지연_이벤트_지연_분"]]

    print(f"[1] 입력 — 이벤트 {len(rows)}건, 측정소 {len({r['station'] for r in rows})}개")
    print(f"    창 길이 {WINDOW_MINUTES}분, 창 {len({window_of(r['event_time']) for r in rows})}개")
    print(f"    도착 시각은 구성값 — 기본 {ARRIVAL_RULE['기본_지연_분']}분,"
          f" {ARRIVAL_RULE['지연_주기']}번째마다 {ARRIVAL_RULE['지연_이벤트_지연_분']}분")
    print(f"    지연 도착으로 구성한 이벤트 {len(late)}건")

    batch = aggregate(rows, grace_min=None)
    speed_before = aggregate(rows, grace_min=GRACE_BEFORE)
    diffs_before = show(
        f"\n[2] 두 로직의 지연 허용이 같을 때 (배치 전체 / 스피드 {GRACE_BEFORE}분)",
        batch, speed_before)

    speed_after = aggregate(rows, grace_min=GRACE_AFTER)
    diffs_after = show(
        f"\n[3] 스피드 레이어만 지연 허용을 {GRACE_BEFORE}분 → {GRACE_AFTER}분으로 줄인 뒤",
        batch, speed_after)

    print("\n[4] 이 실행이 끝나는 방식")
    for d in diffs_after:
        print(f"    {d['window']} — 스피드가 {d['missing']}건을 놓쳐"
              f" 평균이 {d['batch_mean']} 대 {d['speed_mean']}로 갈림")
    print("    예외 없음, 종료 코드 0 — 두 수치가 어긋난 채로 정상 종료함")

    result = {
        "input_files": INPUT_FILES,
        "arrival_rule": ARRIVAL_RULE,
        "arrival_time_is_constructed": True,
        "window_minutes": WINDOW_MINUTES,
        "event_count": len(rows),
        "late_event_count": len(late),
        "batch": batch,
        "speed_grace_%d" % GRACE_BEFORE: speed_before,
        "speed_grace_%d" % GRACE_AFTER: speed_after,
        "mismatch_before": diffs_before,
        "mismatch_after": diffs_after,
        "exit_code": 0,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\noutput={OUTPUT_PATH} mismatch_after={len(diffs_after)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
