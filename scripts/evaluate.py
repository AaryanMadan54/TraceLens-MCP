"""Run real tests and persist measured outcomes. Never emits invented model scores."""
import json
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
xml = root / "runs/evaluation.xml"
xml.parent.mkdir(exist_ok=True)
result = subprocess.run([sys.executable, "-m", "pytest", "-q", f"--junitxml={xml}"], cwd=root)
if not xml.exists():
    raise SystemExit(result.returncode or 1)
cases = []
for case in ET.parse(xml).iter("testcase"):
    status = "failed" if case.find("failure") is not None or case.find("error") is not None else "skipped" if case.find("skipped") is not None else "passed"
    cases.append(dict(name=case.attrib["name"], status=status, seconds=float(case.attrib.get("time", 0))))
out = dict(executed_at=datetime.now(timezone.utc).isoformat(), python=platform.python_version(), platform=platform.system(), command="python scripts/evaluate.py", scope="Offline integration and deterministic/scripted policy checks. No live LLM quality score.", live_llm="not_run", docker="not_run", passed=sum(c["status"] == "passed" for c in cases), failed=sum(c["status"] == "failed" for c in cases), skipped=sum(c["status"] == "skipped" for c in cases), cases=cases)
(root/"examples").mkdir(exist_ok=True)
(root/"examples/evaluation-results.json").write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
raise SystemExit(result.returncode)
