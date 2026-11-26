"""
The interface in a real browser (Chrome driven by Playwright).

Skipped automatically unless `playwright` and a Chrome/Chromium are installed:
    pip install playwright      (and have Google Chrome installed)

Set UI_SCREENSHOTS=/some/folder to save screenshots while it runs.
"""

import os
import shutil
import threading

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")

from app.ui import server as ui_server  # noqa: E402
from tests.test_discovery import FakeWeb  # noqa: E402

CHROME = (
    os.environ.get("CHROME_PATH")
    or shutil.which("google-chrome")
    or shutil.which("chromium")
    or shutil.which("chromium-browser")
)

pytestmark = pytest.mark.skipif(not CHROME, reason="needs Google Chrome or Chromium")

SHOTS = os.environ.get("UI_SCREENSHOTS")


@pytest.fixture
def app_url(monkeypatch):
    fake = FakeWeb()

    monkeypatch.setattr("app.workflows.discovery.search_web", fake.search)
    monkeypatch.setattr("app.workflows.discovery.fetch_headings", fake.headings)
    monkeypatch.setattr("app.workflows.discovery.evidence_ok", lambda *a, **k: (True, ""))

    srv = ui_server.create_server(port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    yield f"http://127.0.0.1:{srv.server_address[1]}/"

    srv.shutdown()
    srv.server_close()


@pytest.fixture
def page(world):
    with playwright_sync.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()

        problems = []
        page.on("pageerror", lambda error: problems.append(str(error)))
        page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)

        page.set_default_timeout(45000)
        page.problems = problems  # a test that provokes errors on purpose may clear these

        yield page

        assert problems == [], problems

        browser.close()


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=False)


def test_find_swap_read_and_annotate(page, app_url):
    page.goto(app_url)

    # header status comes from the (faked) model
    page.wait_for_selector("#chip-llm .label:has-text('Ollama ·')")
    shot(page, "1-home")

    # 1 · Find properties
    page.click("button[data-job=discover]")
    page.wait_for_selector("#selection-title:has-text('Properties for Manali')")

    cards = page.locator("#selection-cols .prop .name")
    names = [cards.nth(i).inner_text() for i in range(cards.count())]

    assert {"Zostel Manali", "The Hosteller Manali", "Johnson's Lodge", "Cafe 1947"} <= set(names)
    assert page.locator("#job-status").inner_text() == "done"
    assert "Discovering stays in Manali" in page.locator("#job-log").inner_text()
    assert page.locator("button[data-job]").first.is_enabled()          # busy state cleared
    shot(page, "2-found")

    # swap: remove Johnson's Lodge, then use it again
    johnson = page.locator("#selection-cols .prop", has_text="Johnson's Lodge")
    johnson.get_by_role("button", name="Remove").click()
    page.wait_for_selector("#selection-hint:not([hidden])")
    again = page.locator("#selection-cols .prop", has_text="Johnson's Lodge")
    again.get_by_role("button", name="Use this instead").wait_for()
    again.get_by_role("button", name="Use this instead").click()
    page.locator("#selection-cols .prop", has_text="Johnson's Lodge").get_by_role("button", name="Remove").wait_for()

    # read the discovery report in the Reports tab
    page.click("nav.tabs button[data-tab=reports]")
    page.locator("#doc-list .item", has_text="Property discovery").click()
    page.wait_for_selector("#viewer .doc table")

    assert "Zostel Manali" in page.locator("#viewer .doc").inner_text()
    assert page.locator("#viewer .doc table").count() >= 2
    shot(page, "3-report")

    # add notes
    page.click("nav.tabs button[data-tab=notes]")
    page.fill("#form-notes [name=subject]", "Zostel Manali")
    page.fill("#form-notes [name=text]", "The heater never worked.\n\nStaff were lovely.")
    page.click("#form-notes button[type=submit]")
    page.wait_for_selector(".toast:has-text('Saved 2 notes')")
    page.wait_for_selector("#note-list .prop:has-text('The heater never worked.')")
    shot(page, "4-notes")


def test_study_then_open_the_finished_report_from_the_activity_panel(page, app_url, monkeypatch):
    page.goto(app_url)

    page.click("button[data-job=discover]")
    page.wait_for_selector("#selection-title:has-text('Properties for Manali')")

    page.click("#form-study details.more summary")             # "More options" is collapsed by default
    page.select_option("#form-study [name=depth]", "quick")
    page.click("button[data-job=study]")

    page.wait_for_selector("#job-results button:has-text('Property study')")
    assert page.locator("#job-status").inner_text() == "done"

    page.click("#job-results button:has-text('Property study')")
    page.wait_for_selector("#viewer h2:has-text('Property study - Manali')")

    assert "Most common customer problems" in page.locator("#viewer .doc").inner_text()
    shot(page, "5-study")

    # researched properties are listed, and a profile opens
    page.locator("#prop-list .item", has_text="Zostel Manali").click()
    page.wait_for_selector("#viewer .doc:has-text('Channels reached')")


def test_mistakes_show_a_message_and_the_page_stays_usable(page, app_url):
    page.goto(app_url)

    page.fill("#form-study [name=place]", "")
    page.click("button[data-job=discover]")
    page.wait_for_selector(".toast.bad:has-text('Please enter a place')")

    assert page.locator("button[data-job=discover]").is_enabled()

    page.click("nav.tabs button[data-tab=ask]")
    page.click("button[data-job=ask]")
    page.wait_for_selector(".toast.bad:has-text('a question')")

    # the two 400 responses above were provoked on purpose
    page.problems.clear()
