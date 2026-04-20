"""Playwright page object for Comm100 Agent Console."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog
from playwright.async_api import Page, Locator

logger = structlog.get_logger()

AGENT_CONSOLE_URL = (
    "https://dash15.lively-chat.com/agentconsole/agentconsole.html"
    "?partnerId=100001&siteId={site_id}"
)
LOGIN_URL = "https://secure.comm100.io/signin"


@dataclass
class ChatMessage:
    sender: str  # "visitor" or "agent"
    content: str


class AgentConsolePage:
    """Interacts with the Comm100 Agent Console via Playwright."""

    def __init__(self, page: Page, site_id: str) -> None:
        self._page = page
        self._site_id = site_id

    async def login(self, email: str, password: str) -> None:
        url = AGENT_CONSOLE_URL.format(site_id=self._site_id)
        await self._page.goto(url, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(3)

        current = self._page.url
        if "signin" in current or "login" in current:
            logger.info("login_required", url=current)

            email_input = self._page.locator(
                "input[type='email'], input[name='email'], input[id*='email']"
            ).first
            await email_input.wait_for(state="visible", timeout=15000)
            await email_input.fill(email)

            password_input = self._page.locator(
                "input[type='password'], input[name='password']"
            ).first
            await password_input.fill(password)

            submit = self._page.locator(
                "button[type='submit'], input[type='submit']"
            ).first
            await submit.click()

            await self._page.wait_for_url("**/agentconsole/**", timeout=30000)
            logger.info("login_success")
        else:
            logger.info("already_logged_in")

        await asyncio.sleep(3)

    async def navigate_to_chats(self) -> None:
        chat_icon = self._page.locator(
            "nav a[href*='chat'], [class*='chat-nav'], "
            "[class*='nav'] [class*='chat']"
        ).first
        try:
            await chat_icon.click(timeout=5000)
        except Exception:
            icons = self._page.locator("nav a, .nav-item, [class*='sidebar'] a")
            count = await icons.count()
            if count >= 2:
                await icons.nth(1).click()
        await asyncio.sleep(2)

    async def get_ongoing_chat_count(self) -> int:
        try:
            ongoing_text = await self._page.locator(
                "text=/Ongoing \\d+/"
            ).first.inner_text(timeout=3000)
            for part in ongoing_text.split():
                if part.isdigit():
                    return int(part)
        except Exception:
            pass
        return 0

    async def get_chat_items(self) -> list[Locator]:
        items = self._page.locator(
            "[class*='chat-item'], [class*='chatItem'], "
            "[class*='chat-list'] > div, [class*='chatList'] > div"
        )
        count = await items.count()
        if count == 0:
            items = self._page.locator(
                ".ongoing-chats li, [class*='ongoing'] li, "
                "[class*='ongoing'] > div"
            )
            count = await items.count()
        return [items.nth(i) for i in range(count)]

    async def click_chat(self, index: int = 0) -> None:
        items = await self.get_chat_items()
        if index < len(items):
            await items[index].click()
            await asyncio.sleep(1)

    async def get_visitor_messages(self) -> list[ChatMessage]:
        messages = []

        msg_elements = self._page.locator(
            "[class*='visitor'] [class*='content'], "
            "[class*='visitor'] [class*='text'], "
            "[class*='message-visitor'], "
            ".visitor-message"
        )
        count = await msg_elements.count()

        if count == 0:
            all_msgs = self._page.locator(
                "[class*='message']"
            )
            total = await all_msgs.count()
            for i in range(total):
                el = all_msgs.nth(i)
                text = await el.inner_text()
                classes = await el.get_attribute("class") or ""
                if "visitor" in classes.lower() or "Visitor" in text:
                    content = text.split("\n")[-1].strip()
                    if content and "joined" not in content and "wait" not in content:
                        messages.append(ChatMessage(sender="visitor", content=content))
        else:
            for i in range(count):
                text = (await msg_elements.nth(i).inner_text()).strip()
                if text:
                    messages.append(ChatMessage(sender="visitor", content=text))

        return messages

    async def get_all_messages(self) -> list[ChatMessage]:
        messages = []

        chat_area = self._page.locator(
            "[class*='chat-area'], [class*='chatArea'], "
            "[class*='message-list'], [class*='messageList'], "
            "[class*='conversation']"
        )

        msg_wrappers = chat_area.locator(
            "[class*='message-wrap'], [class*='messageWrap'], "
            "[class*='msg-wrap'], > div"
        )
        count = await msg_wrappers.count()

        for i in range(count):
            wrapper = msg_wrappers.nth(i)
            text = (await wrapper.inner_text()).strip()
            classes = (await wrapper.get_attribute("class") or "").lower()

            if not text or "joined" in text or "wait for" in text:
                continue

            lines = text.split("\n")
            content = lines[-1].strip() if lines else text

            if "visitor" in classes or "visitor" in text.lower().split("\n")[0]:
                messages.append(ChatMessage(sender="visitor", content=content))
            elif "agent" in classes:
                messages.append(ChatMessage(sender="agent", content=content))

        return messages

    async def send_reply(self, text: str) -> None:
        reply_area = self._page.locator(
            "[class*='reply'] textarea, "
            "[class*='reply'] [contenteditable='true'], "
            "[class*='input-area'] textarea, "
            "textarea[class*='reply'], "
            ".reply-area textarea"
        ).first

        try:
            await reply_area.wait_for(state="visible", timeout=5000)
            await reply_area.click()
            await reply_area.fill(text)
        except Exception:
            textarea = self._page.locator("textarea").first
            await textarea.click()
            await textarea.fill(text)

        await asyncio.sleep(0.5)
        await self._page.keyboard.press("Enter")
        logger.info("reply_sent", length=len(text))
        await asyncio.sleep(1)

    async def accept_new_chat(self) -> bool:
        try:
            accept_btn = self._page.locator(
                "text='Accept', text='Go to Chat'"
            ).first
            if await accept_btn.is_visible(timeout=2000):
                await accept_btn.click()
                await asyncio.sleep(2)
                logger.info("new_chat_accepted")
                return True
        except Exception:
            pass
        return False

    async def has_unread_indicator(self) -> bool:
        try:
            badge = self._page.locator(
                "[class*='badge'], [class*='unread'], "
                "[class*='notification']"
            )
            count = await badge.count()
            return count > 0
        except Exception:
            return False

    async def is_online(self) -> bool:
        try:
            online = self._page.locator("text='Online'").first
            return await online.is_visible(timeout=2000)
        except Exception:
            return False
