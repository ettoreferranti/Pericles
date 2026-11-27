"""LLM plan minds: triggers, prompts, retries, fallback, agent events (ADR-0018)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, cast

from pericles.agents.config import RELIEFS, TRIGGERS, AgentConfig, ticks_for_hours
from pericles.agents.controller import WATCHED, Mind, failed_event
from pericles.agents.executor import Progress, advance, begin
from pericles.agents.plan import Catalog, Plan, catalog_for, check_plan
from pericles.agents.prompt import Situation, Template, load_template, plan_messages
from pericles.agents.scripted import ScriptedMind
from pericles.agents.view import Decision, View
from pericles.core.events import Event
from pericles.core.state import Villager, WorldState
from pericles.llm.types import Message, Request, Result

Complete = Callable[[Sequence[Request]], list[Result]]
IDLE, STEP_COMPLETED, STEP_FAILED, NEED, PERIODIC = TRIGGERS
KIND = "plan"
SEED_BYTES = 4  # request seeds are unsigned 32-bit integers


def seed_for(run_seed: int, villager: str, tick: int) -> int:
    digest = hashlib.sha256(f"{run_seed}:{villager}:{tick}".encode()).digest()
    return int.from_bytes(digest[:SEED_BYTES], "big")


def _optional(value: object) -> str | None:
    return None if value is None else str(value)


@dataclass
class Record:
    """One villager's plan state; everything but `decision` is saved (ADR-0018 §7).

    `rejected` holds an engine failure seen since the step last ran; the step fails with it
    on its next run unless it turns out done (research someone else finished, say).
    """

    plan: Plan | None = None
    index: int = 0
    progress: Progress = field(default_factory=Progress)
    planned_tick: int = 0
    pending: list[str] = field(default_factory=list)
    failure: str | None = None
    above: list[str] = field(default_factory=list)
    fallback_until: int = 0
    rejected: str | None = None
    decision: Decision | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": None if self.plan is None else self.plan.model_dump(mode="json"),
            "index": self.index,
            "progress": self.progress.to_dict(),
            "planned_tick": self.planned_tick,
            "pending": list(self.pending),
            "failure": self.failure,
            "above": list(self.above),
            "fallback_until": self.fallback_until,
            "rejected": self.rejected,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Record:
        plan = data["plan"]
        return cls(
            plan=None if plan is None else Plan.model_validate(plan),
            index=int(data["index"]),
            progress=Progress.from_dict(data["progress"]),
            planned_tick=int(data["planned_tick"]),
            pending=[str(t) for t in data["pending"]],
            failure=_optional(data["failure"]),
            above=[str(r) for r in data["above"]],
            fallback_until=int(data["fallback_until"]),
            rejected=_optional(data["rejected"]),
        )


class PlanMind:
    def __init__(
        self,
        model: str,
        complete: Complete,
        fallback: Mind,
        config: AgentConfig,
        seed: int,
        template: Template,
    ) -> None:
        self.model = model
        self.complete = complete
        self.fallback = fallback
        self.config = config
        self.seed = seed
        self.template = template
        self.records: dict[str, Record] = {}
        self._events: list[tuple[str, dict[str, Any]]] = []

    # -- Planner -----------------------------------------------------------------------

    def prepare(self, view: View, villagers: Sequence[Villager]) -> None:
        alive = view.state.villagers
        self.records = {vid: r for vid, r in self.records.items() if vid in alive}
        asks: dict[str, tuple[str, ...]] = {}
        for villager in villagers:
            record = self.records.setdefault(villager.id, Record())
            record.decision = None
            if view.tick < record.fallback_until:
                continue
            self._run(view, villager, record)
            fired = self._fired(view, villager, record)
            if fired:
                asks[villager.id] = fired
        if asks:
            self._plan(view, asks)

    def decide(self, view: View, villager: Villager) -> Decision | None:
        record = self.records.get(villager.id)
        if record is None or record.plan is None or view.tick < record.fallback_until:
            return self.fallback.decide(view, villager)
        return record.decision

    def observe(self, state: WorldState, events: Sequence[Event]) -> None:
        """Note engine failures; the step they hit is judged on its next run (`_run`)."""
        for event in events:
            if event.kind not in WATCHED or not failed_event(event):
                continue
            record = self.records.get(str(event.data.get("actor")))
            if record is None or record.plan is None or record.rejected is not None:
                continue
            reason = event.data.get("reason", event.kind)
            record.rejected = f"{event.kind}: {reason}"

    def take_events(self) -> list[tuple[str, dict[str, Any]]]:
        out, self._events = self._events, []
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"records": {vid: self.records[vid].to_dict() for vid in sorted(self.records)}}

    def parse(self, data: Mapping[str, Any]) -> object:
        return {str(vid): Record.from_dict(r) for vid, r in data["records"].items()}

    def restore(self, parsed: object) -> None:
        self.records = cast(dict[str, Record], parsed)

    # -- Steps -------------------------------------------------------------------------

    def _note(self, kind: str, **data: Any) -> None:
        self._events.append((kind, {"model": self.model, **data}))

    def _start(self, tick: int, villager: Villager, record: Record) -> None:
        assert record.plan is not None
        steps = record.plan.steps
        record.rejected = None
        if record.index < len(steps):
            record.progress = begin(tick, villager, steps[record.index])
        else:
            record.progress = Progress()

    def _failed(self, tick: int, villager: Villager, record: Record, reason: str) -> None:
        assert record.plan is not None
        step = record.plan.steps[record.index]
        self._note(
            "plan_step",
            actor=villager.id,
            index=record.index,
            action=step.action,
            target=step.target,
            status="failed",
            reason=reason,
        )
        record.failure = reason
        record.pending.append(STEP_FAILED)
        record.index += 1
        self._start(tick, villager, record)

    def _run(self, view: View, villager: Villager, record: Record) -> None:
        """Advance the plan past finished or failed steps to this tick's decision."""
        while record.plan is not None:
            steps = record.plan.steps
            if record.index >= len(steps):
                record.plan = None
                record.pending.append(IDLE)
                return
            step = steps[record.index]
            outcome = advance(view, villager, step, record.progress)
            if outcome.done:
                self._note(
                    "plan_step",
                    actor=villager.id,
                    index=record.index,
                    action=step.action,
                    target=step.target,
                    status="done",
                )
                record.pending.append(STEP_COMPLETED)
                record.index += 1
                self._start(view.tick, villager, record)
                continue
            failed = record.rejected if record.rejected is not None else outcome.failed
            if failed is not None:
                self._failed(view.tick, villager, record, failed)
                continue
            record.decision = outcome.decision
            return

    def _fired(self, view: View, villager: Villager, record: Record) -> tuple[str, ...]:
        fired = set(record.pending)
        if record.plan is None:
            fired.add(IDLE)
        now = [r for r in RELIEFS if view.level(villager, r) >= self.config.act_at[r]]
        if set(now) - set(record.above):
            fired.add(NEED)
        record.above = now
        replan = ticks_for_hours(view.ctx.config.calendar.tick_minutes, self.config.replan_hours)
        if record.plan is not None and view.tick - record.planned_tick >= replan:
            fired.add(PERIODIC)
        return tuple(t for t in TRIGGERS if t in fired and t in self.config.triggers)

    # -- Planning ----------------------------------------------------------------------

    def _plan(self, view: View, asks: Mapping[str, tuple[str, ...]]) -> None:
        villagers = view.state.villagers
        catalogs: dict[str, Catalog] = {}
        batch: list[Request] = []
        for vid in sorted(asks):
            villager, record = villagers[vid], self.records[vid]
            catalogs[vid] = catalog_for(view, villager)
            situation = Situation(asks[vid], record.plan, record.index, record.failure)
            messages = plan_messages(view, villager, situation, catalogs[vid], self.template)
            batch.append(
                Request(
                    KIND,
                    vid,
                    view.tick,
                    self.model,
                    messages,
                    seed_for(self.seed, vid, view.tick),
                    output=Plan,
                    template=self.template.version,
                )
            )
        adopted: dict[str, tuple[Plan, int]] = {}
        dropped: dict[str, tuple[str, bool]] = {}
        notes: list[tuple[str, dict[str, Any]]] = []
        while batch:
            retry: list[Request] = []
            for result in self.complete(batch):
                request, vid = result.request, result.request.villager
                if result.backend_error is not None:
                    dropped[vid] = (f"backend: {result.backend_error}", True)
                    continue
                error = result.error
                plan = cast(Plan | None, result.value)
                if error is None and plan is not None:
                    error = check_plan(plan, catalogs[vid], self.config.max_plan_steps)
                if error is None and plan is not None:
                    adopted[vid] = (plan, request.attempt)
                    continue
                notes.append(
                    (
                        "plan_invalid",
                        {
                            "model": self.model,
                            "actor": vid,
                            "attempt": request.attempt,
                            "error": error,
                        },
                    )
                )
                if request.attempt < self.config.max_retries:
                    retry.append(self._retry(request, result.text, str(error)))
                else:
                    attempts = request.attempt + 1
                    dropped[vid] = (f"invalid output after {attempts} attempts: {error}", False)
            batch = retry
        self._events.extend(notes)
        for vid in sorted(asks):
            villager, record = villagers[vid], self.records[vid]
            if vid in adopted:
                plan, retries = adopted[vid]
                self._note(
                    "plan_made",
                    actor=vid,
                    triggers=list(asks[vid]),
                    goal=plan.goal,
                    steps=[s.model_dump(mode="json") for s in plan.steps],
                    reason=plan.reason,
                    retries=retries,
                    template=self.template.version,
                )
                record.plan, record.index, record.planned_tick = plan, 0, view.tick
                record.pending, record.failure, record.decision = [], None, None
                self._start(view.tick, villager, record)
                self._run(view, villager, record)
                if record.plan is None:
                    # It ended or failed at once (Review Focus 1). `pending` keeps what the
                    # steps fired (step_failed), so the ask after the window says why.
                    self._fall_back(view, vid, record, "the plan gave nothing to do", flagged=False)
                continue
            reason, flagged = dropped[vid]
            record.pending = []
            self._fall_back(view, vid, record, reason, flagged=flagged)

    def _fall_back(
        self, view: View, vid: str, record: Record, reason: str, *, flagged: bool
    ) -> None:
        """The scripted mind drives this villager for fallback_hours (REQ-AGT-005 AC2)."""
        hours = self.config.fallback_hours
        self._note("mind_fallback", actor=vid, reason=reason, flagged=flagged)
        record.plan, record.decision, record.rejected = None, None, None
        record.fallback_until = view.tick + ticks_for_hours(
            view.ctx.config.calendar.tick_minutes, hours
        )

    def _retry(self, request: Request, text: str, error: str) -> Request:
        follow = self.template.retry.substitute(error=error)
        messages = (*request.messages, Message("assistant", text), Message("user", follow))
        return replace(request, messages=messages, attempt=request.attempt + 1)


def plan_minds(
    models: Iterable[str], complete: Complete, config: AgentConfig, seed: int
) -> dict[str, PlanMind]:
    """One plan mind per model key, sharing the gateway and the scripted fallback."""
    template = load_template(config.plan_template)
    return {
        key: PlanMind(key, complete, ScriptedMind(), config, seed, template)
        for key in sorted(models)
    }
