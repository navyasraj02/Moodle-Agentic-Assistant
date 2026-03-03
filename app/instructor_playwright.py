"""
Playwright automation for Moodle instructor actions.

Provides two public async functions used by the FastAPI endpoints:
  - ensure_instructor_session()  → validates / refreshes the instructor login
  - create_assignment(...)       → creates a new assignment in the course
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse, parse_qs

from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError

from .config import (
    MOODLE_URL,
    INSTRUCTOR_USERNAME,
    INSTRUCTOR_PASSWORD,
    HEADLESS,
    TIMEOUT_MS,
    INSTRUCTOR_STORAGE_STATE_PATH,
    SCREENSHOT_DIR,
    COURSE_NAME,
)


# ── Helpers ────────────────────────────────────────────────────────

def _ts() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


async def _screenshot(page, name: str) -> str:
    path = os.path.join(SCREENSHOT_DIR, f"{_ts()}-instructor-{name}.png")
    await page.screenshot(path=path, full_page=True)
    return path


def _is_login_page_sync(html: str) -> bool:
    lower = html[:3000].lower()
    return "log in" in lower and "password" in lower


# ── Session management ─────────────────────────────────────────────

async def ensure_instructor_session() -> None:
    """
    Ensure a valid logged-in instructor session is stored.
    Re-authenticates automatically if the stored session has expired.
    """
    if not INSTRUCTOR_USERNAME or not INSTRUCTOR_PASSWORD:
        raise RuntimeError("INSTRUCTOR_USERNAME / INSTRUCTOR_PASSWORD not set in .env")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)

        # ── Validate existing stored state ───────────────────────────
        if os.path.exists(INSTRUCTOR_STORAGE_STATE_PATH):
            ctx = await browser.new_context(storage_state=INSTRUCTOR_STORAGE_STATE_PATH)
            page = await ctx.new_page()
            page.set_default_timeout(TIMEOUT_MS)
            try:
                await page.goto(urljoin(MOODLE_URL, "/my/"), wait_until="domcontentloaded")
                await page.wait_for_load_state("networkidle")
                body = await page.inner_text("body")
                if not _is_login_page_sync(body):
                    # Session still valid
                    await ctx.close()
                    await browser.close()
                    return
            except Exception:
                pass
            finally:
                try:
                    await ctx.close()
                except Exception:
                    pass
            # Session expired — remove stale state
            try:
                os.remove(INSTRUCTOR_STORAGE_STATE_PATH)
            except Exception:
                pass

        # ── Fresh login ───────────────────────────────────────────────
        ctx = await browser.new_context()
        page = await ctx.new_page()
        page.set_default_timeout(TIMEOUT_MS)
        try:
            await page.goto(MOODLE_URL, wait_until="domcontentloaded")

            login_link = page.get_by_role("link", name=re.compile(r"log in", re.I))
            if await login_link.count() > 0:
                await login_link.first.click()

            await page.locator("input#username").fill(INSTRUCTOR_USERNAME)
            await page.locator("input#password").fill(INSTRUCTOR_PASSWORD)
            await page.get_by_role("button", name=re.compile(r"log in", re.I)).click()

            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(800)

            await ctx.storage_state(path=INSTRUCTOR_STORAGE_STATE_PATH)
        except PWTimeoutError:
            await _screenshot(page, "login-timeout")
            raise
        except Exception:
            await _screenshot(page, "login-error")
            raise
        finally:
            await ctx.close()
            await browser.close()


# ── Course navigation ──────────────────────────────────────────────

async def _get_course_id(page) -> int:
    """Navigate to the configured course and return its Moodle course ID."""
    await page.goto(urljoin(MOODLE_URL, "/my/courses.php"), wait_until="domcontentloaded")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(600)

    # Filter by course name in the search box
    search = page.get_by_role("textbox", name=re.compile("search", re.I))
    if await search.count() > 0:
        await search.fill(COURSE_NAME)
        await page.wait_for_timeout(700)

    # Click matching course link
    links = page.locator('a[href*="/course/view.php"]')
    await links.first.wait_for(state="attached", timeout=TIMEOUT_MS)

    matched = links.filter(has_text=COURSE_NAME).first
    if await matched.count() > 0:
        await matched.wait_for(state="visible", timeout=4000)
        await matched.click()
    else:
        await links.first.click()

    await page.wait_for_load_state("networkidle")

    qs = parse_qs(urlparse(page.url).query)
    if "id" in qs:
        return int(qs["id"][0])
    raise RuntimeError(f"Could not extract course ID from URL: {page.url}")


# ── Form helpers ───────────────────────────────────────────────────

async def _fill_description(page, text: str) -> None:
    """Fill the assignment Description field across TinyMCE / Atto / raw textarea."""
    await page.wait_for_timeout(1200)

    # TinyMCE iframe (Moodle 4.x default)
    iframe = page.locator('iframe[id*="_ifr"], iframe.tox-edit-area__iframe')
    if await iframe.count() > 0:
        body = page.frame_locator('iframe[id*="_ifr"], iframe.tox-edit-area__iframe').first.locator("body")
        await body.wait_for(state="attached", timeout=8000)
        await body.click()
        await body.fill(text)
        return

    # Atto contenteditable div
    atto = page.locator('div.editor_atto_content[contenteditable="true"]')
    if await atto.count() > 0:
        await atto.first.click()
        await atto.first.fill(text)
        return

    # Raw textarea fallback
    ta = page.locator('#id_introeditor, textarea[name="introeditor[text]"]')
    if await ta.count() > 0:
        await ta.first.evaluate("(el, v) => { el.value = v; }", text)
        return

    raise RuntimeError("Could not locate the description editor on the assignment form.")


async def _set_due_date(page, due: datetime) -> None:
    """Enable and populate the Moodle due-date selector widgets."""
    chk = page.locator("#id_duedate_enabled")
    if await chk.count() > 0 and not await chk.is_checked():
        await chk.check()
        await page.wait_for_timeout(300)

    await page.select_option("#id_duedate_day",    str(due.day))
    await page.select_option("#id_duedate_month",  str(due.month))
    await page.select_option("#id_duedate_year",   str(due.year))
    await page.select_option("#id_duedate_hour",   str(due.hour))
    # Moodle minute selects are in 5-min steps
    await page.select_option("#id_duedate_minute", str((due.minute // 5) * 5))


async def _configure_submission_types(page) -> None:
    """Select Online text only; deselect File submissions."""
    # Expand all collapsed sections so checkboxes are accessible
    expand = page.get_by_role("link", name=re.compile(r"expand all", re.I))
    if await expand.count() > 0:
        await expand.click()
        await page.wait_for_timeout(500)

    online = page.locator("#id_assignsubmission_onlinetext_enabled")
    if await online.count() > 0 and not await online.is_checked():
        await online.check()

    file_sub = page.locator("#id_assignsubmission_file_enabled")
    if await file_sub.count() > 0 and await file_sub.is_checked():
        await file_sub.uncheck()


async def _disable_grading_due_date(page) -> None:
    """
    Uncheck the 'Remind me to grade by' date.
    Moodle pre-fills this to a date before the due date which triggers a
    validation error ('Remind me to grade by cannot be earlier than due date').
    Disabling it avoids the error without affecting assignment behaviour.
    """
    chk = page.locator("#id_gradingduedate_enabled")
    if await chk.count() > 0 and await chk.is_checked():
        await chk.uncheck()
        await page.wait_for_timeout(200)


# ── Public API ─────────────────────────────────────────────────────

async def create_assignment(title: str, description: str, due_date: datetime) -> dict:
    """
    Create a new assignment in the configured Moodle course.

    Params:
        title       – Assignment name shown to students
        description – Instructions / description visible to students
        due_date    – Python datetime for the submission deadline

    Returns a dict: { status, msg, course_id }
    """
    await ensure_instructor_session()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        ctx = await browser.new_context(storage_state=INSTRUCTOR_STORAGE_STATE_PATH)
        page = await ctx.new_page()
        page.set_default_timeout(TIMEOUT_MS)

        try:
            # 1. Navigate to course → get course ID
            course_id = await _get_course_id(page)

            # 2. Open the Add Assignment form directly
            form_url = urljoin(
                MOODLE_URL,
                f"/course/modedit.php?add=assign&course={course_id}&section=0&return=0&sr=0",
            )
            await page.goto(form_url, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(400)

            # 3. Assignment name
            await page.locator("#id_name").fill(title)

            # 4. Description
            await _fill_description(page, description)

            # 5. Due date
            await _set_due_date(page, due_date)

            # 6. Submission type → Online text only
            await _configure_submission_types(page)

            # 7. Disable 'Remind me to grade by' — Moodle pre-fills it to a date
            #    before the due date, which causes a validation error on save.
            await _disable_grading_due_date(page)

            # 8. Save the form
            # Moodle renders save buttons as <input type="submit"> with known name attrs.
            # Priority: submitbutton = "Save and return to course"
            #           submitbutton2 = "Save and display"
            save_sel = (
                'input[type="submit"][name="submitbutton"], '
                'input[type="submit"][name="submitbutton2"]'
            )
            save_btn = page.locator(save_sel).first
            await save_btn.wait_for(state="visible", timeout=TIMEOUT_MS)
            await save_btn.scroll_into_view_if_needed()
            await save_btn.click()

            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(800)

            screenshot_path = await _screenshot(page, "assignment-created")

            # Confirm we navigated away from the edit form
            if "modedit.php" in page.url:
                # Extract Moodle's validation error message to help diagnose
                error_msg = ""
                try:
                    err_loc = page.locator(".alert-danger, .error, #id_error_name, .form-control-feedback")
                    if await err_loc.count() > 0:
                        error_msg = " | ".join([
                            (await err_loc.nth(i).inner_text()).strip()
                            for i in range(min(await err_loc.count(), 5))
                            if (await err_loc.nth(i).inner_text()).strip()
                        ])
                except Exception:
                    pass
                detail = f" Moodle said: {error_msg}" if error_msg else ""
                raise RuntimeError(
                    f"Still on the assignment edit form after clicking Save.{detail}"
                )

            return {
                "status": "success",
                "msg": f"Assignment '{title}' created successfully.",
                "course": COURSE_NAME,
                "course_id": course_id,
                "screenshot": screenshot_path,
            }

        except PWTimeoutError:
            await _screenshot(page, "create-timeout")
            raise
        except Exception:
            await _screenshot(page, "create-error")
            raise
        finally:
            await ctx.close()
            await browser.close()
