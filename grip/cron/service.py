"""Cron scheduling service: periodic task execution via cron expressions.

Jobs are stored as JSON in workspace/cron/jobs.json. When a job fires,
it calls EngineProtocol.run() with the job's prompt as the user message.

Uses croniter for cron expression parsing (e.g. "*/5 * * * *" = every 5 min).

Reliability features:
  - State machine: pending → fired → running → succeeded/failed
  - Idempotency keys prevent duplicate task accumulation
  - Deferred execution queue retries jobs that fire while engine is busy
  - last_run only updated AFTER execution completes (not before)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from loguru import logger

from grip.config.schema import CronConfig
from grip.engines.types import EngineProtocol


class JobState(StrEnum):
    """State machine for cron job execution lifecycle."""

    PENDING = "pending"
    FIRED = "fired"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(slots=True)
class CronJob:
    """A single scheduled task definition."""

    id: str
    name: str
    schedule: str
    prompt: str
    enabled: bool = True
    last_run: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    reply_to: str = ""
    idempotency_key: str = ""
    last_state: str = "pending"
    run_count: int = 0
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CronJob:
        valid_keys = cls.__slots__
        return cls(**{k: v for k, v in data.items() if k in valid_keys})

    @staticmethod
    def generate_idempotency_key(name: str, schedule: str, prompt: str) -> str:
        """Deterministic key from job content to prevent duplicates."""
        raw = f"{name.strip().lower()}|{schedule.strip()}|{prompt.strip().lower()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(slots=True)
class _DeferredFire:
    """A job fire that was deferred because the engine was busy."""

    job_id: str
    queued_at: datetime


class CronService:
    """Manages cron job persistence and periodic execution.

    On start(), spawns an asyncio loop that checks every 30 seconds
    whether any job is due. When a job fires, it calls engine.run()
    with the job's prompt as the user message. If the job has a reply_to
    session key (e.g. "telegram:12345"), the result is published to
    the message bus so it reaches the originating channel.

    Reliability guarantees:
      - Jobs transition through a state machine (pending → fired → running → succeeded/failed)
      - last_run is set AFTER execution, not before, preventing the race where
        a job is marked "done" but never actually ran
      - If the engine is busy when a job fires, it goes into a deferred queue
        and retries on the next check cycle instead of being silently dropped
      - Idempotency keys prevent accumulating duplicate jobs with identical
        name + schedule + prompt combinations
    """

    _MAX_DEFERRED = 100
    _MAX_DEFER_AGE_SECONDS = 600

    def __init__(
        self,
        cron_dir: Path,
        engine: EngineProtocol,
        config: CronConfig,
        bus: Any | None = None,
    ) -> None:
        self._cron_dir = cron_dir
        self._jobs_file = cron_dir / "jobs.json"
        self._engine = engine
        self._config = config
        self._bus = bus
        self._jobs: dict[str, CronJob] = {}
        self._running = False
        self._check_interval = 30
        self._pending_tasks: set[asyncio.Task] = set()
        self._executing: set[str] = set()
        self._deferred: deque[_DeferredFire] = deque(maxlen=self._MAX_DEFERRED)

        self._load_jobs()

    def _load_jobs(self) -> None:
        """Load jobs from the persistent JSON file."""
        if not self._jobs_file.exists():
            return
        try:
            data = json.loads(self._jobs_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to read cron jobs file: {}", exc)
            return
        for item in data:
            try:
                job = CronJob.from_dict(item)
                self._jobs[job.id] = job
            except (KeyError, TypeError) as exc:
                logger.warning("Skipping malformed cron job entry: {}", exc)
        logger.debug("Loaded {} cron jobs", len(self._jobs))

    def _save_jobs(self) -> None:
        """Persist all jobs to the JSON file atomically."""
        self._cron_dir.mkdir(parents=True, exist_ok=True)
        data = [job.to_dict() for job in self._jobs.values()]
        tmp = self._jobs_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.rename(self._jobs_file)

    def _find_duplicate(self, name: str, schedule: str, prompt: str) -> CronJob | None:
        """Check if a job with the same content already exists via idempotency key."""
        key = CronJob.generate_idempotency_key(name, schedule, prompt)
        for job in self._jobs.values():
            if job.idempotency_key == key:
                return job
        return None

    def add_job(self, name: str, schedule: str, prompt: str, reply_to: str = "") -> CronJob:
        """Create and persist a new cron job.

        If a job with identical name+schedule+prompt already exists (by
        idempotency key), returns the existing job instead of creating
        a duplicate.

        Args:
            name: Human-readable job name.
            schedule: Cron expression (e.g. "*/5 * * * *").
            prompt: The prompt to send to the engine when the job fires.
            reply_to: Session key to route results to (e.g. "telegram:12345").

        Raises:
            ValueError: If reply_to is set but not in "channel:chat_id" format.
        """
        if reply_to and ":" not in reply_to:
            raise ValueError(
                f"Invalid reply_to format: '{reply_to}'. "
                "Expected 'channel:chat_id' (e.g. 'telegram:12345')."
            )

        existing = self._find_duplicate(name, schedule, prompt)
        if existing:
            logger.info("Job with same content already exists: {} ({})", existing.name, existing.id)
            if reply_to and not existing.reply_to:
                existing.reply_to = reply_to
                self._save_jobs()
            return existing

        idem_key = CronJob.generate_idempotency_key(name, schedule, prompt)
        job = CronJob(
            id=f"cron_{uuid.uuid4().hex[:8]}",
            name=name,
            schedule=schedule,
            prompt=prompt,
            reply_to=reply_to,
            idempotency_key=idem_key,
        )
        self._jobs[job.id] = job
        self._save_jobs()
        logger.info("Cron job added: {} ({})", name, schedule)
        return job

    def remove_job(self, job_id: str) -> bool:
        """Remove a job by ID. Returns True if found and removed."""
        if job_id in self._jobs:
            del self._jobs[job_id]
            self._deferred = deque(
                (d for d in self._deferred if d.job_id != job_id),
                maxlen=self._MAX_DEFERRED,
            )
            self._save_jobs()
            return True
        return False

    def enable_job(self, job_id: str) -> bool:
        if job_id in self._jobs:
            self._jobs[job_id].enabled = True
            self._save_jobs()
            return True
        return False

    def disable_job(self, job_id: str) -> bool:
        if job_id in self._jobs:
            self._jobs[job_id].enabled = False
            self._save_jobs()
            return True
        return False

    def list_jobs(self) -> list[CronJob]:
        return list(self._jobs.values())

    def get_job(self, job_id: str) -> CronJob | None:
        return self._jobs.get(job_id)

    async def start(self) -> None:
        """Start the cron scheduler loop. Runs until cancelled."""
        self._running = True
        logger.info("Cron service started ({} jobs loaded)", len(self._jobs))

        while self._running:
            await self._check_and_run_due_jobs()
            await self._retry_deferred_jobs()
            await asyncio.sleep(self._check_interval)

    async def stop(self) -> None:
        """Signal the scheduler to stop and wait for in-flight jobs."""
        self._running = False
        if self._pending_tasks:
            logger.info("Waiting for {} in-flight cron jobs to finish", len(self._pending_tasks))
            done, _ = await asyncio.wait(self._pending_tasks, timeout=30)
            if len(done) < len(self._pending_tasks):
                logger.warning("Some cron jobs did not finish within shutdown timeout")
        logger.info("Cron service stopped")

    async def _check_and_run_due_jobs(self) -> None:
        """Check all enabled jobs and run any that are due."""
        self._load_jobs()
        now = datetime.now(UTC)

        for job in list(self._jobs.values()):
            if not job.enabled:
                continue
            if job.id in self._executing:
                continue

            if self._is_job_due(job, now):
                self._fire_job(job)

    def _fire_job(self, job: CronJob) -> None:
        """Transition job to FIRED state and spawn execution task.

        If execution is already in progress for this job, defer it
        for retry on the next cycle instead of silently dropping.
        """
        if job.id in self._executing:
            already_deferred = any(d.job_id == job.id for d in self._deferred)
            if not already_deferred:
                self._deferred.append(_DeferredFire(job_id=job.id, queued_at=datetime.now(UTC)))
                logger.info("Deferred cron job {} (engine busy)", job.id)
            return

        job.last_state = JobState.FIRED
        self._save_jobs()

        task = asyncio.create_task(
            self._execute_job(job),
            name=f"cron-{job.id}",
        )
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _retry_deferred_jobs(self) -> None:
        """Retry deferred job fires that were blocked by busy engine."""
        now = datetime.now(UTC)
        retryable: list[_DeferredFire] = []

        while self._deferred:
            entry = self._deferred.popleft()
            age = (now - entry.queued_at).total_seconds()
            if age > self._MAX_DEFER_AGE_SECONDS:
                logger.warning(
                    "Dropping expired deferred fire for job {} (aged {}s)", entry.job_id, int(age)
                )
                continue
            retryable.append(entry)

        for entry in retryable:
            job = self._jobs.get(entry.job_id)
            if job and job.enabled and job.id not in self._executing:
                self._fire_job(job)
            elif job and job.id in self._executing:
                self._deferred.append(entry)

    @staticmethod
    def _ensure_aware(dt: datetime) -> datetime:
        """Ensure a datetime is timezone-aware (default to UTC if naive)."""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt

    def _is_job_due(self, job: CronJob, now: datetime) -> bool:
        """Determine if a cron job should fire based on its schedule."""
        try:
            from croniter import croniter

            if job.last_run:
                last = self._ensure_aware(datetime.fromisoformat(job.last_run))
            else:
                last = self._ensure_aware(datetime.fromisoformat(job.created_at))
            cron = croniter(job.schedule, last)
            next_run = self._ensure_aware(cron.get_next(datetime))
            return now >= next_run
        except ImportError:
            if job.last_run:
                last = self._ensure_aware(datetime.fromisoformat(job.last_run))
            else:
                last = self._ensure_aware(datetime.fromisoformat(job.created_at))
            interval = self._parse_simple_interval(job.schedule)
            return (now - last).total_seconds() >= interval
        except Exception as exc:
            logger.error("Cron expression error for job {}: {}", job.id, exc)
            return False

    @staticmethod
    def _parse_simple_interval(schedule: str) -> float:
        """Extract minute interval from simple cron patterns like '*/N * * * *'.

        Returns interval in seconds. Defaults to 3600 (1 hour) if unparseable.
        """
        parts = schedule.strip().split()
        if parts and parts[0].startswith("*/"):
            try:
                minutes = int(parts[0][2:])
                return minutes * 60
            except ValueError:
                pass
        return 3600

    async def _execute_job(self, job: CronJob) -> None:
        """Run a single cron job through the engine with a timeout.

        State transitions: FIRED → RUNNING → SUCCEEDED or FAILED.
        last_run is set AFTER execution completes to prevent the race
        condition where a job appears "done" but never actually ran.
        """
        self._executing.add(job.id)
        job.last_state = JobState.RUNNING
        self._save_jobs()

        try:
            logger.info("Executing cron job: {} ({})", job.name, job.id)

            timeout = self._config.exec_timeout_minutes * 60
            session_key = f"cron:{job.id}"

            try:
                result = await asyncio.wait_for(
                    self._engine.run(job.prompt, session_key=session_key),
                    timeout=timeout,
                )

                job.last_run = datetime.now(UTC).isoformat()
                job.last_state = JobState.SUCCEEDED
                job.run_count += 1
                job.last_error = ""
                self._save_jobs()

                logger.info(
                    "Cron job {} completed: {} iterations, response length {}",
                    job.id,
                    result.iterations,
                    len(result.response),
                )

                if job.reply_to and self._bus and result.response:
                    await self._publish_result(job, result.response)

            except TimeoutError:
                job.last_run = datetime.now(UTC).isoformat()
                job.last_state = JobState.FAILED
                job.last_error = f"Timed out after {self._config.exec_timeout_minutes} minutes"
                self._save_jobs()

                logger.error("Cron job {} timed out after {}s", job.id, timeout)
                if job.reply_to and self._bus:
                    await self._publish_result(
                        job,
                        f"Cron job '{job.name}' timed out after {self._config.exec_timeout_minutes} minutes.",
                    )
            except Exception as exc:
                job.last_run = datetime.now(UTC).isoformat()
                job.last_state = JobState.FAILED
                job.last_error = str(exc)[:500]
                self._save_jobs()

                logger.error("Cron job {} failed: {}", job.id, exc)
                if job.reply_to and self._bus:
                    await self._publish_result(job, f"Cron job '{job.name}' failed: {exc}")
        finally:
            self._executing.discard(job.id)

    async def _publish_result(self, job: CronJob, text: str) -> None:
        """Publish a cron job result to the message bus for channel delivery."""
        from grip.bus.events import OutboundMessage

        parts = job.reply_to.split(":", 1)
        if len(parts) != 2:
            logger.warning("Invalid reply_to format for cron job {}: {}", job.id, job.reply_to)
            return

        channel, chat_id = parts
        try:
            await self._bus.publish_outbound(
                OutboundMessage(
                    channel=channel,
                    chat_id=chat_id,
                    text=text,
                )
            )
            logger.info("Cron job {} result published to {}:{}", job.id, channel, chat_id)
        except Exception as exc:
            logger.error("Failed to publish cron result for {}: {}", job.id, exc)
