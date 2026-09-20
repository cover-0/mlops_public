#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3-1-compose-plan.py
제3장 실습 3.1 — Docker Compose 기반 파이프라인 구성(계획/점검)

이 실습은 실제로 Docker를 실행하지 않고도,
docker-compose.yml을 읽어 서비스/포트/의존성과 기본 보안 체크 항목을 정리한다.

실행:
    cd practice/chapter3
    python3 code/3-1-compose-plan.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = PROJECT_ROOT / "docker-compose.yml"
OUTPUT_PATH = PROJECT_ROOT / "data" / "output" / "ch3_compose_plan.json"


def parse_ports(service: dict[str, Any]) -> list[str]:
    ports = service.get("ports")
    if not isinstance(ports, list):
        return []
    out: list[str] = []
    for p in ports:
        if isinstance(p, str):
            out.append(p)
    return out


def extract_host_ports(port_mappings: list[str]) -> list[int]:
    host_ports: list[int] = []
    for mapping in port_mappings:
        # "9092:9092" or "127.0.0.1:9092:9092"
        parts = mapping.split(":")
        if len(parts) >= 2:
            try:
                host_ports.append(int(parts[-2]))
            except Exception:
                continue
    return host_ports


def risk_checks(services: dict[str, Any]) -> dict[str, Any]:
    """
    최소 보안 체크(정적):
    - DB 패스워드가 기본값인지(placeholder)
    - 민감 포트 노출 여부(0.0.0.0 바인딩 추정)
    """
    checks: dict[str, Any] = {"warnings": [], "notes": []}

    for name, svc in services.items():
        env = svc.get("environment", {})
        if isinstance(env, dict):
            for k, v in env.items():
                if isinstance(v, str) and re.search(r"(password|passwd)", k, re.IGNORECASE):
                    if v in {"password", "postgres", "admin", "secure_password"}:
                        checks["warnings"].append(f"{name}: weak/default password in {k}")

        ports = parse_ports(svc)
        for p in ports:
            if p.startswith("0.0.0.0:"):
                checks["warnings"].append(f"{name}: port mapping binds 0.0.0.0 ({p})")

    if not checks["warnings"]:
        checks["notes"].append("No obvious weak defaults found in compose file.")

    return checks


def main() -> int:
    try:
        import yaml  # type: ignore
    except Exception as e:
        raise RuntimeError("PyYAML이 필요합니다. `pip install -r code/requirements.txt`를 실행하세요.") from e

    if not COMPOSE_PATH.exists():
        raise FileNotFoundError(f"compose file not found: {COMPOSE_PATH}")

    data = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    services = data.get("services", {}) if isinstance(data, dict) else {}
    if not isinstance(services, dict):
        services = {}

    service_summaries: dict[str, Any] = {}
    all_ports: list[int] = []
    dependencies: dict[str, list[str]] = {}

    for name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        ports = parse_ports(svc)
        deps = svc.get("depends_on", [])
        if isinstance(deps, list):
            dependencies[name] = [d for d in deps if isinstance(d, str)]
        else:
            dependencies[name] = []

        host_ports = extract_host_ports(ports)
        all_ports.extend(host_ports)

        service_summaries[name] = {
            "image": svc.get("image"),
            "ports": ports,
            "depends_on": dependencies[name],
        }

    plan = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "compose_path": str(COMPOSE_PATH),
        "services": service_summaries,
        "host_ports": sorted(set(all_ports)),
        "security_checks": risk_checks(services),
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report(plan, services)
    print(f"output={OUTPUT_PATH} services={len(service_summaries)}")
    return 0


def count_declared_dependencies(services: dict[str, Any]) -> tuple[int, list[str]]:
    """compose 원본에 적힌 depends_on 관계 수를 센다.

    이 스크립트의 파서는 리스트 형태(`depends_on: [a, b]`)만 읽는다.
    헬스체크 조건을 붙인 맵 형태(`depends_on: {a: {condition: ...}}`)는
    산출물에 들어가지 않으므로, 원본 개수를 따로 세어 차이를 드러낸다.
    """
    total = 0
    map_form: list[str] = []
    for name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        deps = svc.get("depends_on")
        if isinstance(deps, list):
            total += len([d for d in deps if isinstance(d, str)])
        elif isinstance(deps, dict):
            total += len(deps)
            map_form.append(name)
    return total, map_form


def report(plan: dict[str, Any], services: dict[str, Any]) -> None:
    """본문 인용용 구간별 출력. 계산은 하지 않고 plan의 값을 그대로 보여 준다."""
    summaries = plan["services"]
    host_ports = plan["host_ports"]
    warnings = plan["security_checks"]["warnings"]

    print("[1] compose 파일")
    print(f"    경로      : {plan['compose_path']}")
    print(f"    생성 시각 : {plan['generated_at']}")

    print(f"\n[2] 서비스 {len(summaries)}개")
    for name, info in summaries.items():
        ports = ", ".join(info["ports"]) if info["ports"] else "-"
        print(f"    {name:<12} {info['image']:<36} ports={ports}")

    print(f"\n[3] 호스트 포트 {len(host_ports)}개")
    print("    " + " ".join(str(p) for p in host_ports))
    multi = [n for n, i in summaries.items() if len(i["ports"]) > 1]
    for name in multi:
        print(f"    서비스 하나가 포트 둘을 엶: {name} → {', '.join(summaries[name]['ports'])}")

    extracted = [(n, d) for n, i in summaries.items() for d in i["depends_on"]]
    declared, map_form = count_declared_dependencies(services)
    print(f"\n[4] 의존성 — 추출 {len(extracted)}건 / 원본 {declared}건")
    for name, dep in extracted:
        print(f"    추출됨   : {name} → {dep}")
    for name in map_form:
        print(f"    누락됨   : {name} (depends_on이 맵 형태여서 이 파서가 읽지 않음)")

    print(f"\n[5] 보안 점검 — 경고 {len(warnings)}건")
    for w in warnings:
        print(f"    {w}")
    print()


if __name__ == "__main__":
    raise SystemExit(main())

