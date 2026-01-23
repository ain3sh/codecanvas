from __future__ import annotations

import argparse
import shutil
import threading
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


def _mirror_artifacts(
    *,
    runs_dir: Path,
    job_name: str,
    targets: list[str],
    dest_dirname: str,
) -> None:
    job_dir = runs_dir / job_name
    if not job_dir.exists():
        return

    artifacts_root = runs_dir.parent / dest_dirname
    try:
        artifacts_root.mkdir(parents=True, exist_ok=True)
    except Exception:
        return

    try:
        trial_dirs = [d for d in job_dir.iterdir() if d.is_dir() and (d / "agent").exists()]
    except Exception:
        return

    for trial_dir in trial_dirs:
        for target in targets:
            src = trial_dir / "agent" / "sessions" / target
            if not src.exists():
                continue
            dst = artifacts_root / target / trial_dir.name
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            except Exception:
                continue


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirror agent session artifacts after a Harbor run finishes.")
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--targets", nargs="+", required=True)
    parser.add_argument("--dest-dirname", default="artifacts")
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    args = parser.parse_args()

    runs_dir = args.runs_dir.resolve()
    job_dir = runs_dir / args.job_name

    result_path = job_dir / "result.json"
    if job_dir.exists() and result_path.exists():
        _mirror_artifacts(
            runs_dir=runs_dir,
            job_name=args.job_name,
            targets=list(args.targets),
            dest_dirname=args.dest_dirname,
        )
        return 0

    done = threading.Event()

    def _try_finish() -> None:
        if job_dir.exists() and result_path.exists():
            done.set()

    class _Handler(FileSystemEventHandler):
        def on_created(self, event) -> None:  # type: ignore[override]
            _try_finish()

        def on_modified(self, event) -> None:  # type: ignore[override]
            _try_finish()

        def on_moved(self, event) -> None:  # type: ignore[override]
            _try_finish()

    observer = Observer()
    handler = _Handler()
    observer.schedule(handler, str(runs_dir), recursive=True)
    observer.start()

    try:
        done.wait(timeout=max(5.0, args.timeout_seconds))
    finally:
        observer.stop()
        observer.join()

    if not done.is_set():
        return 0

    _mirror_artifacts(
        runs_dir=runs_dir,
        job_name=args.job_name,
        targets=list(args.targets),
        dest_dirname=args.dest_dirname,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
