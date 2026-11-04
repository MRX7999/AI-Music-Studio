"""1.2.3: aigm-detector result parsing (ai_probability / model_scores) and the default ensemble name."""
from __future__ import annotations

import json
import stat
import sys
import textwrap

import numpy as np
import pytest
import soundfile as sf

from studio import detect, tools

# what `aigm-detector predict song.wav --json` prints at commit 83db9ac (cli.py + EnsembleResult.to_dict)
REAL = {
    "file": "/Users/me/Music/AI Music Studio/releases/night-drive-2026-11-04/master.wav",
    "verdict": "AI", "ai_probability": 0.8125, "threshold": 0.5, "backend": "mlx",
    "model_scores": {"spectttra-alpha-120s": 0.625, "fakeprint": 1.0},
    "models": {"spectttra-alpha-120s": {"score": 0.625, "backend": "mlx", "processing_time_ms": 90.1,
                                        "window_scores": [0.625]},
               "fakeprint": {"score": 1.0, "backend": "torch", "processing_time_ms": 6.0, "window_scores": None}},
    "dominant_signal": "fakeprint", "processing_time_ms": 120.4, "warnings": [],
}
STATUS = ("Models: spectttra-alpha-120s, fakeprint · backend: mlx · tier: full\n"
          "Loading /Users/me/Music/AI Music \nStudio/releases/night-drive-2026-11-04/master.wav...\n")


@pytest.fixture(autouse=True)
def clean_tool_config():
    old = (dict(tools.CONFIG.overrides), dict(tools.CONFIG.backends))
    yield
    tools.CONFIG.overrides, tools.CONFIG.backends = old


def test_parse_current_output():
    r = detect.parse_aigm_output(STATUS + json.dumps(REAL, indent=2) + "\n")
    assert r["score"] == 0.8125 and r["verdict"] == "AI"
    assert r["models"] == {"spectttra-alpha-120s": 0.625, "fakeprint": 1.0}
    assert "warnings" not in r


def test_parse_list_warnings_and_noise_around():
    two = [dict(REAL, warnings=["Only one model ran: results are less reliable"]), dict(REAL, ai_probability=0.1)]
    noisy = "Fetching 2 files: 100%|██| 2/2 {eta}\n" + STATUS + json.dumps(two, indent=2) + "\nBye {x}\n"
    r = detect.parse_aigm_output(noisy)
    assert r["score"] == 0.8125 and r["warnings"] == ["Only one model ran: results are less reliable"]


def test_parse_models_only_and_old_format():
    only = {"models": {"fakeprint": {"score": 0.25}}, "warnings": []}
    assert detect.parse_aigm_output(json.dumps(only))["score"] == 0.25
    old = {"ensemble_score": 0.4, "individual_results": [{"model_name": "x", "score": 0.4}]}
    r = detect.parse_aigm_output(json.dumps(old))
    assert r["score"] == 0.4 and r["models"] == {"x": 0.4}


def test_parse_errors_are_readable():
    with pytest.raises(RuntimeError, match="no JSON result.*Error: CUDA"):
        detect.parse_aigm_output("Models: fakeprint\nError: CUDA not available\n")
    with pytest.raises(RuntimeError, match="no JSON result"):
        detect.parse_aigm_output('{"verdict": "AI"}')


def test_check_runs_the_cli_with_the_default_ensemble(tmp_path):
    log = tmp_path / "argv.json"
    exe = tmp_path / "aigm-detector"
    exe.write_text(f"#!{sys.executable}\n" + textwrap.dedent(f"""
        import json, os, sys
        json.dump({{"argv": sys.argv[1:], "columns": os.environ.get("COLUMNS")}}, open({str(log)!r}, "w"))
        data = {REAL!r}
        try:
            from rich.console import Console      # the real CLI prints through rich
            c = Console()
            c.print({STATUS.splitlines()[0]!r})
            c.print("Loading " + sys.argv[2] + "...")
            c.print_json(data=dict(data, file=sys.argv[2]))
        except ImportError:
            print({STATUS!r})
            print(json.dumps(dict(data, file=sys.argv[2]), indent=2))
    """), encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    tools.CONFIG.update({"tools": {"aigm": {"path": str(exe)}}})
    wav = tmp_path / "a song with spaces.wav"
    sf.write(wav, np.zeros((44100 * 2, 2), np.float32), 44100)
    rep = detect.check(wav, ["aigm"])
    res = rep["results"]["aigm"]
    assert res["ok"] is True, res
    assert res["score"] == 0.8125 and res["flagged"] is True and res["models"]["fakeprint"] == 1.0
    seen = json.loads(log.read_text())
    assert seen["argv"][:2] == ["predict", str(wav)]
    assert seen["argv"][seen["argv"].index("--models") + 1] == "default"
    assert "--json" in seen["argv"] and seen["columns"] == "1000"
