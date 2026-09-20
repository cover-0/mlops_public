#!/usr/bin/env python3
"""5-1: 지역별 민원 이벤트 윈도우 집계 — 스트리밍·watermark 관찰.

입력 데이터의 정직성: 민원 이벤트는 시뮬레이션 입력이다(4·5장과 동일 프레이밍).
이 실습의 관찰 대상은 데이터 내용이 아니라 Spark Structured Streaming 엔진의
실제 동작(윈도우 집계, watermark의 수용·폐기)이며, 본문에 인용하는 수치는
전부 이 스크립트의 실제 실행 산출물에서 나온다.

시나리오 — 이벤트 파일 3개를 스트림 입력 디렉터리에 순차 "도착"시킨다:
  배치1: 22:00–22:10 창의 정시 이벤트 6건
  배치2: 22:10–22:20 창 이벤트 4건 + watermark "안" 지연 이벤트 1건(22:04 발생)
  배치3: watermark "밖" 지연 이벤트 1건(21:49 발생) + 22:20–22:30 창 이벤트 2건

각 파일 투입 후 processAllAvailable()로 micro-batch 경계를 고정해,
실행마다 같은 배치 구성이 되도록 한다.

실행(Java 17+ 필요):
    python3 code/5-1-streaming-window-aggregation.py
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# 워커/드라이버 파이썬 불일치(PYTHON_VERSION_MISMATCH) 예방:
# 이 스크립트를 실행한 인터프리터를 워커에도 강제한다.
os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import StringType, StructField, StructType

BASE_DIR = Path(__file__).resolve().parent.parent
STREAM_DIR = BASE_DIR / "data" / "input" / "stream"
OUTPUT_DIR = BASE_DIR / "data" / "output"
CHECKPOINT_DIR = OUTPUT_DIR / "checkpoint"
COUNTS_PATH = OUTPUT_DIR / "ch5_window_counts.jsonl"
REPORT_PATH = OUTPUT_DIR / "ch5_late_event_report.json"
SLIDING_PATH = OUTPUT_DIR / "ch5_sliding_demo.json"

WATERMARK_DELAY = "10 minutes"
WINDOW_SIZE = "10 minutes"

# 이벤트 시간은 고정값(재현성). 날짜 자체는 의미 없고 "창과 지연"의 상대 관계가 핵심.
BATCHES: dict[str, list[dict]] = {
    "batch1.json": [  # 22:00–22:10 창의 정시 이벤트
        {"event_id": "E01", "district": "강남구", "category": "불법주차", "event_time": "2026-07-07 22:01:00"},
        {"event_id": "E02", "district": "마포구", "category": "소음",     "event_time": "2026-07-07 22:02:00"},
        {"event_id": "E03", "district": "강남구", "category": "도로파손", "event_time": "2026-07-07 22:03:00"},
        {"event_id": "E04", "district": "관악구", "category": "쓰레기",   "event_time": "2026-07-07 22:05:00"},
        {"event_id": "E05", "district": "강남구", "category": "불법주차", "event_time": "2026-07-07 22:08:00"},
        {"event_id": "E06", "district": "마포구", "category": "가로등",   "event_time": "2026-07-07 22:09:00"},
    ],
    "batch2.json": [  # 다음 창 + watermark 안 지연 이벤트(LATE_OK)
        {"event_id": "E07", "district": "강남구", "category": "소음",     "event_time": "2026-07-07 22:11:00"},
        {"event_id": "E08", "district": "마포구", "category": "불법주차", "event_time": "2026-07-07 22:12:00"},
        {"event_id": "LATE_OK", "district": "강남구", "category": "쓰레기", "event_time": "2026-07-07 22:04:00"},
        {"event_id": "E09", "district": "강남구", "category": "도로파손", "event_time": "2026-07-07 22:14:00"},
        {"event_id": "E10", "district": "마포구", "category": "소음",     "event_time": "2026-07-07 22:18:00"},
    ],
    "batch3.json": [  # watermark 밖 지연 이벤트(LATE_DROP) + 최신 이벤트
        {"event_id": "LATE_DROP", "district": "마포구", "category": "소음", "event_time": "2026-07-07 21:49:00"},
        {"event_id": "E11", "district": "관악구", "category": "불법주차", "event_time": "2026-07-07 22:21:00"},
        {"event_id": "E12", "district": "강남구", "category": "쓰레기",   "event_time": "2026-07-07 22:24:00"},
    ],
}

SCHEMA = StructType([
    StructField("event_id", StringType()),
    StructField("district", StringType()),
    StructField("category", StringType()),
    StructField("event_time", StringType()),
])


def reset_dirs() -> None:
    """이 실행이 다시 만드는 경로만 정리한다.

    체크포인트는 이 스크립트가 만드는 상태 디렉터리이므로 통째로 비운다.
    입력 스트림 디렉터리는 비우지 않는다 — 그 안의 배치 파일은 5-2~5-4 실습의
    입력이기도 해서, 이 실행이 중간에 실패하면 다른 실습까지 멈추기 때문이다.
    대신 stash_stream_files()가 실행 동안만 치웠다가 되돌린다.
    산출물 세 개도 여기서 지우지 않는다. 계산이 끝난 뒤 덮어쓴다.
    """
    if CHECKPOINT_DIR.exists():
        shutil.rmtree(CHECKPOINT_DIR)
    for d in (STREAM_DIR, CHECKPOINT_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)


def stash_stream_files() -> None:
    """스트림 디렉터리를 비우되, 프로세스가 끝날 때 원본을 되돌리도록 등록한다.

    파일 소스는 "새 파일이 도착하는 것"을 micro-batch 경계로 삼으므로
    쿼리를 시작할 때 디렉터리가 비어 있어야 한다. 그렇다고 원본을 지우면
    실행이 중간에 실패했을 때 입력이 사라지므로, 옮겨 두었다가 복원한다.
    이 실행이 같은 이름으로 다시 쓴 파일은 새 것을 남긴다.
    """
    backup = Path(tempfile.mkdtemp(prefix="ch5_stream_"))
    moved: list[str] = []
    for f in sorted(STREAM_DIR.glob("*.json")):
        shutil.move(str(f), str(backup / f.name))
        moved.append(f.name)

    def restore() -> None:
        for name in moved:
            target = STREAM_DIR / name
            if not target.exists():
                shutil.move(str(backup / name), str(target))
        shutil.rmtree(backup, ignore_errors=True)

    atexit.register(restore)


def build_spark() -> SparkSession:
    return (
        SparkSession.builder.appName("ch6-window-aggregation")
        .master("local[2]")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.sql.session.timeZone", "Asia/Seoul")
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate()
    )


def main() -> None:
    reset_dirs()
    # Spark 준비가 실패하면 여기서 끝난다 — 그 전까지는 입력·산출물을 건드리지 않는다
    spark = build_spark()
    spark.sparkContext.setLogLevel("ERROR")

    # 여기서부터 이 실행이 다시 만드는 파일을 정리한다
    stash_stream_files()
    if COUNTS_PATH.exists():
        COUNTS_PATH.unlink()  # 아래 sink가 append 모드로 쓰므로 먼저 비운다

    events = (
        spark.readStream.schema(SCHEMA).json(str(STREAM_DIR))
        .withColumn("event_time", F.to_timestamp("event_time"))
    )
    # 핵심: watermark 선언 + 이벤트 시간 기준 tumbling window 집계
    counts = (
        events.withWatermark("event_time", WATERMARK_DELAY)
        .groupBy(F.window("event_time", WINDOW_SIZE), "district")
        .count()
    )

    micro_batches: list[dict] = []

    def sink(batch_df, batch_id: int) -> None:
        rows = [
            {
                "micro_batch": batch_id,
                "window_start": r["window"]["start"].strftime("%H:%M"),
                "window_end": r["window"]["end"].strftime("%H:%M"),
                "district": r["district"],
                "count": r["count"],
            }
            for r in batch_df.collect()
        ]
        micro_batches.append({"micro_batch": batch_id, "rows": rows})
        with COUNTS_PATH.open("a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    query = (
        counts.writeStream.outputMode("update")
        .foreachBatch(sink)
        .option("checkpointLocation", str(CHECKPOINT_DIR))
        .start()
    )

    # 파일을 순차 "도착"시키고 micro-batch 경계를 고정한다
    dropped_after_batch: dict[str, int] = {}
    for name, rows in BATCHES.items():
        path = STREAM_DIR / name
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8",
        )
        query.processAllAvailable()
        dropped = sum(
            op.get("numRowsDroppedByWatermark", 0)
            for p in query.recentProgress
            for op in p.get("stateOperators", [])
        )
        dropped_after_batch[name] = dropped
    query.stop()

    # ── 관찰 결과에서 지연 이벤트 처리 평가표를 "계산"한다(단정 금지) ──
    def count_of(mb_rows: list[dict], window_start: str, district: str):
        for r in mb_rows:
            if r["window_start"] == window_start and r["district"] == district:
                return r["count"]
        return None

    b1 = next((m["rows"] for m in micro_batches if any(
        r["window_start"] == "22:00" for r in m["rows"])), [])
    b2_updates = [m["rows"] for m in micro_batches[1:]]
    gangnam_2200_initial = count_of(b1, "22:00", "강남구")
    gangnam_2200_after = None
    late_ok_batch = None
    for i, rows in enumerate(b2_updates, start=1):
        c = count_of(rows, "22:00", "강남구")
        if c is not None:
            gangnam_2200_after, late_ok_batch = c, i
    total_dropped = dropped_after_batch.get("batch3.json", 0)

    late_report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "watermark_delay": WATERMARK_DELAY,
        "window_size": WINDOW_SIZE,
        "input_note": "민원 이벤트는 시뮬레이션 입력. 수용/폐기 판정은 실제 실행 산출물에서 계산.",
        "late_events": [
            {
                "event_id": "LATE_OK",
                "event_time": "22:04",
                "arrived": "배치2(엔진이 22:09까지 관측한 뒤)",
                "watermark_at_arrival": "21:59 (= 22:09 - 10m)",
                "decision": "수용" if gangnam_2200_after == (gangnam_2200_initial or 0) + 1 else "판정 불일치(로그 확인)",
                "evidence": f"창 22:00-22:10 강남구 count {gangnam_2200_initial} → {gangnam_2200_after}",
            },
            {
                "event_id": "LATE_DROP",
                "event_time": "21:49",
                "arrived": "배치3(엔진이 22:18까지 관측한 뒤)",
                "watermark_at_arrival": "22:08 (= 22:18 - 10m)",
                "decision": "폐기" if total_dropped >= 1 else "판정 불일치(로그 확인)",
                "evidence": f"numRowsDroppedByWatermark 누적 = {total_dropped}",
            },
        ],
        "dropped_by_watermark_cumulative": dropped_after_batch,
        "micro_batches": micro_batches,
    }
    REPORT_PATH.write_text(json.dumps(late_report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")

    # ── 보조: 같은 이벤트 전체로 sliding window 비교(배치 계산으로 명시) ──
    all_events = [r for rows in BATCHES.values() for r in rows]
    static_df = (
        spark.createDataFrame(all_events, schema=SCHEMA)
        .withColumn("event_time", F.to_timestamp("event_time"))
    )
    sliding = (
        static_df.filter(F.col("district") == "강남구")
        .groupBy(F.window("event_time", "10 minutes", "5 minutes"))
        .count()
        .orderBy("window")
        .collect()
    )
    sliding_rows = [
        {"window": f'{r["window"]["start"].strftime("%H:%M")}-{r["window"]["end"].strftime("%H:%M")}',
         "count": r["count"]}
        for r in sliding
    ]
    SLIDING_PATH.write_text(
        json.dumps({"note": "전체 이벤트에 대한 배치 계산(강남구, 10분 창·5분 슬라이드)",
                    "rows": sliding_rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    spark.stop()

    print(json.dumps({"late_events": late_report["late_events"],
                      "dropped": dropped_after_batch,
                      "sliding_강남구": sliding_rows}, ensure_ascii=False, indent=2))
    print(f"\n[저장] {COUNTS_PATH}\n[저장] {REPORT_PATH}\n[저장] {SLIDING_PATH}")


if __name__ == "__main__":
    main()
