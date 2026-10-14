# CLAUDE.md — MLOps 프로젝트 Claude Code 운영 가이드

> 이 파일은 Claude Code 전용 운영 지침이다.
> 프로젝트 콘텐츠 가이드는 `CODEX.md`, 운영 규칙은 `AGENTS.md`를 참조한다.
> 두 문서와 중복하지 않고, Claude Code 환경에서만 필요한 설정·하네스·에이전트를 다룬다.

---

## 빠른 시작

### Python 실습 환경
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 실행 증거 게이트 (harness)
```bash
# 10장 전체 코드 실행 + SHA-256 증거 생성
python scripts/run_and_capture.py 10

# 특정 파일만
python scripts/run_and_capture.py 10 --file 10-1-model-serving.py

# 검증 모드: 소스 변경 여부만 확인 (실행 안 함)
python scripts/run_and_capture.py 10 --verify
```

### Lint + Test 게이트
```bash
./scripts/harness.sh      # install → lint → test → build → HARNESS_PASS
./scripts/verify.sh        # lint + test → VERIFY_PASS
```

### MS Word 변환
```bash
cd ms-word && npm install && npm run convert:chapter 2
```

---

## 프로젝트 개요

- **제목**: 데이터 엔지니어링과 MLOps: 공공 AI 서비스 운영과 평가 실무
- **구성**: 4 Part / 17장
- **최종 목차**: `contents.md` 참조
- **대상 독자**: 공공 부문 데이터/MLOps 실무자, 공공정책·빅데이터 전공 학부 3-4학년

---

## 최우선 원칙

### 1. 실제 실행 원칙 + 하네스 강제
- 모든 코드는 실제 실행하여 결과 획득. 더미/가상 데이터 금지.
- **본문 수치는 `scripts/run_and_capture.py`로 생성한 `practice/chapterN/results/*.log`에서만 인용한다.** 로그 없는 결과 서술은 가짜로 간주.
- 코드 수정 후 `--verify`로 결과 낡음 확인. 소스 해시 불일치 = 재실행 필요.

### 2. 참고문헌 검증
- 허구의 참고문헌 절대 금지. 모든 인용은 실재 검증 문헌만.
- URL/DOI 가능한 포함.

### 3. 비유 금지 (2026-10-11 사용자 지시)
- 비유를 쓰지 않는다 — 직유·은유·환유·제유·의인화를 모두 포함하며, 「~처럼·~와 같이」 표지를 붙인 것도 비유다. 쉬운 설명이 필요하면 구체적인 수치 예·실제로 있었던 사례·단계를 쪼갠 절차를 쓴다 (2026-10-11 사용자 지시).
- 적용 범위: `docs/`·`lecture/` 원고 전부 + Claude Code의 한국어 응답.
- 예외 셋 — ① 인용문 안의 비유 ② 분야에서 용어로 굳은 표현(생존 편향, 과적합 등 — 첫 등장 시 기제를 한 줄로 풀어 쓴다) ③ 사용자가 비유를 요청한 경우.
- 전역 규칙 `~/.claude/CLAUDE.md` §15.3과 동일하다. 충돌 시 이 규칙이 강의교재 파생 규칙(`lecture/README.md`)보다 우선한다.

### 4. 크로스 플랫폼
- 경로는 `pathlib.Path` / `os.path.join()` 사용. 하드코딩 금지.
- Windows + macOS 모두 실행 가능해야 함.

---

## 하네스 체계

| 하네스 | 역할 | 성공 조건 |
|--------|------|-----------|
| `scripts/run_and_capture.py N` | 실행 증거 게이트 — 코드 실행 + SHA-256 해시 기록 | 모든 파일 exit_code=0 |
| `scripts/harness.sh` | Lint + Test 게이트 — ruff·pytest 자동 감지 실행 | `HARNESS_PASS` 출력 |
| `scripts/verify.sh` | 빠른 점검 (lint + test) | `VERIFY_PASS` 출력 |

### run_and_capture.py 산출물
```
practice/chapterN/
└── results/
    ├── {파일명}.log              # stdout/stderr 전체
    └── {파일명}.evidence.json    # 소스 SHA-256, 출력 SHA-256, 시각, 플랫폼
```

### 증거 인용 규칙
1. 코드 작성 완료 → `python scripts/run_and_capture.py N` 실행
2. 본문에서 수치 인용 시 해당 `.log` 파일에서 복사
3. 코드 수정 후 → `--verify`로 증거 유효성 확인 → 낡으면 재실행
4. 증거 JSON에 휘발성 식별자(run_id 등) 넣지 않는다

---

## 폴더 구조

```
mlops/
├── CLAUDE.md               # 이 파일 — Claude Code 운영 가이드
├── CODEX.md                # 프로젝트 콘텐츠 가이드
├── AGENTS.md               # 운영 규칙 (절대 금지, 강의 교재 모드, 구체성 규칙)
├── contents.md             # 최종 목차 (17장)
├── .claude/
│   ├── settings.json       # git 권한
│   ├── settings.local.json # 로컬 환경 권한
│   ├── GOTCHAS.md          # 지뢰 목록 (집필 전 필독)
│   ├── lessons-learned.md  # 실패→규칙 래칫 로그
│   └── agents/             # 6개 역할 정의
│       ├── planner.md      # 집필계획자
│       ├── researcher.md   # 리서처
│       ├── writer.md       # 작가
│       ├── coder.md        # 코드작성자
│       ├── reviewer.md     # 검토자
│       └── graphic.md      # 그래픽
├── .codex/
│   └── skills/             # Codex CLI 스킬 (역할 정의)
├── .ai/
│   ├── common.md           # 작업 사이클·완료 기준
│   ├── context.md          # 현재 상태
│   ├── todo.md             # 작업 상태
│   └── gotchas.md          # 반복 함정 (레거시 — .claude/GOTCHAS.md로 통합)
├── docs/                   # 최종 완성 원고
├── lecture/                # 학부 강의교재
├── practice/               # 실습 코드
│   └── chapter{N}/
│       ├── code/           # 실행 가능한 전체 코드
│       ├── data/           # 입력/출력 데이터
│       └── results/        # 실행 증거 (run_and_capture.py 산출물)
├── schema/                 # 집필계획서
├── content/                # 리서치·초안·그래픽·리뷰
├── scripts/
│   ├── run_and_capture.py  # 실행 증거 게이트
│   ├── harness.sh          # Lint + Test 게이트
│   └── verify.sh           # 빠른 점검
├── ms-word/                # MS Word 변환 시스템
└── checklists/             # 진행 체크리스트
```

---

## 에이전트 라우팅 (Claude Code)

`.claude/agents/` 아래 6개 에이전트가 정의되어 있다. Codex CLI의 `.codex/skills/`와 동일 역할.

| 에이전트 | 트리거 | 출력 위치 |
|----------|--------|-----------|
| planner | "계획", "스키마", "집필계획서" | `schema/chap{N}.md` |
| researcher | "조사해줘", "리서치", "참고문헌" | `content/research/` |
| writer | "작성해줘", "초안", "원고" | `content/drafts/` → `docs/` |
| coder | "코드", "실습", "예제" | `practice/chapter{N}/code/` |
| reviewer | "검토", "리뷰", "피드백" | `docs/ch{N}.md` (최종) |
| graphic | "다이어그램", "플로우차트" | `content/graphics/` |

---

## .ai/ 작업 메모리

작업 시작 시 아래 순서로 읽는다:
1. `.ai/context.md` — 현재 프로젝트 상태
2. `.ai/todo.md` — 작업 상태
3. `.claude/GOTCHAS.md` — 지뢰 목록

작업 끝에 `context.md`·`todo.md`를 갱신한다.
반복 함정 발견 시 `lessons-learned.md`에 기록, 3회 반복 시 `GOTCHAS.md`로 승격.

---

## 환경 변수 (.env)

```bash
# Multi-LLM 리뷰 (필수)
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...

# 웹 스크래핑 (선택)
FIRECRAWL_API_KEY=...
```

---

## 현재 프로젝트 상태

### 완료된 설정
- 17장 전체 §2.4 재작성·보강 사이클 완료 (codex clean gate 통과)
- 6개 전문 에이전트 구성 (`.claude/agents/` + `.codex/skills/`)
- 실행 증거 게이트 구축 (`scripts/run_and_capture.py`)
- 하네스 체계 구축 (`harness.sh` + `verify.sh` + `run_and_capture.py`)

### 참조 문서 우선순위
1. `AGENTS.md` — 운영 규칙 (최우선)
2. `CODEX.md` — 콘텐츠 가이드
3. `contents.md` — 목차·요구사항
4. `.claude/GOTCHAS.md` — 지뢰 목록

---

**마지막 업데이트**: 2026-08-15
**버전**: 2.0 (geoai 프로젝트 설정 이식)
