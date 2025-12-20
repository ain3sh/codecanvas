# TerminalBench 2.0 Tasks (Eval Subset)

This document summarizes the seven Terminal-Bench 2.0 tasks used in our evaluation. Each summary is intentionally brief and focuses on what the task requires and what distinct capability it pressures.

## Overview

| Task ID | Domain | Difficulty | Registry |
| --- | --- | --- | --- |
| `sanitize-git-repo` | security / version control | medium | https://www.tbench.ai/registry/terminal-bench/2.0/sanitize-git-repo |
| `build-cython-ext` | compilation / python packaging | medium | https://www.tbench.ai/registry/terminal-bench/2.0/build-cython-ext |
| `custom-memory-heap-crash` | debugging / C++ | medium | https://www.tbench.ai/registry/terminal-bench/2.0/custom-memory-heap-crash |
| `db-wal-recovery` | database recovery | medium | https://www.tbench.ai/registry/terminal-bench/2.0/db-wal-recovery |
| `modernize-scientific-stack` | python migration | medium | https://www.tbench.ai/registry/terminal-bench/2.0/modernize-scientific-stack |
| `rstan-to-pystan` | probabilistic programming | medium | https://www.tbench.ai/registry/terminal-bench/2.0/rstan-to-pystan |
| `fix-code-vulnerability` | security / code auditing | hard | https://www.tbench.ai/registry/terminal-bench/2.0/fix-code-vulnerability |

## Task Summaries

### `sanitize-git-repo`

The agent is given a Git repository containing leaked credentials and must remove all sensitive values by replacing them with stable placeholder strings (e.g., AWS keys, GitHub tokens, Huggingface tokens). The core difficulty is balancing recall (finding every secret instance) with precision (avoiding edits to files that are not contaminated), while maintaining consistent placeholder values across the repository.

### `build-cython-ext`

The agent must compile and install `pyknotid` from source into a system Python environment where NumPy is already at 2.3.0, resolving any Cython/C-extension compatibility issues introduced by the NumPy 2.x transition. Success requires navigating Python packaging/build tooling, making minimal targeted source fixes (without restructuring the project), and validating correctness via the provided test suite and a concrete import-and-run snippet that exercises the compiled extensions.

### `custom-memory-heap-crash`

The agent is asked to fix a C++ program that crashes only under an optimized “release” build (with a different libstdc++ build) but not under an unoptimized “debug” build. Only `/app/user.cpp` may be modified, and the final program must also be clean under Valgrind. This task stresses root-causing optimization-sensitive undefined behavior and memory-management bugs under tight edit constraints.

### `db-wal-recovery`

The agent must recover the true state of a SQLite database operating in WAL mode when the WAL file is corrupted or obfuscated such that naive reads expose only the base DB contents. The required output is an exact `recovered.json` containing all 11 records (including WAL changes) in a specific JSON list format sorted by `id`. The key challenge is treating the WAL as a recoverable log and reconstructing state with high output exactness.

### `modernize-scientific-stack`

Given a legacy Python 2.7 climate analysis script that must not be edited, the agent must create a modern Python 3 replacement script and an explicit dependency specification. The task is intentionally narrow—read a CSV with pandas, process two station IDs, compute and print mean temperatures in a fixed format—so the difficulty comes from clean modernization (pathlib/configparser usage, avoiding deprecated idioms) and correct dependency pinning/constraints rather than algorithmic complexity.

### `rstan-to-pystan`

The agent must translate an R+RStan workflow into a Python script using PyStan 3.10.0, without running the original R code and without using cmdstan-based tooling. It must read the original R script to reproduce the Stan model structure and sampling hyperparameters, run posterior sampling deterministically (including a fixed `random_seed` in `stan.build`), and write posterior-mean estimates to multiple CSV outputs with a strict numeric-only format. This task probes careful cross-language semantic translation and reproducible scientific computation under tool constraints.

### `fix-code-vulnerability`

The agent must audit a real, single-file web framework implementation (`/app/bottle.py`), identify a vulnerability with the correct CWE ID(s), and report findings in a machine-readable `/app/report.jsonl` format before applying a fix. The fix is not just “make tests pass”: it must tighten input handling so invalid inputs raise the correct error type rather than being silently ignored or handled via overly generic exceptions. This task emphasizes security reasoning grounded in taxonomy (CWE) and correctness-preserving patching validated by the project’s pytest suite.
