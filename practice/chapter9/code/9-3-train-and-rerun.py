#!/usr/bin/env python3
"""9장 9-3: 후보 두 개를 훈련하고, 같은 설정으로 다시 훈련한다.

무엇을 보이는가
---------------
- 훈련 쌍 6개로 후보 둘(전체 평균 예측기, 최소제곱 선형회귀)을 손으로 계산한다.
- 계산한 MAE·계수를 9-1(MLflow 실습)이 남긴 산출물의 값과 대조한다.
- 같은 입력으로 다시 훈련해 결과가 같은지 확인한다(재현성).
- 입력이 한 건 바뀌면 지문과 메트릭이 함께 바뀌는 것을 보인다(원인 분리).

두 후보 모두 난수를 쓰지 않는 결정적 알고리즘이라 seed가 필요 없다.

의존성: 표준 라이브러리만. Docker·MLflow 없이 실행된다.
실행:   python code/9-3-train-and-rerun.py
산출물: data/output/ch9_training_runs.json
"""

from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "data" / "output"
SOURCE_DIR = BASE_DIR.parent / "chapter7" / "data" / "input" / "ch6_daily"


def load_pairs() -> list[tuple[str, int, int]]:
    """9-2와 같은 규칙으로 훈련 쌍을 만든다."""
    days = sorted(p.name for p in SOURCE_DIR.iterdir() if p.is_dir())
    table: dict[str, dict[str, int]] = {}
    for day in days:
        summary = json.loads((SOURCE_DIR / day / "daily_summary.json").read_text(encoding="utf-8"))
        for row in summary["by_region"]:
            table.setdefault(row["lawd_cd"], {})[day] = int(row["count"])
    return pairs_from_table(table)


def pairs_from_table(table: dict[str, dict[str, int]]) -> list[tuple[str, int, int]]:
    pairs = []
    for cd in sorted(table):
        days = sorted(table[cd])
        for i in range(len(days) - 1):
            pairs.append((cd, table[cd][days[i]], table[cd][days[i + 1]]))
    pairs.sort(key=lambda p: (p[0], p[1]))
    return pairs


def fingerprint(pairs: list[tuple[str, int, int]]) -> str:
    csv = "lawd_cd,x_prev_count,y_count\n" + "".join(f"{a},{b},{c}\n" for a, b, c in pairs)
    return hashlib.sha256(csv.encode("utf-8")).hexdigest()


def train_baseline_mean(pairs) -> dict:
    """후보 1 — 입력과 무관하게 훈련 y의 평균을 내놓는다."""
    ys = [float(c) for _, _, c in pairs]
    const = sum(ys) / len(ys)
    residuals = [abs(y - const) for y in ys]
    return {
        "candidate": "baseline_mean",
        "params": {"model_type": "평균 예측기", "n_samples": len(pairs)},
        "const": round(const, 4),
        "residuals": [round(r, 4) for r in residuals],
        "train_mae": round(sum(residuals) / len(residuals), 4),
    }


def train_linear(pairs) -> dict:
    """후보 2 — 전일 건수의 1차 함수. 최소제곱 해를 직접 계산한다."""
    # 부동소수점 오차 없이 정확한 유리수로 푼다 — 분수 형태로 검산할 수 있다.
    xs = [Fraction(b) for _, b, _ in pairs]
    ys = [Fraction(c) for _, _, c in pairs]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sxy / sxx
    intercept = my - slope * mx
    residuals = [abs(float(y - (slope * x + intercept))) for x, y in zip(xs, ys)]
    return {
        "candidate": "linear",
        "params": {"model_type": "최소제곱 선형회귀", "n_samples": n},
        "slope": round(float(slope), 4),
        "intercept": round(float(intercept), 4),
        "slope_fraction": f"{slope.numerator}/{slope.denominator}",
        "intercept_fraction": f"{intercept.numerator}/{intercept.denominator}",
        "residuals": [round(r, 4) for r in residuals],
        "train_mae": round(sum(residuals) / len(residuals), 4),
    }


def main() -> int:
    pairs = load_pairs()
    fp = fingerprint(pairs)
    base = train_baseline_mean(pairs)
    lin = train_linear(pairs)

    print(f"[1] 훈련 데이터 — 쌍 {len(pairs)}개, 지문 {fp[:16]}…")
    print(f"    x(전일 건수) {[b for _, b, _ in pairs]}")
    print(f"    y(당일 건수) {[c for _, _, c in pairs]}")

    print("\n[2] 후보 1 baseline_mean — 입력과 무관하게 y 평균을 내놓는다")
    print(f"    예측값       {base['const']}  (= y 합 {int(sum(c for _, _, c in pairs))} ÷ {len(pairs)})")
    print(f"    잔차 절댓값  {base['residuals']}")
    print(f"    train_mae    {base['train_mae']:.4f}")

    print("\n[3] 후보 2 linear — 전일 건수의 1차 함수")
    print(f"    slope        {lin['slope']}  (= {lin['slope_fraction']})")
    print(f"    intercept    {lin['intercept']}  (= {lin['intercept_fraction']})")
    print(f"    잔차 절댓값  {lin['residuals']}")
    print(f"    train_mae    {lin['train_mae']:.4f}")
    print(f"    → 복잡한 쪽이 기준선보다 나쁘다: {lin['train_mae']:.4f} > {base['train_mae']:.4f}")

    # 9-1(MLflow·scikit-learn)이 남긴 값과 대조한다.
    report_path = OUTPUT_DIR / "ch9_experiment_report.json"
    print("\n[4] 9-1(scikit-learn)이 남긴 값과 대조")
    if report_path.exists():
        rec = json.loads(report_path.read_text(encoding="utf-8"))["runs"]
        rows = [
            ("baseline_mean train_mae", base["train_mae"], rec["baseline_mean"]["train_mae"]),
            ("linear train_mae", lin["train_mae"], rec["linear"]["train_mae"]),
            ("linear slope", lin["slope"], rec["linear"]["coef"]["slope"]),
            ("linear intercept", lin["intercept"], rec["linear"]["coef"]["intercept"]),
        ]
        for name, mine, theirs in rows:
            print(f"    {name:<26} 손계산 {mine:<8} 기록 {theirs:<8} 일치 {'예' if mine == theirs else '아니오'}")
    else:
        rows = []
        print("    ch9_experiment_report.json 없음 — 대조 생략")

    print("\n[5] 같은 입력으로 다시 훈련(재현성)")
    lin2 = train_linear(pairs)
    mae_equal = lin["train_mae"] == lin2["train_mae"]
    coef_equal = (lin["slope"], lin["intercept"]) == (lin2["slope"], lin2["intercept"])
    print(f"    지문         {fp[:16]}… → {fingerprint(pairs)[:16]}…")
    print(f"    train_mae    {lin['train_mae']:.4f} → {lin2['train_mae']:.4f}   동일 {mae_equal}")
    print(f"    계수         ({lin['slope']}, {lin['intercept']}) → ({lin2['slope']}, {lin2['intercept']})   동일 {coef_equal}")

    # 입력이 몰래 바뀐 상황 — 지문이 원인을 갈라 준다.
    days = sorted(p.name for p in SOURCE_DIR.iterdir() if p.is_dir())
    table: dict[str, dict[str, int]] = {}
    for day in days:
        summary = json.loads((SOURCE_DIR / day / "daily_summary.json").read_text(encoding="utf-8"))
        for row in summary["by_region"]:
            table.setdefault(row["lawd_cd"], {})[day] = int(row["count"])
    table["11440"][days[-1]] += 1
    pairs_alt = pairs_from_table(table)
    fp_alt = fingerprint(pairs_alt)
    base_alt = train_baseline_mean(pairs_alt)
    lin_alt = train_linear(pairs_alt)

    print("\n[6] 입력이 한 건 바뀐 채로 같은 코드를 돌리면 — 마포구 마지막 날 건수 +1")
    print(f"    지문         {fp[:16]}… → {fp_alt[:16]}…   같음 {fp == fp_alt}")
    print(f"    baseline_mean train_mae  {base['train_mae']:.4f} → {base_alt['train_mae']:.4f}")
    print(f"    linear train_mae         {lin['train_mae']:.4f} → {lin_alt['train_mae']:.4f}")
    print(f"    linear slope             {lin['slope']} → {lin_alt['slope']}")
    print("    지문이 다르면 데이터를 의심하고, 지문이 같은데 결과가 다르면 코드·환경·난수를 의심한다")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "data_fingerprint_sha256": fp,
        "runs": {"baseline_mean": base, "linear": lin, "linear_rerun": lin2},
        "reproducibility": {"mae_equal": mae_equal, "coef_equal": coef_equal},
        "cross_check_with_sklearn": [
            {"field": n, "hand_computed": m, "recorded": t, "equal": m == t} for n, m, t in rows
        ],
        "input_changed_one_cell": {
            "data_fingerprint_sha256": fp_alt,
            "baseline_mean_train_mae": base_alt["train_mae"],
            "linear_train_mae": lin_alt["train_mae"],
            "linear_slope": lin_alt["slope"],
        },
    }
    (OUTPUT_DIR / "ch9_training_runs.json").write_text(
        json.dumps(out, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    ok = mae_equal and coef_equal and all(r[1] == r[2] for r in rows) if rows else mae_equal and coef_equal
    print(f"\n증거 파일: {OUTPUT_DIR / 'ch9_training_runs.json'}")
    print("CH9_3_" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
