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
import briefing  # noqa: E402
import collect  # noqa: E402
import news  # noqa: E402
from fakes import fake_bis, fake_fred, fake_lme, fake_news, fake_yahoo  # noqa: E402


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
    page.wait_for_selector("#groups .lrow")
    page.evaluate("localStorage.clear()")

    # 분야 탭마다 그 분야 지표가 모두 나오는지
    counts = page.evaluate("""fetch('data/latest.json').then(r => r.json()).then(async d => {
        const reg = await fetch('data/indicators.json').then(r => r.json());
        const has = new Set(d.indicators.filter(i => i.last).map(i => i.id));
        const out = {};
        for (const i of reg.indicators) if (has.has(i.id)) out[i.group] = (out[i.group] || 0) + 1;
        return out;
    })""")
    for group, n in counts.items():
        page.click(f"#tabs [data-group={group}]")
        assert page.locator("#groups .lrow").count() == n
    assert "마지막 업데이트" in page.locator("#updated").inner_text()
    assert page.locator("#keys .keycard").count() >= 5
    assert page.locator("#curve-chart svg path").count() >= 3
    page.wait_for_selector("#briefing-block:not([hidden]) #briefing-headline")
    assert page.locator("#briefing-headline").inner_text()
    # 가로 스크롤이 생기지 않아야 함
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

    # 기간 전환: 일별 지표는 1주 변화, 월별 지표는 1주 칸을 비움
    page.click("#tabs [data-group=macro]")
    page.click("#period [data-period=w1]")
    assert page.locator("#groups .lrow[data-id=cpi] .pill.na").count() == 1
    page.click("#tabs [data-group=korea]")
    assert page.locator("#groups .lrow[data-id=kospi] .pill:not(.na)").count() == 1
    page.click("#period [data-period=prev]")
    kospi = page.locator("#groups .lrow[data-id=kospi]")

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
    page.click("#tabs [data-group=rates]")
    fed = page.locator("#groups .lrow[data-id=fedfunds]")
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
        box = page.locator("#detail-chart svg").bounding_box()
        page.mouse.move(box["x"] + box["width"] - 14, box["y"] + box["height"] / 2)
        assert page.locator("#detail-chart .tip .headlines li").count() >= 1
    page.click("#detail-close")
    assert errors == []
