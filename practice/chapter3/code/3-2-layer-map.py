#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3-2-layer-map.py
제3장 — compose 서비스를 5계층에 배정한다

3-1이 만든 구성 계획(ch3_compose_plan.json)을 읽어, 서비스 하나하나를
수집·저장·처리·서빙·모니터링 다섯 계층에 배정하고 계층당 개수를 센다.
"계층과 서비스는 1대 1이 아니다"를 숫자로 확인하는 것이 목적이다.

실행:
    cd practice/chapter3
    python3 code/3-2-layer-map.py

선행:
    code/3-1-compose-plan.py 를 먼저 실행해야 한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = PROJECT_ROOT / "data" / "output" / "ch3_compose_plan.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "output" / "ch3_layer_map.json"

LAYERS = ["수집", "저장", "처리", "서빙", "모니터링"]

# 서비스를 계층에 배정하는 규칙. 이 표를 바꾸면 아래 모든 수가 바뀐다.
LAYER_OF = {
    "zookeeper": "수집",     # kafka 브로커의 메타데이터를 관리한다
    "kafka": "수집",
    "postgres": "저장",
    "prometheus": "모니터링",
    "grafana": "모니터링",
    "kafka-ui": "모니터링",  # 판단이 갈리는 항목 — 아래 [4]에서 다시 본다
}

# 비어 있는 계층을 언제 채우는지. 강의계획서의 주차 번호.
FILLED_AT = {
    "처리": "5주차(스트리밍)·6주차(배치)",
    "서빙": "10주차(모델 배포)",
}

# 그 계층이 없을 때 무엇이 실패하는지.
FAILS_WITHOUT = {
    "수집": "유실·과부하",
    "저장": "재처리·감사 불가",
    "처리": "원천이 지표가 되지 못함",
    "서빙": "데이터가 서비스되지 않음",
    "모니터링": "침묵 실패 미발견",
}


def load_plan() -> dict[str, Any]:
    if not PLAN_PATH.exists():
        raise FileNotFoundError(
            f"구성 계획이 없습니다: {PLAN_PATH}\n"
            "먼저 `python3 code/3-1-compose-plan.py`를 실행하세요."
        )
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def assign(services: dict[str, Any], rule: dict[str, str]) -> dict[str, list[str]]:
    """서비스를 계층에 배정한다. 규칙에 없는 서비스는 '미분류'로 모은다."""
    table: dict[str, list[str]] = {layer: [] for layer in LAYERS}
    table["미분류"] = []
    for name in services:
        table.setdefault(rule.get(name, "미분류"), []).append(name)
    return table


def port_count(services: dict[str, Any], names: list[str]) -> int:
    return sum(len(services[n]["ports"]) for n in names)


def main() -> int:
    plan = load_plan()
    services = plan["services"]

    table = assign(services, LAYER_OF)
    empty = [layer for layer in LAYERS if not table[layer]]

    print(f"[1] 계층 배정 — 서비스 {len(services)}개를 계층 {len(LAYERS)}개에 배정")
    for layer in LAYERS:
        members = table[layer] or ["(없음)"]
        print(f"    {layer:<6} {', '.join(members)}")
    if table["미분류"]:
        print(f"    미분류  {', '.join(table['미분류'])}")

    print("\n[2] 계층당 서비스 수와 포트 수")
    print(f"    {'계층':<6} {'서비스':>4} {'포트':>4}  없으면 실패하는 것")
    for layer in LAYERS:
        n = len(table[layer])
        p = port_count(services, table[layer])
        print(f"    {layer:<6} {n:>4} {p:>4}  {FAILS_WITHOUT[layer]}")
    print(f"    {'합계':<6} {len(services):>4} {len(plan['host_ports']):>4}")
    print(f"    계층 {len(LAYERS)}개 대 서비스 {len(services)}개 — 1대 1이 아님")

    print(f"\n[3] 비어 있는 계층 {len(empty)}개")
    for layer in empty:
        print(f"    {layer:<6} 채우는 시점: {FILLED_AT.get(layer, '미정')}")

    # 판단이 갈리는 서비스를 다른 계층으로 옮기면 [2]의 수가 어떻게 바뀌는지.
    alt_rule = dict(LAYER_OF, **{"kafka-ui": "수집"})
    alt = assign(services, alt_rule)
    print("\n[4] 배정 규칙을 바꾸면 — kafka-ui를 모니터링이 아니라 수집으로 보면")
    for layer in ("수집", "모니터링"):
        print(f"    {layer:<6} {len(table[layer])}개 → {len(alt[layer])}개")
    print("    서비스 목록은 그대로이고 배정 규칙만 바뀌었는데 계층당 개수가 달라짐")

    result = {
        "source_plan": str(PLAN_PATH),
        "generated_from": plan["generated_at"],
        "rule": LAYER_OF,
        "layers": {
            layer: {
                "services": table[layer],
                "service_count": len(table[layer]),
                "port_count": port_count(services, table[layer]),
                "fails_without": FAILS_WITHOUT[layer],
            }
            for layer in LAYERS
        },
        "empty_layers": empty,
        "filled_at": {layer: FILLED_AT.get(layer, "미정") for layer in empty},
        "alt_rule_kafka_ui_as_ingest": {
            layer: len(alt[layer]) for layer in ("수집", "모니터링")
        },
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\noutput={OUTPUT_PATH} layers={len(LAYERS)} empty={len(empty)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
