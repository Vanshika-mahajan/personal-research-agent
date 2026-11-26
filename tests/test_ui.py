"""
The interface: Markdown renderer, background jobs and the local web server.

The server tests start a real server on a free port and talk to it over HTTP,
with the web and the model replaced by offline fakes.
"""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from app.storage import research_dir, save_profile
from app.ui import markdown_lite as md
from app.ui import server as ui_server
from app.ui.jobs import Busy, JobManager
from tests.test_discovery import FakeWeb


# ------------------------------------------------------------------
# Markdown renderer
# ------------------------------------------------------------------

def test_tables_headings_lists_and_emphasis_render():
    html = md.render(
        "# Title\n\n"
        "Some **bold** and *italic* and `code`.\n\n"
        "| Name | Score |\n|---|---:|\n| Zostel | 83 |\n| Cafe 1947 | 76 |\n\n"
        "- one\n- two\n  - nested\n- three\n\n"
        "1. first\n2. second\n\n"
        "> a quote\n\n---\n"
    )

    assert "<h1>Title</h1>" in html
    assert "<strong>bold</strong>" in html and "<em>italic</em>" in html and "<code>code</code>" in html
    assert "<th>Name</th>" in html and '<th style="text-align:right">Score</th>' in html
    assert "<td>Zostel</td>" in html and html.count("<tr>") == 3
    assert html.count("<ul>") == 2 and "<li>nested</li>" in html.replace("</li></ul>", "</li>")
    assert "<ol>" in html and "<blockquote>" in html and "<hr>" in html


def test_nothing_from_the_web_can_inject_html_or_scripts():
    hostile = (
        "# <img src=x onerror=alert(1)>\n\n"
        "<script>alert(1)</script> text\n\n"
        "| a | b |\n|---|---|\n| <b>x</b> | `<i>y</i>` |\n\n"
        "[click](javascript:alert(1)) and [ok](https://example.com/a?b=1&c=2)\n\n"
        '[sneaky](https://e.com/"onmouseover="alert(1))\n\n'
        "```\n<script>alert(2)</script>\n```\n"
    )

    html = md.render(hostile)

    assert "<script" not in html and "<img" not in html and "<b>" not in html and "<i>" not in html
    assert "javascript:" not in html                                    # no link made for it
    assert 'href="https://example.com/a?b=1&amp;c=2"' in html           # real links work
    assert '"onmouseover' not in html and " onmouseover=" not in html   # quotes in a URL cannot open an attribute
    assert 'rel="noopener noreferrer"' in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_title_of_and_weird_input():
    assert md.title_of("intro\n\n## **Big** `Title`\n") == "Big Title"
    assert md.title_of("no heading", "fallback") == "fallback"
    assert md.render("") == "" and md.render(None) == ""
    assert "<p>a | b</p>" in md.render("a | b")  # a pipe is not a table without a separator row
    assert "\x00" not in md.render("hello \x000\x00 world")


def test_report_tables_with_emoji_and_pipes_in_cells_render():
    html = md.render("| # | Property |\n|---|---|\n| 1 | Zostel Manali ⚠️ thin |\n| 2 | A \\| B |\n")

    assert "<table>" in html and "Zostel Manali ⚠️ thin" in html and "<td>A | B</td>" in html


# ------------------------------------------------------------------
# Jobs
# ------------------------------------------------------------------

def wait_for(job, timeout=15):
    deadline = time.time() + timeout

    while job.active and time.time() < deadline:
        time.sleep(0.02)

    assert not job.active, f"job still {job.status}"

    return job


def test_job_captures_prints_and_result():
    manager = JobManager()

    def runner(params):
        print("step one")
        print("step two", params["x"])
        return {"summary": "ok"}

    job = wait_for(manager.start("t", "Test", {"x": 5}, runner))

    assert job.status == "done" and job.result == {"summary": "ok"}
    assert job.log == ["step one", "step two 5"]
    assert job.to_dict(since=1)["log"] == ["step two 5"]  # incremental polling


def test_job_errors_are_reported_not_raised():
    manager = JobManager()

    def runner(params):
        print("about to fail")
        raise RuntimeError("boom")

    job = wait_for(manager.start("t", "Test", {}, runner))

    assert job.status == "error" and "RuntimeError: boom" in job.error
    assert any("about to fail" in line for line in job.log)


def test_only_one_job_at_a_time():
    manager = JobManager()
    release = threading.Event()

    first = manager.start("t", "First", {}, lambda p: release.wait(5) and {})

    with pytest.raises(Busy):
        manager.start("t", "Second", {}, lambda p: {})

    release.set()
    wait_for(first)

    wait_for(manager.start("t", "Third", {}, lambda p: {}))  # free again


def test_cancel_stops_at_the_next_printed_line_even_through_broad_excepts():
    manager = JobManager()

    def runner(params):
        for i in range(10_000):
            try:
                print("working", i)
            except Exception:       # the pipeline has many of these; they must not swallow a cancel
                pass
            time.sleep(0.005)

    job = manager.start("t", "Loop", {}, runner)
    time.sleep(0.1)

    assert manager.cancel(job.id) is True

    wait_for(job)

    assert job.status == "cancelled" and job.log[-1] == "Stopped."
    assert manager.cancel(job.id) is False  # nothing left to cancel


def test_log_is_trimmed_but_offsets_stay_valid():
    manager = JobManager()

    def runner(params):
        for i in range(3500):
            print("line", i)

    job = wait_for(manager.start("t", "Chatty", {}, runner))
    view = job.to_dict(since=3490)

    assert view["log_total"] == 3500 and view["log"][-1] == "line 3499" and len(view["log"]) == 10


# ------------------------------------------------------------------
# Web server
# ------------------------------------------------------------------

class Client:
    def __init__(self, base):
        self.base = base

    def call(self, method, path, body=None, headers=None, raw=False):
        data = None
        hdrs = dict(headers or {})

        if body is not None:
            data = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")

        request = urllib.request.Request(self.base + urllib.parse.quote(path, safe="/?=&%:'"), data=data, method=method, headers=hdrs)

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload, status, response_headers = response.read(), response.status, response.headers
        except urllib.error.HTTPError as error:
            payload, status, response_headers = error.read(), error.code, error.headers

        if raw:
            return status, payload, response_headers

        try:
            return status, json.loads(payload), response_headers
        except json.JSONDecodeError:
            return status, payload.decode(), response_headers

    def get(self, path, **kw):
        return self.call("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.call("POST", path, body if body is not None else {}, **kw)

    def run_job(self, kind, params, timeout=40):
        status, data, _ = self.post("/api/jobs", {"kind": kind, "params": params})

        assert status == 202, data

        job_id = data["job"]["id"]
        deadline = time.time() + timeout

        while time.time() < deadline:
            _, job, _ = self.get(f"/api/jobs/{job_id}")

            if job["status"] not in ("queued", "running"):
                return job

            time.sleep(0.05)

        raise AssertionError("job did not finish")


@pytest.fixture
def server():
    srv = ui_server.create_server(port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    yield srv, Client(f"http://127.0.0.1:{srv.server_address[1]}")

    srv.shutdown()
    srv.server_close()


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb()

    monkeypatch.setattr("app.workflows.discovery.search_web", fake.search)
    monkeypatch.setattr("app.workflows.discovery.fetch_headings", fake.headings)

    return fake


def test_page_and_status(server, monkeypatch):
    monkeypatch.setattr("app.llm.provider.llm_health", lambda: (True, "fake llm"))

    _, client = server

    status, page, headers = client.get("/")

    assert status == 200 and "<title>Research Agent</title>" in page
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"

    _, info, _ = client.get("/api/status")

    assert info["llm"] == {"ok": True, "message": "fake llm"} and info["active_job"] is None


def test_requests_that_did_not_come_from_the_page_are_refused(server):
    _, client = server

    assert client.get("/api/status", headers={"Host": "evil.example.com"})[0] == 403          # DNS rebinding
    assert client.post("/api/notes", {"subject": "x", "text": "y"}, headers={"Origin": "https://evil.example.com"})[0] == 403
    assert client.call("POST", "/api/notes", None, headers={"Content-Type": "text/plain"})[0] == 415
    assert client.get("/nope")[0] == 404


def test_find_properties_job_end_to_end(server, web):
    _, client = server

    job = client.run_job("discover", {"place": "Manali", "stays": 3, "cafes": 2})

    assert job["status"] == "done", job
    assert "Discovering stays in Manali" in "\n".join(job["log"])
    assert job["result"]["documents"][0]["label"] == "Which properties and why"

    path = job["result"]["documents"][0]["path"]
    status, doc, _ = client.get("/api/document?path=" + path)

    assert status == 200 and doc["format"] == "md"
    assert "<table>" in doc["html"] and "Zostel Manali" in doc["html"]

    status, view, _ = client.get("/api/selection?place=Manali")
    stays = [p["name"] for p in view["kinds"]["stays"]["current"]]
    cafes = [p["name"] for p in view["kinds"]["cafes"]["current"]]

    assert set(stays) == {"Zostel Manali", "The Hosteller Manali", "Johnson's Lodge"}
    assert set(cafes) == {"Cafe 1947", "Dylan's Toasted & Roasted"}
    assert view["kinds"]["stays"]["current"][0]["score"] > 50 and not view["kinds"]["stays"]["current"][0]["researched"]

    assert client.get("/api/selections")[1]["selections"][0]["place"] == "Manali"
    assert client.get("/api/selection?place=Nowhere")[1] == {"found": False}


def test_swap_a_pick_from_the_interface(server, web):
    _, client = server

    client.run_job("discover", {"place": "Manali", "stays": 3, "cafes": 2})

    status, view, _ = client.post("/api/selection/edit", {"place": "Manali", "action": "remove", "name": "Johnson's Lodge"})

    assert status == 200
    assert "Johnson's Lodge" not in [p["name"] for p in view["kinds"]["stays"]["current"]]
    assert "Johnson's Lodge" in [p["name"] for p in view["kinds"]["stays"]["available"]]
    assert "Edited by hand: stopped studying Johnson's Lodge." in view["notes"]

    _, view, _ = client.post("/api/selection/edit", {"place": "Manali", "action": "add", "name": "Johnson's Lodge"})

    assert "Johnson's Lodge" in [p["name"] for p in view["kinds"]["stays"]["current"]]

    assert client.post("/api/selection/edit", {"place": "Manali", "action": "add", "name": "Nonexistent"})[0] == 400
    assert client.post("/api/selection/edit", {"place": "Nowhere", "action": "remove", "name": "x"})[0] == 400

    # removing everything leaves an empty list; it must not silently fall back to the original picks
    for name in ("Zostel Manali", "The Hosteller Manali", "Johnson's Lodge"):
        _, view, _ = client.post("/api/selection/edit", {"place": "Manali", "action": "remove", "name": name})

    assert view["kinds"]["stays"]["current"] == []


def test_study_job_runs_through_the_interface(server, web, world, monkeypatch):
    monkeypatch.setattr("app.workflows.discovery.evidence_ok", lambda *a, **k: (True, ""))

    _, client = server

    job = client.run_job("study", {"place": "Manali", "stays": 3, "cafes": 2, "depth": "quick"}, timeout=90)

    assert job["status"] == "done", job

    path = job["result"]["documents"][0]["path"]
    _, doc, _ = client.get("/api/document?path=" + path)

    assert doc["title"] == "Property study - Manali" and "Cafe 1947" in doc["html"]

    _, props, _ = client.get("/api/properties")
    names = {p["name"] for p in props["properties"]}

    assert {"Zostel Manali", "Cafe 1947"} <= names

    _, prop, _ = client.get("/api/property?name=Zostel Manali")

    assert prop["name"] == "Zostel Manali" and "Channels reached" in prop["html"]
    assert client.get("/api/property?name=Unknown")[0] == 404

    kinds = {d["kind"] for d in client.get("/api/documents")[1]["documents"]}

    assert "Study" in kinds


def test_model_not_running_gives_a_clear_error(server, monkeypatch):
    monkeypatch.setattr("app.llm.provider.llm_health", lambda: (False, "Ollama is not running"))

    _, client = server

    job = client.run_job("study", {"place": "Manali"})

    assert job["status"] == "error" and "ollama serve" in job["error"]


def test_form_mistakes_are_reported_immediately(server):
    _, client = server

    for kind, params, needle in [
        ("discover", {"place": ""}, "Please enter a place"),
        ("discover", {"place": "Manali", "stays": 0, "cafes": 0}, "at least one"),
        ("discover", {"place": "Manali", "stays": "many"}, "whole number"),
        ("discover", {"place": "Manali", "stays": 99}, "between 0 and 10"),
        ("property", {"name": "X", "place": "Y", "website": "ftp://x"}, "http"),
        ("property", {"name": "X", "place": "Y", "type": "castle"}, "type"),
        ("ask", {"question": ""}, "a question"),
        ("study", {"place": "Manali", "depth": "extreme"}, "Depth"),
        ("nonsense", {}, "Unknown action"),
    ]:
        status, data, _ = client.post("/api/jobs", {"kind": kind, "params": params})

        assert status == 400 and needle in data["error"], (kind, params, data)


def test_second_job_while_one_runs_gets_409(server):
    srv, client = server
    release = threading.Event()

    srv.manager.start("t", "Slow job", {}, lambda p: release.wait(5) and {})

    status, data, _ = client.post("/api/jobs", {"kind": "discover", "params": {"place": "Manali"}})

    assert status == 409 and data["job"]["title"] == "Slow job"
    assert client.get("/api/status")[1]["active_job"]["title"] == "Slow job"

    release.set()


def test_cancel_over_http(server):
    srv, client = server

    def runner(params):
        for i in range(10_000):
            print("tick", i)
            time.sleep(0.005)

    job = srv.manager.start("t", "Loop", {}, runner)
    time.sleep(0.1)

    assert client.post(f"/api/jobs/{job.id}/cancel")[1] == {"cancelled": True}

    wait_for(job)

    assert client.get(f"/api/jobs/{job.id}")[1]["status"] == "cancelled"
    assert client.get("/api/jobs/doesnotexist")[0] == 404


def test_reports_cannot_be_read_outside_the_reports_folder(server, isolated_research_dir):
    _, client = server

    reports = research_dir() / "reports"
    (reports / "ok.md").write_text("# Fine\n\nhello", encoding="utf-8")
    (reports / "page.html").write_text("<html><body>wireframe</body></html>", encoding="utf-8")
    (research_dir() / "properties" / "secret.md").write_text("# secret", encoding="utf-8")
    (research_dir() / "selections").mkdir(exist_ok=True)
    (research_dir() / "selections" / "x.json").write_text("{}", encoding="utf-8")

    assert client.get("/api/document?path=reports/ok.md")[1]["title"] == "Fine"

    for bad in (
        "properties/secret.md", "reports/../properties/secret.md", "../outside.md",
        "selections/x.json", "/etc/passwd", "reports/nothere.md", "reports/ok.md%00.png", "",
    ):
        assert client.get("/api/document?path=" + bad)[0] == 404, bad

    for bad in ("../properties/secret.md", "..%2Fproperties%2Fsecret.md", "reports/../../etc/passwd"):
        assert client.get("/files/" + bad)[0] == 404, bad

    status, body, headers = client.get("/files/reports/ok.md", raw=True)

    assert status == 200 and "attachment" in headers["Content-Disposition"]

    status, body, headers = client.get("/files/reports/page.html", raw=True)

    assert status == 200 and "sandbox" in headers["Content-Security-Policy"] and b"wireframe" in body

    doc = client.get("/api/document?path=reports/page.html")[1]

    assert doc["format"] == "html" and doc["url"] == "/files/reports/page.html"


def test_notes_roundtrip(server):
    _, client = server

    status, data, _ = client.post("/api/notes", {
        "subject": "Zostel Manali", "platform": "Google Maps", "url": "https://maps.example/x",
        "text": "The heater never worked.\n\nStaff were lovely.\n   \nWifi dropped every evening.",
    })

    assert status == 200 and data == {"saved": 3}

    assert client.get("/api/notes")[1]["subjects"][0]["count"] == 3

    notes = client.get("/api/notes?subject=Zostel Manali")[1]["notes"]

    assert [n["text"] for n in notes][:2] == ["The heater never worked.", "Staff were lovely."]
    assert notes[0]["platform"] == "Google Maps"

    for body, needle in [
        ({"subject": "", "text": "x"}, "Say which"),
        ({"subject": "A", "text": "   "}, "Paste at least one"),
        ({"subject": "A", "text": "x", "url": "javascript:alert(1)"}, "http"),
        ({"subject": "A", "text": "x" * 7000}, "too long"),
    ]:
        status, data, _ = client.post("/api/notes", body)

        assert status == 400 and needle in data["error"], body


def test_researched_properties_flag_thin_evidence(server):
    _, client = server

    def profile(name, items, sites):
        return {"key": name, "created_at": "2026-01-01T00:00:00", "spec": {"name": name, "type": "cafe", "place": "Manali"},
                "evidence": [{"claim": f"c{i}", "source_url": f"https://{sites[i % len(sites)]}/{i}"} for i in range(items)],
                "findings": [], "manual_note_count": 0, "coverage": []}

    save_profile("Rich Cafe", profile("Rich Cafe", 12, ["a.com", "b.com", "c.com"]))
    save_profile("Thin Cafe", profile("Thin Cafe", 2, ["a.com"]))

    props = {p["name"]: p for p in client.get("/api/properties")[1]["properties"]}

    assert props["Rich Cafe"]["thin"] is False and props["Rich Cafe"]["source_count"] == 3
    assert props["Thin Cafe"]["thin"] is True


def test_serve_picks_the_next_port_when_busy(monkeypatch):
    blocker = ui_server.create_server(port=0)
    taken = blocker.server_address[1]

    started = {}

    class Stub(ui_server.UIServer):
        def serve_forever(self, *a, **k):
            started["port"] = self.server_address[1]

    monkeypatch.setattr(ui_server, "UIServer", Stub)

    try:
        assert ui_server.serve(port=taken, open_browser=False) == 0
        assert started["port"] != taken
    finally:
        blocker.server_close()
