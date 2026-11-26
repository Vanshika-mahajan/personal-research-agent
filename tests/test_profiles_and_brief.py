import json
from pathlib import Path

from app import main
from app.workflows import profiles, vibers_brief
from app.workflows.profiles import PropertySpec, load_specs, profile_property, top_problems


def test_property_queries_cover_the_channels_in_the_brief():
    hostel = profiles.property_queries(PropertySpec(name="Zostel Old Manali", type="hostel", website="https://www.zostel.com"))
    text = " | ".join(hostel)

    for needle in ("site:instagram.com", "google reviews", "tripadvisor", "booking.com", "site:reddit.com", "site:zostel.com", "complaints"):
        assert needle in text

    cafe = " | ".join(profiles.property_queries(PropertySpec(name="Cafe 1947", type="cafe")))

    assert "zomato" in cafe and "booking.com" not in cafe


def test_load_specs_applies_default_place(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"place": "Goa", "properties": [{"name": "A"}, {"name": "B", "place": "Manali", "type": "cafe"}], "owner_properties": ["A"]}))

    loaded = load_specs(path)

    assert [(p.name, p.place) for p in loaded["properties"]] == [("A", "Goa"), ("B", "Manali")]
    assert loaded["properties"][1].is_lodging is False
    assert loaded["owner_properties"] == ["A"]


def test_starter_properties_file_is_valid():
    loaded = load_specs(Path(__file__).resolve().parent.parent / "research" / "vibers_properties.json")

    assert len(loaded["properties"]) == 5
    assert sum(p.is_lodging for p in loaded["properties"]) == 3
    assert len(loaded["owner_properties"]) == 3


def test_profile_is_cached_and_refresh_redoes_it(world, monkeypatch):
    calls = []

    from tests.fakes import fake_search_web

    def counting(query, max_results=5, official_domains=()):
        calls.append(query)
        return fake_search_web(query, max_results, official_domains)

    monkeypatch.setattr("app.graph.nodes.search_web", counting)

    spec = PropertySpec(name="Zostel Old Manali")

    first = profile_property(spec, depth="quick", log=lambda *_: None)
    searched = len(calls)
    assert searched > 0 and first["findings"]

    profile_property(spec, depth="quick", log=lambda *_: None)
    assert len(calls) == searched  # served from the saved profile

    profile_property(spec, depth="quick", refresh=True, log=lambda *_: None)
    assert len(calls) > searched


def test_new_manual_note_invalidates_the_cached_profile(world, monkeypatch):
    from app.storage import add_manual_note

    spec = PropertySpec(name="Zostel Old Manali")

    profile_property(spec, depth="quick", log=lambda *_: None)

    add_manual_note(spec.name, "Google review: the shower had no hot water at all", platform="Google Maps")

    again = profile_property(spec, depth="quick", log=lambda *_: None)

    assert again["manual_note_count"] == 1
    assert any(e["source_type"] == "manual" for e in again["evidence"])


def _profile(name, texts):
    return {
        "key": name,
        "spec": {"name": name},
        "evidence": [
            {"claim": t, "source_url": f"https://s.example.com/{i}-{name}", "source_title": "t", "source_type": "review"}
            for i, t in enumerate(texts)
        ],
        "findings": [],
    }


def test_top_problems_needs_repetition_and_never_pads():
    profs = [
        _profile("A", ["The bathroom was dirty and smelled", "Staff were rude at reception"]),
        _profile("B", ["Dirty towels and unclean sheets", "Pleasant stay overall"]),
    ]

    problems = top_problems(profs, limit=5, min_sources=2)

    assert [p["theme"] for p in problems][0] == "Cleanliness & hygiene"
    assert all(p["source_count"] >= 2 for p in problems)
    assert len(problems) < 5  # not padded


def test_official_website_text_is_not_counted_as_customer_complaints():
    official = _profile("A", ["No loud music allowed. Noisy guests will be asked to leave."])
    official["evidence"][0]["source_type"] = "official"

    assert top_problems([official, official], min_sources=1) == []


def test_brief_end_to_end_writes_both_documents_and_wireframe(world, isolated_research_dir, tmp_path):
    props = tmp_path / "props.json"
    props.write_text(json.dumps({
        "place": "Manali",
        "properties": [
            {"name": "Zostel Old Manali", "type": "hostel"},
            {"name": "The Hosteller Manali", "type": "hostel"},
            {"name": "Johnson's Lodge", "type": "hotel"},
            {"name": "Cafe 1947", "type": "cafe"},
            {"name": "Dylan's Toasted & Roasted", "type": "cafe"},
        ],
        "owner_properties": ["Zostel Old Manali", "The Hosteller Manali", "Johnson's Lodge"],
    }))

    written = vibers_brief.run_brief(props, depth="quick", log=lambda *_: None)

    part1 = Path(written["part1"]).read_text()
    part2 = Path(written["part2"]).read_text()
    dash = Path(written["dashboard"]).read_text()

    # Part 1 has every section the brief asks for, in order
    headings = [
        "## 1. The properties and what we observed",
        "## 2. The most common customer problems",
        "## 3. The five customer questions, across all properties",
        "## 4. Booking platforms",
        "## 5. What Vibers Connect could improve",
        "## 6. Three ideas that could make Vibers Connect genuinely different",
        "## 7. Your personal opinion as a customer",
    ]
    positions = [part1.index(h) for h in headings]
    assert positions == sorted(positions)

    for name in ("Zostel Old Manali", "Cafe 1947", "Dylan's Toasted & Roasted"):
        assert name in part1

    for platform in ("Zostel (booking experience)", "MakeMyTrip", "Airbnb"):
        assert platform in part1

    # the labels that separate research from ideas are present
    assert "**RESEARCHED**" in part1 and "**IDEA**" in part1 and "**YOUR VIEW**" in part1

    # the opinion section is left for the human, never filled in by the agent
    assert "> *(your answer here)*" in part1

    # Part 2: tools, seven areas, three questions, dashboard table
    for needle in ("PriceLabs", "Lighthouse", "Cloudbeds", "If I owned Zostel Old Manali",
                   "What information is difficult for hotel owners to find?",
                   "What would make an owner open it every morning"):
        assert needle in part2
    assert part2.count("| 1 |") >= 1 and "| 7 | Decision intelligence" in part2

    # wireframe: 7 panels, no unescaped injection, says it is illustrative
    assert dash.count('<section class="card') == 7
    assert "no real data" in dash.lower() or "no real numbers" in dash.lower()


def test_brief_render_only_with_nothing_researched_does_not_crash(isolated_research_dir, tmp_path):
    props = tmp_path / "props.json"
    props.write_text(json.dumps({"properties": [{"name": "A"}, {"name": "B"}, {"name": "C"}]}))

    written = vibers_brief.run_brief(props, render_only=True, use_llm=False, log=lambda *_: None)

    part1 = Path(written["part1"]).read_text()

    assert "Not researched yet" in part1
    assert "[Idea 1 - write yours]" in part1  # blank, not invented
    assert Path(written["dashboard"]).exists()


def test_llm_failure_leaves_ideas_blank_not_made_up(monkeypatch):
    def down(prompt, json_mode=True, timeout=None):
        raise RuntimeError("down")

    monkeypatch.setattr("app.workflows.vibers_brief.generate_text", down)

    ideas = vibers_brief.draft_ideas([], [])

    assert len(ideas) == 3 and all(i["title"].startswith("[Idea") for i in ideas)


def test_dashboard_html_escapes_content():
    data = {"place": "<script>alert(1)</script>", "areas": [
        {"n": 1, "title": "<b>x</b>", "question": "q", "shows": "s", "why": "w", "topic": None, "key": "k"}
    ]}

    html = vibers_brief.render_dashboard_html(data)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_cli_note_list_check_and_missing_brief(world, isolated_research_dir, capsys, tmp_path):
    assert main.main(["note", "Zostel Old Manali", "Dorm was freezing", "--platform", "Google Maps"]) == 0
    assert main.main(["note", "Zostel Old Manali"]) == 1  # nothing to save

    notes = tmp_path / "n.txt"
    notes.write_text("one note here\n\nsecond note here\n")
    assert main.main(["note", "Cafe 1947", "--file", str(notes)]) == 0

    assert main.main(["list"]) == 0
    assert main.main(["brief", "vibers", "--properties", str(tmp_path / "nope.json")]) == 1

    capsys.readouterr()

    assert main.main(["compare"]) == 1  # no profiles yet


def test_cli_refuses_to_start_when_llm_is_down(monkeypatch, capsys):
    monkeypatch.setattr("app.llm.provider.llm_health", lambda: (False, "Ollama is not reachable"))

    assert main.main(["ask", "anything"]) == 2
    assert main.main(["property", "Zostel Old Manali"]) == 2
    assert "Ollama is not reachable" in capsys.readouterr().out


def test_ideas_are_only_marked_as_matching_when_they_target_a_researched_problem(monkeypatch):
    import json as _json

    def llm(prompt, json_mode=True, timeout=None):
        return _json.dumps({"ideas": [
            {"title": "A", "problem_addressed": "Cleanliness is inconsistent", "how_it_works": "x", "why_different": "y"},
            {"title": "B", "problem_addressed": "Guests want teleportation", "how_it_works": "x", "why_different": "y"},
        ]})

    monkeypatch.setattr("app.workflows.vibers_brief.generate_text", llm)

    problems = [{"theme": "Cleanliness & hygiene", "property_count": 2, "source_count": 3}]

    ideas = vibers_brief.draft_ideas(problems, [])

    assert [i["matched"] for i in ideas] == ["yes", "no", "placeholder"]
    assert ideas[2]["title"].startswith("[Idea")


def test_coverage_table_hides_empty_blog_forum_rows_but_keeps_the_brief_channels():
    from app.graph.report_builder import render_coverage_markdown

    table = render_coverage_markdown([])

    for kept in ("Google Maps", "Instagram", "Official website", "Booking platforms", "Review sites"):
        assert kept in table

    assert "Forums" not in table and "Blogs" not in table and "Notes you added" not in table
