# 글로벌 경제 데일리

주요 주가지수·환율·금리·원자재와 미국 거시지표를 매일 자동으로 모아 정적 웹페이지로 보여 줍니다.
서버도 API 키도 필요 없고, GitHub Actions가 수집부터 배포까지 전부 처리합니다.

**주소:** https://navy588.github.io/dash/

## 화면

- **업데이트 시각:** 맨 위에 마지막 업데이트 시각과 다음 업데이트 시각(한국시간)을 표시합니다.
- **오늘의 브리핑:** AI 없이 규칙으로 해석합니다. 평소보다 크게 움직인 지표와 그날 뉴스 헤드라인(무엇이 왜 움직였나), 위험선호/위험회피 판정·미 국채 커브 모양(불·베어 스티프닝/플래트닝)·유가와 금리 조합(시장 해석), 52주 신고가·신저가·연속 상승/하락·연초 대비 최고/최저 자산·전망치 대비 실제치(눈여겨볼 점). `data/briefing.md`로도 받을 수 있습니다.
- **오늘의 시장:** 맨 위 카드에 오늘의 헤드라인, 시장 해석, 크게 움직인 지표 카드(값·변동률·추세 차트·대표 뉴스 '왜?')를 보여 줍니다.
- **주요 지표:** 코스피·원/달러·S&P 500·나스닥·미 국채 10년·WTI·금·비트코인 카드.
- **분야별 시세:** 미국 거시지표, 한국, 미국 주식, 글로벌 주식, 환율, 금리, 원자재·코인을 탭으로 나누고, 직전·1주·1개월·연초·1년 중 기간을 골라 변동률을 봅니다.
  월간·분기 지표는 발표 주기보다 짧은 기간을 비우고 발표월과 전망치를 이름 아래 적습니다. 평소보다 크게(2배 이상) 움직인 지표에는 '평소 N배' 표시가 붙습니다.
  상승은 빨강, 하락은 파랑이며 추세선 색은 최근 3개월 방향을 따릅니다. 오른쪽(모바일은 아래)에 눈여겨볼 점과 미 국채 금리 커브가 있습니다.
- **원자재:** WTI, 유럽 천연가스(TTF, 유로/달러로 환산한 $/MMBtu), 아시아 LNG(JKM, $/MMBtu), 구리·알루미늄·니켈(LME 현금 결제가, $/t), 브렌트, 미국 천연가스, 금, 은, 비트코인 순서입니다.
- **전망치:** 기준금리·실업률·근원 PCE는 FOMC 점도표 중간값, 실질 GDP는 애틀랜타 연은 GDPNow를 차트에 점선으로 이어 그립니다.
- **상세 차트와 "왜 움직였나":** 지표를 누르면 상세 차트가 열립니다(모바일은 아래에서 올라오는 시트). 차트의 각 날짜에 커서를 대면 그날의 변화와 관련 뉴스 헤드라인이 보이고,
  평소보다 크게(2배 이상) 움직인 날은 점으로 표시됩니다. 아래에는 날짜별 변화와 뉴스 링크 목록이 있습니다.
- **미국 국채 금리 커브:** 현재, 1개월 전, 1년 전 비교.

## 구조

```
pipeline/indicators.json   지표 정의 (이름·그룹·출처·코드·단위·변화 표시 방식) — 지표 추가/삭제는 여기만 고치면 됩니다
pipeline/collect.py        수집 → site/data/*.json 생성
pipeline/news.py           지표·날짜별 관련 뉴스 헤드라인 (Google 뉴스 RSS, 키 불필요)
pipeline/briefing.py       latest.json·series·notes → 한국어 일일 브리핑 (data/briefing.json, briefing.md)
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
