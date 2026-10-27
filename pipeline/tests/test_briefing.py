import copy
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import briefing  # noqa: E402
import collect  # noqa: E402
import news  # noqa: E402
from fakes import fake_bis, fake_fred, fake_lme, fake_news, fake_yahoo  # noqa: E402

REG = collect.load_registry()
DEFS = {i["id"]: i for i in REG["indicators"]}
TODAY = date(2026, 10, 24)


def latest():
    out, _ = collect.collect(REG, fetch_fred=fake_fred, fetch_yahoo=fake_yahoo, fetch_lme=fake_lme,
                             fetch_bis=fake_bis, log=lambda *_: None)
    return out


def item(data, ind_id):
    return next(i for i in data["indicators"] if i["id"] == ind_id)


def quiet(data):
    for it in data["indicators"]:
        it["sigma"] = 0.1
        if it["changes"].get("prev"):
            it["changes"]["prev"]["value"] = 0.0
    return data


def move(data, ind_id, value, sigma):
    it = item(data, ind_id)
    it["sigma"] = sigma
    it["changes"]["prev"]["value"] = value


def test_stories_lead_with_big_moves_and_headlines():
    data = quiet(latest())
    move(data, "ust10y", -17.0, -4.0)
    move(data, "wti", 3.8, 2.4)
    move(data, "usdkrw", 0.3, 1.2)
    notes = {"wti": {item(data, "wti")["last"]["date"]: [{"title": "호르무즈 긴장", "url": "https://x", "source": "연합"}]}}

    brief = briefing.build(REG, data, notes=notes, today=TODAY)
    assert [s["id"] for s in brief["stories"]] == ["ust10y", "wti", "usdkrw"]
    assert [s["big"] for s in brief["stories"]] == [True, True, False]
    assert "▼17.0bp 금리 하락" in brief["stories"][0]["text"] and "4.0배" in brief["stories"][0]["text"]
    assert brief["stories"][1]["headlines"][0]["title"] == "호르무즈 긴장"
    assert "원화 약세" in brief["stories"][2]["text"]
    assert brief["headline"].startswith("미 국채 10년 ▼17.0bp 금리 하락, WTI")
    assert brief["as_of"] == "2026-10-23"


def test_reads_mood_curve_and_oil():
    data = quiet(latest())
    for k, v in {"spx": -1.5, "nasdaq": -2.0, "kospi": -1.0, "gold": 1.2, "dxy": 0.4}.items():
        move(data, k, v, -1.0)
    move(data, "vix", 3.0, 2.5)
    move(data, "ust2y", -10.0, -3.0)
    move(data, "ust10y", -17.0, -3.0)
    item(data, "ust2y")["last"]["date"] = item(data, "ust10y")["last"]["date"]
    move(data, "wti", 3.8, 2.4)

    brief = briefing.build(REG, data, today=TODAY)
    assert brief["mood"] == "위험회피" and brief["headline"].startswith("위험회피 · ")
    assert brief["reads"][0].startswith("위험회피 분위기")
    curve = next(t for t in brief["reads"] if t.startswith("미 국채"))
    assert "불 플래트닝" in curve
    assert any("성장을 누를" in t for t in brief["reads"])


def test_bear_steepening_named():
    data = quiet(latest())
    move(data, "ust2y", 2.0, 1.0)
    move(data, "ust10y", 9.0, 2.0)
    item(data, "ust2y")["last"]["date"] = item(data, "ust10y")["last"]["date"]
    assert "베어 스티프닝" in briefing.curve_read(DEFS, {k: item(data, k) for k in ("ust2y", "ust10y")})


def test_context_new_high_and_streak():
    idx = pd.bdate_range("2025-01-01", periods=300)
    s = pd.Series(range(300), index=idx, dtype=float)
    notes = briefing.context_notes(DEFS["kospi"], s)
    assert notes[0] == "52주 신고가" and notes[1].endswith("거래일 연속 상승")
    s2 = s.copy()
    s2.iloc[-1] = 100
    assert briefing.context_notes(DEFS["kospi"], s2) == []


def test_quiet_day_and_stale_sources():
    data = quiet(latest())
    item(data, "kospi")["status"] = "stale"
    brief = briefing.build(REG, data, today=TODAY)
    assert brief["stories"] == []
    assert "조용한 하루" in brief["headline"]
    assert brief["stale"] == ["코스피"]
    assert any("올해 가장 많이 오른 자산:" in t for t in brief["signals"])
    assert any("FOMC 점도표" in t for t in brief["signals"])


def test_outdated_data_is_left_out():
    data = latest()
    move(data, "spx", -3.0, 5.0)
    brief = briefing.build(REG, copy.deepcopy(data), today=date(2026, 11, 30))
    assert all(s["id"] != "spx" for s in brief["stories"])


def test_write_outputs(tmp_path):
    data, series = collect.collect(REG, fetch_fred=fake_fred, fetch_yahoo=fake_yahoo, fetch_lme=fake_lme,
                                   fetch_bis=fake_bis, log=lambda *_: None)
    collect.write_output(tmp_path, REG, data, series)
    news.build_notes(REG, tmp_path, search=fake_news, load_previous=lambda *a: {}, sleep=0, log=lambda *_: None)
    md = briefing.write(tmp_path, TODAY)
    assert (tmp_path / "briefing.json").exists()
    assert md.startswith("# 일일 경제 브리핑 (2026-10-23)")
    assert "## 분야별 요약" not in md
    if "## 무엇이 왜 움직였나" in md:
        assert "](https://example.com/" in md


def test_importance_beats_raw_size():
    data = quiet(latest())
    move(data, "natgas", 15.8, -2.7 * -1)
    move(data, "usdcny", -0.33, -2.1)
    move(data, "kospi", 3.1, 2.0)
    move(data, "wti", 2.0, 1.6)
    brief = briefing.build(REG, data, today=TODAY)
    assert [s["id"] for s in brief["stories"]][:2] == ["kospi", "wti"]
