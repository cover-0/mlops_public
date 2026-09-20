#!/usr/bin/env python3
"""12주차 강의 실행 블록 2 — 품질 규칙, 임계값, 정의 변경.

`12-1-feature-governance.py`의 품질 검사·변경 관리·감사 점검표 구현을 그대로
불러와 같은 입력으로 다시 계산하고, 강의 본문이 인용하는 값을 출력한다.

  - SQLite는 메모리에만 만들고 파일을 쓰지 않는다.
  - 임계값 역산(3)은 이 스크립트에서 같은 입력의 실패율로 계산한다.
  - 난수를 쓰지 않으므로 몇 번 실행해도 같은 출력이 나온다.

실행: python scripts/run_and_capture.py 12 --file 12-4-quality-change.py
"""

from __future__ import annotations

import importlib.util
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc
CODE_DIR = Path(__file__).resolve().parent
INPUT_DIR = CODE_DIR.parent / "data" / "input"

# 하류 업무가 견딜 수 있는 오차에서 역산한 후보 상한 세 개(비교용)
THRESHOLDS = [0.06, 0.05, 0.045]


def load_governance_module():
    path = CODE_DIR / "12-1-feature-governance.py"
    spec = importlib.util.spec_from_file_location("ch12_governance", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    gov = load_governance_module()
    definitions, feature_rows, quality_by_day = gov.load_inputs(INPUT_DIR)
    base_time = max(
        datetime.strptime(r["event_timestamp"], "%Y-%m-%dT%H:%M:%S+00:00").replace(tzinfo=UTC)
        for r in feature_rows
    )

    conn = sqlite3.connect(":memory:")
    try:
        catalog = gov.build_catalog(conn, definitions)
        names = {c["feature_name"] for c in catalog}
        access = gov.evaluate_access(conn, names, base_time)
        quality = gov.check_quality(feature_rows)
        change = gov.manage_change(conn, quality_by_day, catalog, feature_rows, base_time)
        audit = gov.build_audit_checklist(catalog, access, quality, change)
    finally:
        conn.close()

    print("[1] 검사 대상 — 6주차 확정 집계 3일 × 3지역")
    print("    날짜          지역     complaint_count  day_unmapped_rate")
    for r in feature_rows:
        print(f"    {r['aggregate_date']}  {r['region']:<7} {r['complaint_count']:>15} "
              f"{r['day_unmapped_rate']:>18}")
    print(f"    합계 {quality['rows']}행")
    print("    (실패율 열은 6주차가 기록해 둔 값이라 소수 셋째 자리다. [4]에서는 같은 값을")
    print("     원자료로 다시 계산해 넷째 자리로 적는다 — 0.059 와 0.0588 은 같은 수다)")

    print()
    print("[2] 품질 규칙 — 값 하나하나가 계약을 지켰는지 검사한다")
    for rule in quality["rules"]:
        mark = "PASS" if rule["passed"] else "FAIL"
        print(f"    [{mark}] {rule['quality_dim']:<4} {rule['rule']}")
        print(f"            {rule['detail']}")
    print(f"    3종 전부 통과: {quality['all_passed']}")

    print()
    print("[3] 임계값은 관례가 아니라 하류 업무에서 역산한다")
    print("    (판정 규칙: 그날의 매핑 실패율 > 상한 이면 그날 피처를 차단)")
    rates = [(d["date"], d["v1_rate"]) for d in change["per_day"]]
    for th in THRESHOLDS:
        blocked = [date for date, rate in rates if rate > th]
        print(f"    상한 {th:<6} 차단 {len(blocked)}일  {', '.join(blocked) if blocked else '없음'}")
    print("    같은 데이터인데 상한 한 자리를 바꾸면 차단 일수가 0일과 3일 사이를 오간다")

    print()
    print(f"[4] 정의 변경 — {change['feature']}")
    print(f"    v1  {change['from_def']}")
    print(f"    v2  {change['to_def']}")
    print(f"    사유 {change['reason']}")
    print("    날짜          unmapped  valid  physical   v1      v2      값이 바뀌는가")
    for d in change["per_day"]:
        mark = "예" if d["changed"] else "아니오"
        print(f"    {d['date']}  {d['unmapped']:>8}  {d['valid']:>5}  {d['physical']:>8}   "
              f"{d['v1_rate']:<7} {d['v2_rate']:<7} {mark}")
    print(f"    값이 바뀌는 날 {change['changed_days']}일, 영향 행 {change['changed_rows']}행 "
          f"(그날의 3지역)")
    print(f"    영향 소비자 {len(change['impacted_consumers'])}곳 — "
          f"{', '.join(change['impacted_consumers'])}")
    print(f"    요청자 {change['requester']} / 승인자 {change['approver']}")

    print()
    print("[5] 버전 없이 덮어쓰면 — 같은 이름이 두 값을 가리킨다")
    conflict = next(d for d in change["per_day"] if d["changed"])
    print(f"    {conflict['date']} day_unmapped_rate")
    print(f"        v1 정의로 저장된 값  {conflict['v1_rate']}")
    print(f"        v2 정의로 저장된 값  {conflict['v2_rate']}")
    print(f"        차이 {round(conflict['v1_rate'] - conflict['v2_rate'], 4)}")
    print("    이름이 같으므로 소비자는 정의가 바뀐 사실을 모른 채 다른 값을 읽는다")
    print("    과거 예측을 재현하려면 그때 쓰인 정의가 어느 쪽인지 기록이 있어야 한다")

    print()
    print(f"[6] 감사 점검표 — 위 기록에서 자동 생성 ({audit['passed']}/{audit['total']})")
    for item in audit["items"]:
        mark = "PASS" if item["passed"] else "FAIL"
        print(f"    {item['no']:>2}. [{mark}] {item['item']}")
    print("    사람의 주장이 아니라 카탈로그·로그·품질·변경 이력이 근거다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
