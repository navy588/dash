import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect  # noqa: E402
import news  # noqa: E402
from fakes import fake_bis, fake_fred, fake_lme, fake_news, fake_yahoo  # noqa: E402

REG = collect.load_registry()


def test_find_events_covers_every_day_with_sigma():
    idx = pd.bdate_range("2025-01-01", "2026-10-23")
    vals = 100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.005, len(idx))))
    s = pd.Series(vals, index=idx)
    s.loc["2026-06-15":] *= 1.06  # 6% 급등
    events = news.find_events(s, {"freq": "daily", "change": "pct"})
    days = [d for d, *_ in events]
    assert days[-1] == pd.Timestamp("2026-10-23")
    assert len(days) == len([d for d in idx if d > pd.Timestamp("2026-10-23") - pd.Timedelta(days=366)])
    jump = dict((d, (ch, sg)) for d, ch, sg in events)[pd.Timestamp("2026-06-15")]
    assert jump[0] > 5 and jump[1] > 5
    monthly = pd.Series(range(30), index=pd.date_range("2024-05-01", periods=30, freq="MS"), dtype=float)
    assert len(news.find_events(monthly, {"freq": "monthly", "change": "pp"})) == 13


def test_parse_rss_strips_source():
    xml = """<rss><channel><item><title>코스피 2% 급락… 외국인 매도 - 한국경제</title>
    <link>https://news.example/a</link><pubDate>Thu, 23 Oct 2026 07:00:00 GMT</pubDate>
    <source url="https://hankyung.com">한국경제</source></item></channel></rss>"""
    [h] = news.parse_rss(xml)
    assert h == {"title": "코스피 2% 급락… 외국인 매도", "url": "https://news.example/a",
                 "source": "한국경제", "published": "2026-10-23"}
    assert news.clean_title("[뉴욕채권] 국채가 하락…유가 급등 |") == "[뉴욕채권] 국채가 하락…유가 급등"


def test_build_notes_reuses_previous(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "MAX_QUERIES_PER_RUN", 10**6)
    latest, series = collect.collect(REG, fetch_fred=fake_fred, fetch_yahoo=fake_yahoo, fetch_lme=fake_lme, fetch_bis=fake_bis,
                                     log=lambda *_: None)
    collect.write_output(tmp_path, REG, latest, series)
    calls = []

    def search(q, start, end, session=None):
        calls.append((q, start))
        return fake_news(q, start, end)

    news.build_notes(REG, tmp_path, search=search, load_previous=lambda *a: {}, sleep=0, log=lambda *_: None)
    first = len(calls)
    assert first > 0
    # 최신 날짜부터 검색
    assert calls[0][1] >= pd.Timestamp("2026-10-21")
    note = json.loads((tmp_path / "notes" / "kospi.json").read_text(encoding="utf-8"))
    assert note["query"] == "코스피"
    prev = {i["id"]: json.loads((tmp_path / "notes" / f"{i['id']}.json").read_text(encoding="utf-8"))
            for i in REG["indicators"] if (tmp_path / "notes" / f"{i['id']}.json").exists()}
    calls.clear()
    news.build_notes(REG, tmp_path, search=search, load_previous=lambda url, ind_id, s: prev.get(ind_id, {}),
                     sleep=0, log=lambda *_: None, today="2026-12-31")
    assert calls == []  # 모두 재사용

    # 규칙이 바뀐 옛 배포본: 일별 지표는 맞는 헤드라인만 남기고, 월별 지표는 다시 검색
    old = {k: {**v, "rules": 1} for k, v in prev.items()}
    old["kospi"]["events"][-1]["headlines"] = [{"title": "중국 증시 급락", "url": "u", "source": "s"}]
    news.build_notes(REG, tmp_path, search=search, load_previous=lambda url, ind_id, s: old.get(ind_id, {}),
                     sleep=0, log=lambda *_: None, today="2026-12-31")
    searched = {q.split(" ")[0] for q, _ in calls}
    assert "코스피" in searched and "미국" in searched
    assert sum(q == "코스피" for q, _ in calls) == 1


def test_search_failure_does_not_stop(tmp_path):
    latest, series = collect.collect(REG, fetch_fred=fake_fred, fetch_yahoo=fake_yahoo, fetch_lme=fake_lme, fetch_bis=fake_bis,
                                     log=lambda *_: None)
    collect.write_output(tmp_path, REG, latest, series)

    def boom(*a, **k):
        raise RuntimeError("429")

    stats = news.build_notes(REG, tmp_path, search=boom, load_previous=lambda *a: {}, sleep=0, log=lambda *_: None)
    assert stats["failed"] > 0 and stats["searched"] == 0


def test_budget_fills_latest_first(tmp_path, monkeypatch):
    latest, series = collect.collect(REG, fetch_fred=fake_fred, fetch_yahoo=fake_yahoo, fetch_lme=fake_lme, fetch_bis=fake_bis,
                                     log=lambda *_: None)
    collect.write_output(tmp_path, REG, latest, series)
    monkeypatch.setattr(news, "MAX_QUERIES_PER_RUN", 50)
    stats = news.build_notes(REG, tmp_path, search=fake_news, load_previous=lambda *a: {}, sleep=0, log=lambda *_: None)
    assert stats["searched"] == 50 and stats["pending"] > 0
    kospi = json.loads((tmp_path / "notes" / "kospi.json").read_text(encoding="utf-8"))["events"]
    assert kospi[-1]["headlines"] and not kospi[0]["headlines"]


DEFS = {i["id"]: i for i in REG["indicators"]}


def test_country_matching_for_us_cpi():
    cpi = DEFS["cpi"]
    period = news.search_plan(cpi, pd.Timestamp("2026-09-01"))[3]
    keep = ["美 9월 소비자물가 3.0% 상승…예상 하회", "미국 9월 CPI 둔화에 연준 인하 기대"]
    drop = ["중국 9월 소비자물가 0.3% 하락", "9월 소비자물가 2.1%↑…국내 체감물가 여전",
            "미국 8월 CPI 3.1%", "한국·미국 9월 소비자물가 비교"]
    assert [t for t in keep + drop if news.relevant(t, cpi, period)] == keep


def test_search_plan_uses_release_month():
    q, start, end, period = news.search_plan(DEFS["cpi"], pd.Timestamp("2026-09-01"))
    assert q == "미국 소비자물가 CPI 9월" and start == pd.Timestamp("2026-10-01") and end == pd.Timestamp("2026-11-01")
    q, start, end, period = news.search_plan(DEFS["gdp"], pd.Timestamp("2026-07-01"))
    assert q.endswith("3분기") and start == pd.Timestamp("2026-10-01") and period == ["3분기"]
    q, start, end, period = news.search_plan(DEFS["kospi"], pd.Timestamp("2026-10-23"))
    assert (q, start, period) == ("코스피", pd.Timestamp("2026-10-22"), [])


def test_every_indicator_has_match_rules():
    for ind in REG["indicators"]:
        assert ind.get("news") and ind.get("match"), ind["id"]
        assert news.relevant(ind["news"], ind) or ind["id"] in {"spx", "taiex", "dxy", "fedfunds", "ttf", "natgas", "gold"}, ind["id"]


def test_pick_dedupes_and_limits():
    items = [{"title": t} for t in ["코스피 2% 급락", "코스피 2% 급락 ", "환율 급등", "코스피 반등", "코스피 외국인", "코스피 4"]]
    assert [h["title"] for h in news.pick(items, DEFS["kospi"])] == ["코스피 2% 급락", "코스피 반등", "코스피 외국인"]
