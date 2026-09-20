#!/usr/bin/env python3
"""7주차 실습 8.1: Feast 기반 최소 피처 저장소 구성.

6주차 배치가 확정한 일별 민원 집계(스냅숏 동봉)를 피처 원천으로 삼아,
피처 정의(entity·feature view) → 등록(apply) → point-in-time 조회(historical)
→ 온라인 적재(materialize) → 온라인 조회 → 훈련-서빙 일관성 점검의
전체 흐름을 로컬 저장소(parquet + SQLite)에서 실행한다.

- 원천 데이터는 6주차 실측 산출물의 스냅숏이다(민원 자체는 4~7장과 동일한
  시뮬레이션 입력). 관찰 대상은 실제 Feast 엔진의 조인·적재·조회 동작이며,
  본문 인용 수치는 전부 실제 실행 산출물에서 나온다.
- 실행: python code/7-1-feature-store-minimal.py  (또는 python run_chapter7.py)
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"
REPO_DIR = OUTPUT_DIR / "feature_repo"

DAYS = ["2026-07-01", "2026-07-02", "2026-07-03"]


def dump_json(path: Path, obj) -> None:
    """결정적 직렬화(키 정렬) — 6주차와 같은 원칙."""
    path.write_text(
        json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


# ── 1단계: 피처 원천 만들기 — 6주차 확정 집계 → parquet ─────────────
def build_source_parquet() -> Path:
    """일별 집계를 (지역, 타임스탬프, 피처값) 행으로 변환한다.

    타임스탬프는 "값이 알려진 시점"이다: 7/1의 일별 건수는 7/1 마감 후에야
    확정되므로 event_timestamp = 다음 날 00:00(UTC)로 둔다(8.3절의 핵심 결정).
    """
    rows = []
    for day in DAYS:
        summary = json.loads((INPUT_DIR / "ch6_daily" / day / "daily_summary.json").read_text(encoding="utf-8"))
        check = json.loads((INPUT_DIR / "ch6_daily" / day / "quality_check.json").read_text(encoding="utf-8"))
        known_at = datetime.fromisoformat(day + "T00:00:00+00:00") + timedelta(days=1)
        for r in summary["by_region"]:
            rows.append(
                {
                    "lawd_cd": r["lawd_cd"],
                    "event_timestamp": known_at,
                    "complaint_count": int(r["count"]),
                    "day_unmapped_rate": float(check["unmapped_rate"]),
                }
            )
    df = pd.DataFrame(rows)
    path = OUTPUT_DIR / "complaint_daily_features.parquet"
    df.to_parquet(path, index=False)
    print(f"[source] 피처 원천 {len(df)}행 → {path.name}")
    return path


# ── 2단계: 피처 저장소 정의·등록 ─────────────────────────────────
def make_repo(source_path: Path):
    from feast import Entity, FeatureService, FeatureStore, FeatureView, Field, FileSource, ValueType
    from feast.types import Float64, Int64

    REPO_DIR.mkdir(parents=True, exist_ok=True)
    (REPO_DIR / "feature_store.yaml").write_text(
        f"""project: public_complaints
registry: {REPO_DIR / "registry.db"}
provider: local
online_store:
    type: sqlite
    path: {REPO_DIR / "online_store.db"}
entity_key_serialization_version: 3
""",
        encoding="utf-8",
    )

    # entity: 조인 키 — 지역명이 아니라 법정동코드(7.2의 표준 코드 원칙 그대로)
    district = Entity(
        name="district",
        join_keys=["lawd_cd"],
        value_type=ValueType.STRING,
        description="법정동 시군구 코드(행정표준코드) — 6주차 정제의 표준 키",
    )

    # feature view: 어떤 원천에서 어떤 스키마의 피처를 얻는가의 선언
    daily_fv = FeatureView(
        name="complaint_daily",
        entities=[district],
        ttl=timedelta(days=3),  # 신선도 하한: 이보다 오래된 값은 조인하지 않는다
        schema=[
            Field(name="complaint_count", dtype=Int64,
                  description="전일 확정 민원 건수(7장 일별 집계)"),
            Field(name="day_unmapped_rate", dtype=Float64,
                  description="전일 정제 품질 — 매핑 실패율(6주차 quality_check)"),
        ],
        source=FileSource(path=str(source_path), timestamp_field="event_timestamp"),
        tags={  # 8.4절: 피처 거버넌스 메타데이터
            "owner": "민원데이터팀(가상 — 시뮬레이션 표기)",
            "source": "7장 일별 배치 확정 산출물",
            "update_cycle": "일 1회(배치 마감 후)",
            "privacy": "개인정보 없음(지역 단위 집계)",
        },
    )

    # feature service: 모델이 소비하는 피처 묶음의 버전 단위
    service = FeatureService(name="complaint_model_v1", features=[daily_fv])

    store = FeatureStore(repo_path=str(REPO_DIR))
    store.apply([district, daily_fv, service])
    print(f"[apply] 등록: entity={district.name}, view={daily_fv.name}, service={service.name}")
    return store


# ── 3단계: point-in-time 조회(훈련용) ────────────────────────────
def historical_join(store) -> tuple[pd.DataFrame, list[dict]]:
    """기준 시점이 다른 훈련 샘플 4개에 피처를 조인한다 — 미래 누출 방지 관찰.

    관찰 포인트가 둘이다: (1) 각 샘플에는 기준 시점 이전에 확정된 값만 붙는다,
    (2) 조인할 피처가 아예 없는 샘플(최초 확정 이전 시점)은 결과에서 행째로
    탈락한다 — 그래서 조인 후에는 반드시 행 수를 원본과 대조해야 한다.
    """
    entity_df = pd.DataFrame(
        {
            "lawd_cd": ["11620", "11680", "11440", "11680"],
            "event_timestamp": [
                datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),  # 아직 아무 집계도 확정 전
                datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),  # 7/1 집계만 확정
                datetime(2026, 7, 3, 9, 0, tzinfo=timezone.utc),  # 7/2까지 확정
                datetime(2026, 7, 4, 9, 0, tzinfo=timezone.utc),  # 7/3까지 확정
            ],
        }
    )
    df = store.get_historical_features(
        entity_df=entity_df,
        features=store.get_feature_service("complaint_model_v1"),
    ).to_df()
    df = df.sort_values("event_timestamp").reset_index(drop=True)

    # 행 수 대조: 입력 샘플 대비 결과에서 사라진 (키, 시점) 식별
    key = lambda frame: set(zip(frame["lawd_cd"], frame["event_timestamp"].astype(str)))
    lost = sorted(key(entity_df) - key(df))
    dropped = [{"lawd_cd": cd, "as_of": ts} for cd, ts in lost]
    print(f"[historical] 입력 샘플 {len(entity_df)}행 → 조인 결과 {len(df)}행 (탈락 {len(dropped)}행: {dropped})")
    print(df.to_string(index=False))
    return df, dropped


# ── 4단계: 온라인 적재와 조회(서빙용) + 일관성 점검 ──────────────
def online_and_consistency(store, source_path: Path) -> dict:
    # 적재 범위를 명시한다. materialize_incremental의 기본 시작(현재-ttl)은
    # 이 실습처럼 과거 날짜의 피처를 뒤늦게 적재할 때 전부 지나쳐 버린다
    # (실제로 겪은 오류 — 온라인 조회가 조용히 None을 돌려줬다).
    store.materialize(
        start_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
        end_date=datetime.now(timezone.utc),
    )

    keys = [{"lawd_cd": c} for c in ("11440", "11620", "11680")]
    online = store.get_online_features(
        features=store.get_feature_service("complaint_model_v1"),
        entity_rows=keys,
    ).to_dict()

    # 훈련-서빙 일관성 점검: offline 원천의 키별 최신값 == online 조회값
    src = pd.read_parquet(source_path)
    latest = src.sort_values("event_timestamp").groupby("lawd_cd").tail(1).set_index("lawd_cd")
    rows = []
    for i, cd in enumerate(online["lawd_cd"]):
        off_cnt = int(latest.loc[cd, "complaint_count"])
        off_rate = round(float(latest.loc[cd, "day_unmapped_rate"]), 3)
        on_cnt = int(online["complaint_count"][i])
        on_rate = round(float(online["day_unmapped_rate"][i]), 3)
        rows.append(
            {
                "lawd_cd": cd,
                "offline_latest": {"complaint_count": off_cnt, "day_unmapped_rate": off_rate},
                "online": {"complaint_count": on_cnt, "day_unmapped_rate": on_rate},
                "consistent": off_cnt == on_cnt and off_rate == on_rate,
            }
        )
    report = {"checked_keys": len(rows), "all_consistent": all(r["consistent"] for r in rows), "rows": rows}
    print(f"[online] 조회 {len(rows)}건, 훈련-서빙 일관성: {report['all_consistent']}")
    return report


def export_definitions(store) -> dict:
    """피처 정의서: registry에 등록된 정의를 문서로 내보낸다(8.4 거버넌스 자산)."""
    fv = store.get_feature_view("complaint_daily")
    service = store.get_feature_service("complaint_model_v1")
    defs = {
        "project": store.project,
        "entity": {
            "name": "district",
            "join_key": "lawd_cd",
            "description": "법정동 시군구 코드(행정표준코드)",
        },
        "feature_view": {
            "name": fv.name,
            "ttl_days": fv.ttl.days,
            "features": [
                {"name": f.name, "dtype": str(f.dtype), "description": f.description}
                for f in fv.features
            ],
            "timestamp_semantics": "event_timestamp = 값이 확정·공개된 시점(집계 대상일 다음 날 00:00 UTC)",
            "governance": dict(fv.tags),
        },
        "feature_service": {"name": service.name, "views": ["complaint_daily"]},
    }
    return defs


def reset_owned_outputs() -> None:
    """이 실행을 다시 돌리는 데 방해가 되는 것만 비운다.

    피처 저장소 디렉터리는 지난 실행의 등록 정보가 섞이지 않도록 지운다.
    산출물 JSON과 parquet은 지우지 않는다 — 계산이 끝난 뒤 덮어쓰므로,
    실행이 중간에 실패해도 지난 실행의 산출물이 그대로 남는다.
    data/output에는 7-2~7-4의 산출물과 학생이 제출할 파일도 함께 있다.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if REPO_DIR.exists():
        shutil.rmtree(REPO_DIR)


def main() -> int:
    reset_owned_outputs()

    source_path = build_source_parquet()
    store = make_repo(source_path)

    hist, dropped = historical_join(store)
    consistency = online_and_consistency(store, source_path)
    defs = export_definitions(store)

    hist_records = [
        {
            "lawd_cd": r["lawd_cd"],
            "as_of": r["event_timestamp"].isoformat(),
            "complaint_count": None if pd.isna(r["complaint_count"]) else int(r["complaint_count"]),
            "day_unmapped_rate": None if pd.isna(r["day_unmapped_rate"]) else round(float(r["day_unmapped_rate"]), 3),
        }
        for _, r in hist.iterrows()
    ]

    import feast
    report = {
        "feast_version": feast.__version__,
        "entity_rows_requested": 4,
        "historical_join": hist_records,
        "historical_dropped_rows": dropped,
        "consistency": consistency,
    }
    dump_json(OUTPUT_DIR / "ch7_feature_report.json", report)
    dump_json(OUTPUT_DIR / "ch7_feature_definitions.json", defs)
    dump_json(OUTPUT_DIR / "ch7_consistency_report.json", consistency)

    # 종합 판정: point-in-time 기대값(6주차 실측에서 손으로 도출)과 일치하는가
    expected = {
        ("11680", "2026-07-02T09:00:00+00:00"): 8,  # 7/1 강남 8
        ("11440", "2026-07-03T09:00:00+00:00"): 5,  # 7/2 마포 5
        ("11680", "2026-07-04T09:00:00+00:00"): 9,  # 7/3 강남 9
    }
    got = {(r["lawd_cd"], r["as_of"]): r["complaint_count"] for r in hist_records}
    # 확정 전 시점 샘플(11620, 7/1 09:00)은 행째 탈락하는 것이 관찰된 동작
    ok = (
        got == expected
        and len(dropped) == 1
        and dropped[0]["lawd_cd"] == "11620"
        and consistency["all_consistent"]
    )
    print("CH7_RUN_" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
