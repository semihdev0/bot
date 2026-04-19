"""Entry point - main async loop for the Comm100 live chat bot."""

from __future__ import annotations

import asyncio
import signal

import structlog

from src.comm100.ai.claude_client import ClaudeClient
from src.comm100.ai.prompt_builder import PromptBuilder
from src.comm100.api.client import Comm100Client
from src.comm100.chat.processor import ChatProcessor
from src.comm100.chat.state import ChatStateTracker
from src.comm100.chat.template_matcher import TemplateMatcher
from src.comm100.config.loader import load_comm100_config
from src.comm100.exceptions import Comm100AuthError
from src.monitoring.health import write_heartbeat
from src.monitoring.logger import setup_logging

logger = structlog.get_logger()

_shutdown_event = asyncio.Event()


def _handle_signal(signum, frame):
    logger.info("shutdown_signal_received", signal=signum)
    _shutdown_event.set()


async def main() -> None:
    setup_logging()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("comm100_bot_starting")
    config = load_comm100_config()
    logger.info(
        "config_loaded",
        region=config.credentials.region,
        polling_interval=config.settings.polling.interval_seconds,
        templates=len(config.templates.templates),
    )

    api_client = Comm100Client(config.credentials, config.settings.api)
    prompt_builder = PromptBuilder(config.system_prompt)
    claude_client = ClaudeClient(
        config.anthropic_credentials, config.settings.claude, prompt_builder
    )
    template_matcher = TemplateMatcher(config.templates)
    state = ChatStateTracker()

    try:
        await api_client.start()

        ok = await api_client.test_connection()
        if not ok:
            logger.critical("comm100_auth_failed_exiting")
            write_heartbeat(status="auth_error")
            return

        logger.info("comm100_bot_ready")
        write_heartbeat(status="healthy")

        processor = ChatProcessor(
            api_client, claude_client, template_matcher, state, config.settings
        )

        while not _shutdown_event.is_set():
            try:
                await processor.run_polling_cycle()
            except Comm100AuthError:
                logger.error("auth_failed_retrying")
                write_heartbeat(status="auth_error")
                try:
                    await asyncio.wait_for(
                        _shutdown_event.wait(), timeout=60
                    )
                except asyncio.TimeoutError:
                    pass
                continue
            except Exception as e:
                logger.critical("unexpected_error", error=str(e), exc_info=True)
                write_heartbeat(status="error")
                try:
                    await asyncio.wait_for(
                        _shutdown_event.wait(), timeout=30
                    )
                except asyncio.TimeoutError:
                    pass
                continue

            try:
                await asyncio.wait_for(
                    _shutdown_event.wait(),
                    timeout=config.settings.polling.interval_seconds,
                )
            except asyncio.TimeoutError:
                pass

    finally:
        logger.info("comm100_bot_shutting_down")
        write_heartbeat(status="stopped")
        await api_client.close()
        logger.info("comm100_bot_stopped")


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
