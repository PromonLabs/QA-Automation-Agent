"""
Browser Use + Playwright browser agent.

Windows note: Playwright requires ProactorEventLoop for subprocess support.
On Windows we spin up a dedicated ProactorEventLoop thread and dispatch all
async callbacks back to the caller's loop via run_coroutine_threadsafe.
"""
import asyncio
import base64
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from typing import Callable, Optional, Awaitable

from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from app.core.config import settings
from app.models.schemas import ExecutionLog

LogCallbackFn   = Callable[[ExecutionLog], Awaitable[None]]
FrameCallbackFn = Callable[[str], Awaitable[None]]      # base64 JPEG


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BrowserAgent:
    def __init__(
        self,
        exec_id: str,
        headless: bool = None,
        log_callback: Optional[LogCallbackFn] = None,
        frame_callback: Optional[FrameCallbackFn] = None,
        screenshot_mode: Optional[str] = None,
    ):
        self.exec_id      = exec_id
        self.headless     = headless if headless is not None else settings.BROWSER_HEADLESS
        self.log_callback = log_callback
        self.frame_callback = frame_callback
        # Screenshot mode: fail_only | final | all  (from env or override)
        self._screenshot_mode = (screenshot_mode or settings.SCREENSHOT_MODE).lower()
        self.screenshot_dir = settings.SCREENSHOTS_DIR / exec_id
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

        self._page:    Optional[Page]           = None
        self._browser: Optional[Browser]        = None
        self._context: Optional[BrowserContext] = None
        self._pw       = None   # playwright instance — set in _execute for relaunch recovery
        self._step_count = 0
        self._running    = False
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None   # caller's loop
        self._captured_vars: dict = {}   # values extracted from pages during the run
        self._login_sequence_skipped = False
        self._authenticated_domains: set = set()  # domains where login succeeded this run

    # ── Thread-safe callback dispatch ────────────────────────────────────────
    def _dispatch(self, coro) -> None:
        """Schedule a coroutine in the MAIN loop from any thread (fire-and-forget)."""
        if self._main_loop and self._main_loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, self._main_loop)

    # ── Logging ──────────────────────────────────────────────────────────────
    async def _log(self, level: str, message: str,
                   screenshot: Optional[str] = None) -> ExecutionLog:
        log = ExecutionLog(
            timestamp=_now(), level=level, message=message,
            step=self._step_count, screenshot=screenshot,
        )
        if self.log_callback:
            cur = asyncio.get_event_loop()
            if self._main_loop and cur is not self._main_loop:
                self._dispatch(self.log_callback(log))      # cross-thread
            else:
                await self.log_callback(log)                # same loop
        return log

    # ── Screenshots ──────────────────────────────────────────────────────────
    async def _screenshot(self, label: str = "") -> str:
        if not self._page:
            return ""
        filename = f"step_{self._step_count:03d}_{label}_{int(time.time())}.png"
        try:
            await self._page.screenshot(
                path=str(self.screenshot_dir / filename),
                full_page=True,
                animations="disabled",
            )
        except Exception:
            try:
                # Fallback: viewport-only screenshot
                await self._page.screenshot(
                    path=str(self.screenshot_dir / filename), full_page=False
                )
            except Exception:
                return ""
        return filename

    # ── Live frame stream ────────────────────────────────────────────────────
    async def _live_stream_loop(self, interval: float = 0.8):
        while self._running:
            try:
                if self._page and not self._page.is_closed() and self.frame_callback:
                    data = await self._page.screenshot(
                        type="jpeg", quality=60, full_page=False
                    )
                    b64 = base64.b64encode(data).decode()
                    cur = asyncio.get_event_loop()
                    if self._main_loop and cur is not self._main_loop:
                        self._dispatch(self.frame_callback(b64))
                    else:
                        await self.frame_callback(b64)
            except Exception:
                pass
            await asyncio.sleep(interval)

    # ── Smart element finder (searches main page + all frames) ─────────────
    @staticmethod
    def _clean_target(t: str) -> str:
        """
        Strip decorative dashes/stars and extra whitespace from targets like
        '- Login with password  -' → 'Login with password'
        """
        import re as _re
        cleaned = _re.sub(r'^[\s\-\*\|]+|[\s\-\*\|]+$', '', t).strip()
        # Collapse internal double-spaces
        cleaned = _re.sub(r'  +', ' ', cleaned)
        return cleaned if cleaned and cleaned != t else ""

    async def _find(self, target: str, page=None):
        p = page or self._page
        import re as _re

        # Build the list of targets to try: original first, then cleaned
        targets_to_try = [target]
        cleaned = self._clean_target(target)
        if cleaned:
            targets_to_try.append(cleaned)

        for t in targets_to_try:
            for fn in [
                lambda t=t: p.get_by_role("button",   name=_re.compile(_re.escape(t), _re.I)).first,
                lambda t=t: p.get_by_role("link",     name=_re.compile(_re.escape(t), _re.I)).first,
                lambda t=t: p.get_by_role("checkbox", name=_re.compile(_re.escape(t), _re.I)).first,
                lambda t=t: p.get_by_role("radio",    name=_re.compile(_re.escape(t), _re.I)).first,
                lambda t=t: p.get_by_role("menuitem", name=_re.compile(_re.escape(t), _re.I)).first,
                lambda t=t: p.get_by_role("tab",      name=_re.compile(_re.escape(t), _re.I)).first,
                lambda t=t: p.get_by_role("option",   name=_re.compile(_re.escape(t), _re.I)).first,
                lambda t=t: p.get_by_text(t, exact=False).first,
                lambda t=t: p.get_by_role("textbox", name=_re.compile(_re.escape(t), _re.I)).first,
                lambda t=t: p.get_by_label(_re.compile(_re.escape(t), _re.I)).first,
                lambda t=t: p.get_by_placeholder(_re.compile(_re.escape(t), _re.I)).first,
                lambda t=t: p.get_by_title(_re.compile(_re.escape(t), _re.I)).first,
            ]:
                try:
                    el = fn()
                    if await el.count() > 0 and await el.is_visible():
                        return el
                except Exception:
                    continue

        if target.startswith(("#", ".", "[", "//")):
            try:
                return p.locator(target).first
            except Exception:
                pass
        # Search inside child frames
        for frame in p.frames[1:]:
            for t in targets_to_try:
                try:
                    for fn in [
                        lambda t=t, f=frame: f.get_by_role("button", name=_re.compile(_re.escape(t), _re.I)).first,
                        lambda t=t, f=frame: f.get_by_role("link",   name=_re.compile(_re.escape(t), _re.I)).first,
                        lambda t=t, f=frame: f.get_by_text(t, exact=False).first,
                    ]:
                        el = fn()
                        if await el.count() > 0 and await el.is_visible():
                            return el
                except Exception:
                    continue
        return None

    # ── Input-specific finder (searches all frames) ──────────────────────────
    async def _find_input(self, target: str, page=None):
        """Find an interactive input element across all frames."""
        p = page or self._page
        import re as _re
        for frame in p.frames:
            candidates = [
                lambda f=frame: f.get_by_label(_re.compile(_re.escape(target), _re.I)).first,
                lambda f=frame: f.get_by_placeholder(_re.compile(_re.escape(target), _re.I)).first,
                lambda f=frame: f.get_by_role("textbox",   name=_re.compile(_re.escape(target), _re.I)).first,
                lambda f=frame: f.get_by_role("searchbox", name=_re.compile(_re.escape(target), _re.I)).first,
            ]
            for fn in candidates:
                try:
                    el = fn()
                    if await el.count() > 0:
                        tag = await el.evaluate("e => e.tagName.toLowerCase()")
                        ce  = await el.get_attribute("contenteditable")
                        if tag in ("input", "textarea") or ce is not None:
                            if await el.is_visible():
                                return el
                except Exception:
                    continue
            # CSS fallbacks — match by name/id/placeholder/aria-label (full phrase)
            tl = target.lower()
            for attr in ["name", "id", "placeholder", "aria-label"]:
                try:
                    loc = frame.locator(
                        f"input[{attr}*='{tl}' i], textarea[{attr}*='{tl}' i]"
                    ).first
                    if await loc.count() > 0 and await loc.is_visible():
                        return loc
                except Exception:
                    pass
            # Keyword fallback — try each word in target (≥4 chars) against placeholder/aria-label
            words = [w for w in tl.split() if len(w) >= 4]
            for word in words:
                for attr in ["placeholder", "aria-label", "name"]:
                    try:
                        loc = frame.locator(
                            f"input[{attr}*='{word}' i], textarea[{attr}*='{word}' i]"
                        ).first
                        if await loc.count() > 0 and await loc.is_visible():
                            return loc
                    except Exception:
                        pass

            # Password field special case — no visibility check (same Vue/SPA reason as email)
            if any(w in tl for w in ["password", "pass", "pwd"]):
                try:
                    loc = frame.locator("input[type='password']").first
                    if await loc.count() > 0:
                        return loc
                except Exception:
                    pass

            # Email field special case — no visibility check.
            # Vue/SPA login pages render the input in the DOM before it becomes
            # CSS-visible; _direct_login succeeds without is_visible() for the same reason.
            if any(w in tl for w in ["email", "mail"]):
                for sel in [
                    "input[type='email']",
                    "input[name='email']",
                    "input[name*='email' i]",
                    "input[type='text']",   # last resort — matches plain text inputs
                ]:
                    try:
                        loc = frame.locator(sel).first
                        if await loc.count() > 0:
                            return loc
                    except Exception:
                        pass

        return None

    # ── Select dropdown option across all frames ─────────────────────────────
    async def _select_option(self, value: str, page=None) -> bool:
        """Find any <select> in all frames and set its value."""
        p = page or self._page
        for frame in p.frames:
            try:
                selects = await frame.locator("select").all()
                for sel in selects:
                    if not await sel.is_visible():
                        continue
                    try:
                        await sel.select_option(value=value)
                        return True
                    except Exception:
                        try:
                            await sel.select_option(label=value)
                            return True
                        except Exception:
                            pass
            except Exception:
                pass
        return False

    # ── New-tab detection: poll up to 5 s ───────────────────────────────────
    async def _maybe_switch_new_tab(self, pages_before: int) -> bool:
        """Poll for up to 5 s; if a new tab opened, switch self._page to it."""
        for _ in range(10):           # 10 × 0.5 s = 5 s max
            await asyncio.sleep(0.5)
            pages = self._context.pages
            if len(pages) > pages_before:
                new_page = pages[-1]
                try:
                    await new_page.wait_for_load_state("domcontentloaded", timeout=15000)
                    await new_page.wait_for_timeout(600)
                except Exception:
                    pass
                self._page = new_page
                await self._log("info", f"  → Switched to new tab: {new_page.url}")
                return True
        return False

    # ── Already-authenticated check ──────────────────────────────────────────
    @staticmethod
    def _is_login_button(target: str) -> bool:
        lo = target.lower()
        return any(k in lo for k in ("login with password", "log in with password",
                                     "sign in with password", "login with", "log in",
                                     "sign in", "login"))

    @staticmethod
    def _is_login_submit(target: str) -> bool:
        """Final submit button of a login form — not the initiator."""
        lo = target.strip(" -").lower()
        return lo in ("log in", "login", "sign in", "signin")

    @staticmethod
    def _is_credential_field(target: str) -> bool:
        lo = target.lower()
        return any(k in lo for k in ("username", "password", "email field", "email address"))

    async def _already_authenticated(self) -> bool:
        """Return True if the current page looks like an authenticated app (not a login page)."""
        try:
            url = self._page.url.lower()
            body = (await self._page.inner_text("body")).lower()
            login_kw = ("login", "sign in", "signin", "which type of account",
                        "enter your password", "forgot password")
            on_login_page = (
                any(k in url for k in ("/login", "/signin", "/auth"))
                or any(k in body for k in login_kw)
            )
            return not on_login_page
        except Exception:
            return False

    # ── Microsoft login recovery ─────────────────────────────────────────────
    async def _recover_ms_login(self, return_url: str) -> bool:
        """
        Re-authenticate through the Microsoft / Tusass Azure login page and
        navigate back to return_url.  Screenshots are saved at each key step
        so failures are visible in the execution logs.
        Uses ADMIN_USER / ADMIN_PASS from the environment.
        """
        import os
        # Prefer dedicated operations credentials; fall back to ADMIN_USER/PASS
        user = os.environ.get("OPERATIONS_USER") or os.environ.get("ADMIN_USER", "")
        pwd  = os.environ.get("OPERATIONS_PASS") or os.environ.get("ADMIN_PASS", "")
        if not user or not pwd:
            await self._log("info", "  ⚠ OPERATIONS_USER / OPERATIONS_PASS not set — cannot re-login")
            return False

        await self._log("info", f"  🔑 Re-login: starting MS auth for {user}")

        async def _body():
            try:
                return (await self._page.inner_text("body")).lower()
            except Exception:
                return ""

        async def _fill_input(selectors: list, value: str) -> bool:
            for frame in self._page.frames:
                for sel in selectors:
                    try:
                        inp = frame.locator(sel).first
                        if await inp.count() > 0 and await inp.is_visible():
                            await inp.clear()
                            await inp.fill(value)
                            return True
                    except Exception:
                        pass
            return False

        async def _click_btn(labels: list) -> bool:
            """Click the first visible button/input matching any label or selector."""
            for frame in self._page.frames:
                for sel in labels:
                    try:
                        btn = frame.locator(sel).first
                        if await btn.count() > 0 and await btn.is_visible():
                            await btn.click()
                            return True
                    except Exception:
                        pass
            return False

        async def _direct_login() -> bool:
            """Handle the Tusass direct login form (email + password on same page)."""
            try:
                # Use press_sequentially so Vuesax v-model updates correctly
                em = self._page.locator("input[name='email'], input[type='text']").first
                pw = self._page.locator("input[type='password']").first
                if await em.count() > 0 and await pw.count() > 0:
                    await em.clear()
                    await em.press_sequentially(user, delay=30)
                    await em.evaluate("e => e.dispatchEvent(new Event('input',{bubbles:true}))")
                    await em.evaluate("e => e.dispatchEvent(new Event('blur',{bubbles:true}))")
                    await asyncio.sleep(0.5)
                    await pw.clear()
                    await pw.press_sequentially(pwd, delay=30)
                    await pw.evaluate("e => e.dispatchEvent(new Event('input',{bubbles:true}))")
                    await pw.evaluate("e => e.dispatchEvent(new Event('blur',{bubbles:true}))")
                    await asyncio.sleep(0.5)
                    await self._page.keyboard.press("Enter")
                    await asyncio.sleep(5)
                    shot = await self._screenshot("relogin-direct")
                    await self._log("info", "  🔑 Re-login: direct form submitted", screenshot=shot)
                    return True
            except Exception:
                pass
            return False

        try:
            for step in range(60):   # up to 30 s total (0.5 s per tick)
                body = await _body()
                current_url = self._page.url

                # ── Already past all auth pages ──────────────────────────────
                auth_markers = (
                    "sign in", "signin", "enter password", "which type of account",
                    "stay signed in", "keep me signed in",
                )
                is_login_url = "/login" in current_url.lower()
                if not any(m in body for m in auth_markers) and not is_login_url:
                    shot = await self._screenshot(f"relogin-done-{step}")
                    await self._log("info", f"  ✅ Re-login: app page reached", screenshot=shot)
                    break

                # ── Direct login form (Tusass operations /login page) ─────────
                # Both email and password visible simultaneously on same page
                if is_login_url or ("email" in body and "password" in body
                                    and "tusass" in body):
                    shot = await self._screenshot(f"relogin-direct-{step}")
                    await self._log("info", "  🔑 Re-login: direct login form detected", screenshot=shot)
                    if await _direct_login():
                        break
                    await asyncio.sleep(1)
                    continue

                # ── "Stay signed in?" / "Keep me signed in?" ─────────────────
                if "stay signed in" in body or "keep me signed in" in body:
                    shot = await self._screenshot(f"relogin-stay-{step}")
                    await self._log("info", "  🔑 Re-login: 'Stay signed in?' — clicking Yes", screenshot=shot)
                    await _click_btn([
                        "input[value='Yes']", "button:has-text('Yes')",
                        "input[id='idSIButton9']",
                    ])
                    await asyncio.sleep(3)
                    continue

                # ── "Which type of account?" ──────────────────────────────────
                if "which type of account" in body:
                    shot = await self._screenshot(f"relogin-acct-{step}")
                    await self._log("info", "  🔑 Re-login: picking Work/school account", screenshot=shot)
                    for frame in self._page.frames:
                        try:
                            btn = frame.get_by_text("Work or school account").first
                            if await btn.count() > 0:
                                await btn.click()
                                await asyncio.sleep(2)
                                break
                        except Exception:
                            pass
                    continue

                # ── Microsoft: password field ─────────────────────────────────
                pw_filled = await _fill_input(
                    ["input[type='password']", "input[name='passwd']",
                     "input[id='i0118']"], pwd
                )
                if pw_filled:
                    shot = await self._screenshot(f"relogin-ms-pwd-{step}")
                    await self._log("info", "   Re-login: MS password → Sign in", screenshot=shot)
                    await _click_btn([
                        "input[type='submit']", "button[type='submit']",
                        "input[value='Sign in']", "input[id='idSIButton9']",
                    ])
                    await asyncio.sleep(4)
                    continue

                # ── Microsoft: email field ────────────────────────────────────
                em_filled = await _fill_input(
                    ["input[type='email']", "input[name='loginfmt']",
                     "input[id='i0116']"], user
                )
                if em_filled:
                    shot = await self._screenshot(f"relogin-ms-email-{step}")
                    await self._log("info", f"   Re-login: MS email → Next", screenshot=shot)
                    await _click_btn([
                        "input[type='submit']", "button[type='submit']",
                        "input[value='Next']", "input[id='idSIButton9']",
                    ])
                    await asyncio.sleep(4)
                    continue

                await asyncio.sleep(0.5)

            # Wait for the app to fully settle after login
            try:
                await self._page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            await asyncio.sleep(2)

            # Navigate back to the operation detail page
            current = self._page.url
            if current != return_url:
                await self._page.goto(return_url, wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(3)

            shot = await self._screenshot("ms-relogin-final")
            await self._log("info", "   Re-login: returned to operation page", screenshot=shot)
            return True
        except Exception as exc:
            await self._log("info", f"  ⚠ Re-login exception: {exc}")
            return False

    # ── Step executor ────────────────────────────────────────────────────────
    async def execute_step(self, step: dict) -> bool:
        action       = step.get("action", "click").lower()
        target       = str(step.get("target", ""))
        value        = str(step.get("value", step.get("text", "")))
        description  = step.get("description", f"{action}: {target}")
        alternatives = step.get("alternatives", [])   # fallback labels
        optional     = step.get("optional", False)    # skip silently if not found
        self._step_count += 1

        await self._log("info", f"▶ Step {self._step_count}: {description}")

        # ── Page-alive guard ──────────────────────────────────────────────
        # Payment gateways and SPA navigations can close/detach the current
        # page. Before running the step, try to recover a live page from the
        # same context; if not found there, search ALL browser contexts (popup
        # windows open in a separate context). Skip gracefully for optional
        # steps when no live page is available anywhere.
        try:
            if self._page and self._page.is_closed():
                open_pages: list = []

                # 1. Search the same context
                try:
                    open_pages = [p for p in self._context.pages if not p.is_closed()]
                except Exception:
                    pass

                # 2. Fallback: search every context in the browser (popup windows)
                if not open_pages and self._browser:
                    try:
                        for ctx in self._browser.contexts:
                            candidate = [p for p in ctx.pages if not p.is_closed()]
                            if candidate:
                                open_pages = candidate
                                self._context = ctx   
                                break
                    except Exception:
                        pass

                if open_pages:
                    self._page = open_pages[-1]
                    await self._log("info", f"  ⚠ Page was closed; recovered to: {self._page.url}")
                elif optional:
                    await self._log("info", f"  → Optional step skipped (no live page available)")
                    return True
        except Exception:
            pass

        # ── Inner helper: screenshot only when needed ──────────────────────
        async def step_shot(status: str) -> None:
            """
            Screenshot policy (SCREENSHOT_MODE env var):
              none        — zero screenshots, ever (fastest)
              named_only  — only explicit SS / named screenshot steps; no auto shots
              fail_only   — only capture on failure
              final       — skip here (one final is taken at end of run)
              all         — capture every step (debug only)
            """
            mode = self._screenshot_mode
            if mode in ("none", "named_only"):
                return   # only explicit screenshots allowed
            if mode == "final":
                return   # handled at end of _execute
            if mode == "fail_only" and status != "FAIL":
                return   # success shots skipped
            lbl = f"{'ok' if status == 'ok' else 'FAIL'}_s{self._step_count:02d}"
            try:
                shot = await self._screenshot(lbl)
                if shot:
                    icon = "fail" if status == "FAIL" else "ok"
                    await self._log("info", f"  [{icon}] screenshot", screenshot=shot)
            except Exception:
                pass

        try:
            if action == "navigate":
                url = target if target.startswith("http") else f"https://{target}"

                # If current page is already at this URL (same-document hash change),
                # use JS pushState instead of a full Playwright goto() which resets SPA state
                try:
                    current_url = self._page.url
                    cu = urlparse(current_url)
                    tu = urlparse(url)
                    same_origin_path = (cu.scheme == tu.scheme and cu.netloc == tu.netloc
                                        and cu.path == tu.path)
                except Exception:
                    same_origin_path = False

                if same_origin_path:
                    # Same base page (possibly different hash/query).
                    # Check if page already has interactive inputs — if so, the SPA
                    # already rendered the target view; skip navigation to avoid reset.
                    already_ready = False
                    try:
                        inp_count = await self._page.locator(
                            "input[type='text']:visible, input[type='tel']:visible, "
                            "input[type='email']:visible, input:not([type]):visible, "
                            "textarea:visible"
                        ).count()
                        if inp_count > 0:
                            already_ready = True
                    except Exception:
                        pass

                    if already_ready:
                        # Page already shows the right content; preserve SPA state
                        pass   # fall through to step_shot
                    elif tu.fragment:
                        # No inputs yet — try a gentle hash update
                        try:
                            hash_val = "#" + tu.fragment
                            await self._page.evaluate(
                                f"window.location.hash = {json.dumps(hash_val)}"
                            )
                            await asyncio.sleep(1.5)
                        except Exception:
                            pass
                else:
                    nav_timeout = settings.BROWSER_NAVIGATION_TIMEOUT
                    try:
                        await self._page.goto(url, wait_until="domcontentloaded", timeout=nav_timeout)
                    except Exception as nav_err:
                        nav_err_s = str(nav_err)
                        # Payment gateways often close/kill the tab or context after success.
                        # Four-level recovery:
                        closed  = any(k in nav_err_s for k in ("been closed", "Target closed", "context or browser"))
                        aborted = any(k in nav_err_s for k in ("ERR_ABORTED", "frame was detached", "ERR_BLOCKED"))
                        if closed or aborted:
                            recovered = False

                            # Level 1 — reuse an existing open tab
                            if not recovered:
                                try:
                                    open_pages = [p for p in self._context.pages if not p.is_closed()]
                                    if open_pages:
                                        self._page = open_pages[-1]
                                        await self._page.evaluate(f"window.location.href = {json.dumps(url)}")
                                        await asyncio.sleep(3)
                                        try:
                                            await self._page.wait_for_load_state("domcontentloaded", timeout=15000)
                                        except Exception:
                                            pass
                                        await self._log("info", "  ⚠ Switched to existing tab for navigation")
                                        recovered = True
                                except Exception:
                                    pass

                            # Level 2 — open a new page in the existing context
                            if not recovered:
                                try:
                                    self._page = await self._context.new_page()
                                    await self._page.goto(url, wait_until="domcontentloaded", timeout=nav_timeout)
                                    await self._log("info", "  ⚠ Opened new tab for navigation")
                                    recovered = True
                                except Exception:
                                    pass

                            # Level 3 — nuclear: relaunch entire browser (context killed by gateway)
                            if not recovered and self._pw:
                                await self._log("info", "  ⚠ Context dead — relaunching browser for admin navigation")
                                try:
                                    await self._browser.close()
                                except Exception:
                                    pass
                                self._browser = await self._pw.chromium.launch(
                                    headless=self.headless,
                                    slow_mo=settings.BROWSER_SLOW_MO,
                                    args=[
                                        "--no-sandbox",
                                        "--disable-dev-shm-usage",
                                        "--disable-blink-features=AutomationControlled",
                                        "--disable-web-security",
                                        "--allow-running-insecure-content",
                                        "--start-maximized",
                                    ],
                                )
                                self._context = await self._browser.new_context(
                                    viewport={"width": 1280, "height": 800},
                                    user_agent=(
                                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                                    ),
                                    ignore_https_errors=True,
                                )
                                self._page = await self._context.new_page()
                                await self._page.goto(url, wait_until="domcontentloaded", timeout=nav_timeout)
                                recovered = True

                            if not recovered:
                                raise
                        else:
                            raise
                    try:
                        await self._page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                    # Poll up to 60 s for ANY interactive element to appear.
                    # This handles SSO redirect chains (e.g. Microsoft login) where
                    # the page shows a loading spinner for many seconds before the
                    # actual login form renders.
                    for _ in range(120):   # 120 × 0.5 s = 60 s max
                        try:
                            n = await self._page.locator(
                                "button:visible, input:visible, "
                                "[role='button']:visible, a[href]:visible"
                            ).count()
                            if n > 0:
                                break
                        except Exception:
                            pass
                        await asyncio.sleep(0.5)

                # For SPA hash/query routes: give the JS framework time to render the view
                if "#" in url or "?" in url:
                    await asyncio.sleep(1.5)
                    try:
                        await self._page.wait_for_load_state("networkidle", timeout=4000)
                    except Exception:
                        pass
                    # Poll up to 8 s for a text/tel input to appear
                    for _ in range(16):
                        try:
                            inp = self._page.locator(
                                "input[type='text']:visible, input[type='tel']:visible, "
                                "input:not([type]):visible, textarea:visible"
                            ).first
                            if await inp.count() > 0:
                                break
                        except Exception:
                            pass
                        await asyncio.sleep(0.5)

                await self._log("info", f"  → {url}")
                await step_shot("ok")

            elif action in ("click", "button_click"):
                # Skip login buttons only on domains where login already succeeded this run
                if self._is_login_button(target):
                    try:
                        from urllib.parse import urlparse
                        domain = urlparse(self._page.url).netloc
                    except Exception:
                        domain = ""
                    if domain and domain in self._authenticated_domains:
                        await self._log("info", f"  → Already logged in — skipping '{target}'")
                        try:
                            await self._page.wait_for_load_state("networkidle", timeout=8000)
                        except Exception:
                            pass
                        await asyncio.sleep(2)
                        await step_shot("ok")
                        self._login_sequence_skipped = True
                        return True
                    self._login_sequence_skipped = False

                # Track page count BEFORE click to detect new tab
                pages_before = len(self._context.pages)

                # Try primary target, then each alternative label
                el = await self._find(target)
                clicked_name = target
                if not el:
                    for alt in alternatives:
                        el = await self._find(alt)
                        if el:
                            clicked_name = alt
                            break

                if el:
                    await el.scroll_into_view_if_needed()

                    # Listen for new page event BEFORE clicking
                    new_page_holder: list = []
                    def _on_page(pg):
                        new_page_holder.append(pg)
                    self._context.on("page", _on_page)

                    try:
                        await el.click(timeout=10000)
                    except Exception as click_err:
                        err_s = str(click_err)
                        if "intercepts pointer events" in err_s:
                            await self._page.keyboard.press("Escape")
                            await asyncio.sleep(0.5)
                            try:
                                await el.click(timeout=5000)
                            except Exception:
                                await el.evaluate("el => el.click()")
                        else:
                            self._context.remove_listener("page", _on_page)
                            raise

                    # Wait up to 2.5 s for new tab (poll every 250 ms)
                    switched = False
                    for _ in range(10):
                        await asyncio.sleep(0.25)
                        if new_page_holder:
                            new_page = new_page_holder[-1]
                            try:
                                await new_page.wait_for_load_state("domcontentloaded", timeout=15000)
                                await new_page.wait_for_timeout(600)
                            except Exception:
                                pass
                            self._page = new_page
                            await self._log("info", f"  → Switched to new tab: {new_page.url}")
                            switched = True
                            break

                    self._context.remove_listener("page", _on_page)

                    if not switched:
                        try:
                            await self._page.wait_for_load_state("networkidle", timeout=4000)
                        except Exception:
                            pass

                    await self._log("success", f"  → Clicked '{clicked_name}'")
                    # Record domain as authenticated after a login submit succeeds
                    if self._is_login_submit(clicked_name):
                        try:
                            from urllib.parse import urlparse
                            self._authenticated_domains.add(urlparse(self._page.url).netloc)
                        except Exception:
                            pass
                    await step_shot("ok")

                else:
                    # Element not found by text — try <select> option (e.g. amount dropdown)
                    if await self._select_option(target):
                        await self._log("success", f"  → Selected option '{target}' from dropdown")
                        await step_shot("ok")
                    elif re.search(r'\bid\b', target, re.IGNORECASE):
                        # Target looks like an ID column — click first table row link
                        clicked_row = False
                        # Pass 1: Playwright CSS/role selectors
                        for frame in self._page.frames:
                            if clicked_row:
                                break
                            for sel in [
                                "table tbody tr:first-child td a",
                                "table tbody tr:first-child a",
                                "table tr:nth-child(2) td a",
                                "table tr:nth-child(2) td:first-child",
                                "tbody tr:first-child td:first-child",
                                "[role='row']:nth-child(2) [role='cell']:first-child",
                                "[role='gridcell']:first-child a",
                                "tr:not(:first-child) td:first-child a",
                            ]:
                                try:
                                    loc = frame.locator(sel).first
                                    if await loc.count() > 0 and await loc.is_visible():
                                        await loc.click(timeout=8000)
                                        clicked_row = True
                                        await self._log("success", f"  → Clicked first row ('{target}')")
                                        break
                                except Exception:
                                    pass
                        # Pass 2: JavaScript fallback — works on any DOM structure
                        if not clicked_row:
                            try:
                                clicked_row = await self._page.evaluate("""
                                    () => {
                                        // Try links inside table data cells
                                        const tdLinks = document.querySelectorAll('td a, td button');
                                        if (tdLinks.length > 0) { tdLinks[0].click(); return true; }
                                        // Try first data row (skip header rows with th)
                                        const rows = document.querySelectorAll('tr');
                                        for (const row of rows) {
                                            if (row.querySelector('th')) continue;
                                            const cells = row.querySelectorAll('td');
                                            if (cells.length > 0) { cells[0].click(); return true; }
                                        }
                                        // Try role=row
                                        const roleRows = document.querySelectorAll('[role="row"]');
                                        for (const row of roleRows) {
                                            const cells = row.querySelectorAll('[role="cell"], [role="gridcell"]');
                                            if (cells.length > 0) { cells[0].click(); return true; }
                                        }
                                        return false;
                                    }
                                """)
                                if clicked_row:
                                    await self._log("success", f"  → Clicked first row via JS ('{target}')")
                            except Exception:
                                pass
                        if clicked_row:
                            try:
                                await self._page.wait_for_load_state("networkidle", timeout=5000)
                            except Exception:
                                pass
                            await step_shot("ok")
                        elif optional:
                            await self._log("info", f"  → Optional step skipped ('{target}' not present)")
                            await step_shot("ok")
                            return True
                        elif self._is_login_button(target) and await self._already_authenticated():
                            await self._log("info", f"  → Already logged in — skipping '{target}'")
                            await step_shot("ok")
                        else:
                            await self._log("error", f"  ✗ STEP FAILED — '{target}' not found on page")
                            await step_shot("FAIL")
                            return False
                    else:
                        # JS full-DOM fallback: scroll page and click any element
                        # whose text content matches the target string.
                        # Prefers exact text match over partial to avoid e.g.
                        # "Login with Microsoft" winning over plain "Login".
                        js_target = target.lower()
                        try:
                            clicked_js = await self._page.evaluate(f"""
                                (tgt) => {{
                                    const all = [...document.querySelectorAll('a, button, [role="button"], span, li, div')];
                                    // Prefer exact match first, then partial
                                    const el = all.find(e => e.textContent.trim().toLowerCase() === tgt)
                                            || all.find(e => e.textContent.trim().toLowerCase().includes(tgt));
                                    if (el) {{ el.scrollIntoView(); el.click(); return true; }}
                                    return false;
                                }}
                            """, js_target)
                            if clicked_js:
                                await asyncio.sleep(1)
                                await self._log("success", f"  → Clicked '{target}' via JS full-DOM search")
                                await self._maybe_switch_new_tab(pages_before)
                                try:
                                    await self._page.wait_for_load_state("networkidle", timeout=4000)
                                except Exception:
                                    pass
                                await step_shot("ok")
                            elif optional:
                                await self._log("info", f"  → Optional step skipped ('{target}' not present)")
                                await step_shot("ok")
                                return True
                            elif self._is_login_button(target) and await self._already_authenticated():
                                await self._log("info", f"  → Already logged in — skipping '{target}'")
                                await step_shot("ok")
                            else:
                                await self._log("error", f"  ✗ STEP FAILED — '{target}' not found on page")
                                await step_shot("FAIL")
                                return False
                        except Exception:
                            if optional:
                                await self._log("info", f"  → Optional step skipped ('{target}' not present)")
                                await step_shot("ok")
                                return True
                            if self._is_login_button(target) and await self._already_authenticated():
                                await self._log("info", f"  → Already logged in — skipping '{target}'")
                                await step_shot("ok")
                            else:
                                await self._log("error", f"  ✗ STEP FAILED — '{target}' not found on page")
                                await step_shot("FAIL")
                                return False

            elif action == "type":
                # Skip credential fields that follow a skipped login button
                if self._login_sequence_skipped and self._is_credential_field(target):
                    await self._log("info", f"  → Already logged in — skipping type '{target}'")
                    await step_shot("ok")
                    return True
                else:
                    self._login_sequence_skipped = False

                fill_val = value if value else target

                async def _do_type() -> bool:
                    """Try to type fill_val into the target field. Returns True on success."""
                    el = await self._find_input(target)
                    if el:
                        try:
                            await el.click()
                        except Exception:
                            pass
                        # Vuesax wraps inputs in styled containers — the raw <input> is in
                        # the DOM but Playwright sees it as "not visible". Try in order:
                        # 1. press_sequentially (fires all key events Vue v-model needs)
                        # 2. JS evaluate (bypasses visibility — works for vs-inputx)
                        # 3. fill() last resort (may timeout on Vuesax, kept as safety net)
                        typed = False
                        try:
                            await el.clear()
                            await el.press_sequentially(str(fill_val), delay=30)
                            typed = True
                        except Exception:
                            pass
                        if not typed:
                            try:
                                await el.evaluate(
                                    "(el, v) => { el.value = v; "
                                    "el.dispatchEvent(new Event('input',{bubbles:true})); "
                                    "el.dispatchEvent(new Event('change',{bubbles:true})); }",
                                    fill_val,
                                )
                                typed = True
                            except Exception:
                                pass
                        if not typed:
                            await el.fill(fill_val)
                        # Dispatch blur so vee-validate / form validators run
                        try:
                            await el.evaluate(
                                "e => { e.dispatchEvent(new Event('input',{bubbles:true})); "
                                "e.dispatchEvent(new Event('change',{bubbles:true})); "
                                "e.dispatchEvent(new Event('blur',{bubbles:true})); }"
                            )
                        except Exception:
                            pass
                        await self._log("success", f"  → Typed '{fill_val}' into '{target}'")
                        return True
                    # Fallback: fill first visible EMPTY input of any fillable type
                    for frame in self._page.frames:
                        try:
                            inputs = await frame.locator(
                                "input[type='text'],input[type='tel'],input[type='email'],"
                                "input[type='number'],input[type='password'],input:not([type])"
                            ).all()
                            for inp in inputs:
                                try:
                                    if await inp.is_visible():
                                        cur_val = await inp.input_value()
                                        if not cur_val:   # only fill empty inputs
                                            await inp.fill(fill_val)
                                            try:
                                                await inp.evaluate(
                                                    "e => { e.dispatchEvent(new Event('input',{bubbles:true})); "
                                                    "e.dispatchEvent(new Event('blur',{bubbles:true})); }"
                                                )
                                            except Exception:
                                                pass
                                            await self._log("success", f"  → Typed '{fill_val}' (first empty input)")
                                            return True
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    return False

                # First attempt
                filled = await _do_type()
                if not filled:
                    # SPA may still be rendering — wait up to 10 s and retry
                    await self._log("info", f"  ⏳ Waiting for '{target}' input to appear…")
                    for _ in range(20):
                        await asyncio.sleep(0.5)
                        filled = await _do_type()
                        if filled:
                            break

                if filled:
                    await step_shot("ok")
                elif optional:
                    await self._log("info", f"  → Optional type skipped ('{target}' not present)")
                    await step_shot("ok")
                    return True
                elif await self._already_authenticated():
                    # No input found but page is authenticated — credentials already submitted
                    await self._log("info", f"  → Already logged in — skipping type '{target}'")
                    await step_shot("ok")
                else:
                    await self._log("error", f"  ✗ STEP FAILED — no input found for '{target}'")
                    await step_shot("FAIL")
                    return False

            elif action == "select":
                # Try named select first, then any visible dropdown
                sel_val = value if value else target
                el = await self._find(target)
                if el:
                    try:
                        await el.select_option(value=sel_val)
                    except Exception:
                        try:
                            await el.select_option(label=sel_val)
                        except Exception:
                            await el.click()
                    await self._log("success", f"  → Selected '{sel_val}'")
                    await step_shot("ok")
                else:
                    done = await self._select_option(sel_val)
                    if done:
                        await self._log("success", f"  → Selected '{sel_val}' from dropdown")
                        await step_shot("ok")
                    else:
                        await self._log("error", f"  ✗ STEP FAILED — select option '{sel_val}' not found")
                        await step_shot("FAIL")
                        return False

            elif action == "search":
                fill_val = value if value else target

                async def _do_search() -> bool:
                    el = await self._find_input("search")
                    if not el:
                        el = await self._find("search")
                    if el:
                        await el.click()
                        await el.fill(fill_val)
                        await self._page.keyboard.press("Enter")
                        await asyncio.sleep(1.5)
                        return True
                    try:
                        search_loc = self._page.locator(
                            "input[type='search'], input[placeholder*='search' i], "
                            "input[placeholder*='Search' i], input[name*='search' i]"
                        )
                        s = search_loc.first
                        if await s.count() > 0:
                            await s.fill(fill_val)
                            await self._page.keyboard.press("Enter")
                            await asyncio.sleep(1.5)
                            return True
                    except Exception:
                        pass
                    return False

                # Wait up to 10 s for the search box (page may still be loading)
                found = await _do_search()
                if not found:
                    for _ in range(20):   # 20 × 0.5 s = 10 s
                        await asyncio.sleep(0.5)
                        found = await _do_search()
                        if found:
                            break

                # SPA may need a full reload to reach the correct route after
                # navigating while already authenticated
                if not found:
                    await self._log("info", "  🔄 Search box not found — reloading page")
                    try:
                        await self._page.reload(wait_until="domcontentloaded", timeout=15000)
                        await self._page.wait_for_load_state("networkidle", timeout=8000)
                        await asyncio.sleep(2)
                        # COS always shows a login overlay on page load — dismiss it
                        await self._page.keyboard.press("Escape")
                        await asyncio.sleep(1.5)
                    except Exception:
                        pass
                    for _ in range(20):   # another 10 s after reload
                        found = await _do_search()
                        if found:
                            break
                        await asyncio.sleep(0.5)

                if found:
                    await self._log("success", f"  → Searched for '{fill_val}'")
                    await step_shot("ok")
                else:
                    await self._log("error", f"  ✗ STEP FAILED — search box not found")
                    await step_shot("FAIL")
                    return False

            elif action == "wait_for":
                # Poll up to 90s for target text to appear on page.
                # While waiting, auto-handle Microsoft intermediate pages so
                # they don't block the flow ("Stay signed in?", account picker).
                found = False
                words = [w for w in target.lower().split() if len(w) >= 3]
                for _ in range(180):   # 180 × 0.5s = 90s max
                    try:
                        body = await self._page.inner_text("body")
                        body_lower = body.lower()
                        if target.lower() in body_lower or all(w in body_lower for w in words):
                            found = True
                            break
                        # Auto-dismiss Microsoft "Stay signed in?" page
                        if "stay signed in" in body_lower or "keep me signed in" in body_lower:
                            for frame in self._page.frames:
                                for sel in ["input[value='Yes']", "input[id='idSIButton9']",
                                            "button:has-text('Yes')"]:
                                    try:
                                        btn = frame.locator(sel).first
                                        if await btn.count() > 0 and await btn.is_visible():
                                            await btn.click()
                                            await self._log("info", "  🔑 Auto-dismissed 'Stay signed in?'")
                                            await asyncio.sleep(2)
                                            break
                                    except Exception:
                                        pass
                        # Auto-dismiss "Which type of account?" picker
                        elif "which type of account" in body_lower:
                            for frame in self._page.frames:
                                try:
                                    btn = frame.get_by_text("Work or school account").first
                                    if await btn.count() > 0:
                                        await btn.click()
                                        await self._log("info", "  🔑 Auto-selected Work/school account")
                                        await asyncio.sleep(2)
                                        break
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    await asyncio.sleep(0.5)
                msg = f"  ✓ '{target}' appeared" if found else f"  ⚠ Timeout waiting for '{target}' — continuing"
                await self._log("success" if found else "info", msg)
                await step_shot("ok")

            elif action == "wait":
                ms = int(target) if target.isdigit() else 2000
                await asyncio.sleep(ms / 1000)
                await self._log("info", f"  → Waited {ms}ms")
                await step_shot("ok")

            elif action == "screenshot":
                # Wait for page to fully settle before capturing
                try:
                    await self._page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                # Wait for skeleton/loading placeholders to disappear
                try:
                    await self._page.wait_for_function(
                        """() => document.querySelectorAll(
                            '[class*="skeleton"], [class*="loading"], [class*="placeholder"], [class*="shimmer"]'
                        ).length === 0""",
                        timeout=6000,
                    )
                except Exception:
                    pass
                # If target is a specific filename, save with that name
                if target and target.lower().endswith((".png", ".jpg")):
                    safe_name = re.sub(r"[^\w\-.]", "_", target)
                    named_path = self.screenshot_dir / safe_name
                    try:
                        await self._page.screenshot(
                            path=str(named_path), full_page=True, animations="disabled"
                        )
                        await self._log("info", f"  📸 Screenshot saved: {safe_name}", screenshot=safe_name)
                    except Exception:
                        pass
                await step_shot("ok")

            elif action == "verify":
                try:
                    body = await self._page.inner_text("body")
                    if target.lower() in body.lower():
                        await self._log("success", f"  ✓ '{target}' found on page")
                        await step_shot("ok")
                    else:
                        await self._log("error", f"  ✗ STEP FAILED — '{target}' not visible on page")
                        await step_shot("FAIL")
                        return False
                except Exception as e:
                    await self._log("error", f"  ✗ STEP FAILED — verify error: {e}")
                    await step_shot("FAIL")
                    return False

            elif action == "scroll":
                d = target.lower()
                if d in ("bottom", "down"):
                    await self._page.evaluate("window.scrollTo(0,document.body.scrollHeight)")
                elif d in ("top", "up"):
                    await self._page.evaluate("window.scrollTo(0,0)")
                else:
                    await self._page.mouse.wheel(0, 500)
                await self._log("info", f"  → Scrolled {target}")
                await step_shot("ok")

            elif action == "hover":
                el = await self._find(target)
                if el:
                    await el.hover()
                await step_shot("ok")

            elif action == "press_key":
                key = target or value
                await self._page.keyboard.press(key)
                await asyncio.sleep(0.6)
                await self._log("info", f"  → Key: {key}")
                await step_shot("ok")

            elif action == "click_first_row":
                # Click the first row/link in a table or list
                clicked = False
                pages_before = len(self._context.pages)
                for frame in self._page.frames:
                    if clicked:
                        break
                    for sel in [
                        "table tbody tr:first-child td a",
                        "table tbody tr:first-child a",
                        "table tr:nth-child(2) td a",
                        "table tr:nth-child(2) td:first-child",
                        "tbody tr:first-child td:first-child",
                        "[role='row']:nth-child(2) [role='cell']:first-child",
                        "[role='row']:nth-child(2) [role='cell']:first-child a",
                        "[role='gridcell']:first-child a",
                        "tr:not(:first-child) td:first-child a",
                        "ul li:first-child a",
                        ".list-row:first-child", ".row:first-child a",
                    ]:
                        try:
                            loc = frame.locator(sel).first
                            if await loc.count() > 0 and await loc.is_visible():
                                await loc.click(timeout=8000)
                                clicked = True
                                await self._log("success", f"  → Clicked first row ({sel})")
                                await self._maybe_switch_new_tab(pages_before)
                                break
                        except Exception:
                            pass
                # JS fallback — works on any DOM structure including div-based tables
                if not clicked:
                    try:
                        clicked = await self._page.evaluate("""
                            () => {
                                // Links inside table data cells
                                const tdLinks = document.querySelectorAll('td a, td button');
                                if (tdLinks.length > 0) { tdLinks[0].click(); return true; }
                                // First data row (skip header rows with th)
                                const rows = document.querySelectorAll('tr');
                                for (const row of rows) {
                                    if (row.querySelector('th')) continue;
                                    const cells = row.querySelectorAll('td');
                                    if (cells.length > 0) { cells[0].click(); return true; }
                                }
                                // role=row / role=gridcell
                                const roleRows = document.querySelectorAll('[role="row"]');
                                for (const row of roleRows) {
                                    const cells = row.querySelectorAll('[role="cell"], [role="gridcell"]');
                                    if (cells.length > 0) {
                                        const link = cells[0].querySelector('a') || cells[0];
                                        link.click(); return true;
                                    }
                                }
                                // Any visible anchor that looks like a numeric ID
                                const anchors = [...document.querySelectorAll('a')];
                                const idLink = anchors.find(a => /^\\d{4,}$/.test(a.textContent.trim()));
                                if (idLink) { idLink.click(); return true; }
                                return false;
                            }
                        """)
                        if clicked:
                            await self._log("success", f"  → Clicked first row via JS ('{target}')")
                            await self._maybe_switch_new_tab(pages_before)
                    except Exception:
                        pass
                if clicked:
                    try:
                        await self._page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        pass
                    await step_shot("ok")
                else:
                    await self._log("error", f"  ✗ STEP FAILED — first row not found on page")
                    await step_shot("FAIL")
                    return False

            elif action == "refresh_until":
                # Poll: click the page's refresh icon (if present) or full reload,
                # wait 30 s, check for target text OR green-coloured status elements.
                # Up to 40 attempts = 20 min max.
                found = False
                saved_url = self._page.url

                async def _has_green_status() -> bool:
                    """Return True if a STATUS indicator anywhere on the page is green.
                    Checks background-color, color (text), SVG fill, and rgba() format.
                    Skips nav/header/sidebar chrome to avoid false positives."""
                    try:
                        return await self._page.evaluate("""
                            () => {
                                function isGreen(cssColor) {
                                    if (!cssColor || cssColor === 'transparent' ||
                                        cssColor === 'rgba(0, 0, 0, 0)') return false;
                                    const m = cssColor.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
                                    if (!m) return false;
                                    const [r, g, b] = [+m[1], +m[2], +m[3]];
                                    // Green: g dominant, not near-white, not near-grey
                                    return g > 100 && g > r * 1.4 && g > b * 1.4
                                        && !(r > 190 && g > 190 && b > 190);
                                }
                                const SKIP = 'nav, header, aside, footer, ' +
                                    '.vs-sidebar, .vs-navbar, .navbar, .sidebar, ' +
                                    '.menu, [class*="sidebar"], [class*="navbar"]';
                                const candidates = document.querySelectorAll(
                                    'td *, tr *, [class*="status"], [class*="chip"], ' +
                                    '[class*="badge"], [class*="tag"], [class*="label"], ' +
                                    '[class*="dot"], [class*="circle"], [class*="indicator"], ' +
                                    'span, div, svg circle, svg path'
                                );
                                for (const el of candidates) {
                                    if (el.closest(SKIP)) continue;
                                    const cs = window.getComputedStyle(el);
                                    // background-color (div/span dots)
                                    if (isGreen(cs.backgroundColor)) return true;
                                    // color (green text status label)
                                    if (isGreen(cs.color)) return true;
                                    // SVG fill attribute
                                    const fill = el.getAttribute && el.getAttribute('fill');
                                    if (fill && (fill.toLowerCase().includes('green') ||
                                        /^#0[0-9a-f]{2}[8-9a-f][0-9a-f]{2}/i.test(fill)))
                                        return true;
                                    // SVG fill via computed style
                                    if (isGreen(cs.fill)) return true;
                                }
                                return false;
                            }
                        """)
                    except Exception:
                        return False

                async def _click_refresh_icon() -> bool:
                    """Click the in-page refresh icon/button; return True if clicked."""
                    for frame in self._page.frames:
                        for sel in [
                            "button[title*='refresh' i]",
                            "button[aria-label*='refresh' i]",
                            "[title*='refresh' i]:not(meta)",
                            "[aria-label*='refresh' i]",
                            "i.vs-icon:has-text('refresh')",
                            "i.material-icons:has-text('refresh')",
                            "i.material-icons:has-text('cached')",
                            ".refresh-btn", "[class*='refresh'][class*='btn']",
                        ]:
                            try:
                                btn = frame.locator(sel).first
                                if await btn.count() > 0 and await btn.is_visible():
                                    await btn.click()
                                    return True
                            except Exception:
                                pass
                    return False

                for attempt in range(40):
                    # ── Check condition ───────────────────────────────────────
                    try:
                        body = await self._page.inner_text("body")
                        if target.lower() in body.lower():
                            found = True
                            await self._log("success", f"  ✓ '{target}' found after {attempt} refresh(es)")
                            break
                    except Exception:
                        pass
                    if not found and await _has_green_status():
                        found = True
                        await self._log("success", f"  ✓ Green status detected in table after {attempt} refresh(es)")
                        break

                    # ── Refresh: icon click → fallback full reload ────────────
                    clicked = await _click_refresh_icon()
                    if clicked:
                        await self._log("info", "  🔄 Clicked page refresh icon")
                        await asyncio.sleep(3)
                    else:
                        try:
                            await self._page.reload(wait_until="domcontentloaded", timeout=15000)
                            await asyncio.sleep(3)
                        except Exception:
                            pass

                    # ── Auth-redirect recovery ────────────────────────────────
                    try:
                        current_url = self._page.url
                        page_text = (await self._page.inner_text("body")).lower()
                        login_keywords = ("login", "sign in", "signin", "which type of account")
                        is_login_page = (
                            "/login" in current_url.lower()
                            or any(k in current_url.lower() for k in login_keywords)
                            or any(k in page_text for k in login_keywords)
                        )
                        if is_login_page:
                            await self._log("info", "  ⚠ Auth expired — re-logging in")
                            await self._recover_ms_login(saved_url)
                    except Exception:
                        pass

                    await asyncio.sleep(27)   # 3+27 = 30s per cycle

                if not found:
                    await self._log("info", f"  ⚠ '{target}' not seen after 40 refreshes — continuing")
                await step_shot("ok")

            elif action == "extract":
                target_upper = target.upper()
                is_subscriber_id = any(
                    k in target_upper
                    for k in ("EXTERNAL", "SUBSCRIBER", "MSISDN", "MISTIN")
                )

                val = None
                for _ in range(20):   # 20 × 0.5 s = 10 s max
                    try:
                        body = await self._page.inner_text("body")
                        if is_subscriber_id:
                            # Common labels in telecom COS/BSS portals for the
                            # subscriber's external/full number
                            ext_m = re.search(
                                r'(?:External\s+ID|Subscriber\s+ID|MSISDN|'
                                r'Account\s+(?:No\.?|Number)|Phone\s+Number|'
                                r'Mobile\s+Number|Subscriber\s+No\.?|'
                                r'Subscriber\s+Number)\s*[:\s]+(\+?[0-9][\d\s\-\.]{4,20})',
                                body, re.IGNORECASE,
                            )
                            if ext_m:
                                val = re.sub(r'\s+', '', ext_m.group(1).strip())
                                break
                        else:
                            bal_m = re.search(
                                r'(?:Balance|Saldo)\s*[:\s]+([0-9][0-9\s\.,]+\s*(?:kr\.?|DKK)?)',
                                body, re.IGNORECASE,
                            )
                            if bal_m:
                                val = re.sub(r'\s+', ' ', bal_m.group(1).strip())
                                break
                    except Exception:
                        pass
                    await asyncio.sleep(0.5)

                if val:
                    self._captured_vars[target] = val
                    await self._log("success", f"  📊 Captured {target} = {val}")
                else:
                    if is_subscriber_id:
                        # Fall back to MISTIN_ID env var so the report still has a value
                        fallback = (
                            os.environ.get("MISTIN_ID")
                            or os.environ.get("PHONE_NUMBER")
                            or ""
                        )
                        if fallback:
                            self._captured_vars[target] = fallback
                            await self._log(
                                "info",
                                f"  ⚠ External ID not found on page — using env fallback: {fallback}",
                            )
                        else:
                            await self._log("info", f"  ⚠ Could not find external ID on page after 10s")
                    else:
                        await self._log("info", f"  ⚠ Could not find balance on page after 10s")
                await step_shot("ok")

            elif action == "skip":
                await self._log("info", f"  → Skipped")
                return True

            else:
                await self._log("warning", f"  Unknown action '{action}'")
                await step_shot("ok")

            return True

        except Exception as e:
            err_s = str(e)
            # A closed/detached page on an *optional* step should never stop the run.
            _CLOSED = ("been closed", "Target closed", "context or browser",
                       "Target page", "frame was detached", "Execution context")
            if optional and any(k in err_s for k in _CLOSED):
                await self._log(
                    "info",
                    f"  → Optional step skipped (page closed mid-step): {err_s[:120]}"
                )
                return True
            await self._log("error", f"  ✗ STEP FAILED — {e}")
            await step_shot("FAIL")
            return False

    # ── Core Playwright execution ─────────────────────────────────────────────
    async def _execute(self, plan: dict) -> dict:
        """Playwright session — must run in ProactorEventLoop on Windows."""
        steps     = plan.get("steps", [])
        completed = 0
        failed    = []
        self._running = True

        async with async_playwright() as pw:
            self._pw = pw   # store for browser-relaunch recovery
            # Launch browser
            try:
                self._browser = await pw.chromium.launch(
                    headless=self.headless,
                    slow_mo=settings.BROWSER_SLOW_MO,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-web-security",
                        "--allow-running-insecure-content",
                        "--start-maximized",
                    ],
                )
            except Exception as e:
                err = str(e)
                if "executable" in err.lower() or "doesn't exist" in err.lower():
                    raise RuntimeError(
                        "Chromium not installed.\n"
                        "Run:  python -m playwright install chromium\n"
                        f"({err})"
                    )
                raise RuntimeError(f"Browser launch failed: {err}")

            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                ),
                ignore_https_errors=True,
            )
            self._page = await self._context.new_page()
            await self._log("info", f"🚀 Browser launched — {len(steps)} steps")

            # Only stream live frames when NOT headless (visible browser mode)
            live_task = None
            if not self.headless and self.frame_callback:
                live_task = asyncio.create_task(self._live_stream_loop())

            stop_reason = None
            try:
                for step in steps:
                    if not self._running:
                        stop_reason = "cancelled"
                        break
                    ok = await self.execute_step(step)
                    if ok:
                        completed += 1
                    else:
                        # Step failed — record and STOP immediately
                        step_n = step.get("step_number", completed + 1)
                        failed.append(step_n)
                        stop_reason = (
                            f"Step {step_n} failed: {step.get('description', step.get('target',''))}"
                        )
                        await self._log(
                            "error",
                            f"❌ STOPPED at step {step_n} — "
                            f"{step.get('description', step.get('target',''))}"
                        )
                        break   # ← hard stop, no next step
            finally:
                self._running = False
                if live_task:
                    live_task.cancel()
                    try:
                        await live_task
                    except asyncio.CancelledError:
                        pass

            # Final screenshot — skipped in none / named_only modes
            if self._screenshot_mode not in ("none", "named_only"):
                shot = await self._screenshot("final")
                if shot:
                    await self._log("info", "Final state captured", screenshot=shot)
            try:
                await self._browser.close()
            except Exception:
                pass

        rate   = (completed / len(steps) * 100) if steps else 0
        all_ok = (completed == len(steps) and not failed)
        status = "success" if all_ok else ("failed" if completed == 0 else "partial")
        return {
            "status": status,
            "steps_completed": completed,
            "steps_total": len(steps),
            "failed_steps": failed,
            "stop_reason": stop_reason or "all steps completed",
            "success_rate": rate,
            "captured_vars": self._captured_vars,
            "summary": (
                plan.get("expected_outcome", "")
                if all_ok
                else (stop_reason or f"{completed}/{len(steps)} steps completed")
            ),
        }

    # ── Public entry point ────────────────────────────────────────────────────
    async def run(self, plan: dict) -> dict:
        """
        On Windows: Playwright needs ProactorEventLoop for subprocess support.
        We spin up a dedicated thread with its own ProactorEventLoop and dispatch
        all log/frame callbacks back to the caller's loop via run_coroutine_threadsafe.
        """
        if sys.platform == "win32":
            return await self._run_via_proactor_thread(plan)
        return await self._execute(plan)

    async def _run_via_proactor_thread(self, plan: dict) -> dict:
        """Windows: run _execute in a thread that owns a ProactorEventLoop."""
        self._main_loop = asyncio.get_event_loop()

        result_box: list = []
        error_box:  list = []

        def thread_fn():
            # This thread gets its own ProactorEventLoop — subprocess works here
            loop = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(self._execute(plan))
                result_box.append(result)
            except Exception as exc:
                error_box.append(exc)
            finally:
                loop.close()

        t = threading.Thread(target=thread_fn, daemon=True)
        t.start()

        # Keep yielding to the main event loop (so WS broadcasts and HTTP responses work)
        while t.is_alive():
            await asyncio.sleep(0.3)
        t.join()

        if error_box:
            raise error_box[0]

        return result_box[0] if result_box else {
            "status": "failed", "steps_completed": 0, "steps_total": 0,
            "failed_steps": [], "success_rate": 0,
        }
