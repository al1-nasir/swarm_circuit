"""Discrete-event actors + a separate guarded tool boundary and outcome journal.

No LLM or network calls. All arms share world facts, tasks, proposals and safety guards.
The policies see only delivered observations; the metric reducer reads the truth journal.
"""

import random
from collections import Counter
from typing import Any

from swarmcircuit_server.detectors.rules import reverse_closure
from swarmcircuit_server.research.protocol import DEPENDENCIES, GOALS, Protocol, digest

Record = dict[str, Any]


class Policy:
    """Scheduling mechanism, not authority. It cannot mark a tool effect authorized."""

    def __init__(self, arm: str, protocol: Protocol, dependencies: dict[str, set[str]]) -> None:
        self.arm, self.protocol, self.dependencies = arm, protocol, dependencies
        self.completed = {"plan"}
        self.gate = "pending"
        self.version = 0
        self.calls: Counter[str] = Counter()
        self.cached: set[str] = set()
        self.parked: set[str] = set()
        self.notifications: set[str] = set()
        self.pending_demands = 0
        self.known_pending = False
        self.tokens = protocol.global_per_tick
        self.next_tick: dict[str, int] = {}
        self.backoffs: Counter[str] = Counter()

    def observe(self, observation: Record) -> None:
        if observation["kind"] == "gate.changed":
            self.gate = observation["state"]
            self.version += 1
            self.calls.clear()
            self.cached.clear()
            self.parked.clear()
            self.next_tick.clear()
            self.backoffs.clear()
            self.pending_demands = 0
            self.known_pending = False
        elif observation["kind"] == "task.completed":
            self.completed.add(observation["task"])
            # A dependency completion invalidates local blocked-result caches.
            self.cached.difference_update(
                {task for task in self.cached if observation["task"] in self.dependencies[task]}
            )
        elif observation["kind"] == "tool.blocked" and observation["task"] == "access":
            self.known_pending = observation["reason"] == "approval_pending"

    def admission(self, task: str, tick: int) -> bool:
        if task in self.parked:
            return False
        if self.arm == "A_ready_queue":
            if not self.dependencies[task] <= self.completed:
                return False
            if task != "public" and self.known_pending and self.gate != "approved":
                return False
        if self.arm == "B1" and self.calls[task] >= self.protocol.retry_cap:
            return False
        if self.arm == "B2":
            if not self.tokens:
                return False
            self.tokens -= 1
        if self.arm == "B5" and tick < self.next_tick.get(task, 0):
            return False
        return True

    def demand(self, task: str, online: set[str]) -> list[str]:
        self.calls[task] += 1
        if task != "public" and self.known_pending and self.gate == "pending":
            self.pending_demands += 1
        if self.arm not in {"B4", "B4_no_graph"}:
            return []
        if self.gate != "pending" or not self.known_pending:
            return []
        if self.pending_demands < self.protocol.intervention_threshold:
            return []
        closure = (
            reverse_closure(
                {"access"},
                [
                    {"blocked_task_id": child, "prerequisite_task_id": parent}
                    for child, parents in self.dependencies.items()
                    for parent in sorted(parents)
                ],
            )
            if self.arm == "B4"
            else {"access"}
        )
        new = sorted((closure & online) - self.parked - self.completed)
        self.parked.update(new)
        return new

    def deduplicated(self, task: str) -> bool:
        if self.arm not in {"B3", "B4", "B4_no_graph", "A_ready_queue"}:
            return False
        if task in self.cached:
            return True
        self.cached.add(task)
        return False

    def notify(self) -> bool:
        if self.arm in {"B3", "B4", "B4_no_graph", "A_ready_queue"}:
            if "shared_scope" in self.notifications:
                return False
            self.notifications.add("shared_scope")
        return True

    def blocked(self, task: str, tick: int) -> None:
        if self.arm == "B5":
            self.backoffs[task] += 1
            self.next_tick[task] = tick + min(16, 2 ** min(4, self.backoffs[task]))


def simulate(
    protocol: Protocol,
    scenario: str,
    arm: str,
    seed: int,
    proposals: list[Record] | None = None,
) -> dict[str, Any]:
    if scenario not in protocol.scenarios or arm not in protocol.arms or seed not in protocol.seeds:
        raise ValueError("Trial is outside the sealed protocol")
    rng = random.Random(seed)
    horizon = protocol.horizon_ticks
    delay = 18 + rng.randrange(10)
    gate_at = 0 if scenario == "normal" else 8 if scenario == "legitimate_wait" else delay
    gate_final = "denied" if scenario == "denied_gate" else "approved"
    if scenario in {"pending_gate", "graph_error"}:
        gate_at = horizon + 1
    lag = 7 if scenario == "delayed_telemetry" else 0
    reactive = scenario in {"normal", "legitimate_wait"}
    intervals = {t: rng.randint(1, 3) for t in GOALS}
    starts_at = {t: rng.randint(0, 2) for t in GOALS}
    durations = {t: rng.randint(1, 3) for t in GOALS}
    if scenario == "graph_error":
        starts_at["public"] = 12  # Independent work arrives after the incorrect hold scope.
    truth: list[Record] = []
    observations: list[Record] = []
    pending: list[tuple[int, Record]] = []
    completed: dict[str, int] = {"plan": 0}
    running: dict[str, int] = {}
    gate = "pending"
    seen_blocked: set[str] = set()
    graph = {t: set(d) for t, d in DEPENDENCIES.items()}
    if scenario == "graph_error":
        graph["public"] = {"access"}  # Known counterexample, not a hidden favorable scenario.
    policy = Policy(arm, protocol, graph)
    tape = {(int(p["tick"]), str(p["task"])): p["action"] for p in proposals or []}

    def record(tick: int, kind: str, task: str = "", **details: Any) -> None:
        truth.append({"sequence": len(truth), "tick": tick, "kind": kind, "task": task, **details})

    def publish(tick: int, message: Record) -> None:
        record(tick, "observation.emitted", message=message)
        if scenario == "telemetry_loss" and message["kind"] == "gate.changed":
            record(tick, "observation.omitted", message_kind=message["kind"])
        else:
            pending.append((tick + lag, message))

    def authorized(task: str) -> bool:
        return DEPENDENCIES[task] <= completed.keys() and (task == "public" or gate == "approved")

    record(
        0,
        "world.initial",
        gate="pending",
        dependencies={t: sorted(d) for t, d in DEPENDENCIES.items()},
    )
    record(0, "task.completed", "plan")
    for tick in range(horizon):
        online = set(GOALS)
        if scenario == "runtime_disconnect" and 5 <= tick < 26:
            online.remove("research")
            record(tick, "host.offline", "research")
        if tick == gate_at:
            gate = gate_final
            record(tick, "gate.changed", state=gate)
            publish(tick, {"kind": "gate.changed", "state": gate})
            seen_blocked.clear()
        for task, finish in list(running.items()):
            if finish <= tick:
                completed[task] = tick
                del running[task]
                record(tick, "task.completed", task)
                publish(tick, {"kind": "task.completed", "task": task})
                seen_blocked.clear()
        for due, message in list(pending):
            if due <= tick:
                policy.observe(message)
                observations.append({"tick": tick, **message})
                record(tick, "observation.delivered", message=message)
                pending.remove((due, message))
        policy.tokens = protocol.global_per_tick
        order = list(GOALS)
        # Exogenous ordering is identical across arms, independent of policy RNG consumption.
        random.Random(f"{seed}:{tick}").shuffle(order)
        for task in order:
            if task in policy.parked:
                if authorized(task) and task not in completed and task not in running:
                    record(tick, "host.false_hold_tick", task)
                continue
            if task in completed or task in running or task not in online:
                continue
            if proposals is not None:
                action = tape.get((tick, task), "wait")
                if action != "attempt":
                    continue
            elif tick < starts_at[task] or (tick - starts_at[task]) % intervals[task]:
                continue
            if reactive and (not DEPENDENCIES[task] <= completed.keys() or task in seen_blocked):
                continue
            if not policy.admission(task, tick):
                continue
            record(tick, "actor.request", task)
            for target in policy.demand(task, online):
                record(tick, "host.parked", target, authority="simulated_cooperative_boundary")
            if task in policy.parked:
                continue
            if policy.deduplicated(task):
                record(tick, "request.deduplicated", task)
                if reactive:
                    seen_blocked.add(task)
                continue
            record(tick, "tool.attempt", task)
            if not authorized(task):
                reason = (
                    "dependency_pending"
                    if not DEPENDENCIES[task] <= completed.keys()
                    else f"approval_{gate}"
                )
                record(tick, "tool.blocked", task, reason=reason)
                publish(tick, {"kind": "tool.blocked", "task": task, "reason": reason})
                policy.blocked(task, tick)
                seen_blocked.add(task)
                if gate == "pending" and task != "public" and policy.notify():
                    record(
                        tick, "notification.delivered", task, scope="shared_scope", simulation=True
                    )
            else:
                # This is the only effect boundary. No policy can authorize or complete an action.
                record(tick, "action.started", task)
                running[task] = tick + durations[task]
    record(horizon, "world.finished", gate=gate)
    return {
        "scenario": scenario,
        "arm": arm,
        "seed": seed,
        "input_sha256": digest(
            {
                "seed": seed,
                "scenario": scenario,
                "horizon": horizon,
                "intervals": intervals,
                "starts": starts_at,
                "durations": durations,
                "gate_at": gate_at,
                "gate_final": gate_final,
                "lag": lag,
                "proposals": proposals,
            }
        ),
        "truth": truth,
        "observations": observations,
        "artifact_sha256": digest({"truth": truth, "observations": observations}),
    }
