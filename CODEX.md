# CODEX.md

This file provides guidance to Codex CLI when working with code in this repository.

---

# 전문도서 작성 프로젝트 템플릿

## 빠른 시작 명령어

### MS Word 변환
```bash
cd ms-word && npm install              # 의존성 설치 (최초 1회)
npm run convert:chapter 2              # 개별 챕터 변환 (예: 2장)
npm run convert:all                    # 모든 챕터 일괄 변환
npm run create:book                    # 완전한 통합 도서 생성
```

### Python 실습 환경
```bash
cd practice/chapter{N}
python -m venv venv
source venv/bin/activate               # macOS/Linux
# venv\Scripts\activate                # Windows
pip install -r code/requirements.txt
python code/{N}-{M}-{주제}.py          # 실습 코드 실행
```

---

## 프로젝트 개요

이 프로젝트는 **전문도서 자동 집필 시스템**의 범용 템플릿입니다.

### 도서 정보 (사용 시 수정)
- **제목**: {도서 제목}
- **부제**: {부제}
- **구성**: {N} Part / {M}장 / 약 {X}절
- **실습**: {Y}개
- **예상 분량**: {Z}페이지
- **최종 목차**: `contents.md` 참조

---

## 최우선 원칙

### 1. 분량 기준 (탄력적 적용)
| 항목 | 기준 |
|------|------|
| 장 전체 | 약 600-700줄 전후 (난이도/중요성에 따라 조정) |
| A4 페이지 | 약 35쪽 내외 |
| 이론:코드 | 70% : 30% |

**장 유형별 분량**:
- 핵심 개념 장: 600-700줄 (이론:실습 = 70:30)
- 기술 심화 장: 700-800줄 (이론:실습 = 50:50)
- 실습 중심 장: 550-650줄 (이론:실습 = 30:70)

**분량 관리 원칙**:
- **분량보다 완성도 우선**: 억지로 분량 채우기 절대 금지
- **목표 대비 ±20% 허용**: 600줄 목표 시 480~720줄 허용 범위
- **contents.md 요구사항 충족이 핵심**: 분량은 부차적 지표
- **@writer 단계에서 실시간 조정**: 절 작성 중 분량 점검 및 균형 조정

### 2. 실제 실행 원칙
- 모든 코드는 실제 실행하여 결과 획득
- 더미/가상 데이터 금지
- "예시 출력입니다" 형태의 가상 결과 금지
- **크로스 플랫폼 호환성**: 모든 코드는 Windows와 macOS 모두에서 실행 가능해야 함
  - 경로 구분자는 `os.path.join()` 또는 `pathlib.Path` 사용
  - 플랫폼 특정 명령어 사용 금지
  - 경로 하드코딩 대신 상대 경로 또는 환경 변수 활용

### 3. 참고문헌 검증
- 허구의 참고문헌 절대 금지
- 모든 인용은 실재 검증된 문헌만
- URL/DOI 가능한 포함

### 4. 실무 중심 집필 방향

**핵심 원칙**: 실무 중심 ≠ 코드 중심. 원리를 이해하고 적용할 수 있도록 하는 것이 목표.

#### 4.1 원리 중심 설명
- **"왜 필요한가" 먼저, "어떻게 작동하는가" 다음**
- 수학적 증명보다는 직관적 이해에 집중
- 비교와 의사결정 지원 (비교 표 제공)

#### 4.2 코드 제시 원칙
- **핵심 코드만 본문에 포함** (3-5줄)
- **전체 구현 코드는 별도 파일로 분리**: `practice/chapter{N}/code/`
- 파일명은 절 번호와 주제를 반영: `{N}-{M}-{주제}.py`
- 본문에서는 참조 형태로만 언급

#### 4.3 실행 결과와 해석 필수 (CRITICAL)
- **절대 금지**: 가상의 결과값, "예시 출력", 임의로 만든 숫자
- **필수**: 코드를 실제로 실행하여 얻은 결과만 본문에 포함
- 결과 해석 및 실무적 시사점 도출

#### 4.4 수식 설명 원칙
- **수식은 반드시 포함하되, 직관적 설명을 함께 제공**
- 수식 제시 후 직관적 해석을 자연스러운 문장으로 덧붙인다
- "왜 이렇게 설계했나" - 설계 의도 설명
- 예시로 확인 - 구체적 숫자 대입으로 이해 돕기
- 수학적 증명보다는 **개념적 이해**에 집중

#### 4.5 표준 참조 문서
**집필 시 글쓰기 스타일 참조**: `docs/sample.md` 
- 수식+직관적 설명, 비즈니스 연결, 모형 비교표 등 집필 스타일의 모범 사례
- practice 폴더 참조 형식: `_전체 코드는 practice/chapter{N}/code/{파일명}.py 참고_`

---

## 폴더 구조

```
project/
├── CODEX.md               # 이 파일 - 프로젝트 컨텍스트
├── AGENTS.md              # 운영 규칙
├── CLAUDE.md              # 레거시(호환용) 안내
├── contents.md            # 최종 목차 및 집필 방향
├── schema/                # 집필계획서
│   └── chap{N}.md
├── .codex/
│   └── skills/            # Codex 스킬(역할 정의)
├── content/
│   ├── research/          # 리서치 결과
│   ├── drafts/            # 원고 초안
│   ├── graphics/          # 다이어그램/시각자료
│   └── reviews/           # LLM 리뷰 결과
├── docs/                  # 최종 완성 원고 (검토 완료)
│   ├── ch11.md            # 집필 표준 참조 문서 (시계열 분석)
│   └── ch{N}.md
├── lecture/               # 학부 3-4학년용 파생 강의교재
│   ├── README.md          # lecture 작성 원칙
│   ├── chapter{N}.md      # 장별 강의교재
│   ├── assets/            # 강의용 그림·도식
│   └── slides/            # 필요 시 슬라이드 초안
├── practice/              # 실습 코드 및 데이터
│   └── chapter{N}/
│       ├── code/          # 실행 가능한 전체 코드
│       │   ├── {N}-{M}-{주제}.py
│       │   └── requirements.txt
│       └── data/          # 실제/가상 데이터
│           ├── input/
│           └── output/
├── ms-word/               # MS Word 변환 시스템
│   ├── config/            # 설정 파일
│   ├── src/               # 변환 스크립트
│   ├── output/            # 생성된 Word 파일
│   └── templates/         # 템플릿 (머리말, 참고문헌 등)
├── checklists/            # 진행 체크리스트
├── scripts/               # 자동화 스크립트
└── _archive/              # 이전 프로젝트 백업
```

---

## 7단계 워크플로우

```
[1단계: Planning]
    (update_plan) 작업 범위/산출물/검증기준 확정
        │
    $book-planner ── 집필계획서 작성 ──▶ schema/chap{N}.md
        │
        ▼
[2단계: Information Gathering]
    $book-researcher ── 자료 조사 ──▶ content/research/
        │
        ▼
[3단계: Analysis]
    정보 구조화 및 핵심 통찰 추출
        │
        ▼
[4단계: Implementation & Documentation]
    ├── $book-coder ── 코드 우선 작성 ──▶ practice/chapter{N}/code/
    ├── $book-writer ── 결과 기반 문서화 ──▶ content/drafts/
    └── $book-graphic ── 시각자료 ──▶ content/graphics/
        │
        ▼
[5단계: Optimization]
    일관성 및 완성도 검증
        │
        ▼
[6단계: Quality Verification] ⭐ Multi-LLM 리뷰 필수
    $book-reviewer ── 품질 검토 ──▶ content/drafts/
        │
    Multi-LLM 리뷰 (8.5점 이상 필수) ──▶ content/reviews/
        │
    타당한 지적사항 수정 (점수 무관)
        │
    통과 시 ──▶ docs/ch{N}.md (최종 완성본)
        │
        ▼
[7단계: MS Word Conversion]
    MS Word 변환 시스템 ──▶ ms-word/output/*.docx
        │
        ▼
[8단계: Undergraduate Lecture Adaptation]
    docs/ 실무교재 ── 구체 예·수업활동 중심 재구성 ──────▶ lecture/chapter{N}.md
```

### 필수 단계 (5-7단계는 자동 수행)

**CRITICAL**: 집필은 반드시 1-7단계를 **모두 실행**한다. 단계 생략 금지.
**CRITICAL**: 6단계에서 Multi-LLM 리뷰 점수가 8.5 미만이면 수정 후 재검토 필수.
**CRITICAL**: 지적 사항이 타당할 경우 점수와 상관없이 반드시 수정한다.

#### 작업 명령어 해석 기준
| 사용자 명령 | 수행 범위 | 비고 |
|---|---|---|
| "N장 작성" | 1~7단계 전체 | **모든 단계 자동 수행** (Word 변환 포함) |
| "N장 검토" | 5~7단계 | 일관성 검증 + 품질 리뷰 + Word 변환 |
| "N장 변환" | 7단계만 | docs/ch{N}.md → Word |
| "N장 강의교재 작성" | 8단계 | 완료된 실무교재를 근거로 `lecture/chapter{N}.md` 작성 |

### 8단계 학부 강의교재 파생 원칙

- `lecture/`는 실무교재(`docs/`)를 근거로 학부 3-4학년 수업용 원고를 만드는 공간이다.
- 목적은 정확성을 낮추는 것이 아니라, 쉬운 설명·작은 수치 예·실제 사례·수업 질문으로 이해 경로를 바꾸는 것이다. 비유로 설명을 대신하지 않는다(`AGENTS.md` §1 하드 룰).
- 실무교재에 없는 수치, 실행 결과, 참고문헌을 새로 만들지 않는다.
- 복잡한 개발·운영 세부사항은 “더 알아보기”로 줄이고, 핵심 판단 질문을 전면에 둔다.
- 장별 강의교재는 `lecture/README.md`의 템플릿을 따른다.

---

## 스킬 라우팅 규칙

### $book-planner (집필계획자)
- **트리거**: "계획", "스키마", "집필계획서", "구성"
- **도구**: `update_plan`으로 단계/검증기준을 먼저 고정
- **출력**: `schema/chap{N}.md`

### $book-researcher (리서처)
- **트리거**: "조사해줘", "리서치", "자료 찾아줘", "참고문헌"
- **출력**: `content/research/ch{N}-{절}.md`

### $book-writer (작가) ⭐ 분량 관리의 핵심 단계
- **트리거**: "작성해줘", "초안", "원고", "본문"
- **출력**: `content/drafts/ch{N}-{절}.md`
- **분량 관리 워크플로우** (초안 작성 중 실시간 조정):
  ```
  절 작성 → 분량 확인 → 조정 → 다음 절
          ↓
  모든 절 완성 → 전체 분량 확인 → 최종 조정
          ↓
  $book-reviewer: 품질 검증 (분량은 부차적)
  ```
- **핵심 원칙**:
  - contents.md 요구사항 충족이 최우선
  - 절 작성 완료 시마다 분량 점검
  - 목표 대비 ±20% 범위 내 유연하게 조정
  - **품질이 분량보다 우선**: 억지로 분량 채우기 금지

### $book-coder (코드작성자)
- **트리거**: "코드", "실습", "예제", "구현"
- **출력**: `practice/chapter{N}/code/`

### $book-reviewer (검토자)
- **트리거**: "검토", "리뷰", "피드백", "수정"
- **출력**: 인라인 피드백 또는 `docs/ch{N}.md`

### $book-graphic (그래픽)
- **트리거**: "다이어그램", "그래픽", "플로우차트", "아키텍처"
- **출력**: `content/graphics/ch{N}/`

---

## 핵심 작업 규칙

### 문체 가이드 (학술적 글쓰기)
- **비유 금지**: 비유를 쓰지 않는다 — 직유·은유·환유·제유·의인화를 모두 포함하며, 「~처럼·~와 같이」 표지를 붙인 것도 비유다. 쉬운 설명이 필요하면 구체적인 수치 예·실제로 있었던 사례·단계를 쪼갠 절차를 쓴다 (2026-10-11 사용자 지시). `docs/`·`lecture/` 원고와 AI 응답에 모두 적용한다.
- **문체**: 객관적, 논리적, 설명적, 교훈적
- **종결어미**: 격식체 평서문 ('이다', '한다', '보인다')
- **문장 구조**: 단문·복문·중문 혼용, 개조식 금지 (예외: 표, 학습목표)
- **용어**: 전문 용어 영문 병기 (예: "합성곱 신경망(CNN)")

### 수식 표기 (Unicode 인라인)
```
✅ 올바름: Yᵢₜ = αᵢ + λₜ + δ·Dᵢₜ + εᵢₜ
❌ 금지: $Y_{it} = \alpha_i + \lambda_t$ (LaTeX)
```

### 코드 스타일
- Python 3.10+
- PEP 8 준수
- 한국어 주석/docstring
- 실제 실행 결과만 사용

### 참고문헌 형식
```
저자명. (연도). 논문제목. *저널명*. URL/DOI
```

### 표/그림 제목 형식
- **표 제목**: 표 위에 작성 (`**표 2.1** 제목`)
- **그림 제목**: 그림 아래에 작성 (`**그림 3.2** 제목`)
- **번호 체계**: `{장번호}.{순번}`

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

## Multi-LLM 리뷰 시스템 (필수)

### 개요
모든 챕터는 외부 LLM을 통한 품질 검증을 **필수**로 통과해야 한다.

### 검증 항목
1. **내용 타당성**: 기술적 정확성, 논리적 일관성, 실무 적용성
2. **이론/방법론 최신성**: 방법론 유효성, 라이브러리 호환성, 업계 동향
3. **참고문헌 검증**: URL 접근 가능 여부, 인용 실재 여부

### 사용법
```bash
# 프로젝트 venv 활성화 후 실행
venv/bin/python scripts/multi_llm_review.py --chapter 12   # 개별 챕터
venv/bin/python scripts/multi_llm_review.py --all          # 전체 챕터
```

### 출력 파일
- **JSON 결과**: `content/reviews/ch{N}-review.json`
- **Markdown 리포트**: `content/reviews/ch{N}-review.md`

### 통과 기준
- **전체 점수 8.5 이상**이어야 `docs/`에 최종본 저장 가능
- 8.5 미만 시 지적 사항 수정 후 재검토 필수
- **지적 사항이 타당할 경우 점수와 상관없이 수정** (점수가 높아도 유효한 피드백은 반영)

---

## 체크리스트 위치

진행 상황은 `checklists/book-progress.md`에서 추적합니다.

---

## MS Word 변환 시스템

### 개요
완성된 Markdown 원고(`docs/ch{N}.md`)를 전문적인 MS Word 문서(`.docx`)로 변환합니다.

### 사용법
```bash
cd ms-word
npm install                    # 의존성 설치 (최초 1회)
npm run convert:chapter 2      # 개별 챕터 변환
npm run convert:all            # 모든 챕터 일괄 변환
npm run create:book            # 완전한 통합 도서 생성
```

### 출력 파일
- **개별 챕터**: `ms-word/output/ch{N}.docx`
- **통합 도서**: `ms-word/output/{project}-complete-book.docx`

---

## 현재 프로젝트 상태

### 도서 정보
- **제목**: (미정 - contents.md에서 설정)
- **현재 단계**: 템플릿 구축 완료

### 완료된 설정
- ✅ 6개 전문 에이전트 구성
- ✅ 7단계 워크플로우 정의
- ✅ 디렉토리 구조 생성
- ⏳ contents.md 작성 대기
- ⏳ MS Word 변환 시스템 구축 대기

---

**마지막 업데이트**: 2026-01-05
**템플릿 버전**: 1.1
