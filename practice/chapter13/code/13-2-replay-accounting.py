#!/usr/bin/env python3
"""13주차 오프라인 재생(replay): Kafka·Docker 없이 통합 MVP의 회계를 다시 계산한다.

13-1의 통합 MVP는 Docker 데몬과 Kafka 브로커를 요구하므로 강의실에서 바로
돌리기 어렵다. 이 스크립트는 **같은 입력·같은 규칙**을 표준 라이브러리만으로
다시 실행해, 통합 실행이 남긴 산출물의 수치를 재현한다.

무엇을 그대로 옮겼는가(새 규칙 없음 — 전부 기존 코드에서 읽어 온 규약):
  - 드릴 주입 규칙: ingester.py의 `--resend-last 10`(7/2)·`--poison 1`(7/3)
    오염 페이로드는 ingester.py의 POISON_PAYLOAD 상수를 그대로 쓴다(난수 없음).
  - 정제 4갈래(공백 보정·약칭 보정·표준코드 매핑·미기재/미매핑 분리): processor.py
  - 멱등 반영: complaint_id를 키로 한 UPSERT. 재수신은 업무 상태를 바꾸지 않고
    관찰 횟수(seen_count)만 올린다.
  - 일 마감 집계·지연 채점: processor.py의 close_day()

무엇을 못 하는가:
  - 모델 API를 호출하지 않는다. champion 예측값은 커밋된 산출물
    data/output/ch13_bootstrap_summary.json의 export.export_check_forecast에서 읽는다.
    (9주차 champion은 평균 예측기라 입력과 무관하게 같은 값을 낸다 — 9·10주차 실측)

산출물: data/output/ch13_replay_accounting.json (새 파일 — 기존 산출물은 건드리지 않는다)
실행:   py scripts/run_and_capture.py 13 --file 13-2-replay-accounting.py
        또는 py practice/chapter13/code/13-2-replay-accounting.py
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]          # practice/chapter13
IN_DIR = BASE_DIR / "data" / "input"
OUT_DIR = BASE_DIR / "data" / "output"
REPO_ROOT = BASE_DIR.parents[1]
CH6_DAILY = REPO_ROOT / "practice" / "chapter6" / "data" / "output" / "daily"

DAYS = ["2026-07-01", "2026-07-02", "2026-07-03"]
ALIASES = {"강남": "강남구", "마포": "마포구", "관악": "관악구"}   # processor.py와 동일
POISON_PAYLOAD = "{poison: not-json, drill=D1"                    # ingester.py와 동일
# ingester.py에 넘긴 드릴 인자 — run_chapter13.py의 3절과 같다
DRILLS = {
    "2026-07-01": {"resend_last": 0, "poison": 0},
    "2026-07-02": {"resend_last": 10, "poison": 0},
    "2026-07-03": {"resend_last": 0, "poison": 1},
}


def load_mapping() -> dict[str, str]:
    with open(IN_DIR / "lawd_cd_seoul.csv", encoding="utf-8") as f:
        return {row["region_std"]: row["lawd_cd"] for row in csv.DictReader(f)}


def publish(day: str) -> list[str]:
    """ingester.py가 토픽에 흘려보내는 바이트열의 순서를 그대로 만든다."""
    src = IN_DIR / "complaints" / f"{day}.jsonl"
    lines = [x for x in src.read_text(encoding="utf-8").splitlines() if x.strip()]
    cfg = DRILLS[day]
    stream: list[str] = []
    for i, line in enumerate(lines):
        stream.append(line)
        if cfg["poison"] and i == 9:                 # 한복판에 끼워 넣는다(경계 아님)
            stream.extend([POISON_PAYLOAD] * cfg["poison"])
    if cfg["resend_last"]:
        stream.extend(lines[-cfg["resend_last"]:])   # ack 유실 시의 재전송 재현
    return stream


def clean(raw: str | None, mapping: dict[str, str]) -> dict:
    """processor.py ingest_complaint()의 정제 4갈래를 그대로 옮긴 것."""
    name = (raw or "").strip()
    ws = 1 if (raw is not None and name != raw) else 0
    alias = 1 if name in ALIASES else 0
    name = ALIASES.get(name, name)
    if not name:
        return {"status": "missing", "lawd_cd": None, "region": None,
                "ws_stripped": ws, "alias_fixed": alias}
    if name in mapping:
        return {"status": "mapped", "lawd_cd": mapping[name], "region": name,
                "ws_stripped": ws, "alias_fixed": alias}
    return {"status": "unmapped", "lawd_cd": None, "region": None,
            "ws_stripped": ws, "alias_fixed": alias}


def next_day(d: str) -> str:
    return (date.fromisoformat(d) + timedelta(days=1)).isoformat()


def main() -> int:
    mapping = load_mapping()
    boot = json.loads((OUT_DIR / "ch13_bootstrap_summary.json").read_text(encoding="utf-8"))
    forecast = boot["export"]["export_check_forecast"]   # 커밋된 champion 실측값

    state: dict[str, dict] = {}          # complaint_id → 업무 상태(멱등 UPSERT 대상)
    physical: Counter = Counter()        # 날짜별 물리 수신 건수
    quarantine: list[str] = []
    days_out: dict[str, dict] = {}
    predictions: list[dict] = []

    print("== 13주차 오프라인 재생: 정제·멱등·마감 회계 ==")
    print(f"   champion 예측값 {forecast} (출처: data/output/ch13_bootstrap_summary.json)")

    for day in DAYS:
        # ── 1. 발행·소비: 오염은 격리하고 파이프라인은 계속 간다 ──
        for payload in publish(day):
            try:
                rec = json.loads(payload)
            except json.JSONDecodeError:
                quarantine.append("json_parse_error")
                print(f"[replay] 오염 이벤트 격리(json_parse_error) — 파이프라인은 계속")
                continue
            d = rec["created_at"][:10]
            physical[d] += 1
            cid = rec["complaint_id"]
            if cid in state:
                state[cid]["seen_count"] += 1        # 재수신: 관찰 횟수만 오른다
                continue
            row = clean(rec.get("region_raw"), mapping)
            row.update(day=d, category=rec.get("category"), seen_count=1)
            state[cid] = row

        # ── 2. 일 마감: 회계 보존식과 지역별 확정 집계 ──
        rows = [r for r in state.values() if r["day"] == day]
        unique = len(rows)
        redelivered = sum(r["seen_count"] for r in rows) - unique
        counts = Counter(r["status"] for r in rows)
        quality = {
            "date": day,
            "physical_received": physical[day],
            "unique": unique,
            "dedup_dropped": redelivered,
            "mapped": counts["mapped"],
            "missing": counts["missing"],
            "unmapped": counts["unmapped"],
            "ws_stripped": sum(r["ws_stripped"] for r in rows),
            "alias_fixed": sum(r["alias_fixed"] for r in rows),
        }
        quality["preservation_ok"] = (
            quality["physical_received"] == unique + redelivered
            and unique == counts["mapped"] + counts["missing"] + counts["unmapped"]
        )
        by_region_counter = Counter((r["lawd_cd"], r["region"])
                                    for r in rows if r["status"] == "mapped")
        by_region = [{"lawd_cd": cd, "region": rg, "count": n}
                     for (cd, rg), n in sorted(by_region_counter.items())]
        days_out[day] = {"quality": quality, "by_region": by_region}
        print(f"[replay] {day} 마감: 물리수신 {quality['physical_received']}"
              f" / 고유 {unique} (중복 흡수 {redelivered})"
              f" → 매핑 {quality['mapped']} · 미기재 {quality['missing']}"
              f" · 미매핑 {quality['unmapped']} · 보존 {quality['preservation_ok']}")

        # ── 3. 지연 채점: 오늘 확정치로 어제 만든 예측을 채점한다 ──
        actual = {r["lawd_cd"]: r["count"] for r in by_region}
        labeled_today = [p for p in predictions if p["target_date"] == day]
        for p in labeled_today:
            p["actual"] = actual.get(p["lawd_cd"])
            p["abs_error"] = abs(p["forecast"] - p["actual"])
        if labeled_today:
            mae = round(sum(p["abs_error"] for p in labeled_today) / len(labeled_today), 4)
            print(f"[replay] {day}: 지연 레이블 도착 — 예측 {len(labeled_today)}건 채점,"
                  f" 일 MAE {mae}")

        # ── 4. 익일 예측: 오늘 확정 건수가 내일 예측의 입력 피처다 ──
        target = next_day(day)
        for r in by_region:
            predictions.append({"target_date": target, "lawd_cd": r["lawd_cd"],
                                "region": r["region"], "x_prev_count": r["count"],
                                "forecast": forecast, "actual": None, "abs_error": None})

    # ── 5. 앞 주차·통합 실행 산출물과 대조 ──
    labeled = [p for p in predictions if p["abs_error"] is not None]
    mae_by_day = {}
    for d in sorted({p["target_date"] for p in labeled}):
        errs = [p["abs_error"] for p in labeled if p["target_date"] == d]
        mae_by_day[d] = round(sum(errs) / len(errs), 4)
    overall_mae = round(sum(p["abs_error"] for p in labeled) / len(labeled), 4)

    report = json.loads((OUT_DIR / "ch13_integration_report.json").read_text(encoding="utf-8"))
    checks: dict[str, object] = {}
    for d in DAYS:
        ch6q = json.loads((CH6_DAILY / d / "quality.json").read_text(encoding="utf-8"))
        ch6s = json.loads((CH6_DAILY / d / "daily_summary.json").read_text(encoding="utf-8"))
        q = days_out[d]["quality"]
        # 6주차는 파일을 읽는 배치라 물리 수신에 수송 재전송이 없다.
        # 그래서 물리수신이 아니라 **고유 이후의 4갈래**를 맞춰 본다.
        checks[f"{d}_정제회계가_6주차_배치와_일치"] = all(
            q[k] == ch6q[k] for k in ("mapped", "missing", "unmapped",
                                      "ws_stripped", "alias_fixed"))
        checks[f"{d}_확정집계가_6주차_배치와_일치"] = (
            {r["lawd_cd"]: r["count"] for r in days_out[d]["by_region"]}
            == {r["lawd_cd"]: r["count"] for r in ch6s["by_region"]})
        checks[f"{d}_회계보존식_성립"] = q["preservation_ok"]
        checks[f"{d}_통합실행_회계와_일치"] = all(
            q[k] == report["days"][d]["quality"][k]
            for k in ("physical_received", "unique", "dedup_dropped",
                      "mapped", "missing", "unmapped"))
    checks["격리_1건"] = len(quarantine) == 1
    checks["지연MAE가_통합실행과_일치"] = (
        mae_by_day == report["delayed_evaluation"]["mae_by_target_date"]
        and overall_mae == report["delayed_evaluation"]["overall_mae"])

    out = {
        "days": days_out,
        "delayed_evaluation": {"labeled": len(labeled),
                               "mae_by_target_date": mae_by_day,
                               "overall_mae": overall_mae},
        "predictions": predictions,
        "quarantined": len(quarantine),
        "quarantine_reasons": sorted(set(quarantine)),
        "champion_forecast_source": "data/output/ch13_bootstrap_summary.json",
        "cross_checks": checks,
    }
    (OUT_DIR / "ch13_replay_accounting.json").write_text(
        json.dumps(out, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")

    print("\n== 대조표 ==")
    for k, v in checks.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")
    print(f"== 지연 평가: 일별 MAE {mae_by_day}, 전체 {overall_mae}, 미채점"
          f" {len(predictions) - len(labeled)}건 ==")
    ok = all(checks.values())
    print("CH13_REPLAY_" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
