"""수집 결과 중 직전 배포 때도 실패했던 지표(연속 실패)를 GitHub Actions 출력 형식으로 씁니다.

    python pipeline/health.py <직전 배포 data URL> >> "$GITHUB_OUTPUT"

한 번 실패는 일시적 장애일 수 있어 알리지 않고, 두 번 연속일 때만 problems에 넣습니다.
"""
import json
import sys

import requests


def persistent_problems(current, previous):
    prev_bad = {i["id"] for i in (previous or {}).get("indicators", []) if i["status"] != "ok"}
    return [f"{i['id']} ({i['status']}: {i.get('error', '')})"
            for i in current["indicators"] if i["status"] != "ok" and i["id"] in prev_bad]


def main(argv):
    with open("site/data/latest.json", encoding="utf-8") as f:
        current = json.load(f)
    previous = None
    if len(argv) > 1:
        try:
            r = requests.get(f"{argv[1].rstrip('/')}/latest.json", timeout=30)
            previous = r.json() if r.ok else None
        except Exception:  # noqa: BLE001
            previous = None
    print(f"ok={current['counts']['ok']}")
    print("problems=" + json.dumps(persistent_problems(current, previous), ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv)
