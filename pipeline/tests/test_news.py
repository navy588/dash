import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect  # noqa: E402
import news  # noqa: E402
from fakes import fake_fred, fake_lme, fake_news, fake_yahoo  # noqa: E402

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


def test_build_notes_reuses_previous(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "MAX_QUERIES_PER_RUN", 10**6)
    latest, series = collect.collect(REG, fetch_fred=fake_fred, fetch_yahoo=fake_yahoo, fetch_lme=fake_lme,
                                     log=lambda *_: None)
    collect.write_output(tmp_path, REG, latest, series)
    calls = []

    def search(q, d, session=None):
        calls.append((q, d))
        return fake_news(q, d)

    news.build_notes(REG, tmp_path, search=search, load_previous=lambda *a: {}, sleep=0, log=lambda *_: None)
    first = len(calls)
    assert first > 0
    # 최신 날짜부터 검색
    assert calls[0][1] == max(d for _, d in calls)
    note = json.loads((tmp_path / "notes" / "kospi.json").read_text(encoding="utf-8"))
    assert note["query"] == "코스피"
    prev = {i["id"]: {e["date"]: e for e in json.loads((tmp_path / "notes" / f"{i['id']}.json").read_text(encoding="utf-8"))["events"]}
            for i in REG["indicators"] if (tmp_path / "notes" / f"{i['id']}.json").exists()}
    calls.clear()
    news.build_notes(REG, tmp_path, search=search, load_previous=lambda url, ind_id, s: prev.get(ind_id, {}),
                     sleep=0, log=lambda *_: None)
    assert calls == []  # 모두 재사용


def test_search_failure_does_not_stop(tmp_path):
    latest, series = collect.collect(REG, fetch_fred=fake_fred, fetch_yahoo=fake_yahoo, fetch_lme=fake_lme,
                                     log=lambda *_: None)
    collect.write_output(tmp_path, REG, latest, series)

    def boom(*a, **k):
        raise RuntimeError("429")

    stats = news.build_notes(REG, tmp_path, search=boom, load_previous=lambda *a: {}, sleep=0, log=lambda *_: None)
    assert stats["failed"] > 0 and stats["searched"] == 0


def test_budget_fills_latest_first(tmp_path, monkeypatch):
    latest, series = collect.collect(REG, fetch_fred=fake_fred, fetch_yahoo=fake_yahoo, fetch_lme=fake_lme,
                                     log=lambda *_: None)
    collect.write_output(tmp_path, REG, latest, series)
    monkeypatch.setattr(news, "MAX_QUERIES_PER_RUN", 50)
    stats = news.build_notes(REG, tmp_path, search=fake_news, load_previous=lambda *a: {}, sleep=0, log=lambda *_: None)
    assert stats["searched"] == 50 and stats["pending"] > 0
    kospi = json.loads((tmp_path / "notes" / "kospi.json").read_text(encoding="utf-8"))["events"]
    assert kospi[-1]["headlines"] and not kospi[0]["headlines"]
