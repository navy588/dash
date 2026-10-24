"""수집 결과로 한국어 일일 브리핑을 만듭니다. AI 없이 규칙으로 해석합니다.

    python pipeline/briefing.py site/data     # site/data/briefing.json, briefing.md 생성

카드에 이미 있는 숫자를 다시 나열하지 않고, 다음을 문장으로 묶습니다.
- 오늘의 이야기: 평소보다 크게 움직인 지표와 그날의 뉴스 헤드라인(notes/, pipeline/news.py가 생성)
- 시장 해석: 위험선호/위험회피 판정, 미 국채 커브 모양(불·베어 스티프닝/플래트닝), 유가와 금리의 조합
- 눈여겨볼 점: 52주 신고가·신저가, 5거래일 이상 연속 상승·하락, 연초 대비 최고·최저 자산, 전망치와 실제치 차이
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

SIGMA_THRESHOLD = 2      # 이 배수 이상이면 '큰 움직임'
MIN_STORIES = 3          # 큰 움직임이 적은 날도 이만큼은 상위 변동 지표로 채움
MAX_STORIES = 5
STREAK_DAYS = 5
YEAR_OBS = 250           # 52주 ≈ 250거래일
STALE_DAYS = {"daily": 5, "weekly": 12, "monthly": 75, "quarterly": 200}

# 상승/하락이 무엇을 뜻하는지 (환율은 표기 방향에 따라 의미가 반대)
MEANING = {
    "usdkrw": ("원화 약세", "원화 강세"),
    "jpykrw": ("엔화 대비 원화 약세", "엔화 대비 원화 강세"),
    "usdjpy": ("엔화 약세", "엔화 강세"),
    "usdcny": ("위안화 약세", "위안화 강세"),
    "eurusd": ("유로 강세", "유로 약세"),
    "gbpusd": ("파운드 강세", "파운드 약세"),
    "dxy": ("달러 강세", "달러 약세"),
    "vix": ("시장 불안 확대", "시장 불안 완화"),
}

# 위험회피일 때 오르는(+1) / 내리는(-1) 지표
RISK_OFF = {"spx": -1, "nasdaq": -1, "kospi": -1, "vix": +1, "gold": +1, "ust10y": -1, "dxy": +1,
            "usdkrw": +1, "bitcoin": -1, "copper": -1}
# 아래 크기보다 작은 변화는 방향 판단에서 무시 (pct는 %, bp는 bp, abs는 원 단위)
NOISE = {"pct": 0.15, "bp": 2.0, "abs": 0.3, "pp": 0.05}
# 연초 대비 순위에 넣을 자산 (가격형 지표)
RANKED_GROUPS = ("korea", "us", "global", "commodity")


# ── 표기 ────────────────────────────────────────────────────

def _num(v, d):
    return f"{v:,.{d}f}"


def fmt_value(ind, v):
    d = ind.get("decimals", 2)
    if ind["unit"] == "$":
        return "$" + _num(v, d)
    unit = "" if ind["unit"] == "pt" else ind["unit"]
    return _num(v, d) + (" " + unit if (" " in unit or "/" in unit) else unit)


def fmt_change(ind, v, signed=False):
    a = abs(v)
    kind = ind["change"]
    if kind == "pct":
        s = f"{a:.2f}%"
    elif kind == "bp":
        s = f"{a:.0f}bp" if a >= 100 else f"{a:.1f}bp"
    elif kind == "pp":
        s = f"{a:.2f}%p"
    else:
        s = fmt_value(ind, a)
    if signed:
        return ("+" if v > 0 else "−" if v < 0 else "") + s
    return s


def _arrow(v):
    return "▲" if v > 0 else "▼" if v < 0 else "–"


def _verb(ind, v, big):
    if ind["id"] in MEANING:
        return MEANING[ind["id"]][0 if v > 0 else 1]
    if ind["change"] == "bp":
        return "금리 상승" if v > 0 else "금리 하락"
    if big:
        return "급등" if v > 0 else "급락"
    return "상승" if v > 0 else "하락"


# ── 입력 ────────────────────────────────────────────────────

def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_series(data_dir, ids):
    out = {}
    for i in ids:
        d = _load_json(Path(data_dir) / "series" / f"{i}.json")
        if d and d.get("dates"):
            out[i] = pd.Series(d["values"], index=pd.to_datetime(d["dates"]), dtype=float)
    return out


def load_notes(data_dir, ids):
    """{id: {date: [headlines]}} — 헤드라인이 있는 날짜만."""
    out = {}
    for i in ids:
        d = _load_json(Path(data_dir) / "notes" / f"{i}.json")
        if d:
            out[i] = {e["date"]: e["headlines"] for e in d.get("events", []) if e.get("headlines")}
    return out


# ── 해석 ────────────────────────────────────────────────────

def _prev(it):
    c = it["changes"].get("prev")
    return None if c is None else c["value"]


def _sig(ind, v):
    """잡음보다 큰 변화의 방향 (+1/-1/0)."""
    if v is None or abs(v) < NOISE.get(ind["change"], 0):
        return 0
    return 1 if v > 0 else -1


def market_mood(defs, fresh):
    """주식·VIX·금·금리·달러·코인 방향을 모아 위험선호/위험회피를 판정."""
    votes, off, on = 0, [], []
    for k, risk_off_dir in RISK_OFF.items():
        if k not in fresh:
            continue
        d = _sig(defs[k], _prev(fresh[k]))
        if not d:
            continue
        label = f"{defs[k]['name']}{_arrow(d)}"
        if d == risk_off_dir:
            votes += 1
            off.append(label)
        else:
            votes -= 1
            on.append(label)
    if votes >= 3:
        return "위험회피", f"위험회피 분위기: {', '.join(off[:5])}"
    if votes <= -3:
        return "위험선호", f"위험선호 분위기: {', '.join(on[:5])}"
    if off or on:
        return "혼조", "뚜렷한 방향 없는 혼조: " + ", ".join((off + on)[:5])
    return None, None


def curve_read(defs, fresh):
    """미 국채 2년·10년 변화로 커브 모양을 이름 붙입니다."""
    if "ust2y" not in fresh or "ust10y" not in fresh:
        return None
    a, b = fresh["ust2y"], fresh["ust10y"]
    if a["last"]["date"] != b["last"]["date"]:
        return None
    d2, d10 = _prev(a), _prev(b)
    if d2 is None or d10 is None or (abs(d2) < 2 and abs(d10) < 2):
        return None
    spread = b["last"]["value"] - a["last"]["value"]
    tilt = d10 - d2
    level = "불" if (d2 + d10) < 0 else "베어"
    if abs(tilt) < 1.5:
        shape = f"커브는 거의 평행 이동({'금리 하락' if level == '불' else '금리 상승'})"
    elif tilt > 0:
        shape = f"{level} 스티프닝(장기 금리가 더 {'적게 내림' if level == '불' else '많이 오름'})"
    else:
        shape = f"{level} 플래트닝(장기 금리가 더 {'많이 내림' if level == '불' else '적게 오름'})"
    why = {"불 스티프닝": "금리 인하 기대가 커질 때 흔한 모양",
           "불 플래트닝": "경기 둔화·안전자산 선호가 커질 때 흔한 모양",
           "베어 스티프닝": "재정·인플레이션 부담으로 장기물이 밀릴 때 흔한 모양",
           "베어 플래트닝": "긴축 기대가 커질 때 흔한 모양"}
    key = next((k for k in why if shape.startswith(k)), None)
    text = (f"미 국채 2년 {_arrow(d2)}{abs(d2):.1f}bp, 10년 {_arrow(d10)}{abs(d10):.1f}bp → {shape}"
            f"{', ' + why[key] if key else ''}. 10년-2년 차이 {spread:+.2f}%p")
    if spread < 0:
        text += " (역전 상태)"
    return text


def oil_rates_read(defs, fresh):
    if "wti" not in fresh or "ust10y" not in fresh:
        return None
    o, r = _prev(fresh["wti"]), _prev(fresh["ust10y"])
    if o is None or r is None or abs(o) < 1.5 or abs(r) < 4:
        return None
    pair = f"WTI {_arrow(o)}{abs(o):.1f}%와 미 10년 금리 {_arrow(r)}{abs(r):.0f}bp"
    if o > 0 and r < 0:
        return f"{pair}가 겹침 → 공급 충격이 성장을 누를 것이라는 해석 쪽"
    if o > 0 and r > 0:
        return f"{pair}가 겹침 → 인플레이션 우려 쪽"
    if o < 0 and r < 0:
        return f"{pair}가 겹침 → 수요 둔화 우려 쪽"
    return f"{pair} → 유가 하락이 물가 부담을 덜어 주는 쪽"


def context_notes(ind, s):
    """52주 신고가·신저가와 연속 상승·하락 일수."""
    out = []
    if s is None or len(s) < 30:
        return out
    year = s.iloc[-YEAR_OBS:]
    last = s.iloc[-1]
    if len(year) >= YEAR_OBS // 2:
        if last >= year.max() and year.iloc[:-1].max() < last:
            out.append("52주 신고가")
        elif last <= year.min() and year.iloc[:-1].min() > last:
            out.append("52주 신저가")
    diffs = s.diff().iloc[::-1].dropna()
    sign = 0
    n = 0
    for v in diffs:
        cur = 1 if v > 0 else -1 if v < 0 else 0
        if cur == 0 or (sign and cur != sign):
            break
        sign = cur
        n += 1
    if n >= STREAK_DAYS:
        unit = {"daily": "거래일", "weekly": "주", "monthly": "개월"}.get(ind["freq"], "번")
        out.append(f"{n}{unit} 연속 {'상승' if sign > 0 else '하락'}")
    return out


def _outdated(ind, item, today):
    last = datetime.strptime(item["last"]["date"], "%Y-%m-%d").date()
    return (today - last).days > STALE_DAYS[ind["freq"]]


def build(registry, latest, series=None, notes=None, today=None):
    series = series or {}
    notes = notes or {}
    today = today or datetime.now(timezone.utc).date()
    defs = {i["id"]: i for i in registry["indicators"]}
    items = {it["id"]: it for it in latest["indicators"] if it.get("last") and it["id"] in defs}
    fresh = {k: it for k, it in items.items() if it["status"] == "ok" and not _outdated(defs[k], it, today)}

    daily_dates = [it["last"]["date"] for k, it in fresh.items() if defs[k]["freq"] == "daily"]
    as_of = max(daily_dates) if daily_dates else today.isoformat()

    # 1) 오늘의 이야기: 큰 움직임 순, 적으면 상위 변동으로 채움
    ranked = sorted((it for k, it in fresh.items()
                     if defs[k]["freq"] in ("daily", "weekly") and it.get("sigma") is not None
                     and _prev(it) is not None and k != "t10y2y"),
                    key=lambda it: -abs(it["sigma"]))
    big = [it for it in ranked if abs(it["sigma"]) >= SIGMA_THRESHOLD][:MAX_STORIES]
    picked = big + [it for it in ranked if it not in big and abs(it["sigma"]) >= 1][:max(0, MIN_STORIES - len(big))]

    stories = []
    for it in picked:
        ind = defs[it["id"]]
        v = _prev(it)
        is_big = abs(it["sigma"]) >= SIGMA_THRESHOLD
        text = (f"{ind['name']} {fmt_value(ind, it['last']['value'])}, {_arrow(v)}{fmt_change(ind, v)} "
                f"{_verb(ind, v, is_big)} (평소 하루 변동의 {abs(it['sigma']):.1f}배)")
        ctx = context_notes(ind, series.get(it["id"]))
        if ctx:
            text += " · " + ", ".join(ctx)
        heads = notes.get(it["id"], {}).get(it["last"]["date"], [])[:2]
        stories.append({"id": it["id"], "big": is_big, "text": text,
                        "headlines": [{k: h.get(k) for k in ("title", "url", "source")} for h in heads]})

    # 2) 시장 해석
    mood, mood_text = market_mood(defs, fresh)
    reads = [t for t in (mood_text, curve_read(defs, fresh), oil_rates_read(defs, fresh)) if t]

    # 3) 눈여겨볼 점: 이야기에 없는 지표의 신고가·연속 흐름, 연초 대비 순위, 전망 대비
    shown = {s["id"] for s in stories}
    signals = []
    for k, it in fresh.items():
        if k in shown or defs[k]["freq"] != "daily":
            continue
        for c in context_notes(defs[k], series.get(k)):
            signals.append((0 if "52주" in c else 1, f"{defs[k]['name']} {c} ({fmt_value(defs[k], it['last']['value'])})"))
    signals = [t for _, t in sorted(signals)[:6]]

    ytd = [(it["changes"]["ytd"]["value"], k) for k, it in fresh.items()
           if defs[k]["group"] in RANKED_GROUPS and defs[k]["change"] == "pct" and it["changes"].get("ytd")]
    if len(ytd) >= 4:
        ytd.sort()
        top, bottom = ytd[-1], ytd[0]
        signals.append(f"올해 가장 많이 오른 자산: {defs[top[1]]['name']} {top[0]:+.1f}% · "
                       f"가장 부진한 자산: {defs[bottom[1]]['name']} {bottom[0]:+.1f}%")

    for k, it in items.items():
        fc = it.get("forecast")
        if not fc or not fc.get("points") or it["status"] == "missing":
            continue
        ind = defs[k]
        target = fc["points"][0]
        gap = it["last"]["value"] - target["value"]
        when = target["date"][:4] + "년 말" if fc["label"].startswith("FOMC") else "이번 분기"
        signals.append(f"{ind['name']} 현재 {fmt_value(ind, it['last']['value'])}, "
                       f"{fc['label'].split('(')[0]} {when} {fmt_value(ind, target['value'])} "
                       f"(차이 {gap:+.2f}%p)")

    # 헤드라인 한 줄
    lead = stories[0] if stories else None
    if lead and lead["big"]:
        ind = defs[lead["id"]]
        v = _prev(fresh[lead["id"]])
        first = f"{ind['name']} {_arrow(v)}{fmt_change(ind, v)} {_verb(ind, v, True)}"
        others = [defs[s["id"]]["name"] for s in stories[1:] if s["big"]]
        headline = first + (f", {', '.join(others[:2])}도 크게 움직임" if others else "")
    else:
        headline = "평소 범위를 벗어난 큰 움직임 없이 조용한 하루"
    if mood in ("위험회피", "위험선호"):
        headline = f"{mood} · " + headline

    stale = [defs[k]["name"] for k, it in items.items() if it["status"] != "ok"]
    return {
        "as_of": as_of,
        "generated_at": latest.get("generated_at"),
        "headline": headline,
        "mood": mood,
        "stories": stories,
        "reads": reads,
        "signals": signals,
        "stale": stale,
    }


def to_markdown(brief):
    lines = [f"# 일일 경제 브리핑 ({brief['as_of']})", "", f"**{brief['headline']}**", ""]
    if brief["stories"]:
        lines += ["## 무엇이 왜 움직였나", ""]
        for s in brief["stories"]:
            lines.append(f"- {s['text']}")
            lines += [f"  - [{h['title']}]({h['url']})" + (f" — {h['source']}" if h.get("source") else "")
                      for h in s["headlines"]]
        lines.append("")
    if brief["reads"]:
        lines += ["## 시장 해석", ""] + [f"- {t}" for t in brief["reads"]] + [""]
    if brief["signals"]:
        lines += ["## 눈여겨볼 점", ""] + [f"- {t}" for t in brief["signals"]] + [""]
    if brief["stale"]:
        lines += [f"> 이번에 새로 받지 못해 이전 데이터를 쓴 지표: {', '.join(brief['stale'])}", ""]
    lines.append(f"_큰 움직임: 직전 대비 변화가 최근 1년 하루 변동폭(표준편차)의 {SIGMA_THRESHOLD}배 이상. "
                 "해석은 규칙 기반이며 헤드라인은 Google 뉴스에서 자동으로 붙입니다._")
    return "\n".join(lines) + "\n"


def write(data_dir, today=None):
    out = Path(data_dir)
    registry = json.loads((out / "indicators.json").read_text(encoding="utf-8"))
    latest = json.loads((out / "latest.json").read_text(encoding="utf-8"))
    ids = [i["id"] for i in registry["indicators"]]
    brief = build(registry, latest, load_series(out, ids), load_notes(out, ids), today)
    (out / "briefing.json").write_text(json.dumps(brief, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    md = to_markdown(brief)
    (out / "briefing.md").write_text(md, encoding="utf-8")
    return md


if __name__ == "__main__":
    print(write(sys.argv[1] if len(sys.argv) > 1 else "site/data"))
