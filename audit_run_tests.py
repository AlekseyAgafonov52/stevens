"""Run existing checks against an explicitly isolated audit database."""
import os
from pathlib import Path
import subprocess
import sys
import json
import re

ROOT = Path(__file__).resolve().parent
OUT = ROOT / os.environ.get("AUDIT_OUT_DIR", "audit-results")
OUT.mkdir(parents=True, exist_ok=True)
env = os.environ.copy()
env.update(DATABASE_URL=os.environ.get("AUDIT_DATABASE_URL", "postgresql+asyncpg://postgres:audit_local_only@127.0.0.1:55439/stevens_audit"),
           YANDEX_API_KEY="", YANDEX_FOLDER_ID="", PYTHONIOENCODING="utf-8", STEVENS_RATE_LIMIT="0")
bootstrap = "import dotenv,runpy,sys; dotenv.load_dotenv=lambda *a,**k:False; sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name='__main__')"
paths = sorted((ROOT / "tests").glob("test_*.py"))
summary = []
if len(sys.argv) > 1:
    unknown = set(sys.argv[1:]) - {p.name for p in paths}
    if unknown:
        raise SystemExit("Unknown test files: " + ", ".join(sorted(unknown)))
    paths = [p for p in paths if p.name in sys.argv[1:]]
    if (OUT / "backend-status.json").exists():
        summary = json.loads((OUT / "backend-status.json").read_text(encoding="utf-8"))
    summary = [row for row in summary if row["file"] not in {p.name for p in paths}]
for path in paths:
    try:
        result = subprocess.run([sys.executable, "-c", bootstrap, str(path)], cwd=ROOT,
                                env=env, capture_output=True, timeout=180)
        (OUT / (path.stem + ".log")).write_bytes(result.stdout + result.stderr)
        print(f"{path.name}: exit={result.returncode}", flush=True)
        # Some legacy checks print failures without returning a failing exit code.
        reported_failure = re.search(rb"(?m)^(?:FAIL(?:ED)?\b|BAD\b|fails:\s*[1-9]\d*\b)",
                                     result.stdout + result.stderr) is not None
        summary.append({"file": path.name, "exit_code": result.returncode,
                        "reported_failure": reported_failure})
    except subprocess.TimeoutExpired as exc:
        (OUT / (path.stem + ".log")).write_bytes((exc.stdout or b"") + (exc.stderr or b""))
        print(f"{path.name}: TIMEOUT", flush=True)
        summary.append({"file": path.name, "timeout": True})
(OUT / "backend-status.json").write_text(json.dumps(sorted(summary, key=lambda row: row["file"]), indent=2), encoding="utf-8")
raise SystemExit(1 if any(row.get("exit_code") != 0 or row.get("timeout") or row.get("reported_failure")
                         for row in summary) else 0)
