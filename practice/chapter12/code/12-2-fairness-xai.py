#!/usr/bin/env python3
"""실습 16.1: 그룹별 성능 비교와 설명 결과 생성.

9장 산출물 스냅숏(complaint_daily_forecaster의 훈련 쌍 6개)을 입력으로, 실제
배포 모델(champion=상수 평균)과 후보(challenger=선형)를 재구성해 공공 AI 윤리의
두 축을 실측으로 만든다 — 편향성 평가(16.2)와 설명가능성·모델 카드(16.3) — 그리고
정책 AI 평가 루브릭(16.4)·개인정보 영향평가(16.5)·자동화된 결정 이의제기(16.6)를
문서로 생성한다.

  16.2 편향성 평가 : 지역 그룹(강남·마포·관악)별 MAE·편향·캘리브레이션(회귀 공정성)
  16.3 설명가능성  : 계수 + permutation importance(상수 모델 0 vs 선형 모델 >0)
  16.3 모델 카드   : Mitchell et al.(2019) 9절을 9장 증거에서 자동 생성
  16.4 정책 루브릭 : 법적 정합성·정치적 중립성·사회적 유해성 × 4점 척도
  16.5·16.6       : 개인정보 영향평가(제33조)·자동화된 결정 이의제기(제37조의2) 검토 지점
  공공 AI 검토 체크리스트 : 위 산출에서 자동 판정(사람 주장이 아니라 기록이 근거)

원칙
  - 그룹 결과는 실제 예측에서 산출한다(더미 금지). 지역구는 법적 보호속성이 아니라
    운영 그룹축으로 쓰며, 편향 평가의 방법은 보호속성 종류와 무관하게 동일하다.
  - 훈련 쌍 지문을 재계산해 9장 동일성(96f6b6b3…)을 교차 확인한다.
  - 증거 JSON은 sort_keys·seed 고정·now() 금지 → 재실행 바이트 동일.

실행: cd practice/chapter12 && venv/bin/python run_chapter12.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

# 법정동 시군구 코드 → 이름(7.2 행정표준코드) — 그룹 표시용
REGION_NAME = {"11440": "마포구", "11620": "관악구", "11680": "강남구"}
# 그룹 표시 순서(고민원 강남 → 마포 → 관악): 결정적 출력용
REGION_ORDER = ["11680", "11440", "11620"]

MODEL_NAME = "complaint_daily_forecaster"
FINGERPRINT_PREFIX = "96f6b6b3"  # 9·13주차과 교차 확인하는 훈련 데이터 지문


def _round(x: float, n: int = 4) -> float:
    """음수 0(-0.0)을 0.0으로 정규화한 반올림 — 증거 JSON 바이트 안정."""
    r = round(float(x), n)
    return 0.0 if r == 0.0 else r


# ── 입력: 9장 훈련 쌍 스냅숏 ─────────────────────────────────────
def load_pairs(input_dir: Path) -> tuple[pd.DataFrame, str]:
    report = json.loads((input_dir / "ch9_experiment_report.json").read_text("utf-8"))
    df = pd.DataFrame(report["training_pairs"])
    df = df.sort_values(["lawd_cd", "x_prev_count"]).reset_index(drop=True)
    return df, report["data_fingerprint_sha256"]


def data_fingerprint(df: pd.DataFrame) -> str:
    """9장과 같은 방법(정렬된 훈련 쌍 CSV의 sha256)으로 지문을 재계산한다."""
    # lineterminator를 고정한다. pandas 기본값은 실행 OS의 줄바꿈을 따르므로
    # 고정하지 않으면 같은 데이터가 Windows에서 다른 지문을 낸다(9장 교차 확인 실패).
    canon = df[["lawd_cd", "x_prev_count", "y_count"]].to_csv(
        index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(canon).hexdigest()


# ── 모델 재구성: champion(상수 평균) + challenger(선형) ──────────
def fit_models(df: pd.DataFrame):
    from sklearn.dummy import DummyRegressor
    from sklearn.linear_model import LinearRegression

    X = df[["x_prev_count"]].to_numpy(dtype=float)
    y = df["y_count"].to_numpy(dtype=float)
    champion = DummyRegressor(strategy="mean").fit(X, y)   # 9장 v1 = 배포 모델
    challenger = LinearRegression().fit(X, y)              # 9장 v2 = 반려 후보
    coef = {"slope": _round(challenger.coef_[0]),
            "intercept": _round(challenger.intercept_)}
    return champion, challenger, X, y, coef


# ── 16.2 편향성 평가: 그룹별 회귀 공정성 ─────────────────────────
def group_fairness(df: pd.DataFrame, model, X: np.ndarray) -> dict:
    """그룹(지역)별 MAE·편향(평균 부호오차)·캘리브레이션을 실제 예측에서 산출한다."""
    pred_all = model.predict(X)
    groups = []
    for cd in REGION_ORDER:
        mask = (df["lawd_cd"] == cd).to_numpy()
        actual = df["y_count"].to_numpy(dtype=float)[mask]
        pred = pred_all[mask]
        err = pred - actual                       # 부호오차: 음수=과소예측
        groups.append({
            "lawd_cd": cd, "region": REGION_NAME[cd], "n": int(mask.sum()),
            "actual_mean": _round(actual.mean()), "pred_mean": _round(pred.mean()),
            "mae": _round(np.abs(err).mean()),
            "bias": _round(err.mean()),           # E[pred-actual|g] (캘리브레이션/방향)
        })
    maes = [g["mae"] for g in groups]
    overall_mae = _round(np.abs(pred_all - df["y_count"].to_numpy(dtype=float)).mean())
    worst = max(groups, key=lambda g: g["mae"])
    best = min(groups, key=lambda g: g["mae"])
    return {
        "groups": groups,
        "overall_mae": overall_mae,
        "mae_gap": _round(max(maes) - min(maes)),
        "mae_ratio": _round(max(maes) / min(maes)) if min(maes) > 0 else None,
        "worst_group": worst["region"], "best_group": best["region"],
    }


# ── 16.3 설명가능성: 계수 + permutation importance ───────────────
def explain(champion, challenger, X: np.ndarray, y: np.ndarray, coef: dict) -> dict:
    """상수 모델(피처 무시 → 0)과 선형 모델(계수·permutation importance)을 비교한다."""
    from sklearn.inspection import permutation_importance

    def perm(model) -> float:
        r = permutation_importance(model, X, y, scoring="neg_mean_absolute_error",
                                   n_repeats=10, random_state=0)
        return _round(r.importances_mean[0])

    return {
        "feature": "x_prev_count(전일 민원 건수)",
        "champion": {
            "type": "DummyRegressor(mean) — 상수 예측",
            "coefficient": None,
            "permutation_importance": perm(champion),  # 상수 → 정확히 0
            "explanation": "예측이 입력에 의존하지 않는다(피처를 쓰지 않음). "
                           "지역·전일 건수 차이를 반영하지 못하는 것이 그룹 편향의 근본 원인.",
        },
        "challenger": {
            "type": "LinearRegression — 선형",
            "coefficient": coef,   # slope 자명 해석: 전일 1건당 익일 예측 증가분
            "permutation_importance": perm(challenger),
            "explanation": f"전일 건수 1건 증가 시 익일 예측이 계수(slope={coef['slope']})만큼 "
                           "증가한다 — 계수가 곧 설명. 다만 이 극소 표본에서 permutation "
                           "importance가 0 이하로, 전일 건수의 예측 기여가 약하다(9장에서 선형 "
                           "모델이 baseline보다 MAE가 높아 반려된 것과 일관).",
        },
    }


# ── 16.3 모델 카드(Mitchell et al. 2019 — 9절) ──────────────────
def build_model_card(df: pd.DataFrame, fp: str, fair: dict, expl: dict,
                     runs: dict) -> dict:
    worst = fair["worst_group"]
    sections = [
        ("1. 모델 상세(Model Details)",
         [f"모델명: {MODEL_NAME}",
          "배포 모델(champion): v1 baseline_mean — 상수 예측(전 입력 6.0)",
          "후보(challenger): v2 linear — 승격 반려(9장, 개선 없음)",
          f"훈련 데이터 지문(sha256 앞 16자리): {fp[:16]}",
          "소유자: 민원데이터팀(가상·시뮬레이션 표기), 레지스트리: 9장 MLflow"]),
        ("2. 의도된 용도(Intended Use)",
         ["용도: 지역구별 익일 민원 건수 예측(교육용 운영 실습)",
          "범위 밖(out-of-scope): 개인 대상 결정, 자원 최종 배분의 완전 자동화, "
          "행정 처분의 근거로 단독 사용"]),
        ("3. 요인(Factors)",
         ["평가 그룹축: 지역구(강남·마포·관악) — 법적 보호속성이 아니라 운영 그룹축",
          "지역 형평(균형발전)은 실재하는 공공 공정성 관심사"]),
        ("4. 지표(Metrics)",
         ["그룹별 MAE·편향(평균 부호오차)·그룹 캘리브레이션(예측평균 vs 실측평균)",
          f"전체 MAE: {fair['overall_mae']} (9장 baseline 훈련 MAE와 일치)"]),
        ("5. 평가 데이터(Evaluation Data)",
         [f"훈련 쌍 {len(df)}개(3지역 × 2쌍), 원천: 6주차 확정 집계 3일(7/1~7/3)",
          "극소 표본 — 성능의 주장이 아니라 편향 평가의 구조 시연"]),
        ("6. 훈련 데이터(Training Data)",
         [f"평가 데이터와 동일한 {len(df)}쌍(교육용), 지문으로 동일성 증명 가능",
          "7주차 피처 스냅숏 → 9장 (전일→당일) 쌍"]),
        ("7. 정량 분석(Quantitative Analyses)",
         [f"{g['region']}: MAE {g['mae']}, 편향 {g['bias']:+}, "
          f"실측평균 {g['actual_mean']} vs 예측평균 {g['pred_mean']}"
          for g in fair["groups"]] +
         [f"그룹 MAE 격차 {fair['mae_gap']}, 비율 {fair['mae_ratio']}"]),
        ("8. 윤리적 고려(Ethical Considerations)",
         [f"체계적 편향: champion이 {worst} 그룹을 과소예측(편향 음수) — 이 예측을 자원배분에 "
          "쓰면 고민원 지역이 과소 배분될 위험",
          "설명(16.3): 상수 모델이 피처를 무시(permutation importance 0)하는 것이 편향의 근본 원인",
          "자동화된 결정 금지 — 인적 개입과 이의제기 절차 필요(제37조의2)"]),
        ("9. 주의와 권고(Caveats and Recommendations)",
         [f"소표본(n={len(df)})으로 통계적 유의성을 주장하지 않는다 — 방법·구조의 시연",
          "권고: 지역 특성을 반영하는 피처·모델로 그룹 형평 개선, 배포 전 그룹별 성능 게이트",
          "권고: 배포 후 그룹별 성능을 11장 감시에 포함(드리프트와 편향은 다른 층)"]),
    ]
    return {
        "title": f"모델 카드 — {MODEL_NAME}",
        "reference": "Mitchell et al. (2019) Model Cards for Model Reporting",
        "sections": [{"heading": h, "items": items} for h, items in sections],
        "section_count": len(sections),
        "runs": runs,
    }


def model_card_md(card: dict) -> str:
    lines = [f"# {card['title']}", "",
             f"> 자동 생성 — {card['reference']}. 근거: 9장 실험 증거·12주차 그룹 편향 실측.", ""]
    for s in card["sections"]:
        lines.append(f"## {s['heading']}")
        lines.extend(f"- {it}" for it in s["items"])
        lines.append("")
    return "\n".join(lines)


# ── 16.4 정책 AI 평가 루브릭(법적 정합성·중립성·유해성) ──────────
def build_policy_rubric() -> dict:
    scale = "0=부적합 / 1=미흡 / 2=충족 / 3=우수"
    criteria = [
        {"criterion": "법적 정합성(legal alignment)",
         "question": "근거 법령과 목적 제한·영향평가·이의제기 요건을 충족하는가",
         "items": ["근거 법령 명시(개인정보 보호법 제18·23·33·37조의2, AI 기본법)",
                   "목적 제한 준수(등록 목적 밖 이용 차단)",
                   "개인정보 영향평가 대상 여부 판정·수행",
                   "자동화된 결정 시 거부·설명·이의제기 절차 구비"]},
        {"criterion": "정치적 중립성(neutrality)",
         "question": "특정 집단·지역을 체계적으로 불리하게 만들지 않는가",
         "items": ["그룹(지역·집단)별 성능 형평 평가·문서화",
                   "특정 집단의 체계적 불이익(편향 방향) 부재 확인",
                   "평가 그룹축과 보호속성의 정의 근거 명시"]},
        {"criterion": "사회적 유해성(harm)",
         "question": "오류의 방향·규모와 결정의 중대성에 비례한 통제가 있는가",
         "items": ["오류의 방향(과소·과대)과 피해 대상 식별",
                   "결정의 중대성(생명·권리·의무 영향) 평가",
                   "중대한 결정에 인적 개입·이의제기 장치 존재"]},
    ]
    return {"title": "정책 AI 평가 루브릭 초안", "scale": scale,
            "criteria": criteria, "criteria_count": len(criteria),
            "note": "채점 주체는 사람·독립 검증 — LLM-as-a-judge는 보조이며 단독 승인 근거로 쓰지 않는다(14주차)."}


def policy_rubric_md(rub: dict) -> str:
    lines = [f"# {rub['title']}", "", f"> 척도: {rub['scale']}", "",
             f"> {rub['note']}", ""]
    for c in rub["criteria"]:
        lines.append(f"## {c['criterion']}")
        lines.append(f"- 핵심 질문: {c['question']}")
        lines.extend(f"- [ ] {it}" for it in c["items"])
        lines.append("")
    return "\n".join(lines)


# ── 16.5 개인정보 영향평가(제33조) 검토 지점 ─────────────────────
def build_pia_checkpoints() -> dict:
    return {
        "legal_basis": "개인정보 보호법 제33조(개인정보 영향평가) — 공공기관 의무",
        "threshold": "대통령령 기준: 민감정보·고유식별정보 5만명 이상, 연계 50만명 이상, 100만명 이상",
        "checkpoints": [
            "이 시스템이 개인정보파일을 운용하는가(피처가 개인 식별 가능한가)",
            "영향평가 대상 규모(5만/50만/100만) 기준에 해당하는가",
            "수집·이용 목적과 보유 기간이 명시되고 목적 제한을 지키는가(제18조)",
            "민감정보 처리 시 별도 근거·안전조치가 있는가(제23조)",
            "위험요인 분석과 개선사항 도출이 문서화되었는가",
            "영향평가 결과를 개인정보파일 등록 시 첨부하는가",
        ],
        "note": "실습 피처는 지역 단위 집계(개인정보 없음)라 영향평가 비대상이나, "
                "가구·개인 단위 피처로 확장되는 순간 제33조 판정이 선행되어야 한다.",
    }


# ── 16.6 자동화된 결정 이의제기(제37조의2) 절차 ──────────────────
def build_appeal_workflow() -> dict:
    return {
        "legal_basis": "개인정보 보호법 제37조의2(자동화된 결정에 대한 정보주체의 권리 등) — 2024.3.15 시행",
        "material_effect": "중대한 영향 판단: 생명·신체 안전, 권리 박탈, 의무 부담, 제한의 지속성·회복가능성",
        "steps": [
            "고지: 완전 자동화된 결정의 기준·절차·처리 방식을 정보주체가 확인하도록 공개",
            "거부권: 권리·의무에 중대한 영향을 주는 결정을 거부할 수 있게 한다",
            "설명요구권: 결정에 대해 설명 등을 요구할 수 있게 한다",
            "인적 개입: 거부·설명 요구 시 정당한 사유가 없으면 인적 재처리·설명 등 조치",
            "기록: 요구·조치를 로그로 남겨 감사에 답한다(12주차 접근 로그 평행)",
        ],
        "cross_ref": "EU: GDPR 제22조·AI Act 고위험 시스템의 human oversight와 정합.",
    }


# ── 공공 AI 검토 체크리스트(자동 생성) ───────────────────────────
def build_public_ai_checklist(fp_ok: bool, fair: dict, expl: dict, card: dict,
                              rubric: dict, pia: dict, appeal: dict,
                              honest_small_sample: bool) -> dict:
    champ_imp = expl["champion"]["permutation_importance"]
    biases_signed = [g["bias"] for g in fair["groups"]]
    items = [
        ("편향 평가가 그룹별로 산출되었는가", len(fair["groups"]) >= 2),
        ("그룹 MAE 격차·비율이 보고되었는가", fair["mae_gap"] is not None and fair["mae_ratio"] is not None),
        ("편향의 방향(부호)이 식별되었는가", any(b < 0 for b in biases_signed) and any(b > 0 for b in biases_signed)),
        ("설명 결과(permutation importance)가 산출되었는가",
         expl["champion"]["permutation_importance"] is not None
         and expl["challenger"]["permutation_importance"] is not None),
        ("배포 모델의 피처 의존성이 설명되었는가(상수=피처 무시 식별)", champ_imp == 0.0),
        ("모델 카드 9절이 전부 채워졌는가", card["section_count"] == 9
         and all(s["items"] for s in card["sections"])),
        ("모델 카드에 윤리적 고려·한계가 명시되었는가",
         any("윤리" in s["heading"] for s in card["sections"])
         and any("주의" in s["heading"] for s in card["sections"])),
        ("정책 루브릭 3기준(법적 정합성·중립성·유해성)이 정의되었는가", rubric["criteria_count"] == 3),
        ("개인정보 영향평가 검토 지점(제33조)이 있는가", len(pia["checkpoints"]) > 0),
        ("자동화된 결정 이의제기 절차(제37조의2)가 있는가", len(appeal["steps"]) > 0),
        ("소표본 한계가 정직하게 표기되었는가", honest_small_sample),
        ("데이터 지문으로 훈련 데이터가 증명 가능한가(9장 교차)", fp_ok),
    ]
    checklist = [{"no": i + 1, "item": it, "passed": bool(ok)}
                 for i, (it, ok) in enumerate(items)]
    passed = sum(1 for c in checklist if c["passed"])
    return {"total": len(checklist), "passed": passed,
            "all_passed": passed == len(checklist), "items": checklist}


# ── 통합 ────────────────────────────────────────────────────────
def build(input_dir: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    df, fp_recorded = load_pairs(input_dir)
    fp = data_fingerprint(df)
    fp_ok = fp == fp_recorded and fp.startswith(FINGERPRINT_PREFIX)

    champion, challenger, X, y, coef = fit_models(df)
    from sklearn.metrics import mean_absolute_error
    runs = {
        "champion_baseline_mean": {"train_mae": _round(mean_absolute_error(y, champion.predict(X))),
                                   "constant_prediction": _round(float(champion.predict(X[:1])[0]))},
        "challenger_linear": {"train_mae": _round(mean_absolute_error(y, challenger.predict(X))),
                              "coef": coef},
    }

    fair_champ = group_fairness(df, champion, X)
    fair_chall = group_fairness(df, challenger, X)
    expl = explain(champion, challenger, X, y, coef)
    card = build_model_card(df, fp, fair_champ, expl, runs)
    rubric = build_policy_rubric()
    pia = build_pia_checkpoints()
    appeal = build_appeal_workflow()
    honest = "소표본" in card["sections"][8]["items"][0]  # 카드 9절에 한계 표기 존재
    checklist = build_public_ai_checklist(fp_ok, fair_champ, expl, card, rubric, pia, appeal, honest)

    report = {
        "practice": "16.1 그룹별 성능 비교와 설명 결과 생성",
        "inputs": {
            "source": "ch9_experiment_report.json(9장 산출물 스냅숏)",
            "n_pairs": int(len(df)),
            "groups": [REGION_NAME[cd] for cd in REGION_ORDER],
        },
        "fingerprint": {"recomputed_16": fp[:16], "matches_ch9": fp_ok},
        "runs": runs,
        "fairness_champion": fair_champ,
        "fairness_challenger": fair_chall,
        "explanation": expl,
        "policy_rubric_criteria": [c["criterion"] for c in rubric["criteria"]],
        "pia_checkpoint_count": len(pia["checkpoints"]),
        "appeal_step_count": len(appeal["steps"]),
        "public_ai_checklist": checklist,
    }

    def dump(name: str, obj) -> None:
        (output_dir / name).write_text(
            json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n", "utf-8")

    dump("ch12_fairness_report.json", report)
    dump("ch12_model_card.json", card)
    dump("ch12_policy_rubric.json", rubric)
    dump("ch12_public_ai_checklist.json", checklist)
    (output_dir / "ch12_model_card.md").write_text(model_card_md(card), "utf-8")
    (output_dir / "ch12_policy_rubric.md").write_text(policy_rubric_md(rubric), "utf-8")

    report["_extras"] = {"model_card": card, "policy_rubric": rubric,
                         "pia": pia, "appeal": appeal}
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = build(Path(args.input), Path(args.output))
    fc = report["fairness_champion"]
    print(f"지문 9장 일치={report['fingerprint']['matches_ch9']}, "
          f"전체 MAE={fc['overall_mae']}, 그룹 MAE 격차={fc['mae_gap']}, "
          f"감사 체크 {report['public_ai_checklist']['passed']}/{report['public_ai_checklist']['total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
