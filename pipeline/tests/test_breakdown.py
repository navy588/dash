import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import breakdown  # noqa: E402
from fakes import fake_caps, fake_fred, fake_prices  # noqa: E402

CONFIG = json.loads(breakdown.CONSTITUENTS.read_text(encoding="utf-8"))


def test_constituents_are_unique_and_tagged():
    for m in CONFIG["markets"]:
        ts = [i["t"] for i in m["items"]]
        assert len(ts) == len(set(ts)) >= 25, m["id"]
        assert all(i["n"] and i["s"] for i in m["items"])
    korea = {m["id"]: m for m in CONFIG["markets"]}
    assert all(i["t"].endswith(".KS") for i in korea["kospi"]["items"])
    assert all(i["t"].endswith(".KQ") for i in korea["kosdaq"]["items"])


def test_markets_weights_and_changes():
    out = breakdown.build_markets(CONFIG, fake_prices, fake_caps, log=lambda *_: None)
    spx = next(m for m in out["markets"] if m["id"] == "spx")
    assert abs(sum(i["w"] for i in spx["items"]) - 100) < 0.1
    assert spx["items"][0]["cap"] >= spx["items"][-1]["cap"]
    assert set(spx["items"][0]["chg"]) == {"prev", "w1", "m1", "y1", "ytd"}
    kospi = next(m for m in out["markets"] if m["id"] == "kospi")
    assert kospi["items"][0]["t"].isdigit()  # .KS 접미사는 떼고 저장


def test_missing_tickers_are_skipped():
    out = breakdown.build_markets(CONFIG, lambda ts: fake_prices(ts[:10]), fake_caps, log=lambda *_: None)
    assert sum(len(m["items"]) for m in out["markets"]) < 30


def test_changes_periods():
    s = pd.Series([100.0, 110.0], index=pd.to_datetime(["2026-10-22", "2026-10-23"]))
    assert breakdown.changes(s)["prev"] == 10.0


def test_stacks_sum_to_total():
    frames = breakdown.component_frames(fake_fred, log=lambda *_: None)
    stacks = breakdown.build_stacks(frames)
    assert set(stacks) == {"ust10y", "cpi", "gdp"}
    tp = stacks["ust10y"]["charts"][0]
    i = -1
    assert abs(tp["total"]["values"][i] - sum(p["values"][i] for p in tp["parts"])) < 1e-2
    assert stacks["cpi"]["charts"][0]["kind"] == "stack" and len(stacks["cpi"]["charts"][0]["parts"]) == 5


def test_write_survives_market_failure(tmp_path):
    def boom(*a):
        raise RuntimeError("yahoo down")
    written = breakdown.write(tmp_path, fetch_fred=fake_fred, fetch_prices=boom, fetch_caps=fake_caps, log=lambda *_: None)
    assert "markets" not in written and "ust10y" in written
    assert json.loads((tmp_path / "breakdown" / "index.json").read_text()) == ["cpi", "gdp", "ust10y"]
