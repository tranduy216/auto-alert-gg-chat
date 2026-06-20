"""Backtest data cache — save/load backtest results for reuse.

Directory: backtest_data/<run_id>/
  - meta.json:     config hash, timestamp, description, git SHA
  - config.json:   full strategy config
  - summary.json:  per-coin CAGR, DD, SLr, yearly returns
  - trades.json:   every trade (entry/exit/direction/roi/exit_reason/regime)
  - equity.json:   per-bar equity curve (optional, large)

Usage:
    from scripts.utils.backtest_cache import save_run, load_run, find_run_by_config

    run_id = save_run(config, summary, trades, desc="baseline v10")
    run = load_run(run_id)
"""

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "backtest_data"
DATA_DIR.mkdir(exist_ok=True)


def config_hash(config: dict) -> str:
    """Stable hash of a config dict (sort keys, ignore order)."""
    s = json.dumps(config, sort_keys=True, default=str)
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"],
                                       cwd=ROOT, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "unknown"


def _next_run_id() -> str:
    """YYYYMMDD-HHMMSS-<short-hash>."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return ts


def save_run(config: dict, summary: dict, trades: list[dict],
             desc: str = "", equity: list | None = None) -> str:
    """Save a backtest run. Returns the run_id."""
    cfg_h = config_hash(config)

    # Look for identical config → don't duplicate
    existing = find_run_by_config(cfg_h)
    if existing:
        print(f"[cache] identical config already saved as {existing}")
        return existing

    run_id = _next_run_id()
    run_dir = DATA_DIR / run_id
    run_dir.mkdir(parents=True)

    meta = {
        "run_id": run_id,
        "config_hash": cfg_h,
        "description": desc,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    (run_dir / "config.json").write_text(json.dumps(config, indent=2, default=str))
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (run_dir / "trades.json").write_text(json.dumps(trades, indent=2, default=str))
    if equity is not None:
        (run_dir / "equity.json").write_text(json.dumps(equity, default=str))

    print(f"[cache] saved run {run_id} → {run_dir}")
    return run_id


def load_run(run_id: str) -> dict[str, Any]:
    run_dir = DATA_DIR / run_id
    if not run_dir.is_dir():
        raise FileNotFoundError(f"no run {run_id}")
    out = {}
    for name in ("meta", "config", "summary", "trades"):
        p = run_dir / f"{name}.json"
        if p.exists():
            out[name] = json.loads(p.read_text())
    eq = run_dir / "equity.json"
    if eq.exists():
        out["equity"] = json.loads(eq.read_text())
    return out


def list_runs() -> list[dict]:
    runs = []
    if not DATA_DIR.exists():
        return runs
    for d in sorted(DATA_DIR.iterdir()):
        if d.is_dir():
            meta = d / "meta.json"
            if meta.exists():
                runs.append(json.loads(meta.read_text()))
    return runs


def find_run_by_config(cfg_h: str) -> str | None:
    for run in list_runs():
        if run.get("config_hash") == cfg_h:
            return run["run_id"]
    return None
