"""수집 결과(latest.json)로 한국어 일일 브리핑을 만듭니다.

    python pipeline/briefing.py site/data     # site/data/briefing.json, briefing.md 생성

화면의 '오늘의 큰 움직임'과 같은 기준(직전 대비 변화가 최근 1년 변동폭의 2σ 이상)으로
큰 변동 지표를 골라 앞에 두고, 분야별로 대표 지표의 움직임을 한 문장씩 요약합니다.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SIGMA_THRESHOLD = 2
MAX_MOVERS = 5
STALE_DAYS = {"daily": 5, "weekly": 12, "monthly": 75, "quarterly": 200}
FREQ_PREV = {"daily": "전일", "weekly": "전주", "monthly": "전월", "quarterly": "전분기"}

# 분야별 요약에 쓸 대표 지표 (없으면 그 분야의 앞쪽 지표 두 개)
HEADLINERS = {
    "korea": ["kospi", "kosdaq", "usdkrw"],
    "us": ["spx", "nasdaq", "vix"],
    "global": ["nikkei", "shanghai", "stoxx50"],
    "fx": ["dxy", "usdjpy", "eurusd"],
    "rates": ["ust2y", "ust10y"],
    "commodity": ["wti", "gold", "bitcoin"],
    "macro": ["cpi", "unrate"],
}

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


def _num(v, d):
    return f"{v:,.{d}f}"


def fmt_value(ind, v):
    d = ind.get("decimals", 2)
    if ind["unit"] == "$":
        return "$" + _num(v, d)
    unit = "" if ind["unit"] == "pt" else ind["unit"]
    return _num(v, d) + (" " + unit if " " in unit else unit)


def fmt_change(ind, v):
    a = abs(v)
    kind = ind["change"]
    if kind == "pct":
        return f"{a:.2f}%"
    if kind == "bp":
        return f"{a:.0f}bp" if a >= 100 else f"{a:.1f}bp"
    if kind == "pp":
        return f"{a:.2f}%p"
    return fmt_value(ind, a)


def direction(v):
    if abs(v) < 1e-9:
        return "보합", "–"
    return ("상승", "▲") if v > 0 else ("하락", "▼")


def _outdated(ind, item, today):
    last = datetime.strptime(item["last"]["date"], "%Y-%m-%d").date()
    return (today - last).days > STALE_DAYS[ind["freq"]]


def _describe(ind, item):
    """'코스피 2,612.34(▼1.20%)' 형태."""
    c = item["changes"].get("prev")
    s = f"{ind['name']} {fmt_value(ind, item['last']['value'])}"
    if c:
        word, arrow = direction(c["value"])
        s += f"({arrow}{fmt_change(ind, c['value'])})" if word != "보합" else "(보합)"
    return s


def _meaning(ind, v):
    if ind["id"] in MEANING:
        return MEANING[ind["id"]][0 if v > 0 else 1]
    if ind["change"] == "bp":
        return "금리 상승" if v > 0 else "금리 하락"
    return "급등" if v > 0 else "급락"


def build(registry, latest, today=None):
    today = today or datetime.now(timezone.utc).date()
    defs = {i["id"]: i for i in registry["indicators"]}
    items = {it["id"]: it for it in latest["indicators"] if it.get("last") and it["id"] in defs}
    fresh = {k: it for k, it in items.items() if it["status"] == "ok" and not _outdated(defs[k], it, today)}

    daily_dates = [it["last"]["date"] for k, it in fresh.items() if defs[k]["freq"] == "daily"]
    as_of = max(daily_dates) if daily_dates else today.isoformat()

    movers = sorted(
        (it for k, it in fresh.items()
         if defs[k]["freq"] in ("daily", "weekly") and it.get("sigma") is not None
         and abs(it["sigma"]) >= SIGMA_THRESHOLD and it["changes"].get("prev")),
        key=lambda it: -abs(it["sigma"]))[:MAX_MOVERS]

    highlights = []
    for it in movers:
        ind = defs[it["id"]]
        v = it["changes"]["prev"]["value"]
        highlights.append({
            "id": it["id"],
            "text": f"{_describe(ind, it)} — 평소의 {abs(it['sigma']):.1f}배 움직임, {_meaning(ind, v)}",
        })

    if movers:
        names = ", ".join(f"{defs[it['id']]['name']}({direction(it['changes']['prev']['value'])[0]})" for it in movers[:3])
        headline = f"평소보다 크게 움직인 지표 {len(movers)}개: {names}"
    else:
        headline = "평소 범위를 벗어난 큰 움직임 없이 조용한 하루였습니다"

    sections = []
    for g in registry["groups"]:
        ids = [i for i in HEADLINERS.get(g["id"], []) if i in fresh]
        if not ids:
            ids = [i["id"] for i in registry["indicators"] if i["group"] == g["id"] and i["id"] in fresh][:2]
        if not ids:
            continue
        parts = [_describe(defs[i], fresh[i]) for i in ids]
        if g["id"] == "macro":
            parts = [f"{p} [{fresh[i]['last']['date'][:7]} 기준, {FREQ_PREV[defs[i]['freq']]} 대비]" for p, i in zip(parts, ids)]
        sections.append({"group": g["id"], "name": g["name"], "text": ", ".join(parts)})

    stale = [defs[k]["name"] for k, it in items.items() if it["status"] != "ok"]
    return {
        "as_of": as_of,
        "generated_at": latest.get("generated_at"),
        "headline": headline,
        "highlights": highlights,
        "sections": sections,
        "stale": stale,
    }


def to_markdown(brief):
    lines = [f"# 일일 경제 브리핑 ({brief['as_of']})", "", f"**{brief['headline']}**", ""]
    if brief["highlights"]:
        lines += ["## 큰 움직임", ""] + [f"- {h['text']}" for h in brief["highlights"]] + [""]
    lines += ["## 분야별 요약", ""] + [f"- **{s['name']}**: {s['text']}" for s in brief["sections"]] + [""]
    if brief["stale"]:
        lines += [f"> 이번에 새로 받지 못해 이전 데이터를 쓴 지표: {', '.join(brief['stale'])}", ""]
    lines.append(f"_큰 움직임: 직전 대비 변화가 최근 1년 변동폭(표준편차)의 {SIGMA_THRESHOLD}배 이상인 일간·주간 지표_")
    return "\n".join(lines) + "\n"


def write(data_dir, today=None):
    out = Path(data_dir)
    registry = json.loads((out / "indicators.json").read_text(encoding="utf-8"))
    latest = json.loads((out / "latest.json").read_text(encoding="utf-8"))
    brief = build(registry, latest, today)
    (out / "briefing.json").write_text(json.dumps(brief, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    md = to_markdown(brief)
    (out / "briefing.md").write_text(md, encoding="utf-8")
    return md


if __name__ == "__main__":
    print(write(sys.argv[1] if len(sys.argv) > 1 else "site/data"))
