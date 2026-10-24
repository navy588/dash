# 글로벌 경제 데일리

주요 주가지수·환율·금리·원자재와 미국 거시지표를 매일 자동으로 모아 정적 웹페이지로 보여 줍니다.
서버도 API 키도 필요 없고, GitHub Actions가 수집부터 배포까지 전부 처리합니다.

**주소:** https://navy588.github.io/dash/

## 화면

- **오늘의 브리핑:** 큰 움직임과 분야별 대표 지표를 한국어 문장으로 요약합니다. `data/briefing.md`(마크다운)로도 받을 수 있습니다.
- **오늘의 큰 움직임:** 직전 대비 변화가 최근 1년 평균 변동폭(표준편차)의 2배를 넘은 지표만 모아 보여 줍니다.
- **분야별 카드:** 한국, 미국 주식, 글로벌 주식, 환율, 금리, 원자재·코인, 미국 거시지표. 직전·1주·1개월·연초·1년 대비 변화를 고를 수 있습니다.
  상승은 빨강 ▲, 하락은 파랑 ▼이고, 카드마다 기준일을 표시합니다.
- **상세 차트:** 카드를 누르면 3개월부터 전체 기간까지의 차트와 표가 열립니다.
- **미국 국채 금리 커브:** 현재, 1개월 전, 1년 전 비교.

## 구조

```
pipeline/indicators.json   지표 정의 (이름·그룹·출처·코드·단위·변화 표시 방식) — 지표 추가/삭제는 여기만 고치면 됩니다
pipeline/collect.py        수집 → site/data/*.json 생성
pipeline/briefing.py       latest.json → 한국어 일일 브리핑 (data/briefing.json, briefing.md)
pipeline/health.py         연속 실패 지표 판별 (알림용)
pipeline/tests/            단위 테스트, 가짜 데이터로 화면을 띄우는 브라우저 테스트
site/                      정적 페이지 (HTML·CSS·JS, 외부 라이브러리 없음)
.github/workflows/daily.yml  테스트 → 수집 → GitHub Pages 배포 → 상태 알림
legacy/                    이전 Dash 대시보드 (참고용, 실행되지 않음)
```

### 자동화 흐름 (`Daily Update` 워크플로)

1. 매일 07:00(미국장 마감 후)과 16:30(한국장 마감 후, 한국시간)에 실행됩니다.
2. 테스트를 통과하면 FRED와 Yahoo Finance에서 데이터를 받아 JSON을 만듭니다.
3. 받지 못한 지표는 직전 배포본의 데이터를 그대로 쓰고 화면에 "이전 데이터"로 표시합니다.
4. GitHub Pages에 배포합니다. 데이터는 저장소에 커밋하지 않으므로 저장소 용량이 늘지 않습니다.
5. 같은 지표가 두 번 연속 실패하면 `data-health` 라벨의 이슈를 열고(메일 알림), 복구되면 자동으로 닫습니다.
   워크플로 자체가 실패하면 GitHub가 저장소 소유자에게 메일을 보냅니다.

PR에서는 테스트와 실제 수집까지만 하고 배포하지 않습니다. 결과물은 실행 화면의 `site-preview` 아티팩트로 받아 볼 수 있습니다.

### 데이터 형식

- `data/latest.json`: `generated_at`, `counts`(ok/stale/missing), `indicators[]`(`id`, `status`, `last`, `changes.{prev,w1,m1,ytd,y1}`, `sigma`, `spark`), `curve[]`
- `data/series/<id>.json`: `{ "id", "dates": [...], "values": [...] }`
- `data/indicators.json`: 지표 정의 사본
- `data/briefing.json`: `as_of`, `headline`, `highlights[]`(`id`, `text`), `sections[]`(`group`, `name`, `text`), `stale[]` / `data/briefing.md`: 같은 마크다운

## 처음 한 번만 할 일

저장소 **Settings → Pages → Build and deployment → Source** 를 **GitHub Actions** 로 바꿉니다.
그다음 **Actions → Daily Update → Run workflow** 를 한 번 실행하면 위 주소에 페이지가 열립니다.

API 키는 필요 없습니다. FRED 키가 있다면 `FRED_API_KEY` Secret으로 넣을 수 있고, 그러면 공식 API를 씁니다(선택).

## 로컬 실행

```bash
pip install -r pipeline/requirements.txt -r pipeline/requirements-dev.txt
python pipeline/collect.py --out site/data        # 실제 데이터 수집
# 또는 네트워크 없이: python pipeline/tests/make_fixture.py site/data
python -m http.server -d site 8000                # http://localhost:8000
python -m playwright install chromium && python -m pytest -q pipeline/tests
```

시세는 지연되거나 수정될 수 있으며 투자 판단의 근거로 쓰기 위한 자료가 아닙니다.
