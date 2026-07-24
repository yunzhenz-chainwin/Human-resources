import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.services.talent_retention import (
    process_pending_storage_deletions,
    purge_expired_candidates,
)

logger = logging.getLogger(__name__)


def run_retention_cycle(
    *,
    settings: Settings | None = None,
    session_factory: Callable[[], Session] = SessionLocal,
) -> dict[str, int]:
    """Run one bounded scheduled cycle; safe to invoke from an external scheduler too."""

    settings = settings or get_settings()
    totals = {
        "deleted_candidates": 0,
        "deleted_resume_files": 0,
        "deleted_storage_objects": 0,
        "storage_delete_failures": 0,
        "remaining_candidates": 0,
    }
    for _ in range(max(1, settings.talent_retention_max_batches_per_run)):
        with session_factory() as db:
            result = purge_expired_candidates(
                db,
                dry_run=False,
                batch_size=settings.talent_retention_batch_size,
                settings=settings,
                process_storage=False,
            )
        if not result.lock_acquired:
            break
        totals["deleted_candidates"] += result.deleted_candidates
        totals["deleted_resume_files"] += result.deleted_resume_files
        totals["deleted_storage_objects"] += result.deleted_storage_objects
        totals["storage_delete_failures"] += result.storage_delete_failures
        totals["remaining_candidates"] = result.remaining_candidates
        if result.deleted_candidates == 0 or result.remaining_candidates == 0:
            break
    # Always process the durable outbox, including cycles with zero eligible
    # candidates. Keeping it outside the candidate-batch loop also prevents a
    # failed provider from being hammered repeatedly within the same cycle.
    with session_factory() as db:
        storage = process_pending_storage_deletions(
            db,
            limit=(
                settings.talent_retention_batch_size
                * max(1, settings.talent_retention_max_batches_per_run)
                * 2
            ),
            settings=settings,
        )
        totals["deleted_storage_objects"] += storage.deleted_storage_objects
        totals["storage_delete_failures"] += storage.failures
    return totals


async def _stop_requested(stop_event: asyncio.Event, timeout: float) -> bool:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=max(0.01, timeout))
    except TimeoutError:
        return False
    return True


async def run_retention_worker(
    stop_event: asyncio.Event,
    *,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    if await _stop_requested(
        stop_event, settings.talent_retention_worker_initial_delay_seconds
    ):
        return
    while not stop_event.is_set():
        try:
            totals = await asyncio.to_thread(run_retention_cycle, settings=settings)
            logger.info(
                "talent retention cycle completed: candidates=%d resumes=%d "
                "storage_objects=%d failures=%d remaining=%d",
                totals["deleted_candidates"],
                totals["deleted_resume_files"],
                totals["deleted_storage_objects"],
                totals["storage_delete_failures"],
                totals["remaining_candidates"],
            )
        except Exception:
            # Source candidate data is never interpolated into this operational log.
            logger.exception("talent retention cycle failed")
        if await _stop_requested(stop_event, settings.talent_retention_worker_interval_seconds):
            return
