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

- 웹 `apps/biology-assessment-web`과 API `services/biology-assessment-api`는 배포돼 있다
  (`https://suhaeng-biology.vercel.app`). 2026학년도 1학기(정시 1차) 7,211건과 2학기(정시 3차)
  2,135건, 사례 9,346건. 2026-10-31 파서 갱신본: 과제 확정 7,895건, 확정 수행평가 항목 22,882개
  (10-30 배포본 7,843건·23,459개에서 점수 칸·문서 구조 제목·지필고사·채점 질문과 중복 항목을 걷어내고,
  표지 표·숫자 표기로 과목 구간을 찾은 사례를 더했다).
- 발행 DB는 `services/biology-assessment-api/data/*.sqlite.gz.part-*`로 저장소에 실려 있고,
  로컬 검증용 `data/publish/`는 gitignore다.
- 원문 추출은 2026-10-30부터 [kordoc](https://github.com/chrisryugj/kordoc)(`tools/kordoc/`, 버전 고정)으로
  한다. HWP·HWPX·PDF·DOCX·XLSX와 ZIP 구성원을 표의 셀 격자(병합 칸·셀 속 표 포함) 그대로 읽어
  `data/derived/kordoc/`에 저장하고(`scripts/extract_kordoc_documents.py`), `scripts/kordoc_flow.py`가
  틀 표를 풀고 체크 표시(□V→☑)를 살려 파서 입력 텍스트를 만든다. 옛 추출(윈도우 `kordoc-fixed`,
  맥 pyhwp·pdfplumber)이 병합 칸을 한 칸에 뭉개고 체크 표시를 잃던 문제를 이 단계에서 없앴다.
  `scripts/extract_biology_candidate_text.py`는 kordoc를 쓸 수 없는 환경용 예비 추출기로만 남긴다.
- 원문 첨부와 전체 본문 추출본(약 6GB)은 드라이브 공유 패키지 `학교알리미_원문추출본`에서
  `data/drive/학교알리미_원문추출본/`로 복사해 둔다(T7 SSD에만 있고 GitHub에는 없다).

## 2학기(정시 3차, 9월) 공시 갱신 절차

학교알리미 4-가는 정시 1차(4월, `JG_CHASU=1`)에 1학기분, 정시 3차(9월, `JG_CHASU=3`)에 2학기분이
올라온다. 3차 공시는 보통 9월 말에 게시된다(2025년 9월 30일, 2026년은 10월 말 수집 때 이미 공개).
화면의 "학기" 필터와 배지는 본문 추정이 아니라 출처 주소의 `JG_CHASU`로 정한다.

```bash
# 1) 공개됐는지 확인 (exit 0이면 공개, 2면 아직)
.venv/bin/python scripts/collect_schoolinfo_4ga_historical.py --check-only --school 천안쌍용고등학교 --year 2026 --chasu 3

# 2) 전국 수집 (약 2,370교, 학교당 3~10초; 학교 목록을 나눠 수집기 2~3개로 돌리면 1~2시간)
.venv/bin/python scripts/collect_schoolinfo_4ga_historical.py --schools data/derived/schoolinfo_schools.csv \
  --year 2026 --chasu 3 --output-root data/raw/schoolinfo --log data/derived/schoolinfo_4ga_download_log_2026_3.csv

# 3) 매니페스트 → kordoc 변환 (다른 교과 전용 파일은 이름으로 건너뛴다)
.venv/bin/python scripts/build_biology_assessment_manifest.py --log <수집 로그> --output data/derived/2026_3/source_manifest.csv
.venv/bin/python scripts/extract_kordoc_documents.py --manifest data/derived/2026_3/source_manifest.csv \
  --output data/derived/2026_3/kordoc_evidence_source.jsonl --workers 9 --skip-other-departments

# 4) 증거 색인 → 엄격 후보 → 학교·과목 카탈로그 → 추세 → 2학기 발행 DB
#    (build_biology_assessment_evidence_index.py --input-jsonl …, build_strict_biology_shortlist.py,
#     build_school_subject_assessment_catalog.py, build_biology_assessment_trends.py,
#     build_biology_assessment_publish_db.py --evidence-source <색인 source.jsonl>)

# 5) 1학기 DB에 합치기 (같은 파일·같은 과목이 두 차수에 다시 올라온 사례는 뺀다)
.venv/bin/python scripts/merge_publish_dbs.py --base <1학기 상세 DB> --addition <2학기 상세 DB> --output <합친 DB>
```

파서만 바뀌었을 때는 전체를 다시 돌리지 않고 `scripts/refresh_biology_assessment_details.py`로
발행 DB의 상세 표(`assessment_items` 등)만 다시 만든다. `cases`와 `case_id`는 그대로 유지된다.
추출원이나 파서를 크게 바꿨으면 `scripts/compare_extraction_sources.py`로 옛 원문과 새 원문을 같은
파서로 전수 비교해 항목 수 증감과 표 품질(중첩 표·칸 어긋남·태그 노출)을 확인한다.

## 운영 배포

- 주소: `https://suhaeng-biology.vercel.app`
- Vercel 프로젝트: `suhaeng-biology`
- GitHub `master`에 푸시하면 Vercel이 배포한다. 발행 DB를 바꿨으면 `npm run deploy:prepare`
  (데이터 감사 → 렌더러 감사 → verify → package → stage)로 `services/biology-assessment-api/data/`의
  gz 조각을 갱신해 함께 커밋한다. 조각은 커밋마다 저장소를 약 60MB 키우므로 배포는 묶어서 한다.
- Vercel 전송 한도에 맞춘 운영 DB는 사례별 근거를 160자 미리보기로 제공하며,
  로컬 발행 DB의 긴 발췌와 학교알리미 원문은 그대로 보존한다.

작업 범위와 완료 판정 규칙은 [AGENTS.md](AGENTS.md)를 따른다.
제품의 전체 기능 범위와 개발 순서는
[2026 생명과학 수행평가 아이디어 아카이브 제품 범위](docs/BIOLOGY_ASSESSMENT_DESIGN_PRODUCT_SCOPE.md)에 정리한다.
출처 표시·원문 보존·비서열화 원칙은 [SOURCE_POLICY.md](docs/SOURCE_POLICY.md)를 따른다.

## 데이터 위치

- 원문: `data/raw/schoolinfo/` (새로 수집한 것), `data/drive/학교알리미_원문추출본/` (드라이브 패키지 사본)
- 파생 데이터와 검증 결과: `data/derived/`
- 서비스용 축약 DB와 품질 감사: `data/publish/`
- 수집·추출·분류 스크립트: `scripts/`

원문은 수정하거나 삭제하지 않는다. 파생 자료에는 원문 경로, 해시, 추출 상태,
교육과정·과목 판별 근거를 남긴다.

## 로컬 실행과 검증

맥 기준: Python 3.12(`brew install python@3.12`), pnpm 11(`npm i -g pnpm`), Node 24 이상.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r services/biology-assessment-api/requirements.txt -r services/biology-assessment-api/requirements-dev.txt
.venv/bin/pip install pyhwp six olefile docopt pdfplumber openpyxl python-docx   # 원문 추출용
pnpm install --frozen-lockfile
npm run dev
```

웹은 `http://127.0.0.1:3100`, API는 `http://127.0.0.1:8010`에서 실행된다.
API 테스트는 `data/publish/biology_assessment_catalog_detail.sqlite`(와 같은 내용의
`biology_assessment_catalog.sqlite`)가 있어야 한다. 배포 패키지에서 풀어 두면 된다.

```bash
cat services/biology-assessment-api/data/biology_assessment_catalog_detail.sqlite.gz.part-* | gunzip > data/publish/biology_assessment_catalog_detail.sqlite
cp data/publish/biology_assessment_catalog_detail.sqlite data/publish/biology_assessment_catalog.sqlite
```

테스트·코드 검사·프로덕션 빌드는 다음 명령으로 한 번에 확인한다.

```bash
npm run verify
```

주요 화면은 다음과 같다.

- `http://127.0.0.1:3100/trends` — 교육과정·과목별 전국 경향
- `http://127.0.0.1:3100/cases` — 출처와 근거 발췌가 있는 사례
- `http://127.0.0.1:3100/review` — 동일 기준으로 사례를 읽고 기록하는 교사 검토함
- `http://127.0.0.1:3100/design` — 교사 조건 기반 설계 초안
- `http://127.0.0.1:3100/sources` — 데이터 출처와 해석 방법

## 파이프라인 완료 확인

```bash
tail -n 30 data/derived/biology_assessment_final_pipeline.log.jsonl
```

전체 완료 여부는 다음 두 파일의 존재와 검증 통과 결과를 함께 확인한다.

`data/derived/biology_assessment_final_pipeline_completion.json`

`data/derived/biology_assessment_catalog_validation_v2.json`

## 해석상 주의

- 표본이나 모델 검토용 일부 건수를 전국 자료의 총수로 표현하지 않는다.
- 평가계획에서 과목이 검출되지 않았다고 해서 해당 학교가 과목을 개설하지 않은
  것으로 판단하지 않는다.
- 원문은 2026학년도 1·2학기 공시분이다. 2025학년도 2015 개정 생명과학Ⅱ의
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
