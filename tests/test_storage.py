import json

from app import storage


def test_slugify_and_run_id():
    assert storage.slugify("Dylan's Toasted & Roasted") == "dylan-s-toasted-roasted"
    assert storage.slugify("") == "research"
    assert storage.new_run_id("Zostel Old Manali").startswith("zostel-old-manali-")


def test_manual_notes_round_trip(isolated_research_dir):
    storage.add_manual_note("Zostel Old Manali", "Dorm was freezing", platform="Google Maps", source_url="https://g.page/x")
    storage.add_manual_note("Zostel Old Manali", "Loved the bonfire night")

    notes = storage.load_manual_evidence("Zostel Old Manali")

    assert [n["text"] for n in notes] == ["Dorm was freezing", "Loved the bonfire night"]
    assert notes[0]["platform"] == "Google Maps"
    assert storage.load_manual_evidence("Nobody") == []
    assert (isolated_research_dir / "manual" / "zostel-old-manali.jsonl").exists()


def test_empty_note_rejected():
    try:
        storage.add_manual_note("X", "   ")
        assert False, "should have raised"
    except ValueError:
        pass


def test_import_notes_file_splits_on_blank_lines(tmp_path):
    notes_file = tmp_path / "reviews.txt"
    notes_file.write_text("First review text.\nstill first.\n\nSecond review.\n\n\nThird review.\n")

    assert storage.import_notes_file("Cafe 1947", str(notes_file), platform="Google Maps") == 3
    assert len(storage.load_manual_evidence("Cafe 1947")) == 3


def test_profiles_are_stored_per_kind(isolated_research_dir):
    storage.save_profile("Zostel", {"a": 1})
    storage.save_profile("Zostel", {"b": 2}, kind="topics")

    assert storage.load_profile("Zostel") == {"a": 1}
    assert storage.load_profile("Zostel", kind="topics") == {"b": 2}
    assert storage.load_profile("missing") is None
    assert storage.list_profiles() == [{"a": 1}]


def test_corrupt_manual_line_is_skipped(isolated_research_dir):
    storage.add_manual_note("X", "good note")
    path = isolated_research_dir / "manual" / "x.jsonl"
    path.write_text(path.read_text() + "{not json\n")

    assert len(storage.load_manual_evidence("X")) == 1
