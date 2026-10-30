# 프로젝트 범위

이 폴더는 **생명과학 수행평가 설계 도우미** 전용 사이드 프로젝트다.

- 주된 목표: 전국 학교알리미 평가계획 원문에서 2015·2022 개정 생명과학 교과군의 수행평가 계획을 수집·분류·분석하고, 생명과학Ⅰ 수행평가 설계에 활용할 근거를 만든다.
- 대상 과목: 통합과학, 과학탐구실험, 생명과학Ⅰ, 생명과학Ⅱ(2015 개정) / 통합과학1, 과학탐구실험1, 생명과학(2022 개정) / 생명과학실험, 고급생명과학(전문교과).
- 수학 판(`2026 수학 수행평가 아이디어 아카이브`)에서 분기했다. 원본은 `docs/reference-math/`에 읽기 전용으로 두고 수정하지 않으며, 수학 산출물과 결과를 섞지 않는다.
- 기존 `성취기준 기반 탐구주제 분석기`와도 작업 범위·산출물을 섞지 않는다.
- 모든 새 수집물, 파생 데이터, 분석 문서, 스크립트는 이 폴더 안에 둔다.
- 학교알리미 원문은 `data/raw/schoolinfo/` 아래에 보존하고, 자동 추출·분류 결과는 `data/derived/` 아래에 둔다.
- 원문을 수정하거나 삭제하지 않는다. 재처리는 별도 파생 파일로 만들고 출처 경로와 상태를 남긴다.
- 일부 표본이나 모델 검토용 소수 건을 전국 전체 건수로 표현하지 않는다.
- 학교별 과목 미검출은 곧 미개설을 뜻하지 않는다. `미검출`, `추출 실패`, `교육과정 판별 유보`, `개설 여부 미확인`을 구분한다.
- 수집·추출 완료를 말하기 전 원문 수, 학교 수, JSONL 무결성, 성공·짧음·실패 수, 중복 수, 미확인 수를 대조한다.
- 수행평가 유형 분류는 열린 시드 목록이다(탐구, 문제해결, 프로젝트, 발표, 보고서, 포트폴리오, 토론, 제작, 실험, 생태조사). 실제 자료를 분석한 뒤 늘린다.
- 해부·채집·시약·동물윤리가 얽힌 사례는 차단·검토 큐를 만들지 않는다. 사례 카드와 상세에 `안전·윤리 주의` 표시만 남겨 교사가 판단하게 한다.
- 로컬 Python으로 가능한 수집·변환·정규화·집계는 모델 없이 처리한다. 모델은 우수 사례의 의미 판단과 수행평가 재설계 단계에서만 사용하며, 그 단계에 도달하면 사용자에게 모델 상향 필요를 알린다.
- 커밋·푸시·배포는 사용자의 별도 요청 없이는 하지 않는다.

# 새 작업 시작점

새 작업에서는 먼저 `README.md`의 현재 상태와
`data/derived/biology_assessment_final_pipeline.log.jsonl`을 확인한다. 완료 표식인
`data/derived/biology_assessment_final_pipeline_completion.json`이 없으면 파이프라인을
중복 실행하지 말고 기존 프로세스와 로그부터 확인한다.

발행 DB는 `services/biology-assessment-api/data/`의 gz 조각으로 저장소에 있고, 로컬에서는
`data/publish/biology_assessment_catalog_detail.sqlite`로 풀어 쓴다(README "로컬 실행과 검증").

- 원문 표는 세 층으로 본다(2026-10-30 kordoc 전환).
  1. 추출: `scripts/extract_kordoc_documents.py`가 `tools/kordoc/worker.mjs`(kordoc 버전 고정)로 원문을
     블록 구조(셀 격자·병합 칸·셀 속 표)로 읽어 `data/derived/kordoc/`에 저장한다. 표를 글로 뭉개지 않는다.
  2. 흐름: `scripts/kordoc_flow.py`가 틀 표를 풀고, 제목 상자를 제목으로, 칸 속 큰 표(루브릭)는
     바깥 표 뒤로 꺼내고, 작은 메뉴 표는 칸 글로, `□V`는 `☑`로 바꿔 파서 입력 텍스트를 만든다.
     파서에 들어가는 표에는 중첩 표가 없다. 규칙을 고치면 `test_kordoc_flow.py`에 실제 모양 테스트를 넣는다.
  3. 화면: `apps/biology-assessment-web/app/lib/source-html.ts`는 허용 목록 정화와 표시만 한다.
     행을 옮기거나 표를 합치는 DOM 수술을 다시 넣지 않는다. 표가 이상하면 1·2층을 고친다.
  `markdown_fragment_to_html`은 표를 하나씩 그대로 옮긴다(옛 표 융합 판정은 다음 과제 표를 앞 표에
  붙이는 오류를 내서 지웠다). 데이터 층을 고쳤으면 `scripts/refresh_biology_assessment_details.py
  --evidence-source data/derived/kordoc_evidence_source_2026_1.jsonl`로 상세 표만 다시 만들고
  `npm run audit:data`, `npm run audit:renderer`, `npm run package:vercel`, `npm run stage:vercel`
  순으로 배포 패키지를 갱신한다.
- 추출원을 바꾸거나 파서를 크게 고치면 `scripts/compare_extraction_sources.py`로 같은 파서·두 원문을
  전수 비교한다(항목 수 증감과 표 품질 지표). 줄어든 사례는 하나씩 열어 본다.
- 2학기(정시 3차) 원문 수집과 맥 추출 절차는 README "2학기 공시 갱신 절차"를 따른다.

# 파서 품질 작업 절차 (2026-09-15)

- 색인: `python scripts/index_evidence_source.py --evidence-source <6GB jsonl> --output data/derived/evidence_source_offsets.json`
  (한 번만). 이후 `scripts/case_text.py`·`scripts/dump_case_block.py <case_id>` 로 사례 원문을 즉시 연다.
- 재평가: `python scripts/evaluate_parser_sample.py --output data/derived/parser_eval_vN.jsonl`
  (7,211건 약 45분). 발행 DB 대비 사례별 확정 항목 수의 gain/loss 를 낸다. **loss 는 하나씩 열어 본다.**
- 양식 군집: `python scripts/profile_source_templates.py …` 로 표 구조 지문을 뽑고
  `python scripts/report_template_clusters.py --signatures … --evaluation …` 로 군집별 전후 실패율을 본다.
  교육청 이름이 아니라 구조 지문으로 나눈다. 같은 교육청 안에서도 학교가 손본 변형이 있다.
- 파서 변경은 반드시 `services/biology-assessment-api/tests/test_detail_parser.py` 에 실제 문서 모양의
  골든 테스트를 함께 넣는다.

