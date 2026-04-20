"""Entry point - main async loop for the Comm100 live chat bot (Playwright)."""

from __future__ import annotations

import asyncio
import signal

import structlog
from playwright.async_api import async_playwright

from src.comm100.ai.claude_client import ClaudeClient
from src.comm100.ai.prompt_builder import PromptBuilder
from src.comm100.chat.processor import ChatProcessor
from src.comm100.chat.state import ChatStateTracker
from src.comm100.chat.template_matcher import TemplateMatcher
from src.comm100.config.loader import load_comm100_config
from src.comm100.pages.agent_console import AgentConsolePage
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
        polling_interval=config.settings.polling.interval_seconds,
        templates=len(config.templates.templates),
    )

    prompt_builder = PromptBuilder(config.system_prompt)
    claude_client = ClaudeClient(
        config.anthropic_credentials, config.settings.claude, prompt_builder
    )
    template_matcher = TemplateMatcher(config.templates)
    state = ChatStateTracker()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        try:
            console = AgentConsolePage(page, config.credentials.site_id)

            logger.info("logging_in")
            await console.login(
                config.credentials.email, config.credentials.password
            )

            online = await console.is_online()
            logger.info("agent_status", online=online)

            await console.navigate_to_chats()
            logger.info("comm100_bot_ready")
            write_heartbeat(status="healthy")

            processor = ChatProcessor(
                console, claude_client, template_matcher, state, config.settings
            )

            while not _shutdown_event.is_set():
                try:
                    await processor.run_polling_cycle()
                except Exception as e:
                    logger.error("cycle_error", error=str(e), exc_info=True)
                    write_heartbeat(status="error")

                    try:
                        await page.reload(timeout=30000)
                        await asyncio.sleep(5)
                        await console.navigate_to_chats()
                    except Exception:
                        pass

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
            await context.close()
            await browser.close()
            logger.info("comm100_bot_stopped")


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
