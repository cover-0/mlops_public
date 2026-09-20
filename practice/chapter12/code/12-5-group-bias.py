#!/usr/bin/env python3
"""12주차 강의 실행 블록 3 — 그룹별 편향과 설명.

`12-2-fairness-xai.py`의 구현(모델 재구성·그룹 공정성·permutation importance·
이의제기 절차·공공 AI 검토표)을 그대로 불러와 같은 입력(9주차 실험 산출물
스냅숏)으로 다시 계산하고, 강의 본문이 인용하는 값을 출력한다.

  - 파일을 쓰지 않는다(기존 증거 JSON을 건드리지 않음).
  - 모델 적합에 난수를 쓰지 않고 permutation importance는 seed를 고정한다.
  - scikit-learn·pandas·numpy가 필요하다(code/requirements.txt).

실행: python scripts/run_and_capture.py 12 --file 12-5-group-bias.py
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
INPUT_DIR = CODE_DIR.parent / "data" / "input"


def load_fairness_module():
    path = CODE_DIR / "12-2-fairness-xai.py"
    spec = importlib.util.spec_from_file_location("ch12_fairness", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def print_groups(title: str, fair: dict) -> None:
    print(f"    {title}")
    print("    지역     n  실측평균  예측평균   MAE     편향(예측-실측)")
    for g in fair["groups"]:
        print(f"    {g['region']:<7} {g['n']}  {g['actual_mean']:>7}  {g['pred_mean']:>7}  "
              f"{g['mae']:>6}  {g['bias']:+}")
    print(f"    전체 MAE {fair['overall_mae']}  /  그룹 MAE 격차 {fair['mae_gap']}  "
          f"/  비율 {fair['mae_ratio']}배")
    print(f"    가장 나쁜 그룹 {fair['worst_group']}  /  가장 좋은 그룹 {fair['best_group']}")


def main() -> int:
    fx = load_fairness_module()
    df, fp_recorded = fx.load_pairs(INPUT_DIR)
    fp = fx.data_fingerprint(df)

    print("[1] 입력 — 9주차가 남긴 훈련 쌍을 그대로 다시 읽는다")
    print("    원천 data/input/ch9_experiment_report.json")
    print("    지역     전일 건수  당일 건수")
    for row in df.itertuples(index=False):
        print(f"    {fx.REGION_NAME[row.lawd_cd]:<7} {row.x_prev_count:>9} {row.y_count:>10}")
    print(f"    훈련 쌍 {len(df)}개 (3지역 × 2쌍)")
    print(f"    지문 재계산 {fp[:16]} / 9주차 기록 {fp_recorded[:16]} "
          f"— 일치 {fp == fp_recorded}")

    champion, challenger, X, y, coef = fx.fit_models(df)
    fair_champ = fx.group_fairness(df, champion, X)
    fair_chall = fx.group_fairness(df, challenger, X)

    print()
    print("[2] 배포 모델(champion)의 전체 성능과 그룹별 성능")
    print(f"    이 모델은 입력과 무관하게 항상 {fx._round(float(champion.predict(X[:1])[0]))}을 예측한다")
    print_groups("champion = 상수 예측", fair_champ)

    print()
    print("[3] 후보 모델(challenger, 선형)로 바꾸면")
    print(f"    회귀식 예측 = {coef['intercept']} + {coef['slope']} × 전일 건수")
    print_groups("challenger = 선형", fair_chall)
    print(f"    전체 MAE는 {fair_champ['overall_mae']} → {fair_chall['overall_mae']} 로 나빠지고,")
    print(f"    그룹 격차는 {fair_champ['mae_gap']} → {fair_chall['mae_gap']} 로 함께 나빠진다")

    expl = fx.explain(champion, challenger, X, y, coef)
    print()
    print("[4] 왜 그런가 — 예측이 피처를 쓰고 있는지 본다")
    print(f"    검사 피처 {expl['feature']}")
    for key in ("champion", "challenger"):
        e = expl[key]
        print(f"    {key:<11} {e['type']}")
        print(f"        permutation importance {e['permutation_importance']}")
        if e["coefficient"]:
            print(f"        계수 slope {e['coefficient']['slope']} / "
                  f"intercept {e['coefficient']['intercept']}")
    print("    상수 모델의 중요도가 정확히 0 — 값을 섞어도 오차가 그대로다(피처를 안 본다)")

    appeal = fx.build_appeal_workflow()
    card = fx.build_model_card(df, fp, fair_champ, expl, {})
    rubric = fx.build_policy_rubric()
    pia = fx.build_pia_checkpoints()
    honest = "소표본" in card["sections"][8]["items"][0]
    check = fx.build_public_ai_checklist(fp == fp_recorded, fair_champ, expl, card,
                                         rubric, pia, appeal, honest)

    print()
    print(f"[5] 이의제기에 답하려면 갖춰야 하는 통로 {len(appeal['steps'])}개")
    for i, step in enumerate(appeal["steps"], 1):
        print(f"    {i}. {step}")

    print()
    print(f"[6] 공공 AI 검토표 — 위 산출에서 자동 판정 ({check['passed']}/{check['total']})")
    for item in check["items"]:
        mark = "PASS" if item["passed"] else "FAIL"
        print(f"    {item['no']:>2}. [{mark}] {item['item']}")
    print(f"    모델 카드 {card['section_count']}절 / 정책 루브릭 {rubric['criteria_count']}기준이 "
          f"같은 실행에서 생성된다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
