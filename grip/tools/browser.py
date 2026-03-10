"""Browser automation tool powered by Playwright.

Provides agents with the ability to navigate web pages, interact with
elements, take screenshots, and extract content from rendered pages.
Unlike web_fetch which only gets raw HTML, this tool runs a real
Chromium browser — handling JavaScript-rendered SPAs, login flows,
and dynamic content.

Requires: pip install playwright && playwright install chromium
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from typing import Any

from loguru import logger

from grip.tools.base import Tool, ToolContext

_BROWSER_LAUNCH_TIMEOUT = 30_000
_DEFAULT_NAV_TIMEOUT = 30_000
_DEFAULT_VIEWPORT = {"width": 1280, "height": 720}
_SCREENSHOT_MAX_BYTES = 2_000_000
_CONTENT_MAX_CHARS = 80_000


class _BrowserSession:
    """Manages a single Playwright browser instance with page reuse."""

    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None
        self._lock = asyncio.Lock()

    async def ensure_page(self) -> Any:
        """Return the active page, launching browser if needed."""
        async with self._lock:
            if self._page and not self._page.is_closed():
                return self._page

            try:
                from playwright.async_api import async_playwright
            except ImportError as err:
                raise RuntimeError(
                    "Playwright is not installed. "
                    "The browser tool is unavailable until the host installs it."
                ) from err

            if self._playwright is None:
                self._playwright = await async_playwright().__aenter__()

            if self._browser is None or not self._browser.is_connected():
                try:
                    self._browser = await self._playwright.chromium.launch(
                        headless=True,
                        timeout=_BROWSER_LAUNCH_TIMEOUT,
                        args=[
                            "--no-sandbox",
                            "--disable-dev-shm-usage",
                            "--disable-gpu",
                        ],
                    )
                except Exception as exc:
                    error_msg = str(exc).lower()
                    if (
                        "install" in error_msg
                        or "executable" in error_msg
                        or "doesn't exist" in error_msg
                    ):
                        logger.info("Chromium binary missing — auto-installing...")
                        await self._auto_install_chromium()
                        self._browser = await self._playwright.chromium.launch(
                            headless=True,
                            timeout=_BROWSER_LAUNCH_TIMEOUT,
                            args=[
                                "--no-sandbox",
                                "--disable-dev-shm-usage",
                                "--disable-gpu",
                            ],
                        )
                    else:
                        raise

            context = await self._browser.new_context(
                viewport=_DEFAULT_VIEWPORT,
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
            )
            self._page = await context.new_page()
            return self._page

    @staticmethod
    async def _auto_install_chromium() -> None:
        """Run 'playwright install chromium' as a subprocess."""
        import sys

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "playwright",
            "install",
            "chromium",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            detail = (stderr or stdout or b"").decode(errors="replace").strip()
            raise RuntimeError(
                f"Auto-install of Chromium failed (exit {proc.returncode}): {detail}"
            )
        logger.info("Chromium auto-installed successfully")

    async def close(self) -> None:
        """Shut down browser and playwright."""
        async with self._lock:
            if self._page and not self._page.is_closed():
                with contextlib.suppress(Exception):
                    await self._page.close()
                self._page = None

            if self._browser and self._browser.is_connected():
                with contextlib.suppress(Exception):
                    await self._browser.close()
                self._browser = None

            if self._playwright:
                with contextlib.suppress(Exception):
                    await self._playwright.__aexit__(None, None, None)
                self._playwright = None


_shared_session = _BrowserSession()

_INSTALL_PATTERNS = (
    "playwright install",
    "pip install",
    "npx playwright",
    "run the following command",
)


def _sanitize_browser_error(error: str) -> str:
    """Strip install/setup commands from Playwright errors so the agent doesn't execute them."""
    lower = error.lower()
    if any(pat in lower for pat in _INSTALL_PATTERNS):
        return "Browser setup issue — the browser tool is temporarily unavailable. Do not attempt to install anything."
    return error


class BrowserTool(Tool):
    """Navigate and interact with web pages using a headless Chromium browser."""

    @property
    def name(self) -> str:
        return "browser"

    @property
    def description(self) -> str:
        return (
            "Control a headless Chromium browser: navigate to URLs, click elements, "
            "fill forms, select dropdowns, press keys, scroll pages, take screenshots, "
            "and extract rendered page content."
        )

    @property
    def category(self) -> str:
        return "web"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "navigate",
                        "click",
                        "fill",
                        "select",
                        "press",
                        "scroll",
                        "screenshot",
                        "content",
                        "evaluate",
                        "wait",
                        "back",
                        "close",
                    ],
                    "description": "Browser action to perform.",
                },
                "url": {
                    "type": "string",
                    "description": "URL to navigate to (for 'navigate' action).",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector for click/fill/select/press/wait actions.",
                },
                "text": {
                    "type": "string",
                    "description": "Text to type (for 'fill' action).",
                },
                "value": {
                    "type": "string",
                    "description": "Option value to select (for 'select' action). Matches <option value='...'>.",
                },
                "label": {
                    "type": "string",
                    "description": "Option visible text to select (for 'select' action). Used if 'value' is not provided.",
                },
                "key": {
                    "type": "string",
                    "description": "Key to press (for 'press' action). Examples: 'Enter', 'Escape', 'Tab', 'ArrowDown'.",
                },
                "direction": {
                    "type": "string",
                    "enum": ["up", "down"],
                    "description": "Scroll direction (for 'scroll' action). Default: 'down'.",
                },
                "amount": {
                    "type": "integer",
                    "description": "Pixels to scroll (for 'scroll' action). Default: 500.",
                },
                "script": {
                    "type": "string",
                    "description": "JavaScript to execute (for 'evaluate' action).",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in milliseconds. Default: 30000.",
                },
                "save_path": {
                    "type": "string",
                    "description": "File path to save screenshot (for 'screenshot' action). Relative to workspace.",
                },
            },
            "required": ["action"],
        }

    async def execute(self, params: dict[str, Any], ctx: ToolContext) -> str:
        action = params.get("action", "")
        timeout = params.get("timeout", _DEFAULT_NAV_TIMEOUT)

        handlers = {
            "navigate": self._navigate,
            "click": self._click,
            "fill": self._fill,
            "select": self._select,
            "press": self._press,
            "scroll": self._scroll,
            "screenshot": self._screenshot,
            "content": self._content,
            "evaluate": self._evaluate,
            "wait": self._wait,
            "back": self._back,
            "close": self._close,
        }

        handler = handlers.get(action)
        if not handler:
            return f"Error: unknown action '{action}'. Use: {', '.join(handlers.keys())}"

        try:
            return await handler(params, ctx, timeout)
        except RuntimeError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            logger.error("Browser {} failed: {}", action, exc)
            sanitized = _sanitize_browser_error(str(exc))
            return f"Error: browser {action} failed: {sanitized}"

    async def _navigate(self, params: dict[str, Any], ctx: ToolContext, timeout: int) -> str:
        url = params.get("url", "")
        if not url:
            return "Error: 'url' is required for navigate action."

        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        page = await _shared_session.ensure_page()
        response = await page.goto(url, timeout=timeout, wait_until="domcontentloaded")

        status = response.status if response else "unknown"
        title = await page.title()
        return f"Navigated to {url}\nStatus: {status}\nTitle: {title}"

    async def _click(self, params: dict[str, Any], ctx: ToolContext, timeout: int) -> str:
        selector = params.get("selector", "")
        if not selector:
            return "Error: 'selector' is required for click action."

        page = await _shared_session.ensure_page()
        await page.click(selector, timeout=timeout)
        await page.wait_for_load_state("domcontentloaded", timeout=timeout)

        title = await page.title()
        return f"Clicked '{selector}'. Current page: {page.url} ({title})"

    async def _fill(self, params: dict[str, Any], ctx: ToolContext, timeout: int) -> str:
        selector = params.get("selector", "")
        text = params.get("text", "")
        if not selector:
            return "Error: 'selector' is required for fill action."

        page = await _shared_session.ensure_page()
        await page.fill(selector, text, timeout=timeout)
        return f"Filled '{selector}' with text ({len(text)} chars)."

    async def _select(self, params: dict[str, Any], ctx: ToolContext, timeout: int) -> str:
        selector = params.get("selector", "")
        if not selector:
            return "Error: 'selector' is required for select action."

        value = params.get("value", "")
        label = params.get("label", "")
        if not value and not label:
            return "Error: 'value' or 'label' is required for select action."

        page = await _shared_session.ensure_page()
        if value:
            chosen = await page.select_option(selector, value=value, timeout=timeout)
        else:
            chosen = await page.select_option(selector, label=label, timeout=timeout)
        return f"Selected option in '{selector}': {chosen}"

    async def _press(self, params: dict[str, Any], ctx: ToolContext, timeout: int) -> str:
        key = params.get("key", "")
        if not key:
            return "Error: 'key' is required for press action."

        selector = params.get("selector", "")
        page = await _shared_session.ensure_page()
        if selector:
            await page.press(selector, key, timeout=timeout)
        else:
            await page.keyboard.press(key)
        return f"Pressed '{key}'" + (f" on '{selector}'" if selector else "") + "."

    async def _scroll(self, params: dict[str, Any], ctx: ToolContext, timeout: int) -> str:
        direction = params.get("direction", "down")
        amount = params.get("amount", 500)
        delta = amount if direction == "down" else -amount

        page = await _shared_session.ensure_page()
        await page.mouse.wheel(0, delta)
        await page.wait_for_timeout(300)
        scroll_y = await page.evaluate("() => window.scrollY")
        return f"Scrolled {direction} {amount}px. Current scroll position: {scroll_y}px."

    async def _screenshot(self, params: dict[str, Any], ctx: ToolContext, timeout: int) -> str:
        page = await _shared_session.ensure_page()

        save_path = params.get("save_path", "")
        if save_path:
            full_path = ctx.workspace_path / save_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(full_path), full_page=False, timeout=timeout)
            size = full_path.stat().st_size
            return f"Screenshot saved to {full_path} ({size:,} bytes)"

        screenshot_bytes = await page.screenshot(full_page=False, timeout=timeout)

        if len(screenshot_bytes) > _SCREENSHOT_MAX_BYTES:
            screenshot_bytes = await page.screenshot(
                full_page=False, timeout=timeout, quality=50, type="jpeg"
            )

        b64 = base64.b64encode(screenshot_bytes).decode("ascii")
        return f"Screenshot captured ({len(screenshot_bytes):,} bytes). Base64:\n{b64[:200]}..."

    async def _content(self, params: dict[str, Any], ctx: ToolContext, timeout: int) -> str:
        page = await _shared_session.ensure_page()

        text = await page.evaluate("""() => {
            const sel = window.getSelection();
            if (sel && sel.toString().trim()) return sel.toString();

            const main = document.querySelector('main, article, [role="main"]');
            const target = main || document.body;
            return target.innerText || target.textContent || '';
        }""")

        text = text.strip() if text else ""
        if not text:
            return "Page has no visible text content."

        if len(text) > _CONTENT_MAX_CHARS:
            text = (
                text[:_CONTENT_MAX_CHARS]
                + f"\n\n[... truncated {len(text) - _CONTENT_MAX_CHARS} chars ...]"
            )

        title = await page.title()
        url = page.url
        return f"Page: {title}\nURL: {url}\n\n{text}"

    async def _evaluate(self, params: dict[str, Any], ctx: ToolContext, timeout: int) -> str:
        script = params.get("script", "")
        if not script:
            return "Error: 'script' is required for evaluate action."

        page = await _shared_session.ensure_page()
        result = await page.evaluate(script)

        if result is None:
            return "Script executed (no return value)."
        if isinstance(result, str):
            return result[:_CONTENT_MAX_CHARS]
        return json.dumps(result, indent=2, default=str)[:_CONTENT_MAX_CHARS]

    async def _wait(self, params: dict[str, Any], ctx: ToolContext, timeout: int) -> str:
        selector = params.get("selector", "")
        if not selector:
            return "Error: 'selector' is required for wait action."

        page = await _shared_session.ensure_page()
        await page.wait_for_selector(selector, timeout=timeout, state="visible")
        return f"Element '{selector}' is now visible."

    async def _back(self, params: dict[str, Any], ctx: ToolContext, timeout: int) -> str:
        page = await _shared_session.ensure_page()
        await page.go_back(timeout=timeout, wait_until="domcontentloaded")
        title = await page.title()
        return f"Navigated back. Current page: {page.url} ({title})"

    async def _close(self, params: dict[str, Any], ctx: ToolContext, timeout: int) -> str:
        await _shared_session.close()
        return "Browser session closed."


def create_browser_tools() -> list[Tool]:
    """Factory function returning browser tool instances."""
    return [BrowserTool()]
