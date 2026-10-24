import copy
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import briefing  # noqa: E402
import collect  # noqa: E402
from fakes import fake_fred, fake_yahoo  # noqa: E402

REG = collect.load_registry()
TODAY = date(2026, 10, 24)


def latest():
    out, _ = collect.collect(REG, fetch_fred=fake_fred, fetch_yahoo=fake_yahoo, log=lambda *_: None)
    return out


def item(data, ind_id):
    return next(i for i in data["indicators"] if i["id"] == ind_id)


def test_movers_follow_sigma_threshold():
    data = latest()
    for it in data["indicators"]:
        it["sigma"] = 0.5
    item(data, "ust10y").update(sigma=-4.0)
    item(data, "ust10y")["changes"]["prev"]["value"] = -17.0
    item(data, "usdkrw").update(sigma=2.5)
    item(data, "usdkrw")["changes"]["prev"]["value"] = 1.1
    item(data, "unrate").update(sigma=9.0)  # 월간 지표는 큰 움직임에서 제외

    brief = briefing.build(REG, data, TODAY)
    assert [h["id"] for h in brief["highlights"]] == ["ust10y", "usdkrw"]
    assert "▼17.0bp" in brief["highlights"][0]["text"] and "금리 하락" in brief["highlights"][0]["text"]
    assert "원화 약세" in brief["highlights"][1]["text"]
    assert brief["headline"].startswith("평소보다 크게 움직인 지표 2개")
    assert brief["as_of"] == "2026-10-23"


def test_quiet_day_and_stale_sources():
    data = latest()
    for it in data["indicators"]:
        it["sigma"] = 0.1
    item(data, "kospi")["status"] = "stale"
    brief = briefing.build(REG, data, TODAY)
    assert brief["highlights"] == []
    assert "조용한 하루" in brief["headline"]
    assert brief["stale"] == ["코스피"]
    korea = next(s for s in brief["sections"] if s["group"] == "korea")
    assert "코스피" not in korea["text"] and "코스닥" in korea["text"]


def test_outdated_data_is_left_out():
    data = latest()
    item(data, "spx")["sigma"] = 5.0
    brief = briefing.build(REG, copy.deepcopy(data), date(2026, 11, 30))
    assert brief["highlights"] == []
    assert all(s["group"] not in ("us", "korea") for s in brief["sections"])


def test_write_outputs(tmp_path):
    reg = REG
    data, series = collect.collect(reg, fetch_fred=fake_fred, fetch_yahoo=fake_yahoo, log=lambda *_: None)
    collect.write_output(tmp_path, reg, data, series)
    md = briefing.write(tmp_path, TODAY)
    assert (tmp_path / "briefing.json").exists()
    assert md.startswith("# 일일 경제 브리핑 (2026-10-23)")
    assert "## 분야별 요약" in md
