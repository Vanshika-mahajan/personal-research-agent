"""
The local web server behind `python -m app.main ui`.

Standard library only (no new packages). It listens on 127.0.0.1, so it is
reachable only from this computer, and it refuses requests that did not come
from its own page (Host / Origin checks), so a website you happen to have
open cannot start research jobs or write notes.

    GET  /                        the page
    GET  /api/status              Ollama health, model, current job
    GET  /api/web-check           run one test search
    POST /api/jobs                start discover / study / brief / property / ask
    GET  /api/jobs[/<id>]         progress (the log is returned incrementally)
    POST /api/jobs/<id>/cancel
    GET  /api/documents           saved reports
    GET  /api/document?path=...   one report, rendered
    GET  /files/<path>            a report file (download or the dashboard HTML)
    GET  /api/selection[s]        properties chosen for a place
    POST /api/selection/edit      swap a pick for a reserve
    GET  /api/properties          researched properties
    GET  /api/property?name=...   one property's profile, rendered
    GET/POST /api/notes           notes you pasted (Google reviews, Instagram ...)
"""

from __future__ import annotations

import json
import mimetypes
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from app.config import get_settings
from app.storage import (
    add_manual_note,
    list_manual_subjects,
    list_profiles,
    load_manual_evidence,
    load_profile,
    read_json,
    research_dir,
)
from app.ui import actions
from app.ui.jobs import Busy, JobManager
from app.ui.markdown_lite import render, title_of

INDEX_FILE = Path(__file__).with_name("index.html")

MAX_BODY = 2_000_000
MAX_NOTES_PER_REQUEST = 200
MAX_NOTE_CHARS = 6000

LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}

PAGE_CSP = (
    "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; frame-src 'self'; base-uri 'none'; form-action 'none'"
)
FILE_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox"


# ------------------------------------------------------------------
# Data helpers (kept apart from HTTP so they are easy to test)
# ------------------------------------------------------------------

def report_file(relative: str) -> Optional[Path]:
    """A report under research/reports/, or None. Blocks any path that escapes it."""

    relative = unquote(relative or "").lstrip("/")

    if not relative or "\x00" in relative:
        return None

    base = research_dir().resolve()
    reports = (base / "reports").resolve()
    target = (base / relative).resolve()

    if not target.is_file() or target.suffix.lower() not in (".md", ".html"):
        return None

    try:
        target.relative_to(reports)
    except ValueError:
        return None

    return target


def _kind_of(relative: str) -> str:
    name = relative.rsplit("/", 1)[-1]

    if "/vibers/" in relative:
        return "Vibers brief"

    for prefix, kind in (
        ("study_", "Study"),
        ("discovery_", "Discovery"),
        ("property_", "Property"),
        ("problems_", "Comparison"),
    ):
        if name.startswith(prefix):
            return kind

    return "Research"


def list_documents() -> List[Dict[str, Any]]:
    base = research_dir()

    documents = []

    for path in (base / "reports").rglob("*"):
        if not path.is_file() or path.suffix.lower() not in (".md", ".html"):
            continue

        relative = path.relative_to(base).as_posix()
        stat = path.stat()

        if path.suffix.lower() == ".md":
            head = path.read_text(encoding="utf-8", errors="replace")[:3000]
            title = title_of(head, path.stem)
        else:
            title = path.stem.replace("_", " ").replace("part2 ", "Part 2 - ").capitalize()

        documents.append(
            {
                "path": relative,
                "title": title,
                "kind": _kind_of(relative),
                "format": path.suffix.lower().lstrip("."),
                "modified": stat.st_mtime,
                "size": stat.st_size,
            }
        )

    return sorted(documents, key=lambda doc: doc["modified"], reverse=True)


def read_document(relative: str) -> Optional[Dict[str, Any]]:
    path = report_file(relative)

    if path is None:
        return None

    relative = path.relative_to(research_dir().resolve()).as_posix()

    if path.suffix.lower() == ".html":
        return {
            "path": relative,
            "title": path.stem.replace("_", " "),
            "format": "html",
            "url": "/files/" + relative,
            "modified": path.stat().st_mtime,
        }

    text = path.read_text(encoding="utf-8", errors="replace")

    return {
        "path": relative,
        "title": title_of(text, path.stem),
        "format": "md",
        "html": render(text),
        "url": "/files/" + relative,
        "modified": path.stat().st_mtime,
    }


def _slim(item: Dict[str, Any]) -> Dict[str, Any]:
    from app.workflows.discovery import _platform_text

    profile = load_profile(item["name"])

    return {
        "name": item["name"],
        "type": item.get("type", ""),
        "score": item.get("score", 0),
        "thin": bool(item.get("thin")),
        "site_count": item.get("site_count", 0),
        "total_reviews": item.get("total_reviews", 0),
        "earliest_year": item.get("earliest_year"),
        "age_years": item.get("age_years"),
        "seen": _platform_text(item),
        "researched": bool(profile),
        "evidence_count": len(profile.get("evidence", [])) if profile else 0,
    }


def selection_view(selection: Dict[str, Any]) -> Dict[str, Any]:
    from app.workflows.discovery import current_names, render_selection_markdown

    kinds = {}

    for label in ("stays", "cafes"):
        block = selection.get(label) or {}

        lookup: Dict[str, Dict[str, Any]] = {}

        for item in block.get("selected", []) + block.get("reserves", []):
            lookup.setdefault(item["name"], item)

        names = current_names(block)

        kinds[label] = {
            "requested": block.get("requested", 0),
            "qualified": block.get("qualified", len(block.get("selected", []))),
            "current": [_slim(lookup[name]) for name in names if name in lookup],
            "available": [_slim(item) for name, item in lookup.items() if name not in names],
            "rejected": block.get("rejected", [])[:10],
        }

    return {
        "place": selection["place"],
        "created_at": selection.get("created_at", ""),
        "kinds": kinds,
        "notes": selection.get("notes", []),
        "html": render(render_selection_markdown(selection, heading_level=3)),
    }


def list_selections() -> List[Dict[str, Any]]:
    folder = research_dir() / "selections"

    selections = []

    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        try:
            data = read_json(path)
        except Exception:
            continue

        selections.append(
            {
                "place": data.get("place", path.stem),
                "created_at": data.get("created_at", ""),
                "stays": len(data.get("stays", {}).get("selected", [])),
                "cafes": len(data.get("cafes", {}).get("selected", [])),
            }
        )

    return selections


def property_summaries() -> List[Dict[str, Any]]:
    from app.workflows.discovery import evidence_ok, site_key

    summaries = []

    for profile in list_profiles("properties"):
        spec = profile.get("spec", {})
        evidence = profile.get("evidence", [])

        sites = {site_key(item["source_url"]) for item in evidence if item.get("source_url")}

        summaries.append(
            {
                "name": spec.get("name") or profile.get("key", "?"),
                "type": spec.get("type", ""),
                "place": spec.get("place", ""),
                "created_at": profile.get("created_at", ""),
                "evidence_count": len(evidence),
                "source_count": len(sites),
                "verified": sum(
                    1 for f in profile.get("findings", []) if f.get("verification_status") == "VERIFIED"
                ),
                "manual_notes": profile.get("manual_note_count", 0),
                "thin": not evidence_ok(profile)[0],
            }
        )

    return sorted(summaries, key=lambda s: s["created_at"], reverse=True)


def save_notes(payload: Dict[str, Any]) -> int:
    """Notes pasted in the interface; a blank line separates notes."""

    subject = " ".join(str(payload.get("subject", "")).split())
    text = str(payload.get("text", "")).strip()

    if not subject:
        raise ValueError("Say which property or platform the notes are about.")

    if not text:
        raise ValueError("Paste at least one note.")

    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]

    if len(blocks) > MAX_NOTES_PER_REQUEST:
        raise ValueError(f"At most {MAX_NOTES_PER_REQUEST} notes at once.")

    for block in blocks:
        if len(block) > MAX_NOTE_CHARS:
            raise ValueError(f"A single note is too long (max {MAX_NOTE_CHARS} characters).")

    url = str(payload.get("url", "")).strip()

    if url and not url.lower().startswith(("http://", "https://")):
        raise ValueError("The link must start with http:// or https://")

    for block in blocks:
        add_manual_note(
            subject,
            block,
            platform=str(payload.get("platform", ""))[:60],
            source_url=url[:400],
            tag=str(payload.get("tag", ""))[:40],
        )

    return len(blocks)


# ------------------------------------------------------------------
# HTTP
# ------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "ResearchAgentUI"

    # silence the per-request console lines (the console shows job output instead)
    def log_message(self, *args) -> None:
        pass

    # ---- responses ---------------------------------------------------

    def _send(self, status: int, body: bytes, content_type: str, headers: Optional[Dict[str, str]] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")

        for key, value in (headers or {}).items():
            self.send_header(key, value)

        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: Any, status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, message: str, **extra) -> None:
        self._json({"error": message, **extra}, status)

    # ---- guards ------------------------------------------------------

    def _guard(self, post: bool) -> bool:
        host = self.headers.get("Host", "")
        hostname = host.split("]")[0] + "]" if host.startswith("[") else host.rsplit(":", 1)[0]

        if hostname.lower() not in LOCAL_HOSTS:
            self._error(403, "This interface only answers on localhost.")
            return False

        if post:
            content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()

            if content_type != "application/json":
                self._error(415, "Expected JSON.")
                return False

            origin = self.headers.get("Origin")

            if origin and origin != f"http://{host}":
                self._error(403, "Cross-site request refused.")
                return False

        return True

    def _body(self) -> Optional[Dict[str, Any]]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0

        if length > MAX_BODY:
            self._error(413, "Request too large.")
            return None

        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._error(400, "Invalid JSON.")
            return None

        if not isinstance(data, dict):
            self._error(400, "Expected a JSON object.")
            return None

        return data

    @property
    def manager(self) -> JobManager:
        return self.server.manager  # type: ignore[attr-defined]

    # ---- GET ---------------------------------------------------------

    def do_GET(self) -> None:
        if not self._guard(post=False):
            return

        url = urlparse(self.path)
        path = url.path.rstrip("/") or "/"
        query = {key: values[0] for key, values in parse_qs(url.query).items()}

        try:
            self._route_get(path, query)
        except Exception as exc:  # never leave the browser hanging
            self._error(500, f"{type(exc).__name__}: {exc}")

    def _route_get(self, path: str, query: Dict[str, str]) -> None:
        if path == "/":
            self._send(200, INDEX_FILE.read_bytes(), "text/html; charset=utf-8", {"Content-Security-Policy": PAGE_CSP})

        elif path == "/api/status":
            from app.llm import provider

            ok, message = provider.llm_health()
            settings = get_settings()
            active = self.manager.active_job()

            self._json(
                {
                    "llm": {"ok": ok, "message": message},
                    "model": settings.ollama_model,
                    "research_dir": str(settings.research_dir),
                    "fetch_pages": settings.fetch_pages,
                    "active_job": active.to_dict(with_log=False) if active else None,
                }
            )

        elif path == "/api/web-check":
            try:
                from app.tools.web_search import search_web

                results = search_web("Manali hostel reviews", max_results=3)
                self._json({"ok": bool(results), "message": f"Web search works ({len(results)} results)."
                            if results else "Web search returned no results."})
            except Exception as exc:
                self._json({"ok": False, "message": f"Web search failed: {exc}"})

        elif path == "/api/jobs":
            self._json({"jobs": [job.to_dict(with_log=False) for job in self.manager.recent()]})

        elif path.startswith("/api/jobs/"):
            job = self.manager.get(path.split("/")[3])

            if job is None:
                self._error(404, "No such job.")
                return

            try:
                since = int(query.get("since", 0))
            except ValueError:
                since = 0

            self._json(job.to_dict(since=since))

        elif path == "/api/documents":
            self._json({"documents": list_documents()})

        elif path == "/api/document":
            document = read_document(query.get("path", ""))

            if document is None:
                self._error(404, "Report not found.")
            else:
                self._json(document)

        elif path.startswith("/files/"):
            self._serve_file(path[len("/files/"):], download=query.get("download") == "1")

        elif path == "/api/selections":
            self._json({"selections": list_selections()})

        elif path == "/api/selection":
            from app.workflows.discovery import load_selection

            selection = load_selection(query.get("place", "").strip())

            # "nothing saved yet" is a normal state, not an error
            self._json({"found": False} if selection is None else selection_view(selection))

        elif path == "/api/properties":
            self._json({"properties": property_summaries()})

        elif path == "/api/property":
            from app.workflows.profiles import render_property_section

            profile = load_profile(query.get("name", ""))

            if profile is None:
                self._error(404, "That property has not been researched yet.")
            else:
                name = profile.get("spec", {}).get("name") or profile.get("key", "")
                self._json({"name": name,
                            "html": render(render_property_section(profile, heading_level=2))})

        elif path == "/api/notes":
            subject = query.get("subject")

            if subject:
                notes = load_manual_evidence(subject)
                self._json({"notes": [{"text": n.get("text", ""), "platform": n.get("platform", ""),
                                       "source_url": n.get("source_url", ""), "added_at": n.get("added_at", "")}
                                      for n in notes]})
            else:
                self._json({"subjects": list_manual_subjects()})

        else:
            self._error(404, "Not found.")

    def _serve_file(self, relative: str, download: bool) -> None:
        target = report_file(relative)

        if target is None:
            self._error(404, "File not found.")
            return

        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"

        if target.suffix.lower() == ".md":
            content_type = "text/markdown"

        headers = {"Content-Security-Policy": FILE_CSP}

        if download or target.suffix.lower() == ".md":
            headers["Content-Disposition"] = f'attachment; filename="{target.name}"'

        self._send(200, target.read_bytes(), content_type + "; charset=utf-8", headers)

    # ---- POST --------------------------------------------------------

    def do_POST(self) -> None:
        if not self._guard(post=True):
            return

        data = self._body()

        if data is None:
            return

        path = urlparse(self.path).path.rstrip("/")

        try:
            self._route_post(path, data)
        except ValueError as exc:
            self._error(400, str(exc))
        except Exception as exc:
            self._error(500, f"{type(exc).__name__}: {exc}")

    def _route_post(self, path: str, data: Dict[str, Any]) -> None:
        if path == "/api/jobs":
            title, cleaned, runner = actions.prepare(str(data.get("kind", "")), data.get("params") or {})

            try:
                job = self.manager.start(str(data["kind"]), title, cleaned, runner)
            except Busy as busy:
                self._error(409, str(busy), job=busy.job.to_dict(with_log=False))
                return

            self._json({"job": job.to_dict()}, 202)

        elif re.fullmatch(r"/api/jobs/[0-9a-f]+/cancel", path):
            cancelled = self.manager.cancel(path.split("/")[3])
            self._json({"cancelled": cancelled})

        elif path == "/api/selection/edit":
            from app.workflows.discovery import (
                edit_selection,
                load_selection,
                save_selection,
                write_discovery_report,
            )

            selection = load_selection(str(data.get("place", "")).strip())

            if selection is None:
                raise ValueError("No saved properties for that place.")

            edit_selection(selection, str(data.get("action", "")), str(data.get("name", "")))
            save_selection(selection)
            write_discovery_report(selection)

            self._json(selection_view(selection))

        elif path == "/api/notes":
            count = save_notes(data)
            self._json({"saved": count})

        else:
            self._error(404, "Not found.")


class UIServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    manager: JobManager


def create_server(host: str = "127.0.0.1", port: int = 8765, manager: Optional[JobManager] = None) -> UIServer:
    server = UIServer((host, port), Handler)
    server.manager = manager or JobManager()

    return server


def serve(port: int = 8765, open_browser: bool = True) -> int:
    server = None

    for candidate in range(port, port + 10):
        try:
            server = create_server(port=candidate)
            break
        except OSError:
            continue

    if server is None:
        print(f"Ports {port}-{port + 9} are all in use. Try: python -m app.main ui --port 9000")
        return 1

    url = f"http://127.0.0.1:{server.server_address[1]}/"

    print(f"\nResearch agent interface running at {url}")
    print("Leave this window open while you use it. Press Ctrl+C to stop.\n")

    if open_browser:
        threading.Timer(0.8, webbrowser.open, args=(url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped. Everything researched is saved under research/.")
    finally:
        server.server_close()

    return 0
