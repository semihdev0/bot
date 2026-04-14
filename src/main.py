"""Entry point - main async loop for the bonus approval bot."""

from __future__ import annotations

import asyncio
import signal
import sys

import structlog

from src.actions.processor import BonusProcessor
from src.browser.manager import BrowserManager
from src.browser.session import SessionManager
from src.config.loader import load_all_config
from src.monitoring.health import write_heartbeat
from src.monitoring.logger import setup_logging
from src.utils.exceptions import BrowserError, SessionExpiredError

logger = structlog.get_logger()

# Graceful shutdown flag
_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logger.info("shutdown_signal_received", signal=signum)
    _shutdown = True


async def main() -> None:
    """Main entry point for the bonus approval bot."""
    global _shutdown

    # Setup logging
    setup_logging()

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Load and validate all config
    logger.info("bot_starting")
    config = load_all_config()
    logger.info(
        "config_loaded",
        bonus_types=list(config.bonus_rules.bonus_types.keys()),
        polling_interval=config.settings.polling.interval_seconds,
    )

    # Create browser manager
    browser = BrowserManager(config.settings.browser)

    try:
        await browser.start()
        session = SessionManager(browser, config)

        while not _shutdown:
            try:
                # Ensure we have a valid session
                page = await session.ensure_logged_in()

                # Process pending requests
                processor = BonusProcessor(page, config)
                count = await processor.process_pending_requests()

                # Decide sleep duration
                if count == 0:
                    sleep_time = config.settings.polling.pause_on_empty_seconds
                else:
                    sleep_time = config.settings.polling.interval_seconds

                logger.info(
                    "cycle_sleeping",
                    processed=count,
                    sleep_seconds=sleep_time,
                )

                # Sleep with shutdown check
                for _ in range(sleep_time):
                    if _shutdown:
                        break
                    await asyncio.sleep(1)

            except SessionExpiredError:
                logger.warning("session_expired_relogging")
                await session.close()
                continue

            except BrowserError as e:
                logger.error("browser_error_restarting", error=str(e))
                write_heartbeat(status="browser_error")
                await session.close()
                await browser.cleanup()
                await asyncio.sleep(30)
                await browser.start()
                session = SessionManager(browser, config)
                continue

            except Exception as e:
                logger.critical("unexpected_error", error=str(e), exc_info=True)
                write_heartbeat(status="error")
                await session.close()
                await browser.cleanup()
                await asyncio.sleep(60)
                await browser.start()
                session = SessionManager(browser, config)
                continue

    finally:
        logger.info("bot_shutting_down")
        write_heartbeat(status="stopped")
        await browser.cleanup()
        logger.info("bot_stopped")


def run() -> None:
    """Synchronous entry point."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
