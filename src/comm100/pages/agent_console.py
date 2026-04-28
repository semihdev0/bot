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

        # The sidebar has icons: [0]=Visitors(globe), [1]=Chats(bubble), ...
        # Click the 2nd sidebar icon (chat bubble) to go to Chats section
        sidebar_icons = self._page.locator(
            "[class*='sidebar'] svg, "
            "[class*='Sidebar'] svg, "
            "[class*='navigation'] svg, "
            "[class*='Navigation'] svg, "
            "[class*='nav-'] svg, "
            "[class*='Nav-'] svg"
        )
        count = await sidebar_icons.count()
        logger.info("sidebar_icons_found", count=count)

        if count >= 2:
            await sidebar_icons.nth(1).click(force=True)
            logger.info("sidebar_chat_icon_clicked", index=1)
            await asyncio.sleep(3)
            await self._page.screenshot(path="/tmp/comm100_06_after_nav.png")
            return

        # Fallback: try clicking "My Chats" tab
        my_chats = self._page.locator(
            "button:has-text('My Chats'), "
            "[class*='tab']:has-text('My Chats'), "
            "a:has-text('My Chats')"
        ).first
        try:
            if await my_chats.is_visible(timeout=3000):
                await my_chats.click(force=True)
                logger.info("my_chats_tab_clicked")
                await asyncio.sleep(2)
                await self._page.screenshot(path="/tmp/comm100_06_after_nav.png")
                return
        except Exception:
            pass

        # Last resort: find any element that looks like a chat nav
        # Try clicking all sidebar-like items
        all_sidebar = self._page.locator(
            "[class*='sidebar'] > *, [class*='Sidebar'] > *"
        )
        count = await all_sidebar.count()
        if count >= 2:
            await all_sidebar.nth(1).click(force=True)
            logger.info("sidebar_fallback_clicked", index=1)
            await asyncio.sleep(3)
            await self._page.screenshot(path="/tmp/comm100_06_after_nav.png")
            return

        logger.warning("nav_no_chat_icon_found")

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
                # Only return visible items
                visible = []
                for i in range(min(count, 10)):
                    item = items.nth(i)
                    try:
                        if await item.is_visible(timeout=1000):
                            visible.append(item)
                    except Exception:
                        continue
                if visible:
                    logger.info(
                        "chat_items_found",
                        selector=selector,
                        total=count,
                        visible=len(visible),
                    )
                    return visible
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
        messages: list[ChatMessage] = []
        try:
            msg_locator = self._page.locator("[class*='Message-module']")
            count = await msg_locator.count()

            if count == 0:
                return messages

            for i in range(count):
                try:
                    el = msg_locator.nth(i)
                    cls = (await el.get_attribute("class")) or ""

                    if "SystemMessage" in cls:
                        continue

                    text = (await el.inner_text(timeout=3000)).strip()
                    if not text:
                        continue

                    lower = text.lower()
                    if any(skip in lower for skip in [
                        "joined", "katıldı", "görüşmeye",
                        "please wait", "please click", "leave us a message",
                    ]):
                        continue

                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                    content = lines[-1] if lines else ""
                    if not content:
                        continue

                    sender = "visitor"
                    if "Agent" in cls or "agent" in cls or "Right" in cls or "right" in cls:
                        sender = "agent"
                    else:
                        inner_html = (await el.inner_html(timeout=2000)) or ""
                        if "Agent" in inner_html or "agent" in inner_html:
                            sender = "agent"
                        else:
                            # CSS-module hashed class fallback: outgoing messages in
                            # Comm100 typically render aligned right with a different
                            # background. Probe computed style as a last resort.
                            try:
                                aligned_right = await el.evaluate(
                                    "el => { const s = getComputedStyle(el);"
                                    " return s.textAlign === 'right' || s.alignSelf === 'flex-end'"
                                    " || s.justifyContent === 'flex-end'; }"
                                )
                                if aligned_right:
                                    sender = "agent"
                            except Exception:
                                pass

                    messages.append(ChatMessage(sender=sender, content=content))
                except Exception:
                    continue

            if not getattr(self, "_msgs_logged", False) and messages:
                self._msgs_logged = True
                logger.info(
                    "messages_parsed",
                    count=len(messages),
                    sample=[{"s": m.sender, "c": m.content[:40]} for m in messages[:5]],
                )

        except Exception as e:
            logger.error("get_messages_error", error=str(e))

        return messages

    async def send_reply(self, text: str) -> None:
        # First click the "Reply" tab to make sure we're in reply mode
        try:
            reply_tab = self._page.locator(
                "[class*='tab']:has-text('Reply'), "
                "button:has-text('Reply'), "
                "[role='tab']:has-text('Reply')"
            ).first
            if await reply_tab.is_visible(timeout=2000):
                await reply_tab.click(force=True)
                await asyncio.sleep(0.5)
        except Exception:
            pass

        # Find the reply input area
        textarea = None
        textarea_selectors = [
            "[class*='Reply-module'] textarea",
            "[class*='reply-module'] textarea",
            "[class*='Reply-module'] [contenteditable='true']",
            "[class*='reply-module'] [contenteditable='true']",
            "[class*='chatInput'] textarea",
            "[class*='ChatInput'] textarea",
            "[class*='chatInput'] [contenteditable='true']",
            "[class*='ChatInput'] [contenteditable='true']",
            "[class*='reply'] textarea",
            "[class*='Reply'] textarea",
            "[class*='reply'] [contenteditable='true']",
            "[class*='Reply'] [contenteditable='true']",
            "[contenteditable='true']",
            "textarea",
        ]
        for selector in textarea_selectors:
            try:
                loc = self._page.locator(selector).first
                if await loc.is_visible(timeout=1000):
                    textarea = loc
                    logger.info("reply_input_found", selector=selector)
                    break
            except Exception:
                continue

        if not textarea:
            logger.error("reply_textarea_not_found")
            await self._page.screenshot(path="/tmp/comm100_reply_error.png")
            return False

        await textarea.click()
        await asyncio.sleep(0.3)

        # Type the text
        try:
            await textarea.fill(text)
        except Exception:
            await textarea.type(text, delay=10)

        await asyncio.sleep(0.5)

        # Try send button (blue icon at bottom right), fallback to Enter
        send_selectors = [
            "[class*='Send-module'] svg",
            "[class*='send-module'] svg",
            "[class*='sendBtn'] svg",
            "[class*='SendBtn'] svg",
            "button[class*='send']",
            "button[class*='Send']",
            "[title*='Send']",
            "[aria-label*='Send']",
            "[class*='send'] svg",
            "[class*='Send'] svg",
        ]
        send_clicked = False
        for selector in send_selectors:
            try:
                btn = self._page.locator(selector).first
                if await btn.is_visible(timeout=1000):
                    await btn.click(force=True)
                    send_clicked = True
                    logger.info("send_button_clicked", selector=selector)
                    break
            except Exception:
                continue

        if not send_clicked:
            await self._page.keyboard.press("Enter")
            logger.info("send_via_enter")

        logger.info("reply_sent", length=len(text))
        await asyncio.sleep(1)
        return True

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
