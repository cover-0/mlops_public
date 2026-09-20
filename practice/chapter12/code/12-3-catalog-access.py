#!/usr/bin/env python3
"""12주차 강의 실행 블록 1 — 피처 카탈로그와 접근 판정.

`12-1-feature-governance.py`의 구현(카탈로그 적재·접근 판정)을 그대로 불러와
같은 입력(6·7주차 확정 산출물 스냅숏)으로 다시 계산하고, 강의 본문이 인용하는
값을 화면에 출력한다.

  - SQLite는 메모리에만 만들고 파일을 쓰지 않는다.
  - data/output/ 의 기존 증거 JSON은 읽지도 쓰지도 않는다(값은 입력에서 다시 유도).
  - 난수를 쓰지 않으므로 몇 번 실행해도 같은 출력이 나온다.

실행: python scripts/run_and_capture.py 12 --file 12-3-catalog-access.py
"""

from __future__ import annotations

import importlib.util
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc
CODE_DIR = Path(__file__).resolve().parent
INPUT_DIR = CODE_DIR.parent / "data" / "input"


def load_governance_module():
    """파일명이 식별자로 쓸 수 없는 형태라 경로로 직접 적재한다."""
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
    finally:
        conn.close()

    print("[1] 카탈로그 — 정의를 손으로 적지 않고 7주차 등록 파일에서 가져온다")
    print("    정의 원천  data/input/ch7_feature_definitions.json (7주차 등록 추출)")
    print(f"    피처 수    {len(catalog)}개")
    for c in catalog:
        print(f"    - {c['feature_name']}({c['dtype']})")
        print(f"        정의      {c['definition']}")
        print(f"        소유자    {c['owner']}")
        print(f"        개인정보  {c['privacy']}")
        print(f"        소비자    {len(c['consumers'])}곳 — {', '.join(c['consumers'])}")
        print(f"        보존기간  {c['ttl_days']}일, 등록 서비스 {c['version']}")

    print()
    print("[2] 접근 요청 — 같은 판정 코드에 12건을 순서대로 넣는다")
    print("    seq 역할                피처                행위             판정   사유")
    for r in access["log"]:
        print(f"    {r['seq']:>3} {r['role']:<19} {r['feature']:<19} "
              f"{r['action']:<16} {r['decision']:<6} {r['reason']}")
    print(f"    요청 {access['requests']}건 — 허용 {access['allow']} / 거부 {access['deny']}")

    print()
    print("[3] 거부 4건이 걸린 관문 — 서로 다른 지점에서 막혔다")
    for r in access["log"]:
        if r["decision"] != "DENY":
            continue
        if r["role"] not in gov.ACCESS_POLICY:
            gate = "1번 관문: 역할이 정책에 없음"
        elif r["feature"] not in {"complaint_count", "day_unmapped_rate"}:
            gate = "2번 관문: 피처가 카탈로그에 없음"
        else:
            gate = "3번 관문: 역할에 그 행위 권한 없음"
        print(f"    {r['role']}·{r['feature']}·{r['action']}")
        print(f"        {gate}")
        print(f"        요청 목적: {r['purpose']}")

    print()
    print("[4] 같은 요청을 '기록만 하고 막지는 않는' 설계에 넣으면")
    denied = [r for r in access["log"] if r["decision"] == "DENY"]
    denied_value = [r for r in denied if r["action"] == "read_value"]
    denied_log = [r for r in denied if r["action"] == "read_log"]
    print(f"    로그에 남는 줄 수      {len(access['log'])}줄 — 차단 설계와 같음")
    print(f"    실제로 값이 나가는 건수 {access['allow']}건 → {access['requests']}건")
    print(f"    새로 나가는 원시 값 조회 {len(denied_value)}건")
    for r in denied_value:
        print(f"        {r['role']}·{r['feature']} — {r['purpose']}")
    print(f"    새로 나가는 로그 열람  {len(denied_log)}건")
    for r in denied_log:
        print(f"        {r['role']}·{r['feature']} — {r['purpose']}")
    print("    기록은 사고를 설명할 뿐 사고를 막지 않는다")

    print()
    print("[5] 로그가 뒤에 답할 수 있는 질문 — 원시 값을 읽은 주체")
    readers: dict[str, list[str]] = {}
    for r in access["log"]:
        if r["action"] == "read_value" and r["decision"] == "ALLOW":
            readers.setdefault(r["role"], []).append(r["purpose"])
    for role, purposes in readers.items():
        print(f"    {role}: {len(purposes)}건 — {', '.join(purposes)}")
    print("    목적이 함께 적혀 있어야 '등록된 목적 안의 사용이었는가'를 사후에 판정할 수 있다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
