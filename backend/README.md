# 백엔드 — 실제 작동 시스템

[← README](../README.md) · [기획안](../docs/plan.md) · [제안서](../docs/proposal.md) · [룰셋](../docs/ruleset.md)

기획안 5절 아키텍처를 그대로 구현한 운영용 코드. `prototype/` 은 예시 데이터 데모로 남겨 둔다.

```
제품명 조회 ─┬─ 등록된 제품
             └─ 네이버쇼핑 API 후보 ──▶ 제품 선택·등록
                                          │  자료 연결: 화해·자사몰 URL / 사내 사진 업로드
                                          ▼
          [api] 수집·판정 요청 ──▶ [redis 큐] ──▶ [worker]
                                                  ├ 채널 수집 (사내 업로드 → T1 → T2·T4 동시)
                                                  ├ 해시 중복 제거 · 이미지 저장 (MinIO/로컬)
                                                  ├ 상세페이지 통이미지 컷 분할
                                                  ├ OCR (줄별 신뢰도)
                                                  ├ 면 분류
                                                  ├ 룰셋 4상태 판정 · 충돌 보존
                                                  └ 스냅샷 저장 (PostgreSQL)
          [화면] 진행 상태(SSE) · 면별 확보 · 체크리스트 · 수집일 비교
```

## 실행

**로컬 개발** (SQLite, 로컬 이미지 폴더, 작업은 API 프로세스 안에서)

```bash
sudo apt install tesseract-ocr tesseract-ocr-kor      # Mac: brew install tesseract tesseract-lang
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn searchcosme.api:app --reload                  # http://localhost:8000
pytest -q
```

**사내 서버 배포** (PostgreSQL + Redis + Celery 워커 + MinIO)

```bash
cd backend
cp .env.example .env        # 비밀번호·API 키 채우기
docker compose up -d --build
```

## 채널

| 티어 | 채널 | 방식 | 기본값 | 상태 |
|---|---|---|---|---|
| 0 | 사내 업로드 | 화면에서 실물·샘플·도면 사진 + 상세 텍스트 업로드, 면 지정 가능 | 켜짐 | 동작 확인 |
| 1 | 네이버쇼핑 | 공식 검색 API. 후보 검색 + 대표 이미지(전면) | 키 있으면 켜짐 | 요청·응답 처리는 모의 응답으로 검증. **실제 키로는 미검증** |
| 2 | 화해 | 등록한 상품 URL만 연다. robots.txt 준수 | **꺼짐** | 아래 참고 |
| 4 | 브랜드 자사몰 | 등록한 URL을 범용 파서(JSON-LD·OG·내장 JSON·본문)로 읽음 | 켜짐 | 모의 페이지로 검증 |

### 화해를 기본으로 끈 이유

- robots.txt 가 `/api/`, `/product-search`, `/goods-view`, `/product-information` 수집을 금지한다. 제품명 검색을 자동으로 할 수 없다.
- 상품 sitemap 요청에 CloudFront `403 Request blocked` 를 돌려준다. 자동 접근을 막고 있다.
- 이 시스템은 차단을 우회하지 않는다 (브라우저 위장 없음, 차단 응답은 재시도 없이 '수집 실패').

화해 데이터가 필요하면 **제휴·허가**를 받은 뒤 `SC_ENABLE_HWAHAE=1` 로 켠다. 그 전에는 사내 업로드의 상세 텍스트 칸에 전성분 원문을 넣어 같은 효과를 낼 수 있다.

## 판독 엔진

| 단계 | 기본 | 선택 | 비고 |
|---|---|---|---|
| OCR | Tesseract 5 (kor+eng, 사내 구동) | CLOVA OCR, Google Vision | 줄별 신뢰도 필수. 응답 파서는 표본 JSON으로 검증, 실제 API는 미검증 |
| 면 분류 | 규칙 기반 (OCR 텍스트·비율) | Claude 비전 (`SC_FACE_CLASSIFIER=claude`) | Claude 는 `claude-opus-5-5`, 구조화 출력, 거절 시 자동 대체 모델. 실패하면 규칙 기반으로 돌아감 |

Tesseract 실측 (합성 라벨): 선명한 후면 줄 신뢰도 0.82~0.97, 흐린 저해상도 후면 0.22~0.43. 그래서 Tesseract 판독 기준을 0.70 으로 두었다 (`rules/ruleset.yaml` 의 `ocr_line_conf_by_engine`). **검증 게이트에서 실제 사진 40개로 다시 보정한다.**

## 설정

`.env.example` 참고. 주요 값:

| 변수 | 기본 | 설명 |
|---|---|---|
| `SC_DATABASE_URL` | `sqlite:///var/searchcosme.db` | 운영은 `postgresql+psycopg://...` |
| `SC_QUEUE` | `inline` | `celery` 면 Redis 큐 + 별도 워커 |
| `SC_STORAGE` | `local` | `s3` 면 MinIO 등 S3 호환 |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | — | 네이버 검색 API |
| `SC_ENABLE_HWAHAE` | `0` | 제휴·허가 후에만 `1` |
| `SC_OCR_ENGINE` | `tesseract` | `clova` / `google` |
| `SC_FACE_CLASSIFIER` | `heuristic` | `claude` (외부 전송 발생 → 사내 승인 후) |

## 검증한 것 / 못 한 것

| 항목 | 결과 |
|---|---|
| 테스트 38개 (판정 규칙, 실제 OCR, 통이미지 분할, 어댑터, Claude 응답 처리, 저장소, API 전체 흐름) | 통과 |
| PostgreSQL 16 + Redis + Celery 워커 + 실제 OCR 로 전체 흐름 | 동작 (조회 1건 약 2.3초) |
| 브라우저 화면 (검색 → 제품 → 수집 → 결과 → 비교) | 동작, 콘솔 오류 없음 |
| MinIO 실물 | 미검증 (S3 모의로만 확인) |
| `docker compose up` | 미검증 (이 개발 환경에 Docker 데몬 없음). 설정 파일 문법만 확인 |
| 네이버·CLOVA·Google·Claude 실제 호출 | 미검증 (키 없음) |
| 실제 상품 사진 판독률 | 미측정 → 검증 게이트 |

## 구조

```
searchcosme/
  api.py          HTTP API + 화면 제공
  pipeline.py     수집 → 정리 → OCR → 분류 → 판정 → 스냅샷
  tasks.py        Celery 작업 / inline 실행
  adapters/       naver.py · webpage.py(화해·자사몰) · upload.py · registry.py
  vision/         images.py(해시·분할) · ocr.py · classify.py
  rules/          ruleset.yaml · extract.py · judge.py
  models.py       DB 스키마 (제안서 6절)
  storage.py      로컬 / S3(MinIO)
  http.py         봇 UA · robots.txt · 호스트별 호출 간격 · 차단 시 재시도 안 함
  static/         화면
tests/
```

DB 스키마는 시작할 때 없는 테이블만 만든다. 운영 중 스키마를 바꾸게 되면 Alembic 마이그레이션을 붙인다.
