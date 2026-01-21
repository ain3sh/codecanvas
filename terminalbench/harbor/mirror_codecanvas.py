from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path


def _mirror_artifacts(*, runs_dir: Path, job_name: str, task_id: str) -> None:
    job_dir = runs_dir / job_name
    if not job_dir.exists():
        return

    canvas_root = runs_dir.parent / "canvas"
    try:
        canvas_root.mkdir(parents=True, exist_ok=True)
    except Exception:
        return

    try:
        trial_dirs = [
            d for d in job_dir.iterdir() if d.is_dir() and d.name.startswith(f"{task_id}__") and (d / "agent").exists()
        ]
    except Exception:
        return

    for trial_dir in trial_dirs:
        src = trial_dir / "agent" / "sessions" / "codecanvas"
        if not src.exists():
            continue
        dst = canvas_root / trial_dir.name
        try:
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        except Exception:
            continue


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirror CodeCanvas artifacts after a Harbor run finishes.")
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    args = parser.parse_args()

    runs_dir = args.runs_dir.resolve()
    job_dir = runs_dir / args.job_name
    if not job_dir.exists():
        return 0

    deadline = time.time() + max(5.0, args.timeout_seconds)
    result_path = job_dir / "result.json"
    while time.time() < deadline:
        if result_path.exists():
            _mirror_artifacts(runs_dir=runs_dir, job_name=args.job_name, task_id=args.task_id)
            return 0
        time.sleep(max(0.2, args.poll_seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
