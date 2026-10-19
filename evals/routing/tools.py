"""The read-only tool surface the router chooses between.

The names and boundaries are `_docs/product-spec.md` `R-F4.1`, which M4's MCP server will expose. The
spike does not call them: it only decides which one a message needs, and records the choice. The contract
path each tool would call is kept here so a test can fail when `openapi.yaml` loses or renames an operation
the router is allowed to pick.

One gap is deliberate: the database stores top scorers (M2), but `R-F4.1` has no scorer tool. Questions in
the `scorers` class are labelled `route: tool` with no expected tool; the route is scored and the gap is
recorded in decision 0003 rather than papered over here.
"""

from __future__ import annotations

from dataclasses import dataclass

NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    operation: str
    method: str = "get"

    def as_criterion(self) -> str:
        return self.description


TOOLS: tuple[Tool, ...] = (
    Tool(
        name="get_standings",
        description="League table: position, points and goal difference.",
        operation="/competitions/{code}/standings",
    ),
    Tool(
        name="get_fixtures",
        description="Upcoming match dates and kick-off times.",
        operation="/competitions/{code}/matches",
    ),
    Tool(
        name="get_match_result",
        description="The score and status of a played match.",
        operation="/matches/{matchId}",
    ),
    Tool(
        name="get_team_form",
        description="A team's recent results and form.",
        operation="/teams/{teamId}/form",
    ),
    Tool(
        name="get_head_to_head",
        description="Results and win counts between two teams.",
        operation="/head-to-head",
    ),
    Tool(
        name="get_data_freshness",
        description="How old the stored data is and when it was refreshed.",
        operation="/meta/freshness",
    ),
)

KNOWLEDGE_TOOL = Tool(
    name="search_knowledge",
    description="The hand-written notes: rules, formats, definitions and policy.",
    operation="/search/knowledge",
)

#: Every tool the router may name, the notes tool included. `not_applicable` is a choice label, not a tool.
TOOL_BY_NAME: dict[str, Tool] = {tool.name: tool for tool in TOOLS + (KNOWLEDGE_TOOL,)}

#: The tool question both models answer in the same forward pass as the surface. Kept under 20 options
#: (the decision-head cap is 26 per choice; large label sets dilute each option's token budget).
TOOL_CHOICES: dict[str, str] = {
    **{tool.name: tool.as_criterion() for tool in TOOLS},
    NOT_APPLICABLE: "No database tool: the route is notes, clarify or refuse.",
}

#: Recorded in decision 0003 and `_docs/data-model.md`; a scorer question can route correctly and still be
#: unanswerable until M4 adds the tool.
MISSING_SCORER_TOOL = "R-F4.1 exposes no top-scorer tool although the database stores scorer snapshots."
