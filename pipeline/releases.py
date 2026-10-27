"""월간·분기 지표의 발표 일정과 속보치 여부.

- 미국 GDP·PCE: 미 상무부(BEA) 발표 일정표(공식 날짜)
- 그 밖의 지표: 평소 발표 패턴으로 추정한 날짜 (est=True, 화면에는 "11월 중순"처럼 대략 표시)
- 이번 발표일: 수집기가 새 값을 처음 받은 날(지표 나라의 날짜). 공식 일정이 있으면 그 날짜.

지표 정의(indicators.json)의 "release" 항목:
    {"bea": "GDP ("}                                 BEA 일정표에서 제목이 이 글자로 시작하는 행
    {"day": 12}                                      매달 12일 무렵 (추정)
    {"weekday": 4, "nth": 1}                         매달 첫째 금요일 무렵 (추정, 월=0)
    {"bok_gdp": true}                                한국은행 GDP: 분기 끝 다음 달 넷째 목요일(속보), 셋째 달 5일 무렵(잠정)
    "prelim": {"label": "속보치", ...}               최근 값이 속보치인지 표시
"""
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

BEA_URL = "https://www.bea.gov/news/schedule"
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                      "September", "October", "November", "December"], 1)}
TZ = {"krmacro": "Asia/Seoul"}
ORDINAL = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4}


# ── BEA 일정표 ─────────────────────────────────────────
def fetch_bea(session):
    r = session.get(BEA_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0 (global-economy-dashboard)"})
    r.raise_for_status()
    return parse_bea(r.text)


def parse_bea(html):
    """[(date, 제목)]. 날짜 칸은 "October 29" 꼴이고 연도는 표 위 "Year 2026" 제목에서 가져옵니다."""
    out = []
    pos_years = [(m.start(), int(m.group(1))) for m in re.finditer(r"Year\s+(20\d\d)", html)]
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        row = m.group(1)
        text = re.sub(r"<[^>]+>", " ", row)
        text = re.sub(r"\s+", " ", text).strip()
        d = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})"
                      r"(?:,\s*(20\d\d))?", text)
        if not d:
            continue
        subj = re.search(r"subject[^>]*>(.*?)</td>", row, re.S)
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", subj.group(1))).strip() if subj else text[d.end():].strip()
        year = int(d.group(3)) if d.group(3) else None
        if year is None:
            prev = [y for p, y in pos_years if p < m.start()]
            year = prev[-1] if prev else None
        if year is None:
            q = re.search(r"Quarter (20\d\d)|, (20\d\d)\b", title)
            year = int(next(g for g in q.groups() if g)) if q else datetime.now().year
        out.append((date(year, MONTHS[d.group(1)], int(d.group(2))), title))
    return sorted(set(out))


# ── 추정 일정 ──────────────────────────────────────────
def _nth_weekday(y, m, weekday, nth):
    d = date(y, m, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=nth - 1)


def _months(today, back=2, ahead=4):
    p = pd.Period(today, freq="M")
    return [(x.year, x.month) for x in (p + k for k in range(-back, ahead + 1))]


def estimated_dates(rule, today):
    if "day" in rule:
        return [date(y, m, rule["day"]) for y, m in _months(today)]
    if "weekday" in rule:
        return [_nth_weekday(y, m, rule["weekday"], rule.get("nth", 1)) for y, m in _months(today)]
    if rule.get("bok_gdp"):
        out = []
        for y, m in _months(today, 4, 6):
            if m in (1, 4, 7, 10):
                out.append(_nth_weekday(y, m, 3, 4))  # 속보: 분기 끝 다음 달 넷째 목요일
            if m in (3, 6, 9, 12):
                out.append(date(y, m, 5))  # 잠정: 셋째 달 5일 무렵
        return out
    return []


def bok_prelim_until(quarter_start):
    """한국은행 잠정치 추정 발표일 (분기 끝 뒤 셋째 달 5일, 예: 3분기 → 12월 5일)."""
    first = pd.Period(quarter_start, freq="Q").end_time.normalize() + pd.Timedelta(days=1)  # 분기 끝 다음 날
    third = (first + pd.DateOffset(months=2)).to_period("M")
    return date(third.year, third.month, 5)


# ── 지표별 계산 ────────────────────────────────────────
QUARTER_WORD = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}


def _local_today(ind, now):
    return now.astimezone(ZoneInfo(TZ.get(ind["group"], "America/New_York"))).date()


def release_info(ind, last_date, prev_item, now, bea=()):
    """{"last": "YYYY-MM-DD"|None, "next": ..., "est": bool} 또는 None."""
    rule = ind.get("release")
    if not rule:
        return None
    today = _local_today(ind, now)
    if "bea" in rule:
        dates = sorted({d for d, t in bea if t.startswith(rule["bea"])})
        est = False
    else:
        dates = sorted(estimated_dates(rule, today))
        est = True
    nxt = next((d for d in dates if d >= today), None)
    last = None
    prev_rel = (prev_item or {}).get("release") or {}
    prev_last_date = ((prev_item or {}).get("last") or {}).get("date")
    if prev_last_date and prev_last_date != last_date:
        last = today.isoformat()  # 이번 수집에서 새 값이 들어옴
    elif prev_rel.get("last"):
        last = prev_rel["last"]
    elif not est:
        past = [d for d in dates if d < today]
        last = past[-1].isoformat() if past else None
    if not est and nxt == today and last == today.isoformat():
        nxt = next((d for d in dates if d > today), None)
    if last and nxt and nxt.isoformat() <= last:
        nxt = next((d for d in dates if d.isoformat() > last), None)
    if not nxt and not last:
        return None
    return {"last": last, "next": nxt.isoformat() if nxt else None, "est": est}


def prelim_label(ind, last_date, now, bea=()):
    """최근 값이 속보치면 라벨("속보치"), 아니면 None."""
    pr = ind.get("prelim")
    if not pr:
        return None
    today = _local_today(ind, now)
    q = pd.Timestamp(last_date).to_period("Q")
    if pr.get("bea"):
        second = [d for d, t in bea if t.startswith(pr["bea"]) and f"{QUARTER_WORD[q.quarter]} Quarter {q.year}" in t]
        if second:
            return pr["label"] if today < second[0] else None
        # 일정표에서 못 찾으면 분기 끝 후 58일까지를 속보치로 봄
        return pr["label"] if (today - q.end_time.date()).days < 58 else None
    if pr.get("bok"):
        return pr["label"] if today < bok_prelim_until(q.start_time) else None
    return None


def annotate(registry, latest, prev_latest=None, now=None, session=None, log=print):
    """latest.json 지표마다 release·prelim을 채웁니다 (실패해도 조용히 넘어감)."""
    now = now or datetime.now(ZoneInfo("UTC"))
    bea = []
    if any("bea" in (i.get("release") or {}) or (i.get("prelim") or {}).get("bea") for i in registry["indicators"]):
        try:
            bea = fetch_bea(session) if session else []
            log(f"BEA 발표 일정: {len(bea)}건")
        except Exception as e:  # noqa: BLE001
            log(f"BEA 발표 일정 실패: {str(e)[:150]}")
    prev = {i["id"]: i for i in (prev_latest or {}).get("indicators", [])}
    defs = {i["id"]: i for i in registry["indicators"]}
    for item in latest["indicators"]:
        ind = defs[item["id"]]
        if "last" not in item:
            continue
        try:
            rel = release_info(ind, item["last"]["date"], prev.get(item["id"]), now, bea)
            if rel:
                item["release"] = rel
            pl = prelim_label(ind, item["last"]["date"], now, bea)
            if pl:
                item["prelim"] = pl
        except Exception as e:  # noqa: BLE001
            log(f"발표 일정 계산 실패 {item['id']}: {e}")
    return latest
