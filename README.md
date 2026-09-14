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
  (`https://suhaeng-biology.vercel.app`, 11,848개 공개 항목).
- 발행 DB는 `services/biology-assessment-api/data/*.sqlite.gz.part-*`로 저장소에 실려 있고,
  로컬 검증용 `data/publish/`는 gitignore다.
- 원문 수집·추출·분류 파이프라인(`scripts/`)은 2026-09-15부터 맥에서도 돈다.
  윈도우 전용 `kordoc` 대신 `scripts/extract_biology_candidate_text.py`가 HWP(pyhwp)·HWPX·PDF·ZIP을
  같은 JSONL 모양으로 뽑는다. 빠져 있던 `build_biology_extraction_retry_queue.py`,
  `validate_biology_assessment_catalog.py`, `collect_schoolinfo_4ga_historical.py`도 다시 썼다.
- 원문 첨부와 전체 본문 추출본(약 6GB)은 드라이브 공유 패키지 `학교알리미_원문추출본`에서
  `data/drive/학교알리미_원문추출본/`로 복사해 둔다(T7 SSD에만 있고 GitHub에는 없다).

## 2학기(정시 3차, 9월) 공시 갱신 절차

학교알리미 4-가는 정시 1차(4월, `JG_CHASU=1`)에 1학기분, 정시 3차(9월, `JG_CHASU=3`)에 2학기분이
올라온다. 3차 공시는 보통 9월 말에 게시된다(2025년은 9월 30일).

```bash
# 1) 공개됐는지 확인 (exit 0이면 공개, 2면 아직)
.venv/bin/python scripts/collect_schoolinfo_4ga_historical.py --check-only --school 천안쌍용고등학교 --year 2026 --chasu 3

# 2) 전국 수집 (약 2,370교, 0.8초 간격 → 1시간 안팎; 중단돼도 다시 실행하면 이어서 받는다)
.venv/bin/python scripts/collect_schoolinfo_4ga_historical.py --schools data/derived/schoolinfo_schools.csv \
  --year 2026 --chasu 3 --output-root data/raw/schoolinfo --log data/derived/schoolinfo_4ga_download_log_2026_3.csv

# 3) 매니페스트 → 본문 추출(HWP는 파일당 15초쯤 걸린다. --workers 4 권장)
.venv/bin/python scripts/build_biology_assessment_manifest.py --log data/derived/schoolinfo_4ga_download_log_2026_3.csv \
  --output data/derived/biology_assessment_source_manifest_2026_3.csv
.venv/bin/python scripts/extract_biology_candidate_text.py --manifest data/derived/biology_assessment_source_manifest_2026_3.csv \
  --output data/derived/biology_allplan_remaining_text_2026_3_0000.jsonl --workers 4

# 4) 이후는 기존 순서: 재시도 큐 → 근거 색인 → strict → 카탈로그 → 경향 → 검증 → 발행 DB
#    (run_final_biology_assessment_pipeline.py 의 단계와 같다)
```

파서만 바뀌었을 때는 전체를 다시 돌리지 않고 `scripts/refresh_biology_assessment_details.py`로
발행 DB의 상세 표(`assessment_items` 등)만 다시 만든다. `cases`와 `case_id`는 그대로 유지된다.

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
