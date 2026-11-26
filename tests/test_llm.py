from app.llm.provider import generate_text


def test_llm_provider():

    response = generate_text(
        "Reply with exactly: LLM working"
    )

    assert "LLM working" in response