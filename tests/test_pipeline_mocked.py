"""The whole graph, end to end, with an offline LLM and offline web."""

from pathlib import Path

from app.runner import run_research
from app.schemas.research import ResearchQuestion
from app.storage import load_manual_evidence, add_manual_note
from app.workflows.profiles import PropertySpec, question_for


def test_general_question_runs_and_saves_everything(world, isolated_research_dir):
    question = ResearchQuestion(question="What do guests complain about at hostels in Goa?", max_iterations=2)

    result = run_research(question)

    state = result["state"]
    paths = result["paths"]

    # planner used the LLM plan, research found sources, evidence was built
    assert state["search_queries"][0] == "goa hostels guest complaints"
    assert state["sources"] and state["evidence"]

    # all three artefacts were written and the report is Markdown, not JSON
    for key in ("raw", "evidence", "report"):
        assert Path(paths[key]).exists(), key

    report = Path(paths["report"]).read_text()
    assert report.startswith("# Research report")
    assert not report.lstrip().startswith("{")
    assert "## Key findings" in report
    assert "## Sources" in report
    assert "https://www.booking.com/hotel/in/zostel-old-manali.html" in report


def test_report_is_written_in_prose_mode_not_json_mode(world):
    result = run_research(ResearchQuestion(question="What do guests complain about at hostels in Goa?", max_iterations=1))

    summary_calls = [c for c in world.calls if "executive summary" in c["prompt"]]

    assert summary_calls, "the report should ask for a short summary"
    assert all(c["json_mode"] is False for c in summary_calls)
    assert "mix of problems and praise" in result["state"]["report"]


def test_invented_finding_with_unknown_evidence_id_is_dropped(world):
    result = run_research(ResearchQuestion(question="What do guests complain about at hostels in Goa?", max_iterations=1))

    statements = [f["statement"] for f in result["state"]["verified_findings"]]

    assert "Guests hate the parking lot." not in statements
    assert all(f["evidence_ids"] for f in result["state"]["verified_findings"])


def test_follow_up_loop_terminates_at_max_iterations(world):
    result = run_research(ResearchQuestion(question="What do guests complain about at hostels in Goa?", max_iterations=3))

    assert result["state"]["iteration"] <= 3
    assert result["state"]["report"]


def test_property_mode_uses_seed_queries_skips_llm_planner_and_filters_other_venues(world):
    spec = PropertySpec(name="Zostel Old Manali", place="Manali", type="hostel")

    result = run_research(question_for(spec, "quick"), label=spec.name)

    state = result["state"]

    assert not any("expert research planner" in c["prompt"] for c in world.calls)
    assert state["search_queries"][0] == '"Zostel Old Manali" Manali reviews'

    claims = " ".join(e["claim"] for e in state["evidence"])
    assert "Moustache" not in claims  # a different hostel in a listicle
    assert "dirty" in claims

    report = Path(result["paths"]["report"]).read_text()
    assert report.startswith("# Property profile - Zostel Old Manali")


def test_coverage_table_is_honest_about_instagram_and_google(world):
    spec = PropertySpec(name="Zostel Old Manali", place="Manali", type="hostel")

    report = run_research(question_for(spec, "quick"), label=spec.name)["state"]["report"]

    rows = {line.split("|")[1].strip(): line for line in report.splitlines() if line.startswith("| ") and "Channel" not in line and "---" not in line}

    insta = next(v for k, v in rows.items() if k.startswith("Instagram"))
    google = next(v for k, v in rows.items() if k.startswith("Google"))
    booking = next(v for k, v in rows.items() if k.startswith("Booking"))

    assert "⚠️" in insta                      # snippet only
    assert "❌" in google and "note" in google  # nothing + tells you what to do
    assert "✅" in booking                    # booking.com page was read in full


def test_pages_that_need_login_are_not_fetched(world, monkeypatch):
    fetched = []

    def spy(url, max_chars=20000):
        fetched.append(url)
        return ""

    monkeypatch.setattr("app.graph.nodes.fetch_page_text", spy)

    run_research(question_for(PropertySpec(name="Zostel Old Manali"), "quick"))

    assert fetched, "ordinary pages are read"
    assert not any("instagram.com" in u for u in fetched)


def test_manual_notes_flow_into_evidence_and_report(world):
    spec = PropertySpec(name="Zostel Old Manali", place="Manali", type="hostel")

    add_manual_note(spec.name, "Google review: the heater in our dorm was not working at all", platform="Google Maps")

    result = run_research(
        question_for(spec, "quick"),
        label=spec.name,
        manual_evidence=load_manual_evidence(spec.name),
    )

    evidence = result["state"]["evidence"]

    assert evidence[0]["source_type"] == "manual"
    assert "your note" in result["state"]["report"] or "Google Maps" in result["state"]["report"]


def test_llm_down_gives_an_honest_empty_report_not_a_crash(monkeypatch, isolated_research_dir):
    from tests.fakes import fake_fetch_page_text, fake_search_web

    def down(prompt, json_mode=True, timeout=None):
        raise RuntimeError("ollama is down")

    for target in ("app.graph.nodes.generate_text", "app.graph.finding_verifier.generate_text"):
        monkeypatch.setattr(target, down)

    monkeypatch.setattr("app.graph.nodes.search_web", fake_search_web)
    monkeypatch.setattr("app.graph.nodes.fetch_page_text", fake_fetch_page_text)

    result = run_research(ResearchQuestion(question="complaints about hostels in Goa", max_iterations=1))

    report = result["state"]["report"]

    assert "No finding passed verification" in report
    assert Path(result["paths"]["report"]).exists()
