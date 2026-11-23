from app.schemas.research import (
    ResearchQuestion,
    ResearchQuery,
    ResearchPlan,
)


def test_research_question():

    question = ResearchQuestion(
        question="Research hostels in Manali",
        depth="deep",
        max_iterations=3,
    )

    assert question.question == "Research hostels in Manali"
    assert question.depth == "deep"
    assert question.max_iterations == 3


def test_research_query():

    query = ResearchQuery(
        query="best hostels in Manali",
        purpose="Identify popular hostels",
        priority=5,
    )

    assert query.priority == 5


def test_research_plan():

    plan = ResearchPlan(
        queries=[
            ResearchQuery(
                query="Manali hostel reviews",
                purpose="Find recurring complaints",
                priority=5,
            )
        ],
        research_goals=[
            "Identify traveller complaints",
            "Identify positive experiences",
        ],
        expected_output="Evidence-backed research report",
    )

    assert len(plan.queries) == 1