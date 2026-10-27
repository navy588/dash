# 글로벌 경제 데일리

주요 주가지수·환율·금리·원자재와 미국 거시지표를 매일 자동으로 모아 정적 웹페이지로 보여 줍니다.
서버도 API 키도 필요 없고, GitHub Actions가 수집부터 배포까지 전부 처리합니다.

**주소:** https://navy588.github.io/dash/

## 화면

- **업데이트 시각과 검색:** 맨 위에 마지막·다음 업데이트 시각(한국시간)과 지표 검색(`/` 또는 Ctrl/⌘+K)이 있습니다.
- **오늘의 시장:** 헤드라인, 시장 해석(위험선호/회피, 국채 커브 모양, 유가와 금리), 크게 움직인 지표 카드(값·변동률·추세·대표 뉴스 '왜?').
  카드는 '평소 대비 배수 × 중요도' 순으로 고릅니다(경제 > 원자재 > 시장, `pipeline/briefing.py`의 `IMPORTANCE`).
- **주요 지표:** 코스피·원/달러·S&P 500·나스닥·미 국채 10년·WTI·금·비트코인. 최근 3개월 흐름과 최고·최저값.
- **시장 지도:** S&P 500·나스닥 100·코스피·코스닥 시가총액 상위 종목 트리맵. 상자 크기는 시가총액 비중, 색은 등락(하루·1주·1개월·연초·1년).
  옆에 지수를 끌어올린/끌어내린 종목(비중 × 등락률)과 업종별 가중 등락을 보여 줍니다. 종목 목록은 `pipeline/constituents.json`.
- **분야별 시세:** 미국 경제, 한국 경제, 원자재·코인, 한국 주식, 미국 주식, 글로벌 주식, 환율, 금리 순서로 한 화면에 이어서 보여 주고,
  위쪽 탭으로 바로 이동합니다. 경제지표는 최근 발표치 막대 카드, 나머지는 추세선이 있는 목록입니다. 직전·1주·1개월·연초·1년 중 기간을 골라 변동률을 봅니다.
- **원자재 순서:** WTI, 유럽 천연가스(TTF, $/MMBtu), 철광석, 구리, 알루미늄, 니켈(LME), 아시아 LNG(JKM), 브렌트, 미국 천연가스, 금, 은, 비트코인.
- **상세 화면:** 큰 차트(기간 내 최고·최저 표시), 기간별 변화, 1년 범위, 날짜별 "왜 움직였나" 뉴스, 표 보기.
  지수는 구성종목 지도, 미 국채 10년물은 금리 분해(기대 단기금리 경로 + 기간 프리미엄 · 실질금리 + 기대인플레이션),
  미국 CPI는 항목별 기여도, 미국 GDP는 지출 항목별 기여도를 함께 보여 줍니다.
- **뉴스 매칭:** 지표마다 `indicators.json`의 `match`(모든 묶음에서 한 단어 이상)와 `exclude`(다른 나라 등)로 제목을 거릅니다.
  월별·분기 지표는 실제 발표 시기의 기사 중 '9월', '3분기'처럼 기준 기간이 제목에 있는 것만 씁니다.
- **전망치:** 기준금리·실업률·근원 PCE는 FOMC 점도표 중간값, 실질 GDP는 애틀랜타 연은 GDPNow를 점선으로 이어 그립니다.

## 구조

```
pipeline/indicators.json   지표 정의 (이름·그룹·출처·코드·단위·변화 표시 방식) — 지표 추가/삭제는 여기만 고치면 됩니다
pipeline/collect.py        수집 → site/data/*.json 생성
pipeline/news.py           지표·날짜별 관련 뉴스 헤드라인 (Google 뉴스 RSS, 키 불필요)
pipeline/briefing.py       latest.json·series·notes → 한국어 일일 브리핑 (data/briefing.json, briefing.md)
pipeline/breakdown.py      시장 지도(구성종목 등락·시총)와 분해 차트(10년물·CPI·GDP) → data/breakdown/
pipeline/constituents.json 지수별 시가총액 상위 종목 목록
pipeline/health.py         연속 실패 지표 판별 (알림용)
pipeline/tests/            단위 테스트, 가짜 데이터로 화면을 띄우는 브라우저 테스트
site/                      정적 페이지 (HTML·CSS·JS, 외부 라이브러리 없음)
.github/workflows/daily.yml  테스트 → 수집 → GitHub Pages 배포 → 상태 알림
legacy/                    이전 Dash 대시보드 (참고용, 실행되지 않음)
```

### 자동화 흐름 (`Daily Update` 워크플로)

1. 매일 07:00(미국장 마감 후)과 16:30(한국장 마감 후, 한국시간)에 실행됩니다.
2. 테스트를 통과하면 FRED, Yahoo Finance, LME(westmetall.com)에서 데이터를 받아 JSON을 만듭니다.
   이어서 모든 지표의 최근 1년 날짜마다 관련 뉴스를 붙입니다. 오늘 치를 먼저 채우고, 한 번에 400건까지만 검색해
   지난 1년치는 몇 주에 걸쳐 거슬러 올라가며 채워집니다(이미 찾은 날짜는 다시 검색하지 않음).
3. 받지 못한 지표는 직전 배포본의 데이터를 그대로 쓰고 화면에 "이전 데이터"로 표시합니다.
4. GitHub Pages에 배포합니다. 데이터는 저장소에 커밋하지 않으므로 저장소 용량이 늘지 않습니다.
5. 같은 지표가 두 번 연속 실패하면 `data-health` 라벨의 이슈를 열고(메일 알림), 복구되면 자동으로 닫습니다.
   워크플로 자체가 실패하면 GitHub가 저장소 소유자에게 메일을 보냅니다.

PR에서는 테스트와 실제 수집까지만 하고 배포하지 않습니다. 결과물은 실행 화면의 `site-preview` 아티팩트로 받아 볼 수 있습니다.

### 데이터 형식

- `data/latest.json`: `generated_at`, `counts`(ok/stale/missing), `indicators[]`(`id`, `status`, `last`, `changes.{prev,w1,m1,ytd,y1}`, `sigma`, `spark`), `curve[]`
- `data/series/<id>.json`: `{ "id", "dates": [...], "values": [...] }`
- `data/indicators.json`: 지표 정의 사본
- `data/notes/<id>.json`: `{ "id", "query", "events": [{ "date", "change", "sigma", "headlines": [{ "title", "url", "source", "published" }] }] }`
- 전망치가 있는 지표는 `latest.json`의 `forecast: { label, points: [{ date, value }] }`
- `data/breakdown/markets.json`: `markets[]`(`id`, `name`, `as_of`, `items[]`: `t` 티커, `n` 이름, `s` 업종, `cap` 시총, `w` 비중%, `price`, `chg.{prev,w1,m1,ytd,y1}`)
- `data/breakdown/<id>.json`: `charts[]`(`title`, `kind` lines|stack, `dates`, `total`, `parts[]`) / `index.json`: 분해 차트가 있는 지표 id
- `data/briefing.json`: `as_of`, `headline`, `mood`, `stories[]`(`id`, `big`, `text`, `headlines[]`), `reads[]`, `signals[]`, `stale[]` / `data/briefing.md`: 같은 마크다운

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
