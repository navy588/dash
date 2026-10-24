import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect  # noqa: E402
from fakes import daily, fake_fred, fake_yahoo  # noqa: E402

REG = collect.load_registry()


def collect_yahoo_codes():
    return [i["code"] for i in REG["indicators"] if i["source"] == "yahoo"]


def test_registry_is_consistent():
    groups = {g["id"] for g in REG["groups"]}
    ids = [i["id"] for i in REG["indicators"]]
    assert len(ids) == len(set(ids))
    for i in REG["indicators"]:
        assert i["group"] in groups
        assert i["source"] in ("fred", "yahoo")
        assert i["freq"] in collect.START
        assert i["change"] in ("pct", "bp", "pp", "abs")


def test_collect_all_ok(tmp_path):
    latest, series = collect.collect(REG, fetch_fred=fake_fred, fetch_yahoo=fake_yahoo, log=lambda *_: None)
    assert latest["counts"] == {"ok": len(REG["indicators"]), "stale": 0, "missing": 0}
    by_id = {i["id"]: i for i in latest["indicators"]}
    # 전년비 변환: 매월 0.2% 상승 → 연 2.43%
    assert by_id["cpi"]["last"]["value"] == pytest.approx((1.002 ** 12 - 1) * 100)
    # 엔화 100엔 단위
    jpy_code = next(i["code"] for i in REG["indicators"] if i["id"] == "jpykrw")
    assert series["jpykrw"].iloc[-1] == pytest.approx(fake_yahoo([c for c in collect_yahoo_codes()])[jpy_code].iloc[-1] * 100)
    # 금리 변화는 bp
    s = series["ust10y"]
    assert by_id["ust10y"]["changes"]["prev"]["value"] == pytest.approx((s.iloc[-1] - s.iloc[-2]) * 100, abs=1e-3)
    # 연초 대비는 전년 말 값 기준
    assert by_id["kospi"]["changes"]["ytd"]["ref_date"] <= "2025-12-31"
    assert len(by_id["kospi"]["spark"]) == 90
    assert latest["curve"] and latest["curve"][0]["label"] == "1개월"
    # 일별 시계열은 2010년부터
    assert series["kospi"].index[0] >= pd.Timestamp("2010-01-01")

    collect.write_output(tmp_path, REG, latest, series)
    data = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert data["indicators"][0]["id"] == "kospi"
    one = json.loads((tmp_path / "series" / "kospi.json").read_text(encoding="utf-8"))
    assert len(one["dates"]) == len(one["values"])
    assert (tmp_path / "indicators.json").exists()


def test_failures_fall_back_to_previous():
    prev = daily(start="2025-01-01")

    def flaky_yahoo(codes):
        out = fake_yahoo(codes)
        out.pop("^KS11")
        return out

    def broken_fred(code, key=None, session=None):
        raise RuntimeError("503")

    def previous(url, ind_id, session=None):
        return prev if ind_id in ("kospi", "ust10y") else None

    latest, series = collect.collect(REG, previous_url="https://example", fetch_fred=broken_fred,
                                     fetch_yahoo=flaky_yahoo, fetch_previous=previous, log=lambda *_: None)
    by_id = {i["id"]: i for i in latest["indicators"]}
    assert by_id["kospi"]["status"] == "stale" and by_id["kospi"]["error"] == "데이터 없음"
    assert by_id["ust10y"]["status"] == "stale" and "503" in by_id["ust10y"]["error"]
    assert by_id["cpi"]["status"] == "missing" and "cpi" not in series
    assert by_id["spx"]["status"] == "ok"
    assert latest["curve"] == []


def test_main_fails_when_nothing_collected(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(collect, "fetch_fred", boom)
    monkeypatch.setattr(collect, "fetch_yahoo", boom)
    monkeypatch.setattr(collect, "collect", lambda reg, **kw: collect.__dict__["_orig_collect"](
        reg, fetch_fred=boom, fetch_yahoo=boom, fetch_previous=lambda *a, **k: None, log=lambda *_: None))
    assert collect.main(["--out", str(tmp_path)]) == 1
    assert not (tmp_path / "latest.json").exists()


collect._orig_collect = collect.collect


def test_change_kinds():
    assert collect.change(110, 100, "pct") == pytest.approx(10)
    assert collect.change(4.25, 4.0, "bp") == pytest.approx(25)
    assert collect.change(3.5, 3.7, "pp") == pytest.approx(-0.2)
    assert collect.change(1, None, "pct") is None


def test_only_repeated_failures_are_reported():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import health
    cur = {"indicators": [{"id": "a", "status": "stale", "error": "x"}, {"id": "b", "status": "missing"},
                          {"id": "c", "status": "ok"}]}
    prev = {"indicators": [{"id": "a", "status": "stale"}, {"id": "b", "status": "ok"}, {"id": "c", "status": "stale"}]}
    assert health.persistent_problems(cur, prev) == ["a (stale: x)"]
    assert health.persistent_problems(cur, None) == []
