"""Playwright page object for Comm100 Agent Console."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog
from playwright.async_api import Page, Locator

logger = structlog.get_logger()

AGENT_CONSOLE_URL = (
    "https://dash15.lively-chat.com/agentconsole/auth.html"
    "?siteId={site_id}"
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
        # Step 1: Go to Comm100 login page
        logger.info("navigating_to_login", url=LOGIN_URL)
        await self._page.goto(LOGIN_URL, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(3)
        await self._page.screenshot(path="/tmp/comm100_01_login_page.png")

        # Step 2: Fill email
        email_input = self._page.locator(
            "input[type='email'], input[name='email'], "
            "input[id*='email'], input[id*='Email'], "
            "input[placeholder*='mail'], input[placeholder*='Mail']"
        ).first
        await email_input.wait_for(state="visible", timeout=15000)
        await email_input.fill(email)
        logger.info("login_email_filled")

        # Step 3: Fill password
        password_input = self._page.locator(
            "input[type='password'], input[name='password'], "
            "input[id*='password'], input[id*='Password']"
        ).first
        await password_input.wait_for(state="visible", timeout=10000)
        await password_input.fill(password)
        logger.info("login_password_filled")

        # Step 4: Click submit button
        submitted = False
        submit_selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Sign')",
            "button:has-text('Log')",
            "button:has-text('Giriş')",
            "button:has-text('Submit')",
            "#btnLogin",
            "form button",
        ]
        for selector in submit_selectors:
            try:
                btn = self._page.locator(selector).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    submitted = True
                    logger.info("login_submit_clicked", selector=selector)
                    break
            except Exception:
                continue

        if not submitted:
            logger.info("login_submit_fallback_enter")
            await password_input.press("Enter")

        await asyncio.sleep(5)
        await self._page.screenshot(path="/tmp/comm100_02_after_login.png")
        logger.info("login_form_submitted", current_url=self._page.url)

        # Step 5: Navigate to Agent Console
        console_url = AGENT_CONSOLE_URL.format(site_id=self._site_id)
        logger.info("navigating_to_console", url=console_url)
        await self._page.goto(console_url, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(5)
        await self._page.screenshot(path="/tmp/comm100_03_console.png")
        logger.info("console_loaded", current_url=self._page.url)

        # Step 6: Handle "forced login" if another session is active
        await self._handle_forced_login()

        await asyncio.sleep(3)

    async def _handle_forced_login(self) -> None:
        for attempt in range(3):
            clicked = False
            btn_selectors = [
                "button.MuiButton-root:has-text('OK')",
                "button:has-text('OK')",
                "button:has-text('Force')",
                "button:has-text('Continue')",
                "button:has-text('Log In')",
                "button:has-text('Login')",
                "button:has-text('Yes')",
                "button:has-text('Confirm')",
                ".MuiButton-containedPrimary",
            ]
            for selector in btn_selectors:
                try:
                    btn = self._page.locator(selector).first
                    if await btn.is_visible(timeout=2000):
                        text = (await btn.inner_text()).strip()
                        await btn.click()
                        logger.info(
                            "dialog_button_clicked",
                            selector=selector,
                            text=text,
                            attempt=attempt,
                        )
                        clicked = True
                        await asyncio.sleep(3)
                        break
                except Exception:
                    continue

            if not clicked:
                break

        await self._page.screenshot(path="/tmp/comm100_04_after_dialogs.png")
        logger.info("dialog_handling_done", url=self._page.url)

    async def navigate_to_chats(self) -> None:
        logger.info("navigate_to_chats", current_url=self._page.url)
        await self._page.screenshot(path="/tmp/comm100_05_before_nav.png")

        nav_selectors = [
            "[class*='Chat'] svg",
            "[class*='chat'] svg",
            "nav a[href*='chat']",
            "[class*='chat-nav']",
            "[class*='nav'] [class*='chat']",
            "[class*='LiveChat']",
            "[class*='liveChat']",
        ]
        for selector in nav_selectors:
            try:
                el = self._page.locator(selector).first
                if await el.is_visible(timeout=2000):
                    await el.click(force=True)
                    logger.info("nav_clicked", selector=selector)
                    await asyncio.sleep(2)
                    await self._page.screenshot(
                        path="/tmp/comm100_06_after_nav.png"
                    )
                    return
            except Exception:
                continue

        logger.info("nav_no_chat_icon_found_staying_on_current_page")

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
        selectors = [
            "[class*='ChatItem-module']",
            "[class*='chatItem']",
            "[class*='chat-item']",
            "[class*='chat-list'] > div",
            "[class*='chatList'] > div",
            "[class*='ChatList'] > div",
            "[class*='ongoing'] li",
            "[class*='ongoing'] > div",
            "[class*='Ongoing'] > div",
        ]
        for selector in selectors:
            items = self._page.locator(selector)
            count = await items.count()
            if count > 0:
                logger.info(
                    "chat_items_found", selector=selector, count=count
                )
                return [items.nth(i) for i in range(count)]
        return []

    async def take_debug_screenshot(self) -> None:
        import time
        ts = int(time.time()) % 10000
        path = f"/tmp/comm100_debug_{ts}.png"
        await self._page.screenshot(path=path)
        logger.info("debug_screenshot", path=path, url=self._page.url)

    async def click_chat(self, index: int = 0) -> None:
        items = await self.get_chat_items()
        if index < len(items):
            await items[index].evaluate("el => el.click()")
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
        accept_selectors = [
            "button:has-text('Accept')",
            "button:has-text('Go to Chat')",
            ".MuiButton-containedPrimary:has-text('Accept')",
            ".MuiButton-containedPrimary:has-text('Go to Chat')",
        ]
        for selector in accept_selectors:
            try:
                btn = self._page.locator(selector).first
                if await btn.is_visible(timeout=1000):
                    await btn.click(force=True)
                    await asyncio.sleep(2)
                    logger.info("new_chat_accepted", selector=selector)
                    return True
            except Exception:
                continue
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
