#!/usr/bin/env python3
"""9장 9-4: 승격 게이트 규칙을 바꿔 가며 같은 후보를 판정한다.

무엇을 보이는가
---------------
- 같은 훈련 쌍 6개로 후보 셋을 훈련한다(전체 평균·선형회귀·지역별 평균).
- 절대 게이트만 / 상대 조건만 / 둘 다 — 세 규칙으로 같은 후보를 판정해 결과가 갈리는 것을 본다.
- 임계값을 업무 기준으로 조였을 때 어느 후보가 남는지 본다.
- champion 별칭을 옮기고 되돌리면 예측값이 어떻게 바뀌는지 본다(승격과 롤백).

9-1(MLflow 실습)이 등록한 버전은 v1·v2 둘이다. 이 스크립트는 같은 데이터에서
후보를 하나 더 만들어 규칙을 비교하며, 9-1의 산출물은 읽기만 하고 고치지 않는다.

의존성: 표준 라이브러리만. Docker·MLflow 없이 실행된다.
실행:   python code/9-4-gate-matrix.py
산출물: data/output/ch9_gate_matrix.json
"""

from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "data" / "output"
SOURCE_DIR = BASE_DIR.parent / "chapter7" / "data" / "input" / "ch6_daily"

REGION_NAME = {"11440": "마포구", "11620": "관악구", "11680": "강남구"}
GATE_DEFAULT = 1.05  # 9-1이 쓴 절대 게이트
GATE_BUSINESS = 0.80  # 업무 기준을 더 조인 경우


def load_pairs() -> list[tuple[str, int, int]]:
    days = sorted(p.name for p in SOURCE_DIR.iterdir() if p.is_dir())
    table: dict[str, dict[str, int]] = {}
    for day in days:
        summary = json.loads((SOURCE_DIR / day / "daily_summary.json").read_text(encoding="utf-8"))
        for row in summary["by_region"]:
            table.setdefault(row["lawd_cd"], {})[day] = int(row["count"])
    pairs = []
    for cd in sorted(table):
        ds = sorted(table[cd])
        for i in range(len(ds) - 1):
            pairs.append((cd, table[cd][ds[i]], table[cd][ds[i + 1]]))
    pairs.sort(key=lambda p: (p[0], p[1]))
    return pairs


def fingerprint(pairs) -> str:
    csv = "lawd_cd,x_prev_count,y_count\n" + "".join(f"{a},{b},{c}\n" for a, b, c in pairs)
    return hashlib.sha256(csv.encode("utf-8")).hexdigest()


def mae(residuals) -> float:
    return round(sum(residuals) / len(residuals), 4)


def fit_baseline_mean(pairs) -> dict:
    ys = [Fraction(c) for _, _, c in pairs]
    const = sum(ys) / len(ys)
    return {
        "name": "baseline_mean",
        "desc": "훈련 y 전체 평균 — 입력을 보지 않는다",
        "needs": "없음",
        "predict": lambda cd, x: float(const),
        "train_mae": mae([abs(float(y - const)) for y in ys]),
    }


def fit_linear(pairs) -> dict:
    xs = [Fraction(b) for _, b, _ in pairs]
    ys = [Fraction(c) for _, _, c in pairs]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    intercept = my - slope * mx
    return {
        "name": "linear",
        "desc": "전일 건수의 1차 함수",
        "needs": "전일 건수",
        "predict": lambda cd, x: float(slope * Fraction(x) + intercept),
        "train_mae": mae([abs(float(y - (slope * x + intercept))) for x, y in zip(xs, ys)]),
    }


def fit_district_mean(pairs) -> dict:
    """후보 3 — 지역별 y 평균. 입력으로 지역 코드를 요구한다."""
    by_cd: dict[str, list[Fraction]] = {}
    for cd, _, y in pairs:
        by_cd.setdefault(cd, []).append(Fraction(y))
    means = {cd: sum(v) / len(v) for cd, v in by_cd.items()}
    residuals = [abs(float(Fraction(y) - means[cd])) for cd, _, y in pairs]
    return {
        "name": "district_mean",
        "desc": "지역별 y 평균 — 지역마다 다른 값을 낸다",
        "needs": "지역 코드",
        "predict": lambda cd, x: float(means[cd]) if cd in means else None,
        "train_mae": mae(residuals),
        "means": {cd: float(v) for cd, v in means.items()},
    }


def judge(candidate_mae: float, champion_mae: float, gate: float | None, relative: bool) -> str:
    """규칙 하나로 후보 하나를 판정한다."""
    if gate is not None and candidate_mae > gate:
        return "반려(절대 게이트 미달)"
    if relative and champion_mae is not None and candidate_mae >= champion_mae:
        return "반려(개선 없음)"
    return "승격"


def main() -> int:
    pairs = load_pairs()
    fp = fingerprint(pairs)
    cands = [fit_baseline_mean(pairs), fit_linear(pairs), fit_district_mean(pairs)]
    by_name = {c["name"]: c for c in cands}

    print(f"[1] 후보 3개 — 같은 훈련 쌍 {len(pairs)}개, 지문 {fp[:16]}…")
    print("    후보              train_mae  입력으로 요구하는 것  설명")
    for c in cands:
        print(f"    {c['name']:<16} {c['train_mae']:>9.4f}  {c['needs']:<12}  {c['desc']}")

    # 현재 champion은 9-1이 등록한 v1(baseline_mean)이다.
    record_path = OUTPUT_DIR / "ch9_promotion_record.json"
    if record_path.exists():
        rec = json.loads(record_path.read_text(encoding="utf-8"))
        champ_v = rec["champion_version"]
        champ_mae = next(d["train_mae"] for d in rec["decisions"] if d["version"] == champ_v)
        print(f"\n[2] 현재 champion — v{champ_v}, train_mae {champ_mae:.4f}")
        print("    출처 practice/chapter9/data/output/ch9_promotion_record.json")
    else:
        champ_v, champ_mae = 1, by_name["baseline_mean"]["train_mae"]
        print(f"\n[2] 현재 champion — v{champ_v}, train_mae {champ_mae:.4f} (기록 파일 없음, 손계산값 사용)")

    rules = [
        ("A 절대만 (mae <= 1.05)", GATE_DEFAULT, False),
        ("B 상대만 (champion보다 개선)", None, True),
        ("C 둘 다", GATE_DEFAULT, True),
    ]
    challengers = ["linear", "district_mean"]
    print("\n[3] 같은 후보를 세 규칙으로 판정 — champion은 baseline_mean(1.0000)")
    print(f"    {'규칙':<30}{'linear(1.0455)':<24}district_mean(0.6667)")
    matrix = []
    for label, gate, rel in rules:
        verdicts = [judge(by_name[n]["train_mae"], champ_mae, gate, rel) for n in challengers]
        print(f"    {label:<30}{verdicts[0]:<24}{verdicts[1]}")
        matrix.append({"rule": label, **dict(zip(challengers, verdicts))})

    print("\n[4] 규칙 A(절대만)를 쓰면 무엇이 일어나는가")
    print(f"    linear 1.0455 <= {GATE_DEFAULT} 이므로 통과 → champion이 1.0000에서 1.0455로 교체됨")
    print("    운영 모델의 오차가 커졌는데도 규칙은 정상 작동했다고 기록된다")

    print(f"\n[5] 임계값을 업무 기준으로 조이면 — mae <= {GATE_BUSINESS}")
    for c in cands:
        ok = c["train_mae"] <= GATE_BUSINESS
        print(f"    {c['name']:<16} {c['train_mae']:>9.4f}  {'통과' if ok else '미달'}")
    swapped = judge(by_name["baseline_mean"]["train_mae"], by_name["linear"]["train_mae"], None, True)
    print(f"    등록 순서가 반대여서 linear가 먼저 champion이 되었다면, 상대 조건만으로는")
    print(f"    baseline_mean(1.0000 < 1.0455) 판정이 '{swapped}' — 둘 다 업무 기준 미달인데 교체가 일어난다")

    print("\n[6] 별칭 이동과 롤백 — 규칙 C로 district_mean을 v3로 등록한 뒤")
    x_serve, cd_serve = 9.0, "11680"
    p_v1 = by_name["baseline_mean"]["predict"](cd_serve, x_serve)
    p_v3 = by_name["district_mean"]["predict"](cd_serve, x_serve)
    print(f"    champion=v1  {REGION_NAME[cd_serve]} 전일 건수 {x_serve} → 예측 {p_v1:.2f}")
    print(f"    champion=v3  {REGION_NAME[cd_serve]} 전일 건수 {x_serve} → 예측 {p_v3:.2f}")
    print("    별칭 이력    v1 → v3 → (롤백) v1     소비자 코드는 한 줄도 바뀌지 않는다")
    print("    반려된 v2를 지우지 않았기 때문에 되돌아갈 수 있는 버전이 v1·v2 둘이다")

    print("\n[7] 지표가 좋아졌다고 끝나지 않는다 — district_mean의 조건")
    print(f"    훈련에 있는 지역  {', '.join(sorted(by_name['district_mean']['means']))}")
    print(f"    처음 보는 지역 11110을 넣으면  예측 {by_name['district_mean']['predict']('11110', x_serve)}")
    print("    지역별 표본은 2개뿐이라 지역이 늘면 이 방식은 그대로 쓸 수 없다")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "data_fingerprint_sha256": fp,
        "champion_at_start": {"version": champ_v, "train_mae": champ_mae},
        "candidates": [
            {"name": c["name"], "train_mae": c["train_mae"], "needs": c["needs"]} for c in cands
        ],
        "district_means": by_name["district_mean"]["means"],
        "gate_matrix": matrix,
        "business_gate": {
            "threshold": GATE_BUSINESS,
            "pass": [c["name"] for c in cands if c["train_mae"] <= GATE_BUSINESS],
            "fail": [c["name"] for c in cands if c["train_mae"] > GATE_BUSINESS],
        },
        "alias_move": {
            "serve_lawd_cd": cd_serve,
            "serve_prev_count": x_serve,
            "forecast_champion_v1": round(p_v1, 4),
            "forecast_champion_v3": round(p_v3, 4),
            "unseen_district_forecast": by_name["district_mean"]["predict"]("11110", x_serve),
        },
    }
    (OUTPUT_DIR / "ch9_gate_matrix.json").write_text(
        json.dumps(out, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    ok = len(cands) == 3 and by_name["district_mean"]["train_mae"] < champ_mae
    print(f"\n증거 파일: {OUTPUT_DIR / 'ch9_gate_matrix.json'}")
    print("CH9_4_" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
