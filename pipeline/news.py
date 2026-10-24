"""모든 지표의 관측일마다 그날의 관련 뉴스 헤드라인을 붙입니다 (Google 뉴스 RSS, 키 불필요).

    python pipeline/news.py site/data

- 대상: 지표별 최근 1년의 모든 관측일 (일별 지표는 거래일마다, 월별 지표는 발표 기준월마다)
- 각 시점의 변화와 "평소 대비 배수"(sigma, 그 전 1년 변화의 표준편차 기준)를 함께 저장합니다.
- 이미 직전 배포본(PREVIOUS_DATA_URL)에 헤드라인이 있는 날은 다시 검색하지 않고 그대로 씁니다.
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


def find_events(series, ind, lookback_days=LOOKBACK_DAYS):
    """최근 1년 모든 관측일의 (date, change, sigma). sigma는 그 날 이전 1년 변화의 표준편차 기준 배수."""
    if len(series) < 3:
        return []
    vals = series.values
    changes = pd.Series([collect.change(b, a, ind["change"]) for a, b in zip(vals[:-1], vals[1:])],
                        index=series.index[1:], dtype=float)
    window = {"daily": 250, "weekly": 52, "monthly": 12, "quarterly": 8}[ind["freq"]]
    std = changes.shift(1).rolling(window, min_periods=max(window // 2, 4)).std()
    recent = changes[changes.index > series.index[-1] - pd.Timedelta(days=lookback_days)]
    out = []
    for d, ch in recent.items():
        sd = std.get(d)
        sg = round(float(ch / sd), 2) if sd and sd > 0 and pd.notna(sd) and pd.notna(ch) else None
        out.append((d, None if pd.isna(ch) else float(ch), sg))
    return out


def google_news(query, date, session):
    """date 전후 하루의 기사 헤드라인."""
    after = (date - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    before = (date + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    r = session.get(RSS, timeout=20, params={
        "q": f"{query} after:{after} before:{before}", "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    r.raise_for_status()
    return parse_rss(r.text)


def parse_rss(text, limit=HEADLINES):
    root = ET.fromstring(text)
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        source = (item.findtext("source") or "").strip()
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        published = item.findtext("pubDate")
        try:
            published = parsedate_to_datetime(published).strftime("%Y-%m-%d") if published else None
        except (TypeError, ValueError):
            published = None
        if title:
            out.append({"title": title, "url": (item.findtext("link") or "").strip(),
                        "source": source, "published": published})
        if len(out) >= limit:
            break
    return out


def load_series(data_dir, ind_id):
    path = Path(data_dir) / "series" / f"{ind_id}.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    return pd.Series(d["values"], index=pd.to_datetime(d["dates"]), dtype=float)


def load_previous_notes(base_url, ind_id, session):
    if not base_url:
        return {}
    try:
        r = session.get(f"{base_url.rstrip('/')}/notes/{ind_id}.json", timeout=20)
        if r.status_code != 200:
            return {}
        return {e["date"]: e for e in r.json().get("events", [])}
    except Exception:  # noqa: BLE001
        return {}


def build_notes(registry, data_dir, previous_url=None, search=google_news,
                load_previous=load_previous_notes, session=None, sleep=0.5, log=print):
    session = session or collect._session()
    out_dir = Path(data_dir) / "notes"
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = {"events": 0, "searched": 0, "cached": 0, "failed": 0, "pending": 0}

    notes, queue = {}, []
    for ind in registry["indicators"]:
        s = load_series(data_dir, ind["id"])
        if s is None:
            continue
        prev = load_previous(previous_url, ind["id"], session)
        evs = []
        for d, ch, sg in find_events(s, ind):
            key = d.strftime("%Y-%m-%d")
            ev = {"date": key, "change": None if ch is None else round(ch, 4), "sigma": sg, "headlines": []}
            if prev.get(key, {}).get("headlines"):
                ev["headlines"] = prev[key]["headlines"]
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
            ev["headlines"] = search(ind.get("news", ind["name"]), d, session)
            stats["searched"] += 1
        except Exception as e:  # noqa: BLE001
            stats["failed"] += 1
            log(f"  뉴스 검색 실패 {ind['id']} {d:%Y-%m-%d}: {str(e)[:120]}")
        if sleep:
            time.sleep(sleep)

    for ind_id, (ind, evs) in notes.items():
        stats["events"] += len(evs)
        with open(out_dir / f"{ind_id}.json", "w", encoding="utf-8") as f:
            json.dump({"id": ind_id, "query": ind.get("news", ind["name"]), "events": evs},
                      f, ensure_ascii=False, separators=(",", ":"))
    log(f"뉴스: 시점 {stats['events']}개 · 새로 검색 {stats['searched']} · 재사용 {stats['cached']} · "
        f"실패 {stats['failed']} · 다음 실행으로 미룸 {stats['pending']}")
    return stats


def main(argv):
    data_dir = argv[1] if len(argv) > 1 else "site/data"
    build_notes(collect.load_registry(), data_dir, os.environ.get("PREVIOUS_DATA_URL", "").strip() or None)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
