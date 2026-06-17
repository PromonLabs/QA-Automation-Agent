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
from app.agents.llm_client import vision_client

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
        self._last_idle_url: str = ""   # URL we last waited networkidle for (skip re-wait)
        self._shared_browser: Optional[Browser] = None   # set by bulk sequential runner
        self._shared_context: Optional[BrowserContext] = None  # reuse login session across sequential runs
        self._already_in_proactor_loop: bool = False     # skip thread spawn when already in right loop

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
    async def _screenshot(self, label: str = "", timeout_ms: int = 8000) -> str:
        if not self._page:
            return ""
        filename = f"step_{self._step_count:03d}_{label}_{int(time.time())}.png"
        try:
            await self._page.screenshot(
                path=str(self.screenshot_dir / filename),
                full_page=True,
                animations="disabled",
                timeout=timeout_ms,
            )
        except Exception:
            try:
                # Fallback: viewport-only screenshot with tighter timeout
                await self._page.screenshot(
                    path=str(self.screenshot_dir / filename),
                    full_page=False,
                    timeout=timeout_ms,
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
                # CSS attribute search — catches frameworks that store tooltip text in data-*
                lambda t=t: p.locator(
                    f"[aria-label*='{t}' i], [data-tooltip*='{t}' i], "
                    f"[data-title*='{t}' i], [data-hint*='{t}' i], "
                    f"[data-content*='{t}' i]"
                ).first,
                # Vuesax tooltip wrappers (v2: con-vs-tooltip, v3: vs-tooltip__trigger)
                # Filter wrapper by its combined textContent (button icon + tooltip text)
                lambda t=t: p.locator(".con-vs-tooltip").filter(
                    has_text=_re.compile(_re.escape(t), _re.I)
                ).locator("button, [role='button'], a").first,
                lambda t=t: p.locator(".vs-tooltip__trigger").filter(
                    has_text=_re.compile(_re.escape(t), _re.I)
                ).locator("button, [role='button'], a").first,
                # Vuesax tooltip only injected into DOM on hover — hover the button first
                # to make the tooltip appear, then confirm and click.
                # Works for any "create / add / new" icon button with a Vuesax tooltip.
                lambda t=t: p.locator(
                    "button.vs-button--circle, button.vs-button--icon"
                ).first if any(k in t.lower() for k in ("create", "add", "new", "insert")) else None,
            ]:
                try:
                    el = fn()
                    if await el.count() > 0 and await el.is_visible():
                        return el
                except Exception:
                    continue

        if target.startswith(("#", ".", "[", "//")):
            # Wait up to 8 s for the element to appear (handles SPA rendering delays
            # where the button is injected into the DOM after the page settles).
            try:
                await p.wait_for_selector(target, timeout=8000)
            except Exception:
                pass
            try:
                loc = p.locator(target).first
                if await loc.count() > 0:
                    return loc
            except Exception:
                pass
            for frame in p.frames[1:]:
                try:
                    loc = frame.locator(target).first
                    if await loc.count() > 0:
                        return loc
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
            # inputs require is_visible(); textareas skip it (Vuesax hides the raw <textarea>)
            tl = target.lower()
            for attr in ["name", "id", "placeholder", "aria-label"]:
                try:
                    inp_loc = frame.locator(f"input[{attr}*='{tl}' i]").first
                    if await inp_loc.count() > 0 and await inp_loc.is_visible():
                        return inp_loc
                except Exception:
                    pass
                try:
                    ta_loc = frame.locator(f"textarea[{attr}*='{tl}' i]").first
                    if await ta_loc.count() > 0:   # no visibility check for textarea
                        return ta_loc
                except Exception:
                    pass
            # Keyword fallback — try each word in target (≥4 chars) against placeholder/aria-label
            words = [w for w in tl.split() if len(w) >= 4]
            for word in words:
                for attr in ["placeholder", "aria-label", "name"]:
                    try:
                        inp_loc = frame.locator(f"input[{attr}*='{word}' i]").first
                        if await inp_loc.count() > 0 and await inp_loc.is_visible():
                            return inp_loc
                    except Exception:
                        pass
                    try:
                        ta_loc = frame.locator(f"textarea[{attr}*='{word}' i]").first
                        if await ta_loc.count() > 0:   # no visibility check for textarea
                            return ta_loc
                    except Exception:
                        pass

            # ICC / SIM card number field — no visibility check (Vuesax hides the raw input)
            if any(w in tl for w in ["icc", "iccid", "sim", "imsi"]):
                for sel in ["input[type='text']", "input:not([type])", "input"]:
                    try:
                        loc = frame.locator(sel).first
                        if await loc.count() > 0:
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

    # ── Primary action button finder (submit/order/activate) ─────────────────
    async def _click_primary_button(self) -> bool:
        """
        Click the most prominent non-navigation button on the page.
        Used when the exact submit button label is unknown.
        Skips Back / Cancel / Continue / Close buttons.
        Tries Vuesax primary-colour buttons first, then any visible button
        whose text doesn't look like navigation.
        """
        _NAV_WORDS = {"back", "cancel", "close", "previous", "continue", "skip", "next"}

        for frame in self._page.frames:
            try:
                clicked = await frame.evaluate("""
                    () => {
                        const navWords = new Set(
                            ["back","cancel","close","previous","continue","skip","next"]
                        );
                        function isNav(el) {
                            const t = (el.textContent || "").trim().toLowerCase();
                            return navWords.has(t) || t.length === 0;
                        }
                        function isVisible(el) {
                            const r = el.getBoundingClientRect();
                            return r.width > 0 && r.height > 0;
                        }

                        // Pass 1: Vuesax primary / success coloured buttons
                        const vsPrimary = [
                            ...document.querySelectorAll(
                                'button.vs-button--primary, button.vs-button--success, '
                                + 'button[class*="primary"], button[class*="success"], '
                                + '.vs-button--color, button[color="primary"]'
                            )
                        ].filter(el => isVisible(el) && !isNav(el));
                        if (vsPrimary.length) {
                            vsPrimary[vsPrimary.length - 1].click();
                            return vsPrimary[vsPrimary.length - 1].textContent.trim();
                        }

                        // Pass 2: any visible button not in nav list
                        const all = [
                            ...document.querySelectorAll('button, [role="button"]')
                        ].filter(el => isVisible(el) && !isNav(el));
                        if (all.length) {
                            all[all.length - 1].click();
                            return all[all.length - 1].textContent.trim();
                        }

                        return null;
                    }
                """)
                if clicked:
                    await self._log("success", f"  → Clicked primary action button: '{clicked}'")
                    try:
                        await self._page.wait_for_load_state("networkidle", timeout=4000)
                    except Exception:
                        pass
                    return True
            except Exception:
                pass
        return False

    # ── Vision fallback: qwen2.5vl finds element from screenshot ─────────────
    async def _vision_find(self, description: str):
        """
        Take a viewport screenshot and ask qwen2.5vl to locate the element.
        Returns a Playwright locator (by text or coordinates) or None.
        """
        if not self._page:
            return None
        try:
            data = await self._page.screenshot(type="jpeg", quality=70, full_page=False)
            b64  = base64.b64encode(data).decode()
            result = await vision_client.find_element(b64, description)
            if not result.get("found"):
                return None

            await self._log("info", f"  👁 Vision agent located '{description}' → {result.get('element_type','?')} at ({result.get('x')},{result.get('y')})")

            # Try text-based match first (most reliable for clicking)
            text = result.get("element_text", "").strip()
            if text:
                import re as _re
                loc = self._page.get_by_text(_re.compile(_re.escape(text), _re.I), exact=False).first
                try:
                    if await loc.count() > 0 and await loc.is_visible():
                        return loc
                except Exception:
                    pass

            # Fall back to coordinates
            x, y = result.get("x"), result.get("y")
            if x and y:
                # Return a coordinate-click helper wrapped as a simple object
                class _CoordLocator:
                    def __init__(self_, px, py, page):
                        self_.px, self_.py, self_.page = px, py, page
                    async def count(self_): return 1
                    async def is_visible(self_): return True
                    async def click(self_, **kw): await self_.page.mouse.click(self_.px, self_.py)
                    async def scroll_into_view_if_needed(self_): pass
                    async def evaluate(self_, *a, **kw): return None
                    async def input_value(self_): return ""
                    async def clear(self_): pass
                    async def press_sequentially(self_, val, **kw):
                        await self_.page.mouse.click(self_.px, self_.py)
                        await self_.page.keyboard.type(val, delay=15)
                    async def fill(self_, val):
                        await self_.page.mouse.click(self_.px, self_.py)
                        await self_.page.keyboard.type(val, delay=15)
                return _CoordLocator(x, y, self._page)
        except Exception:
            pass
        return None

    # ── Select dropdown option across all frames ─────────────────────────────
    async def _select_option(self, value: str, page=None, label_hint: str = "") -> bool:
        """
        Find a <select> and set its value.
        label_hint: adjacent label text (e.g. "Inventory Type") to prefer the right select
                    on pages with many dropdowns (old-style HTML tables without <label for>).
        Tries (in order):
          1. Playwright exact value/label match on each visible <select>
          2. JavaScript case-insensitive text/value match, preferring <select> whose
             adjacent cell/label contains label_hint
        """
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

        # JS fallback: case-insensitive option text/value match.
        # If label_hint is given, prefer the <select> whose nearest <td>/<th>/sibling
        # contains that text (handles old-style HTML tables with no <label for>).
        for frame in p.frames:
            try:
                result = await frame.evaluate("""
                    ([val, hint]) => {
                        const norm = s => s.trim().toLowerCase();
                        const selects = Array.from(document.querySelectorAll('select'));
                        // Score: 2 = label hint matches row  1 = option match only
                        // Pass 1: exact match; Pass 2: starts-with; Pass 3: contains
                        for (const pass of ['exact', 'startswith', 'contains']) {
                            let best = null, bestScore = 0;
                            for (const sel of selects) {
                                const opts = Array.from(sel.options);
                                let opt;
                                if (pass === 'exact') {
                                    opt = opts.find(o => norm(o.text) === norm(val) || norm(o.value) === norm(val));
                                } else if (pass === 'startswith') {
                                    opt = opts.find(o => norm(o.text).startsWith(norm(val)) || norm(o.value).startsWith(norm(val)));
                                } else {
                                    opt = opts.find(o => norm(o.text).includes(norm(val)) || norm(o.value).includes(norm(val)));
                                }
                                if (!opt) continue;
                                let score = 1;
                                if (hint) {
                                    const row = sel.closest('tr') || sel.parentElement;
                                    if (row && norm(row.textContent).includes(norm(hint))) score = 2;
                                }
                                if (score > bestScore) { best = { sel, opt }; bestScore = score; }
                            }
                            if (best) {
                                best.sel.value = best.opt.value;
                                best.sel.dispatchEvent(new Event('change', {bubbles: true}));
                                return true;
                            }
                        }
                        return false;
                    }
                """, [value, label_hint])
                if result:
                    return True
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
        return any(k in lo for k in ("username", "password", "email field", "email address", "email", "log in", "login"))

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
                    await em.press_sequentially(user, delay=15)
                    await em.evaluate("e => e.dispatchEvent(new Event('input',{bubbles:true}))")
                    await em.evaluate("e => e.dispatchEvent(new Event('blur',{bubbles:true}))")
                    await asyncio.sleep(0.5)
                    await pw.clear()
                    await pw.press_sequentially(pwd, delay=15)
                    await pw.evaluate("e => e.dispatchEvent(new Event('input',{bubbles:true}))")
                    await pw.evaluate("e => e.dispatchEvent(new Event('blur',{bubbles:true}))")
                    await asyncio.sleep(0.5)
                    await self._page.keyboard.press("Enter")
                    await asyncio.sleep(3)
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
                    await asyncio.sleep(2)
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
                    await asyncio.sleep(2)
                    continue

                await asyncio.sleep(0.5)

            # Wait for the app to fully settle after login
            try:
                await self._page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            await asyncio.sleep(1)

            # Navigate back to the operation detail page
            current = self._page.url
            if current != return_url:
                await self._page.goto(return_url, wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(1.5)

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
            Failure screenshots (error_step_NNN.png) are ALWAYS captured regardless
            of mode so the bulk results grid can show where the flow broke.
            """
            mode = self._screenshot_mode
            if status == "FAIL":
                # Always capture on failure — named error_step_NNN.png so the UI
                # can detect it and show a red "Error" badge in the results grid.
                # Use a tight 3-second timeout: a page that failed to load won't
                # render a useful screenshot and the call would otherwise hang.
                lbl = f"error_step_{self._step_count:03d}"
                try:
                    shot = await self._screenshot(lbl, timeout_ms=3000)
                    if shot:
                        await self._log("info", f"  [fail] screenshot", screenshot=shot)
                except Exception:
                    pass
                return
            if mode in ("none", "named_only"):
                return   # only explicit screenshots allowed
            if mode == "final":
                return   # handled at end of _execute
            if mode == "fail_only":
                return   # success shots skipped in fail_only mode
            lbl = f"ok_s{self._step_count:02d}"
            try:
                shot = await self._screenshot(lbl)
                if shot:
                    await self._log("info", f"  [ok] screenshot", screenshot=shot)
            except Exception:
                pass

        try:
            if action == "navigate":
                url = target if target.startswith("http") else f"https://{target}"

                # If current page is already at this URL (same-document hash change),
                # use JS pushState instead of a full Playwright goto() which resets SPA state
                cu = None
                tu = None
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
                    _nav_done = False
                    for _nav_attempt in range(3):
                      try:
                        await self._page.goto(url, wait_until="domcontentloaded", timeout=nav_timeout)
                        _nav_done = True
                        break
                      except Exception as nav_err:
                        nav_err_s = str(nav_err)
                        # Payment gateways often close/kill the tab or context after success.
                        # Four-level recovery:
                        closed  = any(k in nav_err_s for k in ("been closed", "Target closed", "context or browser",
                                                                         "Connection closed", "connection closed",
                                                                         "reading from the driver", "NS_ERROR"))
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
                                _launch_args = [
                                    "--no-sandbox",
                                    "--disable-dev-shm-usage",
                                    "--disable-blink-features=AutomationControlled",
                                    "--disable-web-security",
                                    "--allow-running-insecure-content",
                                    "--start-maximized",
                                ]
                                for _launch_attempt in range(2):
                                    try:
                                        if _launch_attempt > 0:
                                            await self._log("info", "  ⚠ Retrying browser relaunch…")
                                            await asyncio.sleep(3)
                                        self._browser = await self._pw.chromium.launch(
                                            headless=self.headless,
                                            slow_mo=settings.BROWSER_SLOW_MO,
                                            args=_launch_args,
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
                                        break
                                    except Exception as _relaunch_err:
                                        await self._log("info", f"  ⚠ Browser relaunch attempt {_launch_attempt + 1} failed: {_relaunch_err}")
                                        if _launch_attempt == 0:
                                            continue
                                        # Both attempts failed — leave recovered=False so outer code re-raises

                            if not recovered:
                                raise
                            _nav_done = True
                            break
                        else:
                            # Transient failure (timeout, connection refused, etc.) — retry
                            if _nav_attempt < 2:
                                await self._log("info", f"  ⚠ Navigation attempt {_nav_attempt + 1} failed ({nav_err_s[:80]}…) — retrying in 3s")
                                await asyncio.sleep(3)
                                # Open a fresh page so the stale tab doesn't block the retry
                                try:
                                    self._page = await self._context.new_page()
                                except Exception:
                                    pass
                                continue
                            raise
                    _same_domain = (cu.netloc == tu.netloc) if cu and tu else False
                    try:
                        await self._page.wait_for_load_state("networkidle", timeout=2000 if _same_domain else 4000)
                    except Exception:
                        pass
                    if not _same_domain:
                        # Poll up to 5 s for ANY interactive element to appear (cross-domain only).
                        for _ in range(10):    # 10 × 0.5 s = 5 s max
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
                    for _ in range(8):
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

                self._last_idle_url = ""   # new page — reset idle cache
                await self._log("info", f"  → {url}")
                await step_shot("ok")

            elif action in ("click", "button_click"):
                # Skip login buttons if page is already authenticated.
                # Check _already_authenticated() directly — no domain tracking needed
                # so this works correctly for new agent instances in sequential bulk runs.
                if self._is_login_button(target):
                    if await self._already_authenticated():
                        await self._log("info", f"  → Already logged in — skipping '{target}'")
                        await step_shot("ok")
                        self._login_sequence_skipped = True
                        return True
                    self._login_sequence_skipped = False

                # Track page count BEFORE click to detect new tab
                pages_before = len(self._context.pages)

                el = None   # always initialise before the find call below

                # Try primary target, then each alternative label
                if el is None:
                    el = await self._find(target)
                clicked_name = target
                if not el:
                    for alt in alternatives:
                        el = await self._find(alt)
                        if el:
                            clicked_name = alt
                            break

                if el:
                    try:
                        await el.scroll_into_view_if_needed()
                    except Exception:
                        pass  # element may be transitioning — continue to click anyway

                    # Listen for new page event BEFORE clicking
                    new_page_holder: list = []
                    def _on_page(pg):
                        new_page_holder.append(pg)
                    self._context.on("page", _on_page)

                    try:
                        await el.click(timeout=10000)
                    except Exception as click_err:
                        err_s = str(click_err)
                        if any(k in err_s for k in ("intercepts pointer events", "Timeout", "timeout")):
                            # Element may be covered or still animating — use JS click
                            try:
                                await el.evaluate("el => el.click()")
                            except Exception:
                                await self._page.keyboard.press("Escape")
                                await asyncio.sleep(0.5)
                                try:
                                    await el.click(timeout=5000)
                                except Exception:
                                    await el.evaluate("el => el.click()")
                        else:
                            self._context.remove_listener("page", _on_page)
                            raise

                    # Wait up to 5 s for new tab (poll every 250 ms)
                    # Increased from 2.5s — slow servers (tusass.lab.gl under parallel load)
                    # can open the tab after >2.5s, causing the agent to miss the new tab.
                    switched = False
                    _url_before_click = self._page.url
                    for _ in range(20):
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
                        # Login submits need longer — the server validates credentials
                        # and then redirects to the dashboard which may take several seconds.
                        _wait_ms = 4000 if self._is_login_submit(clicked_name) else 2000
                        try:
                            await self._page.wait_for_load_state("networkidle", timeout=_wait_ms)
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
                    elif re.search(r'\bid\b', target, re.IGNORECASE) or re.match(r'^\+?\d[\d\s\-\.]{5,}$', target.strip()):
                        # Target looks like an ID or phone/subscriber number — click first table row link.
                        # Wait up to 60 s for search results to appear (COS can be slow under parallel load).
                        # Also breaks early if a card-style link result appears (COS search uses card UI).
                        for _tbl_wait in range(120):
                            try:
                                tbl_loc = self._page.locator(
                                    "table tbody tr, [role='row']:nth-child(2), "
                                    "tbody tr:not(:first-child)"
                                ).first
                                if await tbl_loc.count() > 0 and await tbl_loc.is_visible():
                                    break
                                # Card-style results (e.g. COS global search)
                                card_loc = self._page.get_by_role("link", name=re.compile(re.escape(target), re.I)).first
                                if await card_loc.count() > 0 and await card_loc.is_visible():
                                    break
                            except Exception:
                                pass
                            await asyncio.sleep(0.5)

                        clicked_row = False
                        # Pass 0: direct click on the card link found during the wait loop.
                        # Playwright .click() often fails on Vue/Vuesax card links because the
                        # navigation event destroys the execution context mid-click. JS evaluate()
                        # fires the click synchronously and returns before any navigation, so it
                        # never errors out. Try Playwright first, fall back to JS.
                        if not clicked_row:
                            try:
                                card_direct = self._page.get_by_role(
                                    "link", name=re.compile(re.escape(target), re.I)
                                ).first
                                if await card_direct.count() > 0 and await card_direct.is_visible():
                                    try:
                                        await card_direct.click(timeout=5000)
                                    except Exception:
                                        await card_direct.evaluate("el => el.click()")
                                    await self._log("success", f"  → Clicked card link ('{target}')")
                                    clicked_row = True
                            except Exception:
                                pass

                        # Pass 1: Playwright CSS/role selectors — covers both table rows
                        # and card-style results (e.g. COS global search uses cards not tables)
                        _safe_target = target.replace("'", "\\'")
                        for frame in self._page.frames:
                            if clicked_row:
                                break
                            for sel in [
                                # Card-style search results: link whose text contains the ID
                                f"a:has-text('{_safe_target}')",
                                f"[role='link']:has-text('{_safe_target}')",
                                # Table row results
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
                                    (tgt) => {
                                        // Card-style: any visible link whose text contains the target ID
                                        const byText = [...document.querySelectorAll('a, [role="link"]')].find(el => {
                                            const r = el.getBoundingClientRect();
                                            return r.width > 0 && r.height > 0 && el.textContent.trim().includes(tgt);
                                        });
                                        if (byText) { byText.click(); return true; }
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
                                            if (cells.length > 0) {
                                                const link = cells[0].querySelector('a') || cells[0];
                                                link.click(); return true;
                                            }
                                        }
                                        // Any visible anchor with a numeric ID as its text
                                        const idLink = [...document.querySelectorAll('a')].find(a => {
                                            const r = a.getBoundingClientRect();
                                            return r.width > 0 && r.height > 0 && /^\\d{4,}$/.test(a.textContent.trim());
                                        });
                                        if (idLink) { idLink.click(); return true; }
                                        return false;
                                    }
                                """, target)
                                if clicked_row:
                                    await self._log("success", f"  → Clicked first row via JS ('{target}')")
                            except Exception:
                                pass
                        # Pass 3: card/link result — use JS evaluate to avoid navigation errors
                        if not clicked_row:
                            try:
                                el_retry = await self._find(target)
                                if el_retry:
                                    try:
                                        await el_retry.click(timeout=5000)
                                    except Exception:
                                        await el_retry.evaluate("el => el.click()")
                                    clicked_row = True
                                    await self._log("success", f"  → Clicked search result card ('{target}')")
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
                            self._login_sequence_skipped = True
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
                                self._login_sequence_skipped = True
                            else:
                                # Phone/subscriber number — click first search result row
                                if re.match(r'^\+?\d[\d\s\-\.]{5,}$', target.strip()):
                                    for _frame in self._page.frames:
                                        _row_clicked = False
                                        for _sel in [
                                            "table tbody tr:first-child td a",
                                            "table tbody tr:first-child a",
                                            "table tr:nth-child(2) td a",
                                            "tbody tr:first-child td:first-child",
                                            "[role='row']:nth-child(2) [role='cell']:first-child",
                                        ]:
                                            try:
                                                _loc = _frame.locator(_sel).first
                                                if await _loc.count() > 0 and await _loc.is_visible():
                                                    await _loc.click(timeout=8000)
                                                    await self._log("success", f"  → Clicked first search result row for '{target}'")
                                                    _row_clicked = True
                                                    break
                                            except Exception:
                                                pass
                                        if _row_clicked:
                                            try:
                                                await self._page.wait_for_load_state("networkidle", timeout=5000)
                                            except Exception:
                                                pass
                                            await step_shot("ok")
                                            return True
                                # Submit-type step: try clicking the primary action button
                                _SUBMIT_WORDS = ("submit", "create", "confirm", "finish",
                                                 "order", "activate", "save", "done", "complete")
                                if any(w in target.lower() for w in _SUBMIT_WORDS):
                                    clicked_primary = await self._click_primary_button()
                                    if clicked_primary:
                                        await step_shot("ok")
                                        return True
                                # Final resort: vision agent
                                vision_el = await self._vision_find(target)
                                if vision_el:
                                    await self._log("info", f"  👁 Vision agent clicking '{target}'")
                                    await vision_el.click()
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
                                self._login_sequence_skipped = True
                            else:
                                _SUBMIT_WORDS = ("submit", "create", "confirm", "finish",
                                                 "order", "activate", "save", "done", "complete")
                                if any(w in target.lower() for w in _SUBMIT_WORDS):
                                    clicked_primary = await self._click_primary_button()
                                    if clicked_primary:
                                        await step_shot("ok")
                                        return True
                                vision_el = await self._vision_find(target)
                                if vision_el:
                                    await self._log("info", f"  👁 Vision agent clicking '{target}'")
                                    try:
                                        await vision_el.click()
                                    except Exception:
                                        pass
                                    await step_shot("ok")
                                else:
                                    await self._log("error", f"  ✗ STEP FAILED — '{target}' not found on page")
                                    await step_shot("FAIL")
                                    return False

            elif action == "type":
                # Fast-skip credential fields: either after login-button skip OR
                # when the page is already authenticated (saves 15s wait per field)
                if self._is_credential_field(target):
                    if self._login_sequence_skipped or await self._already_authenticated():
                        await self._log("info", f"  → Already logged in — skipping type '{target}'")
                        await step_shot("ok")
                        self._login_sequence_skipped = True
                        return True
                else:
                    self._login_sequence_skipped = False

                fill_val = value if value else target

                # Substitute captured vars (e.g. ${SUBSCRIBER_EXTERNAL_ID} from extract step)
                if "${" in fill_val:
                    for k, v in self._captured_vars.items():
                        fill_val = fill_val.replace(f"${{{k}}}", str(v))

                # If the LLM produced a descriptive phrase instead of a bare value
                # (e.g. "your phone number 547643 in the input box" instead of "547643"),
                # extract just the numeric token so the form gets the right input.
                if " " in fill_val and re.search(r'\d{4,}', fill_val):
                    _extracted = re.search(r'\b(\d{4,})\b', fill_val)
                    if _extracted:
                        fill_val = _extracted.group(1)

                async def _do_type() -> bool:
                    """Try to type fill_val into the target field. Returns True on success."""
                    el = await self._find_input(target)
                    if el:
                        tl_target = target.lower()
                        # ICC/SIM Vuesax special path: the raw <input> is hidden inside a
                        # styled container. Click the visible parent to focus the component,
                        # then type via keyboard so Vue's v-model receives native key events.
                        if any(w in tl_target for w in ["icc", "iccid", "sim card", "simcard"]):
                            try:
                                focused = await el.evaluate("""el => {
                                    let node = el.parentElement;
                                    for (let i = 0; i < 6; i++) {
                                        if (!node) break;
                                        const r = node.getBoundingClientRect();
                                        if (r.width > 50 && r.height > 10) {
                                            node.click();
                                            return true;
                                        }
                                        node = node.parentElement;
                                    }
                                    el.focus();
                                    return true;
                                }""")
                                if focused:
                                    await asyncio.sleep(0.3)
                                    await el.evaluate("el => { el.value = ''; }")
                                    await self._page.keyboard.type(str(fill_val), delay=15)
                                    try:
                                        await el.evaluate(
                                            "(el, v) => { "
                                            "el.dispatchEvent(new Event('input',{bubbles:true})); "
                                            "el.dispatchEvent(new Event('change',{bubbles:true})); "
                                            "el.dispatchEvent(new Event('blur',{bubbles:true})); }",
                                            fill_val,
                                        )
                                    except Exception:
                                        pass
                                    await asyncio.sleep(0.3)
                                    await self._log("success", f"  → Typed '{fill_val}' into '{target}'")
                                    return True
                            except Exception:
                                pass

                        try:
                            await el.click(timeout=3000)
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
                            await el.press_sequentially(str(fill_val), delay=15)
                            typed = True
                        except Exception:
                            pass
                        if not typed:
                            try:
                                # Use the native HTMLInputElement setter so Vue's reactivity
                                # detects the change (plain el.value = v bypasses Vue's proxy).
                                await el.evaluate(
                                    "(el, v) => { "
                                    "const setter = Object.getOwnPropertyDescriptor("
                                    "  (el.tagName==='TEXTAREA'?window.HTMLTextAreaElement:window.HTMLInputElement).prototype, 'value').set; "
                                    "setter.call(el, v); "
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
                                "input[type='number'],input[type='password'],input:not([type]),"
                                "textarea"
                            ).all()
                            for inp in inputs:
                                try:
                                    if await inp.is_visible():
                                        cur_val = await inp.input_value()
                                        if not cur_val:
                                            await inp.click(timeout=3000)
                                            await inp.clear()
                                            await inp.press_sequentially(str(fill_val), delay=15)
                                            try:
                                                await inp.evaluate(
                                                    "e => { e.dispatchEvent(new Event('input',{bubbles:true})); "
                                                    "e.dispatchEvent(new Event('change',{bubbles:true})); "
                                                    "e.dispatchEvent(new Event('blur',{bubbles:true})); }"
                                                )
                                            except Exception:
                                                pass
                                            await self._log("success", f"  → Typed '{fill_val}' (first empty input)")
                                            return True
                                except Exception:
                                    pass
                            # ── Second pass: no visibility check ─────────────────
                            # Vuesax / Vue inputs are often hidden from Playwright's
                            # is_visible() but still exist in the DOM and accept input.
                            for inp in inputs:
                                try:
                                    cur_val = await inp.input_value()
                                    if not cur_val:
                                        # Use native HTMLInputElement setter so Vue's reactivity
                                        # detects the change (plain el.value = v bypasses Vue's proxy).
                                        await inp.evaluate(
                                            "(el, v) => { "
                                            "el.focus(); "
                                            "const setter = Object.getOwnPropertyDescriptor("
                                            "  (el.tagName==='TEXTAREA'?window.HTMLTextAreaElement:window.HTMLInputElement).prototype, 'value').set; "
                                            "setter.call(el, v); "
                                            "el.dispatchEvent(new Event('input',{bubbles:true})); "
                                            "el.dispatchEvent(new Event('change',{bubbles:true})); "
                                            "el.dispatchEvent(new Event('blur',{bubbles:true})); }",
                                            fill_val,
                                        )
                                        await self._log("success", f"  → Typed '{fill_val}' (hidden Vue input)")
                                        return True
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    return False

                # First attempt
                filled = await _do_type()
                if not filled:
                    # SPA may still be rendering — wait up to 45 s and retry
                    await self._log("info", f"  ⏳ Waiting for '{target}' input to appear…")
                    for _ in range(90):
                        await asyncio.sleep(0.5)
                        filled = await _do_type()
                        if filled:
                            break

                if filled:
                    # Give Vue/SPA a rendering tick before capturing the screenshot
                    await asyncio.sleep(0.3)
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
                # Wait 4s for the page to settle before attempting to select
                # (amount-selection pages often render after a short SPA delay)
                await asyncio.sleep(4)
                try:
                    await self._page.wait_for_load_state("networkidle", timeout=4000)
                except Exception:
                    pass
                # target = field label (e.g. "Inventory Type"), value = option to pick (e.g. "ICCID")
                sel_val = value if value else target
                label_hint = target if value else ""
                el = await self._find(target)
                selected = False
                if el:
                    try:
                        await el.select_option(value=sel_val)
                        selected = True
                    except Exception:
                        try:
                            await el.select_option(label=sel_val)
                            selected = True
                        except Exception:
                            pass
                if not selected:
                    # Pass label_hint so JS prefers the <select> next to the right label
                    selected = await self._select_option(sel_val, label_hint=label_hint)
                if not selected:
                    # Portal uses custom amount buttons/cards (not a native <select>).
                    # Try clicking any visible element whose text exactly or partially matches sel_val.
                    pages_before = len(self._context.pages)
                    js_val = sel_val.lower()
                    try:
                        clicked_js = await self._page.evaluate(f"""
                            (val) => {{
                                const all = [...document.querySelectorAll(
                                    'button, [role="button"], [role="option"], [role="radio"], '
                                    + 'li, label, span, div, a'
                                )];
                                const el = all.find(e => e.textContent.trim().toLowerCase() === val)
                                        || all.find(e => e.textContent.trim().toLowerCase().includes(val));
                                if (el) {{ el.scrollIntoView(); el.click(); return true; }}
                                return false;
                            }}
                        """, js_val)
                        if clicked_js:
                            await asyncio.sleep(1)
                            selected = True
                            await self._log("success", f"  → Clicked amount option '{sel_val}' via JS fallback")
                            await self._maybe_switch_new_tab(pages_before)
                            try:
                                await self._page.wait_for_load_state("networkidle", timeout=4000)
                            except Exception:
                                pass
                    except Exception:
                        pass
                if selected:
                    await self._log("success", f"  → Selected '{sel_val}'")
                    await step_shot("ok")
                else:
                    await self._log("error", f"  ✗ STEP FAILED — select option '{sel_val}' not found")
                    await step_shot("FAIL")
                    return False

            elif action == "search":
                fill_val = value if value else target

                async def _do_search() -> bool:
                    # ── Pass 1: semantic search selectors ─────────────────
                    # Note: _find("search") is intentionally NOT used here because it
                    # matches non-input elements like <span class="title">Search…</span>
                    # which crashes .fill(). Only _find_input() guarantees an actual input.
                    el = await self._find_input("search")
                    if el:
                        try:
                            await el.click(timeout=3000)
                        except Exception:
                            pass
                        try:
                            await el.fill(fill_val)
                        except Exception:
                            return False
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
                    # ── Pass 2: broad fallback — first visible text/tel input ──
                    for frame in self._page.frames:
                        try:
                            inputs = await frame.locator(
                                "input[type='text']:visible, input[type='tel']:visible, "
                                "input:not([type]):visible"
                            ).all()
                            for inp in inputs:
                                try:
                                    cur = await inp.input_value()
                                    if cur == "" or cur == fill_val:
                                        try:
                                            await inp.click(timeout=3000)
                                        except Exception:
                                            pass
                                        await asyncio.sleep(0.2)
                                        await inp.fill(fill_val)
                                        await asyncio.sleep(0.3)
                                        await self._page.keyboard.press("Enter")
                                        await asyncio.sleep(1.5)
                                        await self._log("info", f"  → Typed '{fill_val}' in search input")
                                        return True
                                except Exception:
                                    pass
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

                # SPA may need a fresh navigation to reach the correct route after
                # navigating while already authenticated (e.g. COS lands on customer
                # detail instead of subscriber list — search box is not visible).
                if not found:
                    await self._log("info", "  🔄 Search box not found — navigating to base URL")
                    try:
                        # Navigate to the root of the current origin so the SPA
                        # starts at the subscriber list (not the last customer detail).
                        base_url = "/".join(self._page.url.split("/")[:3])
                        await self._page.goto(base_url, wait_until="domcontentloaded", timeout=20000)
                        await self._page.wait_for_load_state("networkidle", timeout=4000)
                        await asyncio.sleep(1)
                        # COS shows a login overlay on every page load — dismiss it.
                        # Pressing Escape reveals the "Login with password" button.
                        await self._page.keyboard.press("Escape")
                        await asyncio.sleep(1)
                        # If still on the login overlay, click "Login with password"
                        # and re-authenticate so the subscriber list is accessible.
                        try:
                            body_lo = (await self._page.inner_text("body")).lower()
                            if "login" in body_lo and not await self._already_authenticated():
                                await self._recover_ms_login(base_url)
                                await asyncio.sleep(2)
                        except Exception:
                            pass
                    except Exception:
                        pass
                    for _ in range(20):   # another 10 s after navigation
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
                # Skip networkidle + skeleton waits when already settled on this URL
                current_url = self._page.url if self._page else ""
                if current_url != self._last_idle_url:
                    try:
                        await self._page.wait_for_load_state("networkidle", timeout=3000)
                    except Exception:
                        pass
                    try:
                        await self._page.wait_for_function(
                            """() => document.querySelectorAll(
                                '[class*="skeleton"], [class*="loading"], [class*="placeholder"], [class*="shimmer"]'
                            ).length === 0""",
                            timeout=2000,
                        )
                    except Exception:
                        pass
                    self._last_idle_url = current_url
                # Named screenshot (e.g. "save as receipt.png")
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
                else:
                    # SS / bare screenshot step — always save as ss_NNN.png so the
                    # PDF reporter can include it regardless of SCREENSHOT_MODE.
                    ss_count = sum(1 for s in self.screenshot_dir.iterdir()
                                   if s.name.startswith("ss_")) if self.screenshot_dir.exists() else 0
                    ss_name  = f"ss_{ss_count + 1:03d}.png"
                    ss_path  = self.screenshot_dir / ss_name
                    try:
                        await self._page.screenshot(
                            path=str(ss_path), full_page=True, animations="disabled"
                        )
                        await self._log("info", f"  📸 SS screenshot saved: {ss_name}", screenshot=ss_name)
                    except Exception:
                        pass
                await step_shot("ok")

            elif action == "verify":
                # Wait 4s for the page to fully settle before verifying
                await asyncio.sleep(4)
                try:
                    await self._page.wait_for_load_state("networkidle", timeout=4000)
                except Exception:
                    pass
                # ── Balance math verification ──────────────────────────────────
                # When the step is about verifying a balance update, do real math
                # instead of a text search that will never match "OLD + TOPUP = NEW".
                _desc_lo = description.lower()
                _is_balance_check = any(
                    w in _desc_lo for w in ("balance", "topup", "top-up", "top up", "topped")
                )
                if _is_balance_check:
                    def _parse_num(s: str) -> Optional[float]:
                        """
                        Parse a balance string that may use European format.
                        Examples:
                          "50,00 kr."  → 50.0
                          "100,00 kr." → 100.0
                          "1.234,56"   → 1234.56
                          "50"         → 50.0
                        """
                        if not s:
                            return None
                        # Strip currency suffix and whitespace
                        s = re.sub(r'\s*(kr\.?|dkk|usd|eur|gbp)\s*', '', s, flags=re.IGNORECASE).strip().rstrip('.')
                        if not s:
                            return None
                        # European format: comma before exactly 2 digits at end → decimal comma
                        if re.search(r',\d{2}$', s):
                            # e.g. "1.234,56" → remove thousand-dot → "1234.56"
                            s = s.replace('.', '').replace(',', '.')
                        else:
                            # Standard or already-dotted decimal — just remove stray commas
                            s = s.replace(',', '')
                        try:
                            return float(s) if s else None
                        except Exception:
                            return None

                    async def _extract_balance_from_page() -> Optional[str]:
                        """Re-read the current page balance (same regex as the extract action)."""
                        try:
                            body = await self._page.inner_text("body")
                            m = re.search(
                                r'(?:Balance|Saldo)\s*[:\s]+([0-9][0-9\s,\.]+\s*(?:kr\.?|DKK)?)',
                                body, re.IGNORECASE,
                            )
                            if m:
                                return re.sub(r'\s+', ' ', m.group(1).strip())
                        except Exception:
                            pass
                        return None

                    old_raw = self._captured_vars.get("OLD_BALANCE", "")
                    new_raw = self._captured_vars.get("NEW_BALANCE", "")

                    # Topup amount: check value field first, then description, then target
                    topup_raw = value
                    if not topup_raw:
                        _amt_m = re.search(
                            r'(?:topup|top[.\-\s]?up|amount)\s*[\-–\s]*(\d+(?:[.,]\d+)?)',
                            description, re.IGNORECASE,
                        )
                        if _amt_m:
                            topup_raw = _amt_m.group(1)
                        else:
                            _nums = re.findall(r'\b(\d+(?:[.,]\d+)?)\b', description)
                            if _nums:
                                topup_raw = _nums[-1]

                    old_num   = _parse_num(old_raw)
                    topup_num = _parse_num(str(topup_raw) if topup_raw else "")

                    # Balance-update retry loop.
                    # On every attempt: reload the page and wait 15s for COS to propagate.
                    # On attempt 2: also re-navigate to the subscriber's detail page so we
                    #   read the correct balance (not a stale home-page value).
                    # Subscriber ID priority (avoids contaminated MISTIN_ID env var):
                    #   1. SUBSCRIBER_EXTERNAL_ID captured this run
                    #   2. ID parsed from the current page URL  (e.g. /customers/299223016)
                    #   3. Short subscriber number extracted from exec_id or current URL
                    async def _best_subscriber_id() -> str:
                        # 1. captured var set during this run (most reliable)
                        sid = self._captured_vars.get("SUBSCRIBER_EXTERNAL_ID", "")
                        if sid:
                            return sid
                        # 2. subscriber ID embedded in the current page URL
                        try:
                            url = self._page.url
                            m = re.search(r'/(?:customers?|subscribers?)/(\d+)', url, re.IGNORECASE)
                            if m:
                                return m.group(1)
                        except Exception:
                            pass
                        # 3. Read subscriber ID from the page body (detail page shows it)
                        try:
                            body = await self._page.inner_text("body")
                            m = re.search(
                                r'(?:External\s+ID|Subscriber\s+ID|MSISDN|Account\s+(?:No\.?|Number))'
                                r'\s*[:\s]+(\d{6,})',
                                body, re.IGNORECASE,
                            )
                            if m:
                                return m.group(1)
                        except Exception:
                            pass
                        return ""

                    if old_num is not None and topup_num is not None:
                        new_num = _parse_num(new_raw)
                        expected = old_num + topup_num

                        # Balance-update retry loop: COS can take 15–30 s to propagate.
                        # Attempt 0: wait 3 s; attempts 1-3: reload page and wait 15 s each.
                        # Attempt 2+: also re-navigate to the subscriber's detail page.
                        _RETRY_WAITS = [3, 15, 15, 15]
                        for _attempt, _wait in enumerate(_RETRY_WAITS):
                            if new_num is not None and abs(new_num - expected) <= 1.0:
                                break
                            await asyncio.sleep(_wait)
                            # Reload the page so we get the server-side committed balance
                            try:
                                await self._page.reload(wait_until="domcontentloaded", timeout=20000)
                                try:
                                    await self._page.wait_for_load_state("networkidle", timeout=5000)
                                except Exception:
                                    pass
                                await asyncio.sleep(2)
                            except Exception:
                                pass
                            # On attempt 2+, re-navigate directly to subscriber detail page
                            if _attempt >= 1:
                                _sid = await _best_subscriber_id()
                                if _sid:
                                    try:
                                        _cur_url = self._page.url
                                        _base = re.sub(r'/customers?/\d+.*', '', _cur_url)
                                        _detail_url = f"{_base}/customers/{_sid}"
                                        await self._page.goto(_detail_url, wait_until="domcontentloaded", timeout=20000)
                                        try:
                                            await self._page.wait_for_load_state("networkidle", timeout=5000)
                                        except Exception:
                                            pass
                                        await asyncio.sleep(2)
                                    except Exception:
                                        pass
                            fresh = await _extract_balance_from_page()
                            if fresh:
                                new_raw = fresh
                                self._captured_vars["NEW_BALANCE"] = fresh
                                new_num = _parse_num(fresh)
                                await self._log("info", f"  📊 Re-captured NEW_BALANCE = {fresh} (attempt {_attempt + 1})")

                        if new_num is not None:
                            if abs(new_num - expected) <= 1.0:
                                await self._log(
                                    "success",
                                    f"  ✓ Balance verified: {old_num} + {topup_num} = {new_num} ✔"
                                )
                                await step_shot("ok")
                                return True
                            else:
                                await self._log(
                                    "error",
                                    f"  ✗ STEP FAILED — Balance mismatch: {old_num} + {topup_num} "
                                    f"≠ {new_num} (expected {expected:.2f})"
                                )
                                await step_shot("FAIL")
                                return False
                    # If we couldn't parse the captured vars, fall through to text search

                # ── Standard text search ───────────────────────────────────────
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
                # ── Phone-number button grid (Vuesax Vue component) ──────────
                # JS el.click() doesn't trigger Vue's selection handler.
                # Strategy: JS finds the phone number text, Playwright native-clicks it.
                if not clicked:
                    phone_text = None
                    try:
                        phone_text = await self._page.evaluate("""
                            () => {
                                const allBtns = [...document.querySelectorAll(
                                    'button, [role="button"], li, div, span, a'
                                )];
                                const phoneBtn = allBtns.find(el => {
                                    const t = el.textContent.trim();
                                    const r = el.getBoundingClientRect();
                                    return /^[\\d\\s]{5,15}$/.test(t) && /\\d{2,}/.test(t)
                                        && r.width > 0 && r.height > 0;
                                });
                                return phoneBtn ? phoneBtn.textContent.trim() : null;
                            }
                        """)
                    except Exception:
                        pass
                    if phone_text:
                        import re as _re
                        try:
                            loc = self._page.get_by_text(
                                _re.compile(_re.escape(phone_text), _re.I), exact=True
                            ).first
                            if await loc.count() > 0:
                                await loc.click(timeout=5000)
                                clicked = True
                                await self._log("success", f"  → Clicked phone number '{phone_text}' (native click)")
                                await self._maybe_switch_new_tab(pages_before)
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
                    for k in ("EXTERNAL", "SUBSCRIBER", "MSISDN", "MISTIN", "ICC")
                )

                val = None
                for _ in range(20):   # 20 × 0.5 s = 10 s max
                    try:
                        body = await self._page.inner_text("body")
                        if is_subscriber_id:
                            # ── Pass 1: label:value pattern (detail pages) ──────
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

                            # ── Pass 2: table column (inventory/search result pages) ──
                            # Finds the column index of "External Id" / "ICCID" / "ICC"
                            # in the table header, then reads the first data row cell.
                            js_val = await self._page.evaluate("""
                                () => {
                                    const COL_KEYWORDS = ['external id','iccid','icc id','sim id','external'];
                                    function normTxt(el) { return el.textContent.trim().toLowerCase(); }
                                    // Try every table on the page
                                    for (const tbl of document.querySelectorAll('table')) {
                                        const headers = [...tbl.querySelectorAll('th')];
                                        let colIdx = -1;
                                        for (let i = 0; i < headers.length; i++) {
                                            const t = normTxt(headers[i]);
                                            if (COL_KEYWORDS.some(k => t.includes(k))) {
                                                colIdx = i; break;
                                            }
                                        }
                                        if (colIdx < 0) continue;
                                        // First data row in that column
                                        const rows = tbl.querySelectorAll('tbody tr');
                                        for (const row of rows) {
                                            const cells = row.querySelectorAll('td');
                                            const cell = cells[colIdx];
                                            if (!cell) continue;
                                            const txt = cell.textContent.trim().replace(/\\s+/g, '');
                                            if (/^\\d{8,}$/.test(txt)) return txt;
                                        }
                                    }
                                    return null;
                                }
                            """)
                            if js_val:
                                val = str(js_val).strip()
                                break
                        else:
                            is_data_target = any(
                                k in target.upper() for k in ("DATA", "GB", "MB")
                            )
                            if is_data_target:
                                # Extract Extra Data / data addon amount (GB or MB)
                                data_m = re.search(
                                    r'(?:Extra\s+Data|Data\s+Add(?:on)?|Data\s+Balance|Data)\s*[:\s]+'
                                    r'([0-9][0-9\s\.,]*\s*(?:GB|MB|TB)?)',
                                    body, re.IGNORECASE,
                                )
                                if data_m:
                                    val = re.sub(r'\s+', ' ', data_m.group(1).strip())
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
                    if is_subscriber_id:
                        # Store the current subscriber page URL for reliable re-navigation later
                        try:
                            self._captured_vars["SUBSCRIBER_PAGE_URL"] = self._page.url
                        except Exception:
                            pass
                else:
                    if is_subscriber_id:
                        # ICC_ID must come from the page — phone/MSISDN vars are wrong fallbacks
                        if "ICC" in target.upper():
                            fallback = os.environ.get("ICC_ID") or ""
                        else:
                            fallback = (
                                os.environ.get("MISTIN_ID")
                                or os.environ.get("PHONE_NUMBER")
                                or ""
                            )
                        if fallback:
                            self._captured_vars[target] = fallback
                            await self._log(
                                "info",
                                f"  ⚠ {target} not found on page — using env fallback: {fallback}",
                            )
                        else:
                            await self._log("info", f"  ⚠ Could not find external ID on page after 10s")
                    else:
                        is_data_target = any(k in target.upper() for k in ("DATA", "GB", "MB"))
                        if is_data_target:
                            await self._log("info", f"  ⚠ Could not find Extra Data amount on page after 10s")
                        else:
                            await self._log("info", f"  ⚠ Could not find balance on page after 10s")
                await step_shot("ok")

            elif action == "click_existing_contact":
                # The "Select contact" dropdown is open. Strategy:
                # 1. JS finds the contact name (text immediately after "Create contact")
                # 2. Playwright native click on the LAST element with that text
                #    (Vuesax appends the dropdown panel to the END of the DOM body,
                #     so .last hits the dropdown option rather than the sidebar entry)
                # 3. Fallback: keyboard ArrowDown × N + Enter
                clicked = False
                contact_name = None

                # Step 1 — find the contact name via JS (don't click yet)
                for frame in self._page.frames:
                    try:
                        contact_name = await frame.evaluate("""
                            () => {
                                const all = [...document.querySelectorAll(
                                    'li, [role="option"], div, span, a'
                                )].filter(el => {
                                    const t = el.textContent.trim();
                                    const r = el.getBoundingClientRect();
                                    return t.length > 0 && t.length < 100
                                        && r.width > 0 && r.height > 0;
                                });
                                let afterCreate = false;
                                for (const el of all) {
                                    const t = el.textContent.trim();
                                    if (t.toLowerCase() === 'create contact') {
                                        afterCreate = true;
                                        continue;
                                    }
                                    if (afterCreate && t.length > 2
                                            && !t.toLowerCase().startsWith('create')
                                            && /[A-Za-zÀ-ɏ]/.test(t)) {
                                        return t;
                                    }
                                }
                                return null;
                            }
                        """)
                        if contact_name:
                            break
                    except Exception:
                        pass

                # Step 2 — Playwright native click on the contact name
                if contact_name:
                    import re as _re
                    for frame in self._page.frames:
                        try:
                            # .last targets the dropdown panel (appended last in DOM)
                            loc = frame.get_by_text(
                                _re.compile(_re.escape(contact_name.strip()), _re.I)
                            ).last
                            if await loc.count() > 0:
                                await loc.click(timeout=5000)
                                await self._log("success", f"  → Selected contact: '{contact_name}'")
                                clicked = True
                                break
                        except Exception:
                            pass

                # Step 3 — keyboard fallback: ArrowDown past "Create contact", Enter
                if not clicked:
                    try:
                        await self._page.keyboard.press("ArrowDown")
                        await asyncio.sleep(0.3)
                        await self._page.keyboard.press("ArrowDown")
                        await asyncio.sleep(0.3)
                        await self._page.keyboard.press("Enter")
                        await asyncio.sleep(0.5)
                        name = contact_name or "contact"
                        await self._log("success", f"  → Selected contact via keyboard: '{name}'")
                        clicked = True
                    except Exception:
                        pass

                if clicked:
                    await asyncio.sleep(1.5)
                    try:
                        await self._page.wait_for_load_state("networkidle", timeout=4000)
                    except Exception:
                        pass
                    await step_shot("ok")
                else:
                    await self._log("error", f"  ✗ STEP FAILED — no existing contact found in dropdown")
                    await step_shot("FAIL")
                    return False

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
    async def _run_steps(self, steps: list) -> dict:
        """Run steps against self._context / self._page (already set up)."""
        completed  = 0
        failed: list = []
        self._running = True

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
                    break
        finally:
            self._running = False
            if live_task:
                live_task.cancel()
                try:
                    await live_task
                except asyncio.CancelledError:
                    pass

        if self._screenshot_mode not in ("none", "named_only"):
            shot = await self._screenshot("final")
            if shot:
                await self._log("info", "Final state captured", screenshot=shot)

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
        }

    async def _execute(self, plan: dict) -> dict:
        """Playwright session — must run in ProactorEventLoop on Windows."""
        steps = plan.get("steps", [])
        expected_outcome = plan.get("expected_outcome", "")

        def _wrap(result: dict) -> dict:
            result["summary"] = (
                expected_outcome if result["status"] == "success"
                else (result.get("stop_reason") or f"{result['steps_completed']}/{result['steps_total']} steps completed")
            )
            return result

        # ── Shared browser path: reuse session context or create new one ──────────
        if self._shared_browser:
            self._browser = self._shared_browser
            context_alive = False
            if self._shared_context:
                try:
                    _ = self._shared_context.pages   # raises if context is closed
                    context_alive = True
                except Exception:
                    pass
            if context_alive:
                # Reuse existing context — login session stays alive, skip re-login
                self._context = self._shared_context
                # Close leftover pages from the previous run
                for old_pg in list(self._context.pages):
                    try:
                        await old_pg.close()
                    except Exception:
                        pass
                self._page = await self._context.new_page()
                # Pre-mark known domains as authenticated so login steps are skipped
                for env_key in ("COS_URL", "PORTAL_URL", "MSITCOS_URL"):
                    url = os.environ.get(env_key, "")
                    if url:
                        try:
                            from urllib.parse import urlparse as _up
                            self._authenticated_domains.add(_up(url).netloc)
                        except Exception:
                            pass
                await self._log("info", f"🔄 Session reused — {len(steps)} steps (login skipped)")
            else:
                self._context = await self._shared_browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                    ),
                    ignore_https_errors=True,
                )
                self._page = await self._context.new_page()
                await self._log("info", f"🚀 Browser context ready — {len(steps)} steps")
            result = await self._run_steps(steps)
            try:
                await self._page.close()   # close page but keep context + session alive
            except Exception:
                pass
            return _wrap(result)

        # ── Own browser path: existing behavior ─────────────────────────────────
        async with async_playwright() as pw:
            self._pw = pw
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
                        # Parallel-run stability: prevent background throttling and
                        # reduce per-instance memory pressure when 7+ browsers run together.
                        "--disable-background-timer-throttling",
                        "--disable-renderer-backgrounding",
                        "--disable-backgrounding-occluded-windows",
                        "--no-first-run",
                        "--disable-default-apps",
                        "--ignore-certificate-errors",
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
            result = await self._run_steps(steps)
            try:
                await self._browser.close()
            except Exception:
                pass

        return _wrap(result)

    # ── Public entry point ────────────────────────────────────────────────────
    async def run(self, plan: dict) -> dict:
        """
        On Windows: Playwright needs ProactorEventLoop for subprocess support.
        We spin up a dedicated thread with its own ProactorEventLoop and dispatch
        all log/frame callbacks back to the caller's loop via run_coroutine_threadsafe.
        When already_in_proactor_loop=True (bulk sequential runner) we skip the
        thread spawn because the caller already runs inside a ProactorEventLoop.
        """
        if sys.platform == "win32" and not self._already_in_proactor_loop:
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
        try:
            while t.is_alive():
                await asyncio.sleep(0.3)
        except asyncio.CancelledError:
            t.join()
            raise
        t.join()

        if error_box:
            raise error_box[0]

        return result_box[0] if result_box else {
            "status": "failed", "steps_completed": 0, "steps_total": 0,
            "failed_steps": [], "success_rate": 0,
        }
