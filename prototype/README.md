# 프로토타입

[← README](../README.md) · [제안서](../docs/proposal.md)

제안서(1안)의 구조를 그대로 따르는 동작하는 프로토타입. **수집만 예시 데이터**이고, 그 뒤의 처리(중복 제거, 면 배치, 4상태 판정, 충돌 보존, 스냅샷 적재·비교)는 실제 로직이다.

## 실행

```bash
cd prototype
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload      # http://localhost:8000
pytest -q                          # 판정 규칙·추출·API 테스트
python scripts/build_static.py     # 서버 없이 여는 데모 → dist/demo.html
```

환경 변수: `SC_DB_PATH`(기본 `var/search_cosme.db`), `SC_FIXTURE_DELAY`(예시 수집 지연 배수, 기본 1).

## 제안서와 다른 점

| 제안서 (운영) | 프로토타입 | 바꿀 때 |
|---|---|---|
| 네이버쇼핑 API · 화해 실제 수집 | `FixtureAdapter` 가 `app/fixtures/products.json` 을 읽음 | 같은 `ChannelAdapter` 인터페이스로 실제 어댑터 구현. 화해는 법무 검토 후 |
| 비전 LLM 면 분류 | `FixtureFaceClassifier` (예시 데이터에 적힌 면) | `FaceClassifier` 구현 교체 |
| OCR 엔진 (게이트에서 3종 비교) | `FixtureOcr` (예시 데이터에 적힌 줄 + 신뢰도) | `OcrEngine` 구현 교체. 줄별 신뢰도 필수 |
| PostgreSQL · MinIO | SQLite, 이미지는 OCR 줄을 그린 SVG | `app/store.py` 교체 |
| Celery + Redis | 서버 프로세스 안의 asyncio 작업 | 워커 분리 |

## 예시 데이터로 보이는 상황

| 제품 | 보여주는 것 |
|---|---|
| 수분 장벽 크림 (용기형) | 채널 간 같은 사진 중복 제거, 전성분 **충돌**(후면 OCR ≠ 화해 상세 텍스트), 하면 미확보, 기능성 "없음", 8월 수집분과 비교 |
| 수분 장벽 크림 기획세트 | 같은 이름 제품이 둘 → **후보 선택 단계** |
| 데일리 선크림 (튜브) | 저해상도 후면 → **판독불가**, 전성분은 화해 상세 텍스트로 보완, 씰링부 LOT·EXP, 면 분류 신뢰도 낮은 사진은 미분류 |
| 진정 토너 | 화해 **수집 실패**(차단) → 해당 채널만 실패 표시, 나머지 결과는 정상 |

모든 브랜드·제품·URL은 가상이다.

## 구조

```
app/
  adapters/   base.py (인터페이스), fixture.py (예시 데이터 어댑터)
  pipeline/   collector.py (흐름), vision.py (면 분류·OCR 인터페이스),
              extract.py (항목 추출), judge.py (4상태 판정)
  rules/      ruleset.yaml (판정 기준, 코드와 분리)
  store.py    스냅샷 저장 (제안서 6절 스키마)
  views.py    API 응답 모양
  render.py   예시 이미지 SVG
  static/     화면 (조회부 / 진행부 / 결과부)
scripts/build_static.py   정적 데모 빌드
tests/                    판정 규칙 테스트 포함
```
