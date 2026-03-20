"""
Workflow Recorder — Record, persist, and replay user action sequences.

Workflows are named sequences of desktop actions that can be:
  - Recorded from live user interaction (via IntentFusion)
  - Saved as reusable templates
  - Replayed with optional parameterization
  - Shared or imported

Storage: data/workflows/*.json
"""

from __future__ import annotations

import json
import time
import asyncio
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger


WORKFLOWS_DIR = Path("data/workflows")


@dataclass
class WorkflowStep:
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    delay_ms: int = 300  # delay before this step
    source: str = ""
    description: str = ""


@dataclass
class Workflow:
    id: str
    name: str
    description: str = ""
    steps: List[WorkflowStep] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    run_count: int = 0

    def to_dict(self) -> Dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: Dict) -> "Workflow":
        steps = [WorkflowStep(**s) for s in data.pop("steps", [])]
        return cls(steps=steps, **data)


class WorkflowRecorder:
    """Manages workflow recording, persistence, and replay."""

    def __init__(self):
        WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        self._workflows: Dict[str, Workflow] = {}
        self._load_all()

    def _load_all(self):
        for f in WORKFLOWS_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                wf = Workflow.from_dict(data)
                self._workflows[wf.id] = wf
            except Exception as e:
                logger.warning(f"Failed to load workflow {f}: {e}")

    def _save(self, wf: Workflow):
        path = WORKFLOWS_DIR / f"{wf.id}.json"
        path.write_text(
            json.dumps(wf.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def create_from_recording(
        self,
        recorded_actions: List[Dict],
        name: str,
        description: str = "",
        tags: Optional[List[str]] = None,
    ) -> Workflow:
        """Create a workflow from recorded IntentFusion actions."""
        wf_id = f"wf_{int(time.time() * 1000)}"

        steps = []
        prev_ts = None
        for act in recorded_actions:
            delay = 300
            if prev_ts and "timestamp" in act:
                delay = min(max(int(act["timestamp"] - prev_ts), 100), 5000)
            prev_ts = act.get("timestamp")

            steps.append(WorkflowStep(
                action=act.get("action", ""),
                params=act.get("params", {}),
                delay_ms=delay,
                source=act.get("source", ""),
            ))

        wf = Workflow(
            id=wf_id,
            name=name,
            description=description,
            steps=steps,
            tags=tags or [],
        )

        self._workflows[wf.id] = wf
        self._save(wf)
        logger.info(f"Created workflow '{name}' with {len(steps)} steps")
        return wf

    def list_workflows(self) -> List[Dict]:
        return [
            {
                "id": wf.id,
                "name": wf.name,
                "description": wf.description,
                "steps": len(wf.steps),
                "tags": wf.tags,
                "run_count": wf.run_count,
                "created_at": wf.created_at,
            }
            for wf in sorted(
                self._workflows.values(),
                key=lambda w: w.updated_at,
                reverse=True,
            )
        ]

    def get_workflow(self, wf_id: str) -> Optional[Workflow]:
        return self._workflows.get(wf_id)

    def delete_workflow(self, wf_id: str) -> bool:
        if wf_id in self._workflows:
            del self._workflows[wf_id]
            path = WORKFLOWS_DIR / f"{wf_id}.json"
            if path.exists():
                path.unlink()
            return True
        return False

    async def replay(
        self,
        wf_id: str,
        executor,
        speed: float = 1.0,
        on_step=None,
    ) -> Dict[str, Any]:
        """
        Replay a workflow by executing each step.

        Args:
            wf_id: Workflow ID
            executor: Callable(action, params) that executes desktop commands
            speed: Playback speed multiplier (2.0 = 2x faster)
            on_step: Optional callback(step_index, total, step_data)

        Returns:
            Result dict with success status and step results.
        """
        wf = self._workflows.get(wf_id)
        if not wf:
            return {"success": False, "error": "Workflow not found"}

        results = []
        total = len(wf.steps)

        for i, step in enumerate(wf.steps):
            # Apply delay
            delay_s = (step.delay_ms / 1000) / max(speed, 0.1)
            if delay_s > 0:
                await asyncio.sleep(delay_s)

            # Notify progress
            if on_step:
                try:
                    on_step(i, total, asdict(step))
                except Exception:
                    pass

            # Execute
            try:
                result = await executor(step.action, step.params)
                results.append({"step": i, "action": step.action, "ok": True, "result": result})
            except Exception as e:
                logger.error(f"Workflow step {i} failed: {e}")
                results.append({"step": i, "action": step.action, "ok": False, "error": str(e)})

        wf.run_count += 1
        wf.updated_at = time.time()
        self._save(wf)

        return {
            "success": all(r["ok"] for r in results),
            "workflow_id": wf_id,
            "steps_total": total,
            "steps_ok": sum(1 for r in results if r["ok"]),
            "results": results,
        }


# Singleton
_recorder: Optional[WorkflowRecorder] = None

def get_workflow_recorder() -> WorkflowRecorder:
    global _recorder
    if _recorder is None:
        _recorder = WorkflowRecorder()
    return _recorder
