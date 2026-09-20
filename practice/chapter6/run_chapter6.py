#!/usr/bin/env python3
"""Chapter 7: 일별 민원 요약 DAG — 실습 실행기(전체 시나리오).

시나리오
  A. 3일치(2026-07-01~03) 일별 DAG 실행 — 의존성 순서·정제 통계 관찰
  B. 같은 날짜(07-01) 재실행 — 산출물 해시 비교(멱등·재현성 증빙)
  C. 입력 없는 날짜(07-04) 실행 — 실패 전파(failed / upstream_failed) 관찰
  D. 주간 롤업 DAG 실행 — 일별 산출물 합산 + 총계 보존 검증

실행:
    cd practice/chapter6
    source venv/bin/activate
    python run_chapter6.py
증거 산출물: data/output/ch6_batch_run_report.json
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "data" / "output"
DAG_FILE = BASE_DIR / "code" / "6-1-daily-report-dag.py"

# airflow import 전에 환경을 실습 폴더로 고정한다(DAG 파일과 동일 값).
os.environ["AIRFLOW_HOME"] = str(OUTPUT_DIR / "airflow_home")
os.environ["AIRFLOW__CORE__DAGS_FOLDER"] = str(DAG_FILE.parent)
os.environ["AIRFLOW__CORE__LOAD_EXAMPLES"] = "False"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module():
    spec = importlib.util.spec_from_file_location("ch6_daily_report_dag", DAG_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def task_states(dagrun) -> list[dict]:
    """태스크별 상태·시작 시각(실행 순서의 증거)을 수집한다."""
    tis = sorted(
        dagrun.get_task_instances(),
        key=lambda ti: (ti.start_date is None, ti.start_date),
    )
    return [
        {
            "task_id": ti.task_id,
            "state": str(ti.state),
            "start": ti.start_date.isoformat() if ti.start_date else None,
        }
        for ti in tis
    ]


def main() -> int:
    import pendulum

    # 재현성: 이전 실행 산출물(메타데이터 DB 포함)을 지우고 시작하되,
    # data/output 전체가 아니라 이 실행이 다시 만드는 것만 지운다.
    # 같은 폴더에 6-2~6-5의 산출물과 학생이 제출할 파일이 함께 있기 때문이다.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("airflow_home", "daily", "weekly"):
        target = OUTPUT_DIR / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    module = load_module()
    print("== 준비: 메타데이터 DB 마이그레이션 + DAG 직렬화 ==")
    module.bootstrap()

    report: dict = {
        "airflow_version": __import__("airflow").__version__,
        "python_version": sys.version.split()[0],
        "daily_runs": [],
    }

    # ── A. 3일치 일별 실행 ──
    print("\n== 시나리오 A: 3일치 일별 DAG 실행 ==")
    for day in ("2026-07-01", "2026-07-02", "2026-07-03"):
        y, m, d = map(int, day.split("-"))
        dagrun = module.daily_dag.test(logical_date=pendulum.datetime(y, m, d, tz="UTC"))
        quality = json.loads((OUTPUT_DIR / "daily" / day / "quality_check.json").read_text(encoding="utf-8"))
        summary = json.loads((OUTPUT_DIR / "daily" / day / "daily_summary.json").read_text(encoding="utf-8"))
        report["daily_runs"].append(
            {
                "logical_date": day,
                "dagrun_state": str(dagrun.state),
                "tasks": task_states(dagrun),
                "quality": quality,
                "by_region": summary["by_region"],
                "top_category": summary["top_category"],
            }
        )
        print(f"  {day}: dagrun={dagrun.state}, mapped={quality['mapped']}, "
              f"missing={quality['missing']}, unmapped={quality['unmapped']}, dup={quality['dup_removed']}")

    # ── B. 같은 날짜 재실행 → 산출물 해시 비교 ──
    print("\n== 시나리오 B: 2026-07-01 재실행 — 산출물 해시 비교(멱등) ==")
    day_out = OUTPUT_DIR / "daily" / "2026-07-01"
    before = {name: sha256(day_out / name) for name in ("daily_summary.json", "report.md")}
    rerun = module.daily_dag.test(logical_date=pendulum.datetime(2026, 7, 1, tz="UTC"))
    after = {name: sha256(day_out / name) for name in ("daily_summary.json", "report.md")}
    identical = before == after
    report["idempotency_check"] = {
        "logical_date": "2026-07-01",
        "rerun_state": str(rerun.state),
        "sha256_before": before,
        "sha256_after": after,
        "identical": identical,
    }
    print(f"  재실행 dagrun={rerun.state}, 산출물 동일={identical}")
    for name in before:
        print(f"    {name}: {before[name][:16]}… -> {after[name][:16]}…")

    # ── C. 입력 없는 날짜 → 실패 전파 관찰 ──
    print("\n== 시나리오 C: 2026-07-04(입력 없음) — 실패 전파 관찰 ==")
    fail_run = module.daily_dag.test(logical_date=pendulum.datetime(2026, 7, 4, tz="UTC"))
    fail_tasks = task_states(fail_run)
    report["failure_run"] = {
        "logical_date": "2026-07-04",
        "dagrun_state": str(fail_run.state),
        "tasks": fail_tasks,
    }
    print(f"  dagrun={fail_run.state}")
    for t in fail_tasks:
        print(f"    {t['task_id']}: {t['state']}")

    # ── D. 주간 롤업 ──
    print("\n== 시나리오 D: 주간 롤업 DAG 실행 ==")
    weekly_run = module.weekly_dag.test(logical_date=pendulum.datetime(2026, 7, 5, tz="UTC"))
    weekly = json.loads(
        (OUTPUT_DIR / "weekly" / "2026-07-05" / "weekly_summary.json").read_text(encoding="utf-8")
    )
    report["weekly_run"] = {
        "dagrun_state": str(weekly_run.state),
        "tasks": task_states(weekly_run),
        "summary": weekly,
    }
    print(f"  dagrun={weekly_run.state}, physical_total={weekly['physical_total']}, "
          f"mapped_total={weekly['mapped_total']}, preservation_ok={weekly['preservation_ok']}")
    for row in weekly["by_region"]:
        print(f"    {row['lawd_cd']} {row['region']}: {row['count']}건")

    # ── 증거 저장 + 종합 판정 ──
    evidence = OUTPUT_DIR / "ch6_batch_run_report.json"
    evidence.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    ok = (
        all(r["dagrun_state"] == "success" for r in report["daily_runs"])
        and report["idempotency_check"]["identical"]
        and report["failure_run"]["dagrun_state"] == "failed"
        and report["weekly_run"]["dagrun_state"] == "success"
        and weekly["preservation_ok"]
    )
    print(f"\n증거 파일: {evidence}")
    print("CH6_RUN_" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
