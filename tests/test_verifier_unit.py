import json

from app.graph.finding_verifier import is_grounded, verify_findings_with_llm


def test_is_grounded():
    claims = ["Several guests complained that the bathroom was dirty and smelled."]

    assert is_grounded("Guests complained about a dirty bathroom.", claims)
    assert not is_grounded("The parking lot is far too small.", claims)
    assert not is_grounded("", claims)
    assert not is_grounded("Dirty bathroom", [])


def test_llm_saying_verified_is_overruled_when_wording_is_ungrounded(monkeypatch):
    evidence = [{"evidence_id": "evidence_1", "claim": "The rooftop cafe has mountain views."}]

    findings = [
        {"finding_id": "finding_1", "statement": "Guests complained the dorm was freezing and noisy.",
         "evidence_ids": ["evidence_1"]},
        {"finding_id": "finding_2", "statement": "The rooftop cafe has mountain views.",
         "evidence_ids": ["evidence_1"]},
    ]

    def always_verified(prompt, json_mode=True, timeout=None):
        return json.dumps({"verifications": [
            {"finding_id": "finding_1", "status": "VERIFIED", "reason": "sure"},
            {"finding_id": "finding_2", "status": "VERIFIED", "reason": "sure"},
        ]})

    monkeypatch.setattr("app.graph.finding_verifier.generate_text", always_verified)

    result = {f["finding_id"]: f for f in verify_findings_with_llm("q", findings, evidence)}

    assert result["finding_1"]["verification_status"] == "UNSUPPORTED"
    assert "Downgraded" in result["finding_1"]["verification_reason"]
    assert result["finding_2"]["verification_status"] == "VERIFIED"


def test_verifier_fails_closed_when_llm_breaks(monkeypatch):
    def broken(prompt, json_mode=True, timeout=None):
        raise RuntimeError("model crashed")

    monkeypatch.setattr("app.graph.finding_verifier.generate_text", broken)

    result = verify_findings_with_llm(
        "q",
        [{"finding_id": "finding_1", "statement": "Dirty bathroom", "evidence_ids": ["evidence_1"]}],
        [{"evidence_id": "evidence_1", "claim": "Dirty bathroom"}],
    )

    assert result[0]["verification_status"] == "UNSUPPORTED"


def test_verifier_only_sends_cited_evidence_and_batches(monkeypatch):
    prompts = []

    def spy(prompt, json_mode=True, timeout=None):
        prompts.append(prompt)
        return json.dumps({"verifications": []})

    monkeypatch.setattr("app.graph.finding_verifier.generate_text", spy)
    monkeypatch.setenv("VERIFY_BATCH_SIZE", "2")

    evidence = [{"evidence_id": f"evidence_{i}", "claim": f"UNIQUE-CLAIM-{i} about guests"} for i in range(1, 6)]
    findings = [
        {"finding_id": f"finding_{i}", "statement": f"claim {i}", "evidence_ids": [f"evidence_{i}"]}
        for i in range(1, 5)
    ]

    verify_findings_with_llm("q", findings, evidence)

    assert len(prompts) == 2  # 4 findings in batches of 2
    assert "UNIQUE-CLAIM-1" in prompts[0] and "UNIQUE-CLAIM-3" not in prompts[0]
    assert "UNIQUE-CLAIM-5" not in prompts[0] + prompts[1]  # never cited


def test_aspects_change_the_relevance_rules(monkeypatch):
    seen = {}

    def spy(prompt, json_mode=True, timeout=None):
        seen["prompt"] = prompt
        return json.dumps({"verifications": []})

    monkeypatch.setattr("app.graph.finding_verifier.generate_text", spy)

    args = ("q", [{"finding_id": "finding_1", "statement": "s", "evidence_ids": ["evidence_1"]}],
            [{"evidence_id": "evidence_1", "claim": "c"}])

    verify_findings_with_llm(*args, aspects=["What guests appreciate most"])
    assert "What guests appreciate most" in seen["prompt"]
    assert "Do NOT reject praise" in seen["prompt"]

    verify_findings_with_llm(*args)
    assert "IRRELEVANT unless they" in seen["prompt"]
