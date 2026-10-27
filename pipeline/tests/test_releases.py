import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import releases  # noqa: E402

BEA = [(date(2026, 10, 29), "GDP (Advance Estimate), 3rd Quarter 2026"),
       (date(2026, 10, 30), "Personal Income and Outlays, September 2026"),
       (date(2026, 11, 25), "GDP (Second Estimate) and Corporate Profits, 3rd Quarter 2026"),
       (date(2026, 11, 25), "Personal Income and Outlays, October 2026")]
NOW = datetime(2026, 10, 27, 23, 0, tzinfo=timezone.utc)  # 미국 10/27, 한국 10/28
GDP = {"id": "gdp", "group": "macro", "release": {"bea": "GDP ("},
       "prelim": {"label": "속보치", "bea": "GDP (Second Estimate)"}}
KRGDP = {"id": "krgdp", "group": "krmacro", "release": {"bok_gdp": True}, "prelim": {"label": "속보치", "bok": True}}


def test_bea_schedule_gives_exact_next_date():
    rel = releases.release_info(GDP, "2026-04-01", None, NOW, BEA)
    assert rel == {"last": None, "next": "2026-10-29", "est": False}


def test_new_value_sets_last_release_to_local_today():
    prev = {"last": {"date": "2026-04-01"}}
    rel = releases.release_info(GDP, "2026-07-01", prev, datetime(2026, 10, 29, 22, 0, tzinfo=timezone.utc), BEA)
    assert rel["last"] == "2026-10-29" and rel["next"] == "2026-11-25"
    # 다음 수집에서는 그대로 유지
    again = releases.release_info(GDP, "2026-07-01", {"last": {"date": "2026-07-01"}, "release": rel},
                                  datetime(2026, 10, 30, 22, 0, tzinfo=timezone.utc), BEA)
    assert again["last"] == "2026-10-29"


def test_us_advance_estimate_is_prelim_until_second_estimate():
    assert releases.prelim_label(GDP, "2026-07-01", datetime(2026, 11, 1, tzinfo=timezone.utc), BEA) == "속보치"
    assert releases.prelim_label(GDP, "2026-07-01", datetime(2026, 11, 26, 15, tzinfo=timezone.utc), BEA) is None
    assert releases.prelim_label(GDP, "2026-04-01", NOW, BEA) is None  # 지난 분기는 확정치


def test_korean_gdp_prelim_and_estimated_schedule():
    assert releases.prelim_label(KRGDP, "2026-07-01", NOW) == "속보치"
    assert releases.prelim_label(KRGDP, "2026-04-01", NOW) is None
    rel = releases.release_info(KRGDP, "2026-07-01", None, NOW)
    assert rel["est"] and rel["next"] == "2026-12-05"


def test_estimated_rules():
    fri = releases.estimated_dates({"weekday": 4, "nth": 1}, date(2026, 10, 28))
    assert date(2026, 11, 6) in fri and all(d.weekday() == 4 and d.day <= 7 for d in fri)
    assert date(2026, 11, 12) in releases.estimated_dates({"day": 12}, date(2026, 10, 28))


def test_parse_bea_rows():
    html = """<h3>Year 2026</h3><table><tr class="scheduled-releases-type-press">
      <td class="scheduled-date"><div class="release-date">October 29</div><div class="release-time">8:30 AM</div></td>
      <td class="release-title scheduled-releases-type" headers="view-field-scheduled-release-subject-table-column">GDP (Advance Estimate), 3rd Quarter 2026 </td></tr>
      <tr><td>November 25</td><td class="x" headers="subject">GDP (Second Estimate) and Corporate Profits, 3rd Quarter 2026</td></tr></table>"""
    rows = releases.parse_bea(html)
    assert rows == [(date(2026, 10, 29), "GDP (Advance Estimate), 3rd Quarter 2026"),
                    (date(2026, 11, 25), "GDP (Second Estimate) and Corporate Profits, 3rd Quarter 2026")]
