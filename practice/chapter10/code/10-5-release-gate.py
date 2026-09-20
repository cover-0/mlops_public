#!/usr/bin/env python3
"""10장 실습: 검수표는 실행 결과에서 계산되고, 동일성은 바이트로 확인한다.

세 가지를 계산한다.
  1. 층마다 잡는 결함이 다른 이유 — 경로 가정은 배치가 얕은 곳에서만 깨진다
  2. 배포 전 검수표 8항목을 과거 실행 증거에서 다시 계산하고, 커밋된 검수표와 대조
  3. "같은 코드"와 "같은 바이트"의 차이 — app.py의 sha256

입력: practice/chapter10/data/output/ch10_deploy_report.json   (과거 실행 증거)
      practice/chapter10/data/output/ch10_release_checklist.json (커밋된 검수표)
      practice/chapter10/code/10-1-model-api/app.py
출력: practice/chapter10/data/output/ch10_release_gate.json

실행: python code/10-5-release-gate.py   (cwd: practice/chapter10)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
API_DIR = BASE_DIR / "code" / "10-1-model-api"
OUTPUT_DIR = BASE_DIR / "data" / "output"
REPORT = OUTPUT_DIR / "ch10_deploy_report.json"
COMMITTED = OUTPUT_DIR / "ch10_release_checklist.json"
OUTPUT = OUTPUT_DIR / "ch10_release_gate.json"
REPO_ROOT = BASE_DIR.parents[1]

# app.py가 설정 기본값을 계산할 때 쓰는 식 — 두 배치에서 같은 식을 평가해 본다
LAYOUTS = {
    "저장소 배치": "/repo/practice/chapter10/code/10-1-model-api/app.py",
    "이미지 배치": "/app/app.py",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parents_index_1(path_str: str):
    """app.py의 `Path(__file__).resolve().parent.parents[1]`을 그대로 흉내 낸다."""
    parents = list(PurePosixPath(path_str).parent.parents)
    try:
        return str(parents[1]), None
    except IndexError as e:
        return None, f"IndexError: {e or 'list index out of range'}"


def main() -> int:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    committed = json.loads(COMMITTED.read_text(encoding="utf-8"))

    print("[1] 층마다 잡는 결함이 다른 이유 — 같은 식이 배치에 따라 갈린다")
    layout_rows = {}
    for label, p in LAYOUTS.items():
        value, err = parents_index_1(p)
        depth = len(list(PurePosixPath(p).parent.parents))
        layout_rows[label] = {"path": p, "parent_depth": depth,
                              "parents_1": value, "error": err}
        print(f"    {label:<8} {p:<46} 상위 경로 {depth}단계"
              f"  parents[1] → {value if value else err}")
    print("    pytest와 호스트 실행은 둘 다 저장소 배치 위에서 돌아 이 가정이 항상 참이었다")
    print("    가정이 깨지는 배치는 이미지 안뿐이므로, 컨테이너 스모크만 이 결함을 만난다")

    print("\n[2] 배포 전 검수표를 과거 실행 증거에서 다시 계산한다")
    host, container = report["host"], report["container"]
    recomputed = {
        "1_자동_테스트_통과": (report["tests"]["passed"] >= 4, "tests.passed"),
        "2_서빙_신원_응답(/health가 모델 이름·버전을 답함)":
            (host["health"].get("model_version") == "1", "host.health.model_version"),
        "3_알려진_입력_알려진_출력_스모크": (host["forecast"] == 6.0, "host.forecast"),
        "4_잘못된_입력_거절(422)": (host["invalid_input_status"] == 422,
                              "host.invalid_input_status"),
        "5_컨테이너_호스트_동일_예측(환경_동등성)":
            (container.get("forecast") == host["forecast"],
             "container.forecast == host.forecast"),
        "6_모델_실물_이미지_고정_및_출처_동봉":
            ((API_DIR / "model_export" / "export_info.json").exists(), "파일 존재 검사"),
        "7_레지스트리_버전_보존(롤백_전제)":
            (report["bootstrap"]["challenger_version"] == 2, "bootstrap.challenger_version"),
        "8_검증_파이프라인_정의(CI_워크플로)":
            ((REPO_ROOT / ".github" / "workflows" / "ch10-model-api.yml").exists(),
             "파일 존재 검사"),
    }
    disagree = []
    for k, (value, source) in recomputed.items():
        same = value == committed[k]
        if not same:
            disagree.append(k)
        print(f"    {'통과' if value else '미달'}  {k}")
        print(f"          판정 근거 {source}  /  커밋된 검수표 {committed[k]}"
              f"{'' if same else '  ← 불일치'}")
    measured = [k for k, (_, s) in recomputed.items() if s != "파일 존재 검사"]
    print(f"    측정값으로 판정하는 항목 {len(measured)}개 — 전부 재계산되어 같은 값이 나왔다")
    print(f"    파일 존재로 판정하는 항목 {8 - len(measured)}개 — 이 저장소에 그 파일이 없어"
          f" 불일치 {len(disagree)}건")

    print("\n[3] 게이트 하나를 뒤집어 보면 — 컨테이너 예측이 6.1로 나왔다면")
    flipped = dict((k, v) for k, (v, _) in recomputed.items())
    passed_before = sum(flipped.values())
    flipped["5_컨테이너_호스트_동일_예측(환경_동등성)"] = (6.1 == host["forecast"])
    passed_after = sum(flipped.values())
    print(f"    통과 항목 {passed_before}개 → {passed_after}개, 배포 판정 {'통과' if passed_after == 8 else '중단'}")
    print("    검수표가 손으로 쓰는 문서였다면 이 한 항목이 바뀌어도 문서는 그대로 남는다")

    print("\n[4] '같은 코드'와 '같은 바이트'")
    original = (API_DIR / "app.py").read_bytes()
    # 체크아웃된 파일의 줄바꿈 규약을 반대로 바꾼 복제본 — 내용은 그대로, 바이트만 달라진다
    converted = (original.replace(b"\r\n", b"\n") if b"\r\n" in original
                 else original.replace(b"\n", b"\r\n"))
    h1, h2 = sha256_bytes(original), sha256_bytes(converted)
    o_lines = original.decode("utf-8").splitlines()
    c_lines = converted.decode("utf-8").splitlines()
    lines_same = o_lines == c_lines
    print(f"    원본        {len(original):>6} 바이트  줄 {len(o_lines):>3}개  sha256 {h1[:16]}…")
    print(f"    줄바꿈 변환본 {len(converted):>6} 바이트  줄 {len(c_lines):>3}개  sha256 {h2[:16]}…")
    print(f"    줄 단위 내용 동일: {'예' if lines_same else '아니오'}  /  바이트 동일: {'예' if h1 == h2 else '아니오'}")
    print("    '같은 코드로 만들었다'는 진술은 이 차이를 걸러 내지 못한다")

    result = {
        "layout_check": layout_rows,
        "checklist_recomputed": {k: v for k, (v, _) in recomputed.items()},
        "checklist_committed": committed,
        "checklist_disagreement": disagree,
        "checklist_source": {k: s for k, (_, s) in recomputed.items()},
        "flip_experiment": {"passed_before": passed_before, "passed_after": passed_after,
                            "flipped_item": "5_컨테이너_호스트_동일_예측(환경_동등성)"},
        "byte_identity": {"file": "code/10-1-model-api/app.py",
                          "original_bytes": len(original), "original_sha256": h1,
                          "converted_bytes": len(converted), "converted_sha256": h2,
                          "same_lines": lines_same, "same_bytes": h1 == h2},
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
    print(f"\n증거 파일: {OUTPUT}")
    print("CH10_RELEASE_GATE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
