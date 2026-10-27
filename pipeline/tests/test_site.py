"""가짜 데이터로 정적 사이트를 띄워 화면이 깨지지 않는지 확인합니다 (Playwright 필요)."""
import functools
import http.server
import os
import shutil
import sys
import threading
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline"))
import breakdown  # noqa: E402
import briefing  # noqa: E402
import collect  # noqa: E402
import news  # noqa: E402
from fakes import fake_bis, fake_caps, fake_fred, fake_lme, fake_news, fake_prices, fake_yahoo  # noqa: E402


@pytest.fixture(scope="module")
def site_url(tmp_path_factory):
    www = tmp_path_factory.mktemp("www")
    shutil.copytree(ROOT / "site", www, dirs_exist_ok=True)
    real = os.environ.get("SITE_DATA_DIR")  # 실제 수집 결과로 확인할 때
    if real:
        shutil.copytree(real, www / "data", dirs_exist_ok=True)
    else:
        reg = collect.load_registry()
        latest, series = collect.collect(reg, fetch_fred=fake_fred, fetch_yahoo=fake_yahoo, fetch_lme=fake_lme, fetch_bis=fake_bis, log=lambda *_: None)
        collect.write_output(www / "data", reg, latest, series)
        news.build_notes(reg, www / "data", search=fake_news, load_previous=lambda *a: {}, sleep=0,
                         log=lambda *_: None)
        briefing.write(www / "data")
        breakdown.write(www / "data", fetch_fred=fake_fred, fetch_prices=fake_prices, fetch_caps=fake_caps,
                        log=lambda *_: None)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(www))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        yield b
        b.close()


@pytest.mark.parametrize("viewport,scheme", [({"width": 1280, "height": 900}, "light"),
                                             ({"width": 390, "height": 844}, "dark")])
def test_dashboard_renders(browser, site_url, viewport, scheme):
    page = browser.new_page(viewport=viewport, color_scheme=scheme)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    # 외부 웹폰트를 못 받는 환경(오프라인 CI 등)은 무시
    page.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text and errors.append(m.text))
    page.goto(site_url)
    page.wait_for_selector("#groups .ind")
    page.evaluate("localStorage.clear()")

    # 분야마다 그 분야 지표가 모두 나오는지 (경제지표는 카드, 나머지는 목록)
    counts = page.evaluate("""fetch('data/latest.json').then(r => r.json()).then(async d => {
        const reg = await fetch('data/indicators.json').then(r => r.json());
        const has = new Set(d.indicators.filter(i => i.last).map(i => i.id));
        const out = {};
        for (const i of reg.indicators) if (has.has(i.id)) out[i.group] = (out[i.group] || 0) + 1;
        return out;
    })""")
    for group, n in counts.items():
        assert page.locator(f"#g-{group} .ind").count() == n
        assert page.locator(f"#tabs [data-group={group}]").count() == 1
    assert page.locator("#g-macro .mcard").count() == counts["macro"]
    page.click("#tabs [data-group=rates]")
    assert "마지막 업데이트" in page.locator("#updated").inner_text()
    assert page.locator("#keys .keycard").count() >= 5
    assert page.locator("#curve-chart svg path").count() >= 3
    page.wait_for_selector("#briefing-block:not([hidden]) #briefing-headline")
    assert page.locator("#briefing-headline").inner_text()

    # 시장 지도: 트리맵과 기여도 목록
    if page.evaluate("fetch('data/breakdown/markets.json').then(r => r.ok)"):
        page.wait_for_selector("#map .tm-cell")
        assert page.locator("#map-market button").count() >= 2
        page.click("#map-period [data-period=m1]")
        cell = page.locator("#map .tm-cell").first
        cell.hover()
        assert page.locator("#map .tm-tip").is_visible()
        assert page.locator("#map-side .ms-row").count() >= 5
    # 가로 스크롤이 생기지 않아야 함
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

    # 기간 전환: 일별 지표는 1주 변화, 월별 지표는 1주 칸을 비움
    page.click("#period [data-period=w1]")
    assert page.locator("#groups .ind[data-id=cpi] .pill.na").count() == 1
    assert page.locator("#groups .ind[data-id=kospi] .pill:not(.na)").count() == 1
    page.click("#period [data-period=prev]")
    kospi = page.locator("#groups .ind[data-id=kospi]")

    # 검색으로 지표 열기
    page.keyboard.press("/")
    page.fill("#search-input", "코스닥")
    assert page.locator("#search-results .sr").count() >= 1
    page.keyboard.press("Enter")
    page.wait_for_selector("#detail[open] #detail-chart svg path")
    assert page.locator("#detail-title").inner_text() == "코스닥"
    page.click("#detail-close")

    # 상세 차트와 툴팁
    kospi.click()
    page.wait_for_selector("#detail-chart svg path")
    box = page.locator("#detail-chart svg").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    assert page.locator("#detail-chart .tip").is_visible()
    page.click("#ranges [data-range=all]")
    page.wait_for_selector("#detail-chart svg path")
    assert page.locator("#detail-table tbody tr").count() > 10
    page.click("#detail-close")

    # 전망치는 표에 표시하고 차트에서는 점선
    fed = page.locator("#groups .ind[data-id=fedfunds]")
    if "전망" in fed.inner_text():
        fed.click()
        page.wait_for_selector("#detail-chart path[stroke-dasharray]")
        page.click("#detail-close")

    # 날짜별 관련 뉴스가 있으면 툴팁과 목록에 표시
    page.locator("#keys .keycard[data-id=kospi]").click()
    page.wait_for_selector("#detail-chart svg path")
    page.click("#ranges [data-range='3m']")
    page.wait_for_selector("#detail-chart svg path")
    if page.locator("#detail-events .event-row").count():
        page.locator("#detail-chart svg").scroll_into_view_if_needed()
        box = page.locator("#detail-chart svg").bounding_box()
        page.mouse.move(box["x"] + box["width"] - 14, box["y"] + box["height"] / 2)
        assert page.locator("#detail-chart .tip .headlines li").count() >= 1
    page.click("#detail-close")

    # 분해 차트: 10년물(선), CPI(누적 막대)
    for ind_id in ("ust10y", "cpi"):
        if page.evaluate(f"fetch('data/breakdown/{ind_id}.json').then(r => r.ok)"):
            page.locator(f"#groups .ind[data-id={ind_id}]").click()
            page.wait_for_selector("#detail-breakdown:not([hidden]) .bd-chart svg")
            page.click("#detail-close")
    assert errors == []
