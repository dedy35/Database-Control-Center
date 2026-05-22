from __future__ import annotations

from typing import Any

from src.activity_log import log_activity
from src.ai_plan_validator import validate_filter_plan, validate_write_proposal
from src.write_guard import WriteActionPlan


class AIActionRouter:
    def __init__(self, window) -> None:
        self.window = window

    def route(self, response: dict[str, Any], page_context: dict[str, Any]) -> dict[str, Any]:
        response_type = str(response.get("type") or "explanation")
        result = dict(response)

        if response_type == "filter_plan" and response.get("filter_plan"):
            validated = validate_filter_plan(
                response["filter_plan"],
                allowed_tables=self.window.get_available_tables(),
                allowed_columns=self.window.allowed_columns_for_table(str(response["filter_plan"].get("table") or "")),
            )
            result["filter_plan"] = validated
            log_activity("AI_FILTER_PLAN_CREATED", "AI created a filter plan.", {"table": validated.get("table")})
            return result

        if response_type == "write_proposal" and response.get("write_proposal"):
            proposal = validate_write_proposal(
                response["write_proposal"],
                allowed_tables=self.window.get_available_tables(),
                allowed_columns_by_table=self.window.allowed_columns_by_table(),
            )
            write_plan = self.window.build_write_plan_from_ai_proposal(proposal, page_context)
            result["write_plan"] = write_plan
            log_activity(
                "AI_WRITE_PROPOSAL_CREATED",
                "AI created a write proposal that still requires approval.",
                {"action": proposal.get("action"), "table": proposal.get("table")},
            )
            return result

        if response_type == "report_draft":
            log_activity("AI_REPORT_DRAFT_CREATED", "AI created a report draft.", {"page": page_context.get("page")})
            return result

        return result

    def apply_filter_plan(self, plan: dict[str, Any]) -> None:
        self.window.data_explorer_page.apply_query_plan(plan)
        self.window.navigate_to("Data Explorer")
        log_activity("AI_FILTER_PLAN_APPLIED", "AI filter plan was applied in Data Explorer.", {"table": plan.get("table")})

    def review_write_plan(self, plan: WriteActionPlan) -> None:
        self.window.review_and_execute_write_plan(plan)

