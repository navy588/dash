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
import collect  # noqa: E402
from fakes import fake_fred, fake_yahoo  # noqa: E402


@pytest.fixture(scope="module")
def site_url(tmp_path_factory):
    www = tmp_path_factory.mktemp("www")
    shutil.copytree(ROOT / "site", www, dirs_exist_ok=True)
    reg = collect.load_registry()
    latest, series = collect.collect(reg, fetch_fred=fake_fred, fetch_yahoo=fake_yahoo, log=lambda *_: None)
    collect.write_output(www / "data", reg, latest, series)
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
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.goto(site_url)
    page.wait_for_selector(".grid .tile")

    reg = collect.load_registry()
    assert page.locator(".grid .tile").count() == len(reg["indicators"])
    assert "갱신" in page.locator("#updated").inner_text()
    assert page.locator("#curve-chart svg path").count() >= 3
    # 가로 스크롤이 생기지 않아야 함
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

    # 기간 전환
    page.click("#period [data-period=ytd]")
    assert "연초 대비" in page.locator(".grid .tile .date").first.inner_text()

    # 상세 차트와 툴팁
    page.locator(".grid .tile").first.click()
    page.wait_for_selector("#detail-chart svg path")
    box = page.locator("#detail-chart svg").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    assert page.locator("#detail-chart .tip").is_visible()
    page.click("#ranges [data-range=all]")
    page.wait_for_selector("#detail-chart svg path")
    assert page.locator("#detail-table tbody tr").count() > 10
    page.click("#detail-close")
    assert errors == []
