"""Health check and heartbeat for monitoring bot liveness."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import structlog

logger = structlog.get_logger()

HEALTH_FILE = Path("logs/health.json")


def write_heartbeat(
    status: str = "healthy",
    processed: int = 0,
    approved: int = 0,
    rejected: int = 0,
    errors: int = 0,
) -> None:
    """Write a health status file that external monitors can check."""
    try:
        HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "timestamp": datetime.now().isoformat(),
            "status": status,
            "stats": {
                "processed": processed,
                "approved": approved,
                "rejected": rejected,
                "errors": errors,
            },
        }
        HEALTH_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.debug("heartbeat_written", status=status)
    except Exception as e:
        logger.error("heartbeat_write_failed", error=str(e))
