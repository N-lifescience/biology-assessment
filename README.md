# 2026 생명과학 수행평가 아이디어 아카이브

2026학년도 학교알리미 교과별 교수·학습 및 평가계획 원문을 바탕으로
2015·2022 개정 생명과학 교과군의 수행평가명과 평가 구조를 확인하고,
다른 학교 사례에서 수업 아이디어를 찾도록 돕는 교사용 아카이브다.

`2026 수학 수행평가 아이디어 아카이브`를 같은 구조로 분기한 생명과학 판이다.
출발 코드 원본은 `docs/reference-math/07_사이트_출발코드/`에 읽기 전용으로 보존한다.

## 대상 교과군

- 2015 개정: 통합과학, 과학탐구실험, 생명과학Ⅰ, 생명과학Ⅱ
- 2022 개정: 통합과학1, 과학탐구실험1, 생명과학
- 전문교과: 생명과학실험, 고급생명과학
- 시범 과목: 생명과학Ⅰ / 생명과학1

## 현재 상태

- 웹 `apps/biology-assessment-web`과 API `services/biology-assessment-api`를
  생명과학 대상으로 리브랜딩 완료 (5개 화면 구조는 수학 판과 동일)
- 수집·추출·분류 파이프라인(`scripts/`)과 데이터는 아직 없다.
  API가 기대하는 발행 파일은 `data/publish/biology_assessment_catalog.sqlite`와
  `data/publish/biology_assessment_catalog_detail.sqlite`다.
- 데이터가 없으므로 화면의 수치 패널은 자리표시자(`—`)이고,
  발행 데이터에 의존하는 API 테스트는 현재 실패한다(각 파일 상단 TODO 참고).
- 다음 단계: 생명과학 평가계획 원문 수집 → 발행 DB 생성 → 화면 수치·테스트 기대값 확정

## 운영 배포

- 공개 예정 주소: `https://suhaeng-biology.vercel.app`
- Vercel 프로젝트: `suhaeng-biology`
- 아직 배포하지 않았다. 발행 DB가 생긴 뒤 `npm run deploy:prepare`로 준비한다.
- Vercel 전송 한도에 맞춘 운영 DB는 사례별 근거를 160자 미리보기로 제공하며,
  로컬 발행 DB의 긴 발췌와 학교알리미 원문은 그대로 보존한다.

작업 범위와 완료 판정 규칙은 [AGENTS.md](AGENTS.md)를 따른다.
제품의 전체 기능 범위와 개발 순서는
[2026 생명과학 수행평가 아이디어 아카이브 제품 범위](docs/BIOLOGY_ASSESSMENT_DESIGN_PRODUCT_SCOPE.md)에 정리한다.
출처 표시·원문 보존·비서열화 원칙은 [SOURCE_POLICY.md](docs/SOURCE_POLICY.md)를 따른다.

## 데이터 위치

- 원문: `data/raw/schoolinfo/`
- 파생 데이터와 검증 결과: `data/derived/`
- 서비스용 축약 DB와 품질 감사: `data/publish/`
- 수집·추출·분류 스크립트: `scripts/`

원문은 수정하거나 삭제하지 않는다. 파생 자료에는 원문 경로, 해시, 추출 상태,
교육과정·과목 판별 근거를 남긴다.

## 로컬 실행과 검증

의존성은 아직 설치하지 않았다. `pnpm-lock.yaml`은 수학 판에서 가져온 것이므로
첫 실행 전 `pnpm install`로 다시 생성한다.

```powershell
npm run dev
```

웹은 `http://127.0.0.1:3100`, API는 `http://127.0.0.1:8010`에서 실행된다.
테스트·코드 검사·프로덕션 빌드는 다음 명령으로 한 번에 확인한다.

```powershell
npm run verify
```

주요 화면은 다음과 같다.

- `http://127.0.0.1:3100/trends` — 교육과정·과목별 전국 경향
- `http://127.0.0.1:3100/cases` — 출처와 근거 발췌가 있는 사례
- `http://127.0.0.1:3100/review` — 동일 기준으로 사례를 읽고 기록하는 교사 검토함
- `http://127.0.0.1:3100/design` — 교사 조건 기반 설계 초안
- `http://127.0.0.1:3100/sources` — 데이터 출처와 해석 방법

## 파이프라인 완료 확인

```powershell
Get-Content -LiteralPath 'data\derived\biology_assessment_final_pipeline.log.jsonl' -Tail 30 -Encoding utf8
```

전체 완료 여부는 다음 두 파일의 존재와 검증 통과 결과를 함께 확인한다.

`data/derived/biology_assessment_final_pipeline_completion.json`

`data/derived/biology_assessment_catalog_validation_v2.json`

## 해석상 주의

- 표본이나 모델 검토용 일부 건수를 전국 자료의 총수로 표현하지 않는다.
- 평가계획에서 과목이 검출되지 않았다고 해서 해당 학교가 과목을 개설하지 않은
  것으로 판단하지 않는다.
- 현재 원문은 대부분 2026학년도 1학기이므로, 2025학년도 2015 개정 생명과학Ⅱ의
  전국 경향은 역사 자료를 추가 수집한 뒤 별도로 분석한다.
- 해부·채집·시약·동물윤리가 얽힌 사례는 별도 차단 시스템을 두지 않고,
  사례 카드·상세에 `안전·윤리 주의` 표시만 보여 교사가 판단하게 한다.
- 로컬 Python 추출·집계 단계는 낮은 모델로 진행할 수 있다. 의미 기반 우수 사례
  선별과 생명과학Ⅰ 재설계 단계에서는 모델 상향 여부를 사용자에게 먼저 알린다.

## 프로젝트 경계

생명과학 평가계획 작업의 기준 산출물은 `data/raw/schoolinfo/`, `data/derived/`,
`scripts/`, `AGENTS.md`이며, 수학 판(`docs/reference-math/`)이나 기존
`성취기준 기반 탐구주제 분석기` 프로젝트와 결과를 섞지 않는다.
`docs/reference-math/`는 참조 전용이며 수정하지 않는다.
