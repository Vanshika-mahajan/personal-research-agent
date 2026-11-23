from app.graph.state import ResearchState
from app.schemas.research import ResearchPlan, ResearchQuery


def research_planner(state: ResearchState) -> dict:
    """Create the initial research plan."""

    question = state["question"]

    plan = ResearchPlan(
        queries=[
            ResearchQuery(
                query=question.question,
                purpose="Understand the main topic",
                priority=5,
            ),
            ResearchQuery(
                query=f"{question.question} reviews complaints",
                purpose="Find recurring problems and negative experiences",
                priority=4,
            ),
            ResearchQuery(
                query=f"{question.question} reviews positive experiences",
                purpose="Find recurring positive experiences",
                priority=4,
            ),
        ],
        research_goals=[
            "Understand the topic",
            "Identify recurring problems",
            "Identify positive experiences",
        ],
        expected_output="Evidence-backed research report",
    )

    return {
        "research_plan": plan,
        "iteration": 0,
        "max_iterations": question.max_iterations,
    }


def mock_research(state: ResearchState) -> dict:
    """
    Temporary research node.

    We are deliberately using fake research here to test
    the LangGraph loop before adding real web tools.
    """

    iteration = state.get("iteration", 0)

    return {
        "iteration": iteration + 1,
    }


def quality_check(state: ResearchState) -> dict:
    """
    Temporary quality checker.

    For testing:
    iterations 1 and 2 -> insufficient
    iteration 3 -> sufficient
    """

    iteration = state.get("iteration", 0)

    if iteration < 3:
        return {
            "missing_information": [
                "Additional evidence is required."
            ],
            "evidence_score": iteration / 3,
        }

    return {
        "missing_information": [],
        "evidence_score": 1.0,
    }