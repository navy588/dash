"""수집 결과 요약을 출력합니다 (워크플로 로그·요약용).

    python pipeline/summary.py site/data
"""
import json
import sys
from pathlib import Path


def summarize(data_dir):
    d = Path(data_dir)
    lines = []
    latest = json.loads((d / "latest.json").read_text(encoding="utf-8"))
    bad = [f"{i['id']}({i['status']})" for i in latest["indicators"] if i["status"] != "ok"]
    lines.append(f"지표 {len(latest['indicators'])}개 · 정상 {latest['counts'].get('ok')} · 문제 {', '.join(bad) or '없음'}")
    for i in latest["indicators"]:
        if i.get("last"):
            lines.append(f"  {i['id']}: {i['last']['date']} {i['last']['value']:.4g}")
    notes = list((d / "notes").glob("*.json")) if (d / "notes").exists() else []
    if notes:
        with_h = 0
        for p in notes:
            ev = json.loads(p.read_text(encoding="utf-8"))["events"]
            if ev and ev[-1]["headlines"]:
                with_h += 1
                lines.append(f"  뉴스 {p.stem}: {ev[-1]['date']} {ev[-1]['headlines'][0]['title'][:60]}")
        lines.append(f"최근 시점에 뉴스가 붙은 지표 {with_h}/{len(notes)}")
    bp = d / "briefing.json"
    if bp.exists():
        b = json.loads(bp.read_text(encoding="utf-8"))
        lines.append(f"브리핑: {b['headline']} · 카드 {[s['id'] for s in b['stories']]}")
    mp = d / "breakdown" / "markets.json"
    if mp.exists():
        for m in json.loads(mp.read_text(encoding="utf-8"))["markets"]:
            top = ", ".join(f"{x['n']} {x['w']:.1f}% {x['chg']['prev']:+.2f}%" for x in m["items"][:3])
            lines.append(f"시장 지도 {m['name']} {len(m['items'])}종목 ({m['as_of']}): {top}")
    for k in ("ust10y", "cpi", "gdp"):
        p = d / "breakdown" / f"{k}.json"
        if p.exists():
            for c in json.loads(p.read_text(encoding="utf-8"))["charts"]:
                parts = ", ".join(f"{x['name']} {x['values'][-1]:.2f}" for x in c["parts"])
                lines.append(f"분해 {k} {c['dates'][-1]}: {c['total']['name']} {c['total']['values'][-1]:.2f} = {parts}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summarize(sys.argv[1] if len(sys.argv) > 1 else "site/data"))
