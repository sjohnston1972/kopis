"""Regression coverage for double-execution locking (kopis #10, #11, #12).

These tests exist to prove one property: an approved remediation's device
commands can run AT MOST ONCE, even when two callers race for it. That is
the whole point — kopis pushes config to live network devices, and running
the same remediation twice is a real operational hazard (see issue #3).

Concurrency is real, not simulated
-----------------------------------
Every "concurrent" test below fires two coroutines with `asyncio.gather`,
each opening its OWN `AsyncSession` (its own DB connection) from
`session_factory`. That's deliberate: it mirrors what actually happens in
production, where two racing callers are two separate requests, each with
its own DB connection/session — possibly even on two different backend
worker processes. A test that just called `execute_approved()` twice in a
row, sequentially, would pass against a naive in-process boolean flag or
even against no guard at all in some orderings; it would prove nothing
about the actual race. Firing both through `asyncio.gather` so their
`UPDATE ... WHERE status = ...` statements are in flight to Postgres at
essentially the same time is what actually exercises the database-level
compare-and-swap in `approval_service._atomic_transition` and its
row-locking behaviour.

Confirmed failing pre-fix
--------------------------
Before `claim_executing()` / `_atomic_transition()` existed (i.e. against
the original `execute_approved` that only checked
`approval.status != "approved"` and `approval_service.approve()`/`deny()`
that did a plain read-then-write), `test_two_concurrent_executes_run_device_commands_once`
and `test_concurrent_approve_calls_only_one_wins` both fail: the pre-fix
code has no synchronization at all, so both concurrent callers
independently observe the pre-race status and both proceed — the mocked
`_send_commands_sync` gets invoked twice, and both `approve()` calls
return a non-None Approval. This was verified by `git stash`-ing the
fix commits (keeping this test file) and re-running the suite: both tests
failed as expected, everything else stayed green. See the PR/report for
the exact commands.

No real device or pyATS is touched: `_send_commands_sync` and
`services.snapshot_engine.take_snapshot` are both mocked.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from services import approval_service
from services import execution_engine


def _make_send_commands_mock():
    """A fake pyATS/Netmiko command runner that records every call."""

    def _fake(device, commands):
        return {
            "hostname": device.hostname,
            "outputs": [{"command": c, "output": "ok", "success": True} for c in commands],
            "duration_seconds": 0.01,
            "success": True,
        }

    return Mock(side_effect=_fake)


@pytest.fixture(autouse=True)
def _mock_device_io(monkeypatch):
    """Never let any test in this module touch a real device or pyATS.

    take_snapshot is imported lazily (`from services.snapshot_engine import
    take_snapshot`) inside execute_approved's pre-flight check, so patching
    the attribute on the source module (rather than on execution_engine)
    is what actually takes effect at call time.
    """
    monkeypatch.setattr(
        "services.snapshot_engine.take_snapshot",
        AsyncMock(return_value=[]),
    )


@pytest.fixture
def widen_read_then_write_window(monkeypatch):
    """Force genuine, deterministic interleaving for any code that still
    does a plain read-then-write (i.e. calls approval_service.get_approval()
    and later writes based on what it read).

    Why this exists: two asyncio tasks racing through a *very* short
    critical section (one SELECT, one COMMIT) over a local Postgres
    connection can, depending on event-loop/driver scheduling, happen to
    run back-to-back without ever actually overlapping on a given run —
    even though the code has no synchronization preventing it. Confirmed
    empirically: a plain `asyncio.gather()` of two approve() calls against
    the pre-fix code passed 5/5 repeated runs with no barrier, and even a
    fixed 50ms post-read sleep only caught the race in 4/5 runs. The
    absence of an observed race in a given run does not mean the code is
    safe — it can just mean that run got lucky timing, which is exactly
    the trap called out for this task (a test must not pass by accident
    against broken code).

    This uses an asyncio.Barrier(2) as a rendezvous instead of a sleep:
    both concurrent callers block right after finishing their read until
    BOTH have arrived, so neither can proceed to check-and-write until the
    other has already observed the identical pre-write state. That removes
    the timing dependence entirely rather than just making the window
    wider — verified 10/10 against the pre-fix code below.

    This patches approval_service.get_approval, which the CURRENT
    approve()/deny()/claim_executing() implementations never call in their
    write path (they use a single atomic UPDATE ... WHERE ... RETURNING
    instead) — so this fixture has zero effect on the fixed code's actual
    behavior or the property it's proving. It only matters for (and only
    forces open the race window for) a read-then-write implementation.
    """
    barrier = asyncio.Barrier(2)
    original = approval_service.get_approval

    async def _synced_get_approval(db, approval_id):
        result = await original(db, approval_id)
        await barrier.wait()
        return result

    monkeypatch.setattr(approval_service, "get_approval", _synced_get_approval)


async def _gather_sessions(session_factory, n, coro_fn):
    """Open `n` independent AsyncSessions and run coro_fn(session) on all
    of them concurrently via asyncio.gather. Returns the list of results.
    """
    sessions = [session_factory() for _ in range(n)]
    opened = [await s.__aenter__() for s in sessions]
    try:
        results = await asyncio.gather(*(coro_fn(sess) for sess in opened))
    finally:
        for s in sessions:
            await s.__aexit__(None, None, None)
    return results


# ── #10: atomic claim before running device commands ──────────────────────


@pytest.mark.asyncio
async def test_two_concurrent_executes_run_device_commands_once(
    monkeypatch, session_factory, make_approval, db
):
    """Two concurrent execute_approved() calls for the same approval:
    device commands run exactly once, the loser short-circuits without
    touching the device.
    """
    send_mock = _make_send_commands_mock()
    monkeypatch.setattr(execution_engine, "_send_commands_sync", send_mock)

    approval_id = await make_approval(status="approved")

    results = await _gather_sessions(
        session_factory, 2, lambda sess: execution_engine.execute_approved(sess, approval_id)
    )

    # The device-command function was invoked exactly once across both
    # concurrent attempts — this is the core double-execution guarantee.
    assert send_mock.call_count == 1

    skipped = [r for r in results if r.get("skipped")]
    executed = [r for r in results if not r.get("skipped")]
    assert len(skipped) == 1
    assert len(executed) == 1
    # The loser must not carry an execution result / device output — it
    # never got near the device.
    assert "outputs" not in skipped[0]

    from db.tables import Approval
    from sqlalchemy import select

    row = (await db.execute(select(Approval).where(Approval.id == approval_id))).scalar_one()
    assert row.status == "executed"


@pytest.mark.asyncio
async def test_claim_executing_only_succeeds_from_approved(session_factory, make_approval):
    """Direct unit check of the atomic claim's precondition."""
    pending_id = await make_approval(status="pending")
    executed_id = await make_approval(status="executed")
    approved_id = await make_approval(status="approved")

    async with session_factory() as db:
        assert await approval_service.claim_executing(db, pending_id) is None
        assert await approval_service.claim_executing(db, executed_id) is None
        claimed = await approval_service.claim_executing(db, approved_id)
        assert claimed is not None
        assert claimed.status == "executing"
        # Claiming again must fail now that it's already "executing".
        assert await approval_service.claim_executing(db, approved_id) is None


@pytest.mark.asyncio
async def test_mark_executed_requires_executing_state(session_factory, make_approval):
    """mark_executed must not clobber a row that was never claimed (still
    'approved') — it should no-op, not silently overwrite state.
    """
    approval_id = await make_approval(status="approved")
    async with session_factory() as db:
        result = await approval_service.mark_executed(
            db, approval_id, {"outputs": [], "success": True}, success=True
        )
        assert result is None

    async with session_factory() as db:
        from db.tables import Approval
        from sqlalchemy import select

        row = (await db.execute(select(Approval).where(Approval.id == approval_id))).scalar_one()
        # Still "approved" — the bogus mark_executed call had no effect.
        assert row.status == "approved"


# ── #11: approve()/deny() atomicity ────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_approve_calls_only_one_wins(
    session_factory, make_approval, db, widen_read_then_write_window
):
    approval_id = await make_approval(status="pending")

    results = await _gather_sessions(
        session_factory,
        2,
        lambda sess: approval_service.approve(sess, approval_id, approved_by="racer"),
    )

    winners = [r for r in results if r is not None]
    losers = [r for r in results if r is None]
    assert len(winners) == 1
    assert len(losers) == 1

    from db.tables import Approval
    from sqlalchemy import select

    row = (await db.execute(select(Approval).where(Approval.id == approval_id))).scalar_one()
    assert row.status == "approved"


@pytest.mark.asyncio
async def test_concurrent_deny_calls_only_one_wins(
    session_factory, make_approval, db, widen_read_then_write_window
):
    approval_id = await make_approval(status="pending")

    results = await _gather_sessions(
        session_factory,
        2,
        lambda sess: approval_service.deny(sess, approval_id, approved_by="racer"),
    )

    winners = [r for r in results if r is not None]
    assert len(winners) == 1

    from db.tables import Approval
    from sqlalchemy import select

    row = (await db.execute(select(Approval).where(Approval.id == approval_id))).scalar_one()
    assert row.status == "denied"


@pytest.mark.asyncio
async def test_deny_after_approve_is_noop(session_factory, make_approval):
    approval_id = await make_approval(status="pending")

    async with session_factory() as db:
        approved = await approval_service.approve(db, approval_id, approved_by="alice")
        assert approved is not None

    async with session_factory() as db:
        denied = await approval_service.deny(db, approval_id, approved_by="bob")
        assert denied is None  # already approved — deny is a no-op, not an override

    async with session_factory() as db:
        from db.tables import Approval
        from sqlalchemy import select

        row = (await db.execute(select(Approval).where(Approval.id == approval_id))).scalar_one()
        assert row.status == "approved"


# ── #12: end-to-end regression coverage ────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_approve_triggered_and_manual_execute_run_once(
    monkeypatch, session_factory, make_approval, db
):
    """Reproduces the exact scenario from issue #3: approving auto-triggers
    a background execution, and an operator (or script) fires the manual
    /execute endpoint for the same approval right after. Both code paths
    call execute_approved() concurrently for the same approval_id — device
    commands must run only once.
    """
    send_mock = _make_send_commands_mock()
    monkeypatch.setattr(execution_engine, "_send_commands_sync", send_mock)

    approval_id = await make_approval(status="pending")

    # Approve synchronously first, exactly like the /approve route does
    # before it spawns the background execution task.
    async with session_factory() as approve_session:
        approved = await approval_service.approve(approve_session, approval_id, approved_by="alice")
        assert approved is not None

    # Now race the auto-triggered background execution against a manual
    # execute call for the same approval — this is the two-code-path race
    # described in issue #3.
    results = await _gather_sessions(
        session_factory, 2, lambda sess: execution_engine.execute_approved(sess, approval_id)
    )

    assert send_mock.call_count == 1
    assert sum(1 for r in results if r.get("skipped")) == 1


@pytest.mark.asyncio
async def test_reset_orphaned_executing_on_startup(session_factory, make_approval, db):
    """Simulates a crash: an approval stuck in 'executing' (claimed but
    never completed) must be reset so it doesn't stay stuck forever and
    doesn't permanently block claim_executing() from ever running it.
    Sibling 'approved'/'pending' rows must be left untouched.
    """
    stuck_id = await make_approval(status="executing")
    approved_id = await make_approval(status="approved")
    pending_id = await make_approval(status="pending")

    count = await approval_service.reset_orphaned_executing(db)
    assert count == 1

    from db.tables import Approval
    from sqlalchemy import select

    stuck = (await db.execute(select(Approval).where(Approval.id == stuck_id))).scalar_one()
    approved = (await db.execute(select(Approval).where(Approval.id == approved_id))).scalar_one()
    pending = (await db.execute(select(Approval).where(Approval.id == pending_id))).scalar_one()

    assert stuck.status == "failed"
    assert stuck.execution_result and "error" in stuck.execution_result
    assert approved.status == "approved"  # untouched — still legitimately claimable
    assert pending.status == "pending"  # untouched
