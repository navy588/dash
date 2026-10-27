"""모든 지표의 관측일마다 그날의 관련 뉴스 헤드라인을 붙입니다 (Google 뉴스 RSS, 키 불필요).

    python pipeline/news.py site/data

- 대상: 지표별 최근 1년의 모든 관측일 (일별 지표는 거래일마다, 월별 지표는 발표 기준월마다)
- 각 시점의 변화와 "평소 대비 배수"(sigma, 그 전 1년 변화의 표준편차 기준)를 함께 저장합니다.
- 국가·주제를 정확히 맞춥니다. 지표마다 indicators.json의 "match"(모든 묶음에서 한 단어 이상 포함)와
  "exclude"(하나라도 있으면 제외)로 제목을 거릅니다. 예: 미국 CPI에는 '미국/美/연준'과 '소비자물가/CPI'가
  모두 들어 있고 한국·중국 등 다른 나라가 없는 제목만 붙습니다.
- 월별·분기별 지표는 기준월이 아니라 실제 발표 시기(다음 달 등)의 기사를, '9월'·'3분기'처럼
  기준 기간이 제목에 들어 있는 것만 씁니다.
- 이미 직전 배포본(PREVIOUS_DATA_URL)에 헤드라인이 있는 날은 다시 검색하지 않고 그대로 씁니다
  (가져온 헤드라인도 같은 규칙으로 다시 거릅니다).
- 최신 날짜부터 검색하고 한 번 실행의 검색 횟수를 제한하므로, 매 실행마다 오늘 치는 바로 채워지고
  지난 1년치는 몇 주에 걸쳐 거슬러 올라가며 채워집니다.

출력: <data>/notes/<id>.json  {"id", "events": [{"date", "change", "sigma", "headlines": [{"title", "url", "source", "published"}]}]}
"""
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402

MAX_QUERIES_PER_RUN = int(os.environ.get("NEWS_MAX_QUERIES", "400"))
LOOKBACK_DAYS = 366
HEADLINES = 3
RSS = "https://news.google.com/rss/search"
RULES = 2  # 검색·매칭 규칙 버전. 바뀌면 월별·주별 지표의 지난 헤드라인은 다시 검색합니다.


def find_events(series, ind, lookback_days=LOOKBACK_DAYS):
    """최근 1년 모든 관측일의 (date, change, sigma). sigma는 그 날 이전 1년 변화의 표준편차 기준 배수."""
    if len(series) < 3:
        return []
    vals = series.values
    changes = pd.Series([collect.change(b, a, ind["change"]) for a, b in zip(vals[:-1], vals[1:])],
                        index=series.index[1:], dtype=float)
    window = {"daily": 250, "weekly": 52, "monthly": 12, "quarterly": 8}[ind["freq"]]
    std = changes.shift(1).rolling(window, min_periods=max(window // 2, 4)).std()
    recent = changes[changes.index > series.index[-1] - pd.DateOffset(days=lookback_days)]
    out = []
    for d, ch in recent.items():
        sd = std.get(d)
        sg = round(float(ch / sd), 2) if sd and sd > 0 and pd.notna(sd) and pd.notna(ch) else None
        out.append((d, None if pd.isna(ch) else float(ch), sg))
    return out


def search_plan(ind, date):
    """(검색어, 검색 시작일, 검색 종료일, 제목에 꼭 있어야 할 기간 표현)."""
    query = ind.get("news", ind["name"])
    freq = ind["freq"]
    if freq == "monthly":  # 기준월 다음 달에 발표
        start = date + pd.DateOffset(months=1)
        return f"{query} {date.month}월", start, start + pd.DateOffset(months=1), [f"{date.month}월"]
    if freq == "quarterly":  # 분기 끝난 뒤 한 달 뒤 속보치, 이후 잠정·확정치
        q = (date.month - 1) // 3 + 1
        start = date + pd.DateOffset(months=3)
        return f"{query} {q}분기", start, start + pd.DateOffset(months=3), [f"{q}분기"]
    if freq == "weekly":  # 토요일로 끝나는 주, 다음 목요일 발표
        return query, date + pd.Timedelta(days=4), date + pd.Timedelta(days=8), []
    return query, date - pd.Timedelta(days=1), date + pd.Timedelta(days=2), []


def google_news(query, start, end, session):
    """start 이후 end 이전 기사 헤드라인 (거르기 전 전부)."""
    r = session.get(RSS, timeout=20, params={
        "q": f"{query} after:{start:%Y-%m-%d} before:{end:%Y-%m-%d}", "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    r.raise_for_status()
    return parse_rss(r.text, limit=None)


def relevant(title, ind, period=()):
    """제목이 이 지표(국가·주제·기간)에 관한 기사인지."""
    t = title.casefold()
    has = lambda words: any(w.casefold() in t for w in words)  # noqa: E731
    groups = ind.get("match") or [[ind.get("news", ind["name"])]]
    if not all(has(g) for g in groups):
        return False
    if ind.get("exclude") and has(ind["exclude"]):
        return False
    return not period or has(period)


def pick(items, ind, period=(), limit=HEADLINES):
    out, seen = [], set()
    for h in items:
        key = h["title"].replace(" ", "")[:30]
        if key in seen or not relevant(h["title"], ind, period):
            continue
        seen.add(key)
        out.append(h)
        if len(out) >= limit:
            break
    return out


def clean_title(title):
    """'제목 | 매체'에서 매체가 잘린 뒤 남는 꼬리 기호를 지웁니다."""
    return title.rstrip(" |·-").strip()


def parse_rss(text, limit=HEADLINES):
    root = ET.fromstring(text)
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        source = (item.findtext("source") or "").strip()
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        title = clean_title(title)
        published = item.findtext("pubDate")
        try:
            published = parsedate_to_datetime(published).strftime("%Y-%m-%d") if published else None
        except (TypeError, ValueError):
            published = None
        if title:
            out.append({"title": title, "url": (item.findtext("link") or "").strip(),
                        "source": source, "published": published})
        if limit and len(out) >= limit:
            break
    return out


def load_series(data_dir, ind_id):
    path = Path(data_dir) / "series" / f"{ind_id}.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    return pd.Series(d["values"], index=pd.to_datetime(d["dates"]), dtype=float)


def load_previous_notes(base_url, ind_id, session):
    """직전 배포본의 notes/<id>.json 내용 ({"rules", "events": [...]}). 없으면 {}."""
    if not base_url:
        return {}
    try:
        r = session.get(f"{base_url.rstrip('/')}/notes/{ind_id}.json", timeout=20)
        if r.status_code != 200:
            return {}
        return r.json()
    except Exception:  # noqa: BLE001
        return {}


def build_notes(registry, data_dir, previous_url=None, search=google_news,
                load_previous=load_previous_notes, session=None, sleep=0.5, log=print, today=None):
    session = session or collect._session()
    today = pd.Timestamp(today or pd.Timestamp.now().normalize())
    out_dir = Path(data_dir) / "notes"
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = {"events": 0, "searched": 0, "cached": 0, "failed": 0, "pending": 0}

    notes, queue = {}, []
    for ind in registry["indicators"]:
        s = load_series(data_dir, ind["id"])
        if s is None:
            continue
        payload = load_previous(previous_url, ind["id"], session) or {}
        same_rules = payload.get("rules") == RULES and payload.get("query") == ind.get("news", ind["name"])
        prev = {e["date"]: e for e in payload.get("events", [])} if same_rules or ind["freq"] == "daily" else {}
        evs = []
        for d, ch, sg in find_events(s, ind):
            key = d.strftime("%Y-%m-%d")
            ev = {"date": key, "change": None if ch is None else round(ch, 4), "sigma": sg, "headlines": []}
            old = [{**h, "title": clean_title(h.get("title", ""))} for h in prev.get(key, {}).get("headlines", [])]
            _, _, end, period = search_plan(ind, d)
            old = pick(old, ind, period)
            # 같은 규칙으로 이미 찾아봤는데 없던 날은, 기사가 더 나올 수 있는 최근 며칠만 다시 찾습니다
            settled = same_rules and key in prev and end < today - pd.Timedelta(days=3)
            if old or settled:
                ev["headlines"] = old
                stats["cached"] += 1
            else:
                queue.append((d, ind, ev))
            evs.append(ev)
        notes[ind["id"]] = (ind, evs)

    # 최신 날짜부터 모든 지표를 돌아가며 검색 → 오늘 치가 항상 먼저 채워짐
    queue.sort(key=lambda q: q[0], reverse=True)
    for n, (d, ind, ev) in enumerate(queue):
        if n >= MAX_QUERIES_PER_RUN:
            stats["pending"] = len(queue) - n
            break
        try:
            query, start, end, period = search_plan(ind, d)
            ev["headlines"] = pick(search(query, start, end, session), ind, period)
            stats["searched"] += 1
        except Exception as e:  # noqa: BLE001
            stats["failed"] += 1
            log(f"  뉴스 검색 실패 {ind['id']} {d:%Y-%m-%d}: {str(e)[:120]}")
        if sleep:
            time.sleep(sleep)

    for ind_id, (ind, evs) in notes.items():
        stats["events"] += len(evs)
        stats["with_headlines"] = stats.get("with_headlines", 0) + sum(bool(e["headlines"]) for e in evs)
        with open(out_dir / f"{ind_id}.json", "w", encoding="utf-8") as f:
            json.dump({"id": ind_id, "query": ind.get("news", ind["name"]), "rules": RULES, "events": evs},
                      f, ensure_ascii=False, separators=(",", ":"))
    log(f"뉴스: 시점 {stats['events']}개 · 새로 검색 {stats['searched']} · 재사용 {stats['cached']} · "
        f"실패 {stats['failed']} · 다음 실행으로 미룸 {stats['pending']} · 헤드라인 있는 시점 {stats.get('with_headlines', 0)}")
    return stats


def main(argv):
    data_dir = argv[1] if len(argv) > 1 else "site/data"
    build_notes(collect.load_registry(), data_dir, os.environ.get("PREVIOUS_DATA_URL", "").strip() or None)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
