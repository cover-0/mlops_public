#!/usr/bin/env python3
"""9장 실습 9.1: MLflow 실험 기록과 모델 등록.

8장 피처(전일 민원 건수) 스냅숏으로 "다음 날 건수 예측" 후보 2개를 훈련하며,
실험 기록(파라미터·메트릭·아티팩트·데이터 지문) → 재현성 검증 → 모델 레지스트리
등록(버전) → 승격 게이트(별칭 champion) → 별칭 로드·예측의 전 흐름을 실행한다.

- 훈련 데이터는 8장 피처 원천 스냅숏(원천은 4~7장 시뮬레이션 민원의 확정 집계)
  에서 만든 (전일 건수 → 당일 건수) 6쌍이다. 데이터가 극소하므로 성능 수치는
  모델 품질의 주장이 아니라 기록·등록 메커니즘 관찰용이다 — 정직 표기.
- 실행: python code/9-1-mlflow-tracking.py  (또는 python run_chapter9.py)
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"

def reset_owned_outputs() -> None:
    """이 실행을 다시 돌리는 데 방해가 되는 것만 비운다.

    실험 추적 DB와 run 디렉터리는 지난 실행 기록이 섞이지 않도록 지운다.
    산출물 JSON은 지우지 않는다 — 계산이 끝난 뒤 덮어쓰므로, 실행이 중간에
    실패해도 지난 실행의 산출물이 그대로 남는다.
    data/output에는 9-2~9-5의 산출물과 학생이 제출할 파일도 함께 있다.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = [OUTPUT_DIR / "mlflow.db", OUTPUT_DIR / "mlruns"]
    targets += sorted(OUTPUT_DIR.glob("training_pairs_*.csv"))
    for target in targets:
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

MODEL_NAME = "complaint_daily_forecaster"
MAE_GATE = 1.05  # 승격 게이트: 훈련 MAE가 이 값 이하일 것(베이스라인 1.0 기준 소폭 여유)


def dump_json(path: Path, obj) -> None:
    path.write_text(
        json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


# ── 훈련 데이터: 8장 피처에서 (전일 건수 → 당일 건수) 쌍 만들기 ──
def build_training_pairs() -> pd.DataFrame:
    src = pd.read_parquet(INPUT_DIR / "complaint_daily_features.parquet")
    # event_timestamp는 "알려진 시점"(집계일 다음 날 00:00, 8장) — 집계 대상일로 환산
    # pd.Timedelta(1, "D") 형태 — 이 환경(numpy 최신)에서 days=1 키워드는 DeprecationWarning
    src = src.assign(day=src["event_timestamp"].dt.normalize() - pd.Timedelta(1, "D"))
    src = src.sort_values(["lawd_cd", "day"])
    pairs = []
    for cd, g in src.groupby("lawd_cd"):
        g = g.reset_index(drop=True)
        for i in range(len(g) - 1):
            pairs.append(
                {
                    "lawd_cd": cd,
                    "x_prev_count": int(g.loc[i, "complaint_count"]),
                    "y_count": int(g.loc[i + 1, "complaint_count"]),
                }
            )
    df = pd.DataFrame(pairs).sort_values(["lawd_cd", "x_prev_count"]).reset_index(drop=True)
    return df


def data_fingerprint(df: pd.DataFrame) -> str:
    """훈련 데이터 지문(sha256) — 5·7장의 지문 기법을 훈련 데이터에 적용."""
    canon = df.to_csv(index=False).encode("utf-8")
    return hashlib.sha256(canon).hexdigest()


# ── 후보 훈련 + 기록 ─────────────────────────────────────────────
def train_and_log(candidate: str, df: pd.DataFrame, fingerprint: str):
    """후보 1개를 훈련하고 run으로 기록한다. (run_id, mae, 계수요약) 반환."""
    import mlflow
    import mlflow.sklearn
    from sklearn.dummy import DummyRegressor
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import mean_absolute_error

    X = df[["x_prev_count"]].to_numpy(dtype=float)
    y = df["y_count"].to_numpy(dtype=float)

    if candidate == "baseline_mean":
        model = DummyRegressor(strategy="mean")
        params = {"model_type": "DummyRegressor", "strategy": "mean"}
    elif candidate == "linear":
        model = LinearRegression()
        params = {"model_type": "LinearRegression", "fit_intercept": True}
    else:
        raise ValueError(candidate)

    with mlflow.start_run(run_name=candidate) as run:
        model.fit(X, y)
        pred = model.predict(X)
        mae = float(mean_absolute_error(y, pred))

        # 파라미터: 모델 설정 + 데이터 지문(어느 데이터로 훈련했는가의 증거)
        mlflow.log_params({**params, "n_samples": len(df), "features": "x_prev_count",
                           "data_sha256_16": fingerprint[:16]})
        mlflow.log_metric("train_mae", mae)
        # 9.4 공공 운영 메타데이터(시뮬레이션 표기): 감사가 요구하는 항목을 태그로
        mlflow.set_tags({
            "owner": "민원데이터팀(가상)",
            "purpose": "지역구별 익일 민원 건수 예측(교육용)",
            "data_source": "8장 피처 스냅숏(원천: 시뮬레이션 민원 확정 집계 7/1~7/3)",
            "data_period": "2026-07-01~2026-07-03",
        })
        # 아티팩트: 훈련 데이터 원본과 모델
        csv_path = OUTPUT_DIR / f"training_pairs_{candidate}.csv"
        df.to_csv(csv_path, index=False)
        mlflow.log_artifact(str(csv_path), artifact_path="training_data")
        # MLflow 3: log_model이 돌려주는 model_uri가 등록·로드의 정본 경로다
        # (구식 "runs:/<run_id>/model" 경로는 MLflow 3의 저장 구조에서 깨진다 — 실제 겪은 오류)
        model_info = mlflow.sklearn.log_model(model, name="model", input_example=X[:1])

        coef = None
        if candidate == "linear":
            coef = {"slope": round(float(model.coef_[0]), 4),
                    "intercept": round(float(model.intercept_), 4)}
        print(f"[run] {candidate}: train_mae={mae:.4f} run_id={run.info.run_id[:8]}… coef={coef}")
        return run.info.run_id, mae, coef, model_info.model_uri


# ── 레지스트리: 등록·게이트·별칭 ─────────────────────────────────
def register_and_gate(client, run_id: str, model_uri: str, mae: float, note: str) -> dict:
    """run의 모델을 버전으로 등록하고 절대 게이트(메트릭 임계)를 평가한다.

    승격은 이중 판정이다: metric_gate_pass(절대 게이트)와 별개로, 기존 champion
    대비 개선까지 확인한 최종 결과를 promoted에 기록한다(main에서 확정).
    반려된 후보가 "게이트 통과"로만 남으면 감사 기록이 자기모순이 된다.
    """
    mv = client.create_model_version(
        name=MODEL_NAME, source=model_uri, run_id=run_id, description=note
    )
    # run_id는 실행마다 바뀌는 휘발성 식별자라 커밋되는 증거 파일에는 넣지 않는다
    # (재실행 시 diff 0가 증거의 결정성 — 연결 관계는 mlflow.db/UI에서 확인)
    decision = {
        "version": int(mv.version),
        "train_mae": round(mae, 4),
        "metric_gate": f"train_mae <= {MAE_GATE}",
        "metric_gate_pass": mae <= MAE_GATE,
        "promoted": False,  # 상대 조건(champion 대비 개선)까지 본 뒤 main에서 확정
    }
    return decision


def main() -> int:
    # 의존성 임포트를 파괴적 정리보다 먼저 — 미설치 환경에서 기존 증거 파일만 지우고
    # 죽는 사고 방지(임포트 실패 시 output은 건드리지 않은 채 종료)
    import mlflow
    import sklearn  # noqa: F401 — 조기 확인용(실제 사용은 train_and_log·report)
    from mlflow import MlflowClient

    reset_owned_outputs()

    # 레지스트리는 DB 백엔드가 필요하다 — 로컬 SQLite로 고정(홈 오염 방지)
    mlflow.set_tracking_uri(f"sqlite:///{OUTPUT_DIR / 'mlflow.db'}")
    mlflow.set_experiment("complaint_forecast")

    df = build_training_pairs()
    fp = data_fingerprint(df)
    print(f"[data] 훈련 쌍 {len(df)}개, 지문 {fp[:16]}…")
    print(df.to_string(index=False))

    # ── 시나리오 1: 후보 2개 훈련·기록 ──
    print("\n== 시나리오 1: 후보 2개 실험 기록 ==")
    run_base, mae_base, _, uri_base = train_and_log("baseline_mean", df, fp)
    run_lin, mae_lin, coef_lin, uri_lin = train_and_log("linear", df, fp)

    # ── 시나리오 2: 재현성 — 같은 설정 재실행 → 같은 결과 ──
    print("\n== 시나리오 2: 같은 설정 재실행(재현성) ==")
    _run_lin2, mae_lin2, coef_lin2, _uri_lin2 = train_and_log("linear", df, fp)
    repro = {
        "mae_equal": mae_lin == mae_lin2,
        "coef_equal": coef_lin == coef_lin2,
        "mae_first": round(mae_lin, 4),
        "mae_rerun": round(mae_lin2, 4),
        "coef": coef_lin,
    }
    print(f"  메트릭 동일={repro['mae_equal']}, 계수 동일={repro['coef_equal']}")

    # ── 시나리오 3: 레지스트리 — v1 등록·승격, v2 등록·게이트 판정 ──
    print("\n== 시나리오 3: 모델 등록과 승격 게이트 ==")
    client = MlflowClient()
    client.create_registered_model(
        MODEL_NAME, description="지역구별 익일 민원 건수 예측(교육용·시뮬레이션 데이터)"
    )
    d1 = register_and_gate(client, run_base, uri_base, mae_base, "베이스라인(평균) — 최초 등록")
    if d1["metric_gate_pass"]:
        client.set_registered_model_alias(MODEL_NAME, "champion", d1["version"])
        d1["promoted"] = True
        d1["action"] = "champion 별칭 부여(승격)"
    d2 = register_and_gate(client, run_lin, uri_lin, mae_lin, "선형회귀 후보 — 개선 시도")
    champion_v = int(client.get_model_version_by_alias(MODEL_NAME, "champion").version)
    # 판정은 반올림 전 원값으로 — 표시용 반올림이 판정을 바꾸면 안 된다
    if d2["metric_gate_pass"] and mae_lin < mae_base:
        client.set_registered_model_alias(MODEL_NAME, "champion", d2["version"])
        d2["promoted"] = True
        d2["action"] = "champion 전환(승격)"
        champion_v = d2["version"]
    else:
        d2["action"] = "승격 반려 — 절대 게이트 통과했으나 기존 champion 대비 개선 없음"
    print(f"  v{d1['version']}: {d1['action']} / v{d2['version']}: {d2['action']} → champion=v{champion_v}")

    # ── 시나리오 4: 별칭으로 로드·예측(서빙 관점) ──
    print("\n== 시나리오 4: 별칭(champion)으로 로드·예측 ==")
    loaded = mlflow.pyfunc.load_model(f"models:/{MODEL_NAME}@champion")
    x_serve = 9.0  # 강남구의 최신 피처(8장 온라인 조회 실측값 9)
    forecast = float(loaded.predict(pd.DataFrame({"x_prev_count": [x_serve]}))[0])
    print(f"  입력(전일 건수)={x_serve} → 예측={forecast:.2f} (champion=v{champion_v})")

    # ── 산출물: 승격 검수 기록 + 증거 파일 ──
    promotion_record = {
        "model_name": MODEL_NAME,
        "champion_version": champion_v,
        "gate_rule": f"train_mae <= {MAE_GATE} 그리고 기존 champion 대비 개선",
        "decisions": [d1, d2],
        "reproducibility_check": repro,
        "data_fingerprint_sha256": fp,
        "reviewer": "검수 담당(가상 — 시뮬레이션 표기)",
        "notes": "훈련 데이터 6쌍(교육용 극소 데이터) — 성능 수치는 메커니즘 관찰용",
    }
    dump_json(OUTPUT_DIR / "ch9_promotion_record.json", promotion_record)

    report = {
        "mlflow_version": mlflow.__version__,
        "sklearn_version": sklearn.__version__,
        "training_pairs": df.to_dict(orient="records"),
        "data_fingerprint_sha256": fp,
        "runs": {
            "baseline_mean": {"train_mae": round(mae_base, 4)},
            "linear": {"train_mae": round(mae_lin, 4), "coef": coef_lin},
            "linear_rerun": {"train_mae": round(mae_lin2, 4), "coef": coef_lin2},
        },
        "reproducibility": repro,
        "registry": {"decisions": [d1, d2], "champion_version": champion_v},
        "serving_via_alias": {"input_prev_count": x_serve, "forecast": round(forecast, 4)},
    }
    dump_json(OUTPUT_DIR / "ch9_experiment_report.json", report)

    ok = (
        len(df) == 6
        and repro["mae_equal"] and repro["coef_equal"]
        and d1["promoted"] and not d2["promoted"]
        and champion_v == d1["version"]
        and abs(forecast - mae_sanity_expected(df)) < 1e-9
    )
    print(f"\n증거 파일: {OUTPUT_DIR / 'ch9_experiment_report.json'}")
    print("CH9_RUN_" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def mae_sanity_expected(df: pd.DataFrame) -> float:
    """champion이 베이스라인(평균)일 때의 기대 예측값 = y 평균."""
    return float(df["y_count"].mean())


if __name__ == "__main__":
    raise SystemExit(main())
