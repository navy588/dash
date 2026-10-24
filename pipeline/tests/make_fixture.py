"""가짜 데이터로 site/data를 만듭니다 (네트워크 없이 화면 확인용).

    python pipeline/tests/make_fixture.py site/data
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect  # noqa: E402
from fakes import fake_fred, fake_yahoo  # noqa: E402

if __name__ == "__main__":
    reg = collect.load_registry()
    latest, series = collect.collect(reg, fetch_fred=fake_fred, fetch_yahoo=fake_yahoo)
    collect.write_output(sys.argv[1] if len(sys.argv) > 1 else "site/data", reg, latest, series)
