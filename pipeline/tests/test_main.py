import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect  # noqa: E402
from fakes import fake_fred, fake_lme, fake_yahoo  # noqa: E402


def test_main_writes_output(monkeypatch, tmp_path, capsys):
    original = collect.collect
    monkeypatch.setattr(collect, "collect", lambda reg, **kw: original(
        reg, fetch_fred=fake_fred, fetch_yahoo=fake_yahoo, fetch_lme=fake_lme, log=lambda *_: None))
    assert collect.main(["--out", str(tmp_path)]) == 0
    assert (tmp_path / "latest.json").exists()
    assert "코스피" in capsys.readouterr().out
