import argparse
import logging
from pathlib import Path
import signal
import sys
from uuid import UUID

# Ensure repository root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from packages.core.config import settings
from packages.services.outbox_worker import OutboxWorker


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("apps.worker")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Employee Platform - Background Outbox Worker",
    )
    parser.add_argument(
        "--worker-id",
        type=str,
        default=None,
        help="Unique identifier for this worker instance (default: auto-generated)",
    )
    parser.add_argument(
        "--tenant-id",
        type=str,
        default=None,
        help="Optional tenant UUID to restrict processing to a specific tenant",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=settings.outbox_worker_poll_interval,
        help="Polling interval in seconds when queue is empty",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=settings.outbox_worker_batch_size,
        help="Maximum number of outbox events to claim per batch",
    )
    parser.add_argument(
        "--lock-timeout",
        type=int,
        default=settings.outbox_worker_lock_timeout,
        help="Lock lease timeout in seconds before event is considered stale",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Exit after processing N polling iterations (useful for testing and batch jobs)",
    )

    args = parser.parse_args()

    tenant_uuid: UUID | None = None
    if args.tenant_id:
        try:
            tenant_uuid = UUID(args.tenant_id)
        except ValueError:
            logger.error("Invalid tenant UUID: %s", args.tenant_id)
            sys.exit(1)

    worker = OutboxWorker(
        worker_id=args.worker_id,
        tenant_id=tenant_uuid,
        poll_interval_seconds=args.poll_interval,
        batch_size=args.batch_size,
        lock_timeout_seconds=args.lock_timeout,
    )

    def handle_shutdown(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info("Received %s signal, initiating graceful worker shutdown...", sig_name)
        worker.stop()

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    logger.info(
        "Starting Outbox Worker [%s] (poll_interval=%.1fs, batch_size=%d, lock_timeout=%ds, tenant_id=%s)",
        worker.worker_id,
        args.poll_interval,
        args.batch_size,
        args.lock_timeout,
        tenant_uuid or "all",
    )

    try:
        worker.run(max_iterations=args.max_iterations)
    except Exception as exc:
        logger.error("Fatal error running outbox worker: %s", exc, exc_info=True)
        sys.exit(1)

    logger.info("Outbox Worker [%s] shutdown complete.", worker.worker_id)


if __name__ == "__main__":
    main()
