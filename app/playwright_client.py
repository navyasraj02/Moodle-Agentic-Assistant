import os
import time
import re
from urllib.parse import urljoin, urlparse, parse_qs
from datetime import datetime
from dateutil import parser as dtparser
from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError
from .config import (
    MOODLE_URL, STUDENT_USERNAME, STUDENT_PASSWORD,
    HEADLESS, TIMEOUT_MS, STORAGE_STATE_PATH, SCREENSHOT_DIR, COURSE_NAME,
)

def _ts() -> str:
    return time.strftime("%Y%m%d-%H%M%S")

def _clean_title(title: str) -> str:
    title = " ".join(title.splitlines()).strip()
    title = re.sub(r"\s+Assignment\s*$", "", title, flags=re.I).strip()
    return title

def _extract_due_date_from_block(text: str) -> str | None:
    text = " ".join(text.splitlines()).strip()

    # Example: "Due: Saturday, 28 February 2026, 12:00 AM"
    m = re.search(
        r"\bDue:\s*([A-Za-z]+,\s*\d{1,2}\s+[A-Za-z]+\s+\d{4},\s*\d{1,2}:\d{2}\s*(?:AM|PM))",
        text,
    )
    if m:
        return m.group(1).strip()

    # fallback
    m2 = re.search(r"\bDue:\s*(.+)$", text)
    if not m2:
        return None

    tail = m2.group(1).strip()
    tail = re.split(r"\s{2,}(?:Add submission|Submission status|Grading status|Time remaining)\b", tail)[0].strip()
    return tail or None

def _status_from_due(due_str: str | None) -> str:
    if not due_str:
        return "open"
    try:
        due_dt = dtparser.parse(due_str, fuzzy=True)
        now = datetime.now(due_dt.tzinfo)  # tz-aware compare if tz exists
        return "closed" if due_dt < now else "open"
    except Exception:
        # If parsing fails, don't block scanning
        return "open"

def _extract_assignment_id(link: str) -> int | None:
    try:
        parsed = urlparse(link)
        qs = parse_qs(parsed.query)
        if "id" in qs and qs["id"]:
            return int(qs["id"][0])
    except Exception:
        return None
    return None

async def _click_course_from_my_courses(page, course_name: str):
    """
    Robustly click a course from /my/courses.php.
    Handles dynamic DOM refreshes during search/filtering.
    """
    course_links = page.locator('a[href*="/course/view.php"]')

    # 1. Wait for the initial load
    await course_links.first.wait_for(state="attached", timeout=TIMEOUT_MS)

    # 2. Filtering Logic (Matches your search interaction)
    if course_name:
        # We use a loop to retry if the element detaches during the process
        for _ in range(3): 
            try:
                matched = course_links.filter(has_text=course_name).first
                if await matched.count() > 0:
                    # check visibility AND attachment in one go
                    await matched.wait_for(state="visible", timeout=2000)
                    await matched.scroll_into_view_if_needed()
                    await matched.click()
                    return
            except Exception:
                await page.wait_for_timeout(500) # Short breather for DOM to settle
                continue

    # 3. Fallback: Click the first available course if search/filter is finicky
    count = await course_links.count()
    for i in range(min(count, 5)):
        try:
            cand = course_links.nth(i)
            # Crucial: Check if it's still attached before scrolling
            if await cand.is_visible():
                await cand.scroll_into_view_if_needed()
                await cand.click()
                return
        except Exception:
            # If this specific index detached, move to the next one
            continue

    # Final attempt: direct click on the first link found
    await course_links.first.click()

async def _screenshot(page, name: str):
    path = os.path.join(SCREENSHOT_DIR, f"{_ts()}-{name}.png")
    await page.screenshot(path=path, full_page=True)
    return path

async def ensure_student_session() -> None:
    """
    Ensure we have a VALID logged-in session stored in STORAGE_STATE_PATH.
    If stored session exists but is expired (redirects to login), re-login and overwrite it.
    """

    async def _is_login_page(page) -> bool:
        # Moodle login page typically has username/password inputs
        if await page.locator("input#username").count() > 0:
            return True
        if await page.locator("input#password").count() > 0:
            return True
        # Also handle the "session timed out" banner
        body = ""
        try:
            body = (await page.inner_text("body"))[:2000].lower()
        except Exception:
            pass
        return "log in" in body and "password" in body

    async def _login_and_save(context, page) -> None:
        await page.goto(MOODLE_URL, wait_until="domcontentloaded")

        # In some themes, there is a "Log in" link; in others you may already be on login page
        login_link = page.get_by_role("link", name=re.compile(r"log in", re.I))
        if await login_link.count() > 0:
            await login_link.first.click()

        await page.locator("input#username").fill(STUDENT_USERNAME)
        await page.locator("input#password").fill(STUDENT_PASSWORD)
        await page.get_by_role("button", name=re.compile(r"log in", re.I)).click()

        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(800)

        # Save fresh session
        await context.storage_state(path=STORAGE_STATE_PATH)

    if not STUDENT_USERNAME or not STUDENT_PASSWORD:
        raise RuntimeError("Missing STUDENT_USERNAME / STUDENT_PASSWORD in .env")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)

        # 1) If we have a stored state, validate it
        if os.path.exists(STORAGE_STATE_PATH):
            context = await browser.new_context(storage_state=STORAGE_STATE_PATH)
            page = await context.new_page()
            page.set_default_timeout(TIMEOUT_MS)

            try:
                # Go to a page that requires login
                test_url = urljoin(MOODLE_URL, "/my/")
                await page.goto(test_url, wait_until="domcontentloaded")
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(500)

                # If redirected to login → session expired
                if await _is_login_page(page):
                    # session dead -> recreate
                    await context.close()
                    os.remove(STORAGE_STATE_PATH)

                else:
                    # session valid
                    await context.close()
                    await browser.close()
                    return

            except Exception:
                # any weirdness -> force re-login
                try:
                    await context.close()
                except Exception:
                    pass
                try:
                    os.remove(STORAGE_STATE_PATH)
                except Exception:
                    pass

        # 2) No stored state (or it was invalid) -> login fresh
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(TIMEOUT_MS)

        try:
            await _login_and_save(context, page)
        except PWTimeoutError:
            await _screenshot(page, "login-timeout")
            raise
        except Exception:
            await _screenshot(page, "login-error")
            raise
        finally:
            await context.close()
            await browser.close()

async def scan_assignments() -> dict:
    """
    Open Moodle as logged-in student, navigate to course, and return assignment list.
    Extract due dates from course page when available and compute open/closed status.
    """
    await ensure_student_session()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(storage_state=STORAGE_STATE_PATH)
        page = await context.new_page()
        page.set_default_timeout(TIMEOUT_MS)

        try:
            # 1) Go to My courses
            my_courses_url = urljoin(MOODLE_URL, "/my/courses.php")
            await page.goto(my_courses_url, wait_until="domcontentloaded")

            # Wait for async UI to finish loading
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(800)

            # 2) Filter via search (works even if visible title != COURSE_NAME)
            search_box = page.get_by_role("textbox", name=re.compile("search", re.I))
            if await search_box.count() > 0:
                await search_box.fill(COURSE_NAME)
                await page.wait_for_timeout(800)

            # 3) Click the course robustly (no fragile div.card)
            await _click_course_from_my_courses(page, COURSE_NAME)

            # 4) Prefer scraping from main content first (usually has Due:)
            main = page.locator("#region-main")
            assign_links_main = main.locator('a[href*="/mod/assign/view.php"]')
            await assign_links_main.first.wait_for(timeout=TIMEOUT_MS)

            count_main = await assign_links_main.count()
            best = {}  # link -> item

            for i in range(count_main):
                a = assign_links_main.nth(i)

                title_raw = (await a.inner_text()).strip()
                title = _clean_title(title_raw)

                href = await a.get_attribute("href")
                if not href or not title:
                    continue

                link = urljoin(MOODLE_URL, href)

                # ---- robust: find nearby text that contains "Due:" ----
                due_date = None
                block_text = None

                candidates = [
                    a.locator("xpath=ancestor::li[1]"),
                    a.locator("xpath=ancestor::*[@role='listitem'][1]"),
                    a.locator("xpath=ancestor::div[1]"),
                ]

                for cand in candidates:
                    if await cand.count() > 0:
                        txt = await cand.first.inner_text()
                        if "Due:" in txt:
                            block_text = txt
                            break

                if not block_text:
                    # fallback: climb up to find any ancestor containing "Due:"
                    for level in range(1, 12):
                        anc = a.locator(f"xpath=ancestor::*[{level}]")
                        if await anc.count() == 0:
                            continue
                        txt = await anc.first.inner_text()
                        if "Due:" in txt:
                            block_text = txt
                            break

                if block_text:
                    due_date = _extract_due_date_from_block(block_text)

                status = _status_from_due(due_date)

                assignment_id = _extract_assignment_id(link) or 0

                best[link] = {
                    "assignment_id": assignment_id,
                    "title": title,
                    "due_date": due_date,
                    "link": link,
                    "status": status,
                }

            # 5) Fallback: scan anywhere else for missing ones (left nav etc.)
            assign_links_all = page.locator('a[href*="/mod/assign/view.php"]')
            count_all = await assign_links_all.count()

            for i in range(count_all):
                a = assign_links_all.nth(i)

                title_raw = (await a.inner_text()).strip()
                title = _clean_title(title_raw)

                href = await a.get_attribute("href")
                if not href or not title:
                    continue

                link = urljoin(MOODLE_URL, href)

                if link in best:
                    continue

                assignment_id = _extract_assignment_id(link) or 0

                best[link] = {
                    "assignment_id": assignment_id,
                    "title": title,
                    "due_date": None,
                    "link": link,
                    "status": "open",
                }

            assignments = list(best.values())
            return {"course": COURSE_NAME, "count": len(assignments), "assignments": assignments}

        except PWTimeoutError:
            await _screenshot(page, "scan-timeout")
            raise
        except Exception:
            await _screenshot(page, "scan-error")
            raise
        finally:
            await context.close()
            await browser.close()

def _detect_submission_type(page_text: str) -> str:
    """Heuristic detection based on Moodle assignment plugin labels."""
    t = page_text.lower()
    has_file = ("file submissions" in t) or ("file submission" in t) or ("upload a file" in t)
    has_text = ("online text" in t) or ("online text submissions" in t) or ("online text submission" in t)

    if has_file and has_text:
        return "both"
    if has_file:
        return "file"
    if has_text:
        return "text"
    return "unknown"

async def _extract_instructions(page) -> str:
    """
    Extract only true assignment description/instructions.
    Avoid returning the entire page status table.
    """
    candidates = [
        "#intro",
        "#region-main .activity-description",
        "#region-main .intro",
    ]

    for sel in candidates:
        loc = page.locator(sel)
        if await loc.count() > 0:
            txt = (await loc.first.inner_text()).strip()
            if txt:
                return "\n".join([line.rstrip() for line in txt.splitlines()]).strip()

    return ""  # important: don't fallback to #region-main

def _extract_submission_status(page_text: str) -> str | None:
    """Extract a short 'Submission status' value when present."""
    m = re.search(r"Submission\s+status\s*\n\s*([^\n]+)", page_text, flags=re.I)
    if m:
        return m.group(1).strip()
    return None

async def read_assignment(assignment_link: str) -> dict:
    """Open a specific assignment page and extract instructions + submission metadata."""
    await ensure_student_session()

    if not assignment_link:
        raise ValueError("assignment_link is required")

    link = urljoin(MOODLE_URL, assignment_link)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(storage_state=STORAGE_STATE_PATH)
        page = await context.new_page()
        page.set_default_timeout(TIMEOUT_MS)

        try:
            # 1) Open assignment page
            await page.goto(link, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(400)

            # 2) Title
            title = None
            title_loc = page.locator("#page-header h1")
            if await title_loc.count() > 0:
                title = (await title_loc.first.inner_text()).strip()
            if not title:
                title = (await page.title()).strip()

            # 3) Main text (for due date + status + submission status)
            main = page.locator("#region-main")
            main_text = await (main.first.inner_text() if await main.count() > 0 else page.inner_text("body"))

            due_date = _extract_due_date_from_block(main_text)
            status = _status_from_due(due_date)

            submission_status = _extract_submission_status(main_text)

            # 4) Instructions (strict)
            instructions = await _extract_instructions(page)  # may be ""

            # 5) Can submit? (button or link)
            add_btn = page.get_by_role("button", name=re.compile(r"add submission|edit submission", re.I))
            add_link = page.get_by_role("link", name=re.compile(r"add submission|edit submission", re.I))
            can_submit = (
                (await add_btn.count() > 0 and await add_btn.first.is_visible()) or
                (await add_link.count() > 0 and await add_link.first.is_visible())
            )

            # 6) Detect submission type by opening submission form (no saving)
            submission_type = "unknown"
            if can_submit:
                moved = await _open_submission_form_if_possible(page)
                if moved:
                    submission_type = await _detect_submission_type_on_submission_page(page)

            assignment_id = _extract_assignment_id(link) or 0

            return {
                "assignment_id": assignment_id,
                "title": _clean_title(title),
                "link": link,
                "due_date": due_date,
                "status": status,
                "submission_type": submission_type,
                "instructions": instructions,  # strict (no noisy fallback)
                "can_submit": can_submit,
                "submission_status": submission_status,
            }

        except PWTimeoutError:
            await _screenshot(page, "read-timeout")
            raise
        except Exception:
            await _screenshot(page, "read-error")
            raise
        finally:
            await context.close()
            await browser.close()

async def read_assignment_by_id(assignment_id: int) -> dict:
    """Build link from id and reuse read_assignment()."""
    if assignment_id <= 0:
        raise ValueError("assignment_id must be a positive integer")

    link = urljoin(MOODLE_URL, f"/mod/assign/view.php?id={assignment_id}")
    return await read_assignment(link)

async def _open_submission_form_if_possible(page) -> bool:
    """
    Click Add submission / Edit submission if present.
    Returns True if navigation to submission form likely happened.
    """
    # Moodle sometimes uses a button, sometimes a link
    candidates = [
        page.get_by_role("button", name=re.compile(r"add submission|edit submission", re.I)),
        page.get_by_role("link", name=re.compile(r"add submission|edit submission", re.I)),
    ]

    for c in candidates:
        if await c.count() > 0 and await c.first.is_visible():
            await c.first.click()
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(400)
            return True
    return False


async def _detect_submission_type_on_submission_page(page) -> str:
    """
    Detect submission type from the submission form page:
    - File submissions: file manager / draftfilemanager element exists
    - Online text: textarea/editor exists
    """
    # FILE: Moodle filepicker / filemanager
    file_manager = page.locator(
        'div.filemanager, div.fp-repo, div[data-fieldtype="filemanager"], .filemanager-container, .dndupload-message'
    )

    # TEXT: Moodle online text editor (TinyMCE usually)
    # Depending on Moodle, it can be textarea[name="onlinetext[text]"] or an iframe editor
    online_text_area = page.locator('textarea[name*="onlinetext"]')
    tinymce = page.locator('div.tox.tox-tinymce, iframe[id*="tiny"]')

    has_file = await file_manager.count() > 0
    has_text = (await online_text_area.count() > 0) or (await tinymce.count() > 0)

    if has_file and has_text:
        return "both"
    if has_file:
        return "file"
    if has_text:
        return "text"
    return "unknown"