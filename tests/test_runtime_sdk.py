import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import httpx
import pytest
from swarmcircuit import ControlError, SwarmCircuit

from tests.test_control import controlled as controlled
from tests.test_control import queue, state


def wait_state(client, cid, expected, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/control-commands/{cid}")
        if response.json()["state"] == expected:
            return response.json()
        time.sleep(0.01)
    raise AssertionError(f"Command did not reach {expected}")


def drive_checkpoint(client, config, clock, sdk, *, lost_ack=False):
    entered, release, executed = Event(), Event(), []
    with sdk.run("cooperative", mode="control") as run:
        work = run.task("protected read", agent="reader")
        independent = run.task("independent read", agent="other")
        with run.runtime("test-host", heartbeat_interval=0.05, poll_interval=0.01) as runtime:
            session = {
                "runtime_session_id": runtime.session_id,
                "fencing_epoch": runtime.epoch,
                "session_token": runtime.token,
            }

            def on_enter(point):
                entered.set()
                assert release.wait(3)

            def worker():
                with work:
                    runtime.checkpoint(
                        work, action="before_mock_read", timeout=5, on_enter=on_enter
                    )
                    executed.append("once")

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(worker)
                try:
                    assert entered.wait(3)
                    hold, _ = queue(client, config, run.run_id, session, work.task_id)
                    assert hold.status_code == 202, hold.text
                    assert state(client, run.run_id, work.task_id) == "running"
                    release.set()
                    wait_state(client, hold.json()["command_id"], "applied")
                    assert not executed and not future.done()
                    with independent:
                        pass
                    assert state(client, run.run_id, independent.task_id) == "completed"
                    resume, _ = queue(
                        client, config, run.run_id, session, work.task_id, kind="resume_task"
                    )
                    assert resume.status_code == 202, resume.text
                    wait_state(client, resume.json()["command_id"], "applied")
                    future.result(timeout=3)
                finally:
                    release.set()
                    runtime.stopping.set()
            assert executed == ["once"]
            assert len(runtime.applied) == 2
            with client.app.state.db.read() as conn:
                assert (
                    conn.execute(
                        "SELECT COUNT(*) FROM control_acknowledgements WHERE run_id=?",
                        (run.run_id,),
                    ).fetchone()[0]
                    == 2
                )
    assert state(client, run.run_id, work.task_id) == "completed"


def test_sdk_physically_parks_and_releases_once_while_independent_task_continues(controlled):
    client, _, clock, config = controlled
    with SwarmCircuit(config.project_id, config.sdk_token, client=client, clock_ms=clock) as sdk:
        drive_checkpoint(client, config, clock, sdk)


def test_lost_ack_responses_reconcile_without_repeating_effect(controlled):
    client, _, clock, config = controlled

    class LoseEveryAckResponse:
        def request(self, method, url, **kwargs):
            result = client.request(method, url, **kwargs)
            if url.endswith("/ack"):
                raise httpx.ReadError("ACK committed but response lost")
            return result

    with SwarmCircuit(
        config.project_id,
        config.sdk_token,
        client=LoseEveryAckResponse(),
        clock_ms=clock,
        sleep=lambda _: None,
    ) as sdk:
        drive_checkpoint(client, config, clock, sdk, lost_ack=True)


def test_sdk_coalesces_host_approval_callback_without_granting_authority(controlled):
    client, _, clock, config = controlled
    scope = {
        "principal": "demo",
        "purpose": "read",
        "resource": "mock-data",
        "counterparty": "mock",
        "permission_scope": "read",
        "policy_revision": "v1",
        "amount": "1.00",
        "asset": "MOCK",
    }
    presented = []
    with SwarmCircuit(config.project_id, config.sdk_token, client=client, clock_ms=clock) as sdk:
        with sdk.run("notifications", mode="control") as run:
            first, second = run.task("a", agent="a"), run.task("b", agent="b")
            with run.runtime("approval-host") as runtime:
                ap1 = runtime.present_approval_once(first, scope, presented.append)
                ap2 = runtime.present_approval_once(second, scope, presented.append)
                assert ap1 == ap2
                assert presented == [ap1]
            with client.app.state.db.read() as conn:
                assert (
                    conn.execute(
                        "SELECT state FROM approvals WHERE approval_id=?", (ap1,)
                    ).fetchone()[0]
                    == "pending"
                )
                dispositions = [
                    r[0]
                    for r in conn.execute(
                        "SELECT disposition FROM approval_requests WHERE run_id=?", (run.run_id,)
                    )
                ]
                assert sorted(dispositions) == ["coalesced", "presented"]


def test_uncertain_presentation_is_never_automatically_repeated(controlled):
    client, _, clock, config = controlled
    scope = {
        "principal": "demo",
        "purpose": "read",
        "resource": "data",
        "counterparty": "mock",
        "permission_scope": "read",
        "policy_revision": "v1",
    }
    calls = []

    def ambiguous(approval_id):
        calls.append(approval_id)
        raise RuntimeError("Notification outcome unknown")

    with SwarmCircuit(config.project_id, config.sdk_token, client=client, clock_ms=clock) as sdk:
        with sdk.run("uncertain-presentation", mode="control") as run:
            work = run.task("a", agent="a")
            with run.runtime("host") as runtime:
                with pytest.raises(RuntimeError):
                    runtime.present_approval_once(work, scope, ambiguous)
                runtime.present_approval_once(work, scope, ambiguous)
            assert len(calls) == 1
            with client.app.state.db.read() as conn:
                assert (
                    conn.execute(
                        "SELECT state FROM runtime_approval_presentations WHERE run_id=?",
                        (run.run_id,),
                    ).fetchone()[0]
                    == "unknown"
                )


def test_observe_mode_and_irreversible_boundaries_are_not_controlled(controlled):
    client, _, clock, config = controlled
    with SwarmCircuit(config.project_id, config.sdk_token, client=client, clock_ms=clock) as sdk:
        with sdk.run("observe") as run:
            with pytest.raises(ControlError, match="observe_only"):
                run.runtime("host")
        with sdk.run("control", mode="control") as run:
            work = run.task("payment", agent="buyer")
            with run.runtime("host") as runtime:
                with pytest.raises(ControlError, match="unsupported_boundary"):
                    runtime.checkpoint(work, action="pay", reversible=False)


def test_checkpoint_timeout_cannot_execute_following_code(controlled):
    client, _, clock, config = controlled
    ran = []
    with SwarmCircuit(config.project_id, config.sdk_token, client=client, clock_ms=clock) as sdk:
        with sdk.run("timeout", mode="control") as run:
            a = run.task("incomplete prerequisite", agent="a")
            b = run.task("dependent", agent="b")
            b.depends_on(a)
            with run.runtime("host") as runtime:
                with pytest.raises(ControlError, match="checkpoint_timeout"):
                    with b:
                        runtime.checkpoint(b, action="read", timeout=0.05)
                        ran.append("unsafe")
            assert not ran
            assert state(client, run.run_id, b.task_id) == "running"


def test_backpressure_parks_sdk_dependency_closure_and_preserves_pending_approval(controlled):
    client, _, clock, config = controlled
    executed = []
    with SwarmCircuit(config.project_id, config.sdk_token, client=client, clock_ms=clock) as sdk:
        with sdk.run("causal-backpressure", mode="control") as run:
            root = run.task("approval root", agent="root")
            child = run.task("dependent", agent="child")
            independent = run.task("independent", agent="independent")
            child.depends_on(root)
            with run.runtime("host", poll_interval=0.01) as runtime:
                gate = root.wait_for_approval(
                    {
                        "principal": "test-host",
                        "purpose": "mock-read",
                        "resource": "mock",
                        "counterparty": "mock",
                        "permission_scope": "read",
                        "policy_revision": "v1",
                    }
                )
                entered = {work.task_id: Event() for work in (root, child)}

                def worker(work):
                    try:
                        runtime.checkpoint(
                            work,
                            action="before_mock_read",
                            timeout=5,
                            on_enter=lambda point: entered[work.task_id].set(),
                        )
                        executed.append(work.task_id)
                    except ControlError as exc:
                        return exc.code

                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(worker, work) for work in (root, child)]
                    try:
                        assert all(signal.wait(3) for signal in entered.values())
                        result = client.post(
                            f"/api/v1/runs/{run.run_id}/backpressure",
                            json={
                                "approval_id": gate,
                                "reason": "shared pending gate",
                                "apply": True,
                            },
                            headers={
                                "Authorization": f"Bearer {config.operator_token}",
                                "Idempotency-Key": str(uuid4()),
                            },
                        )
                        assert result.status_code == 200, result.text
                        assert len(result.json()["command_ids"]) == 2
                        for cid in result.json()["command_ids"]:
                            wait_state(client, cid, "applied")
                        with independent:
                            pass
                        assert state(client, run.run_id, independent.task_id) == "completed"
                        assert all(
                            state(client, run.run_id, w.task_id) == "held" for w in (root, child)
                        )
                        assert not executed and all(not future.done() for future in futures)
                        with client.app.state.db.read() as conn:
                            assert (
                                conn.execute(
                                    "SELECT state FROM approvals WHERE approval_id=?", (gate,)
                                ).fetchone()[0]
                                == "pending"
                            )
                    finally:
                        runtime.stopping.set()
                    assert all(
                        future.result(timeout=3) == "runtime_disconnected" for future in futures
                    )
    assert not executed
