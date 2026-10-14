"""Refresh the static demo from a completed fixture run and actual evaluation results."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
state=json.loads((root/"examples/recovery/progress.json").read_text("utf-8"))
assert state["identity"]["mode"] == "fixture" and state["status"] == "complete"
payload={"report":state["report"],"evidence":state["evidence"],"events":state["events"],"evaluations":json.loads((root/"examples/evaluation-results.json").read_text("utf-8"))}
web=root/"src/tracelens/web"
web.mkdir(exist_ok=True)
(web/"demo-data.json").write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
print("Exported recorded SYNTHETIC fixture demo")
