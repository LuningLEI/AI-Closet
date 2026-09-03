from __future__ import annotations

from dataclasses import dataclass

from app.agent.intents import AgentIntent, IntentName
from app.agent.planner import AgentPlanner
from app.agent.skills import CatalogAdviceSkill, ClosetSummarySkill, RecommendationSkill, SkillResult, build_skill_call
from app.models.api import ChatResponse
from app.repositories.closet_repository import ClosetRepository
from app.services.recommendation import RecommendationEngine


@dataclass(frozen=True)
class AgentPlanStep:
    skill_name: str
    reason: str


class WardrobeAgentRuntime:
    """
    A lightweight agent runtime with explicit intent detection, planning, and skill execution.
    It stays deterministic for local development while exposing the same shape a more formal
    planner-executor agent would use.
    """

    def __init__(self, repository: ClosetRepository, recommendation_engine: RecommendationEngine) -> None:
        self.planner = AgentPlanner()
        self.summary_skill = ClosetSummarySkill(repository)
        self.recommend_skill = RecommendationSkill(repository, recommendation_engine)
        self.catalog_skill = CatalogAdviceSkill(repository)
        self.skill_registry = {
            IntentName.RECOMMEND: self.recommend_skill,
            IntentName.SUMMARY: self.summary_skill,
            IntentName.ADVICE: self.catalog_skill,
        }

    def respond(self, message: str, user_id: str | None = None) -> ChatResponse:
        intent = self.planner.plan(message)
        plan = self._build_plan(intent)
        execution_results: list[tuple[AgentPlanStep, SkillResult]] = []
        skills_used = []
        metadata = {"intent": intent.as_metadata(), "plan": [step.__dict__ for step in plan]}

        for step in plan:
            skill = self.skill_registry[step.skill_name]
            result = skill.run(message, user_id, intent=intent)
            execution_results.append((step, result))
            skills_used.append(build_skill_call(skill.name, result.payload))

            if step.skill_name == IntentName.RECOMMEND:
                metadata["recommendations"] = result.payload.get("recommendations", [])
                metadata["recommendation_context"] = result.payload.get("context")
            elif step.skill_name == IntentName.SUMMARY:
                metadata["summary"] = result.payload.get("summary")
            elif step.skill_name == IntentName.ADVICE:
                metadata["system"] = result.payload

        reply = self._compose_reply(intent, execution_results)
        return ChatResponse(reply=reply, metadata=metadata, skills_used=skills_used)

    def _build_plan(self, intent: AgentIntent) -> list[AgentPlanStep]:
        steps: list[AgentPlanStep] = []

        if IntentName.RECOMMEND in intent.intents:
            steps.append(
                AgentPlanStep(
                    skill_name=IntentName.RECOMMEND,
                    reason="The user is asking for outfit generation or styling guidance.",
                )
            )

        if IntentName.SUMMARY in intent.intents:
            steps.append(
                AgentPlanStep(
                    skill_name=IntentName.SUMMARY,
                    reason="The user is asking about closet coverage, gaps, or inventory state.",
                )
            )

        if not steps:
            steps.append(
                AgentPlanStep(
                    skill_name=IntentName.ADVICE,
                    reason="Fallback to general wardrobe guidance when the request is not clearly actionable.",
                )
            )
        elif intent.primary_intent == IntentName.ADVICE and IntentName.ADVICE not in intent.intents:
            steps.append(
                AgentPlanStep(
                    skill_name=IntentName.ADVICE,
                    reason="Add explanation context because the user is also asking for strategy or improvement advice.",
                )
            )

        return steps

    def _compose_reply(
        self,
        intent: AgentIntent,
        execution_results: list[tuple[AgentPlanStep, SkillResult]],
    ) -> str:
        result_by_skill = {step.skill_name: result for step, result in execution_results}
        parts: list[str] = []

        if recommendation := result_by_skill.get(IntentName.RECOMMEND):
            parts.append(recommendation.summary)

        if summary := result_by_skill.get(IntentName.SUMMARY):
            if intent.primary_intent == IntentName.SUMMARY:
                parts.append(summary.summary)
            else:
                parts.append("Closet context: " + summary.summary)

        if advice := result_by_skill.get(IntentName.ADVICE):
            parts.append(advice.summary)

        return " ".join(parts)
