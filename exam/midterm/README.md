# 중간 미니 프로젝트 — 강사용 (공개 저장소에 올리지 않는다)

`exam/`은 `.gitignore`에 들어 있다. 이 폴더의 정답 풀이·채점 스크립트·문제지는 커밋되지 않는다.

| 파일 | 하는 일 |
|---|---|
| `solution/m-1·m-2·m-3` | 학생용 골격(`practice/midterm/code/`)을 다 채운 정답 풀이. 채점·문항 생성이 `compute()`를 불러 쓴다 |
| `grade.py` | 재택 산출물 값 일치 채점(40점 만점 → 25점 환산). 학번으로 데이터를 다시 만들고 정답과 항목별로 대조 |
| `inclass.py` | 현장 지필 문제지(`sheets/<학번>.md`)와 정답 키(`keys/<학번>.json`) 생성 |

## 순서

```bash
# 1. 현장 검증 문제지 — 수강생 명단(첫 열 student_id)으로 한 번에
python exam/midterm/inclass.py --roster exam/midterm/roster.csv

# 2. 재택 산출물 채점 — 학생 제출 압축을 푼 폴더마다
python exam/midterm/grade.py --student-id 20231234 --submission <압축 푼 폴더>
python exam/midterm/grade.py --student-id 20231234 --submission <폴더> --json > <학번>_grade.json
```

## 주의

- 학생용 골격의 처리 규칙(각 파일 맨 위 설명)을 바꾸면 `solution/`의 같은 파일도 똑같이 고친다. 둘이 어긋나면 채점과 문항 정답이 함께 틀린다.
- `practice/midterm/code/m-0-make-dataset.py`를 고치면 같은 학번에서 나오는 데이터가 바뀐다. 학생에게 배포한 뒤에는 고치지 않는다.
- 생성기 코드는 공개되어 있으므로, 학생이 코드를 읽어 결함 위치를 추론할 수는 있다. 그래도 현장 문항의 「설정값을 바꾸면」 판단은 생성기를 읽어서는 답이 나오지 않는다.
- 문항 3(1)의 정답은 범위(최소·최대)다. 키의 `q3_1_actual_rule_result`는 실제 규칙으로 돌린 값이며 참고용이다.
- 문항 2(2)의 키 `q2_2_recovered`가 비어 있는 학생이 있을 수 있다(지연 5분에서 폐기가 적은 경우). 그때는 「없음」과 근거가 정답이다.
