"""Fast-path skill router — Tier 1 (direct) and Tier 2 (fallback) routing."""

from dataclasses import dataclass
from typing import Optional
from .manifest import SkillRegistry
from .loader import SkillLoader
from .orchestrator import WorkflowOrchestrator
from .learning import SkillConflictResolver


@dataclass
class RoutingDecision:
    """Result of fast-path routing analysis."""
    route_type: str  # "direct", "fallback", "agent", "none"
    skill_name: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""


class FastPathRouter:
    """Route tasks directly to high-confidence skills, fallback to agent if needed."""

    TIER1_CONFIDENCE_THRESHOLD = 0.95
    TIER1_SUCCESS_RATE_THRESHOLD = 0.9
    TIER2_CONFIDENCE_THRESHOLD = 0.7
    TIER2_CANDIDATE_LIMIT = 3

    def __init__(self):
        self.registry = SkillRegistry()
        loader = SkillLoader()
        self.orchestrator = WorkflowOrchestrator(loader)
        self.conflict_resolver = SkillConflictResolver()

    def route(self, prompt: str) -> RoutingDecision:
        """
        Analyze a prompt and decide routing tier.

        Returns:
            RoutingDecision with route_type in ["direct", "fallback", "agent", "none"]
            - "direct": Tier 1 — execute skill immediately (confidence ≥ 0.95, success ≥ 0.9)
            - "fallback": Tier 2 — offer skill to agent, fall back to full agent if fails
            - "agent": Standard agent dispatch (no matching skill)
            - "none": Unable to process
        """
        if not prompt or not prompt.strip():
            return RoutingDecision(
                route_type="agent",
                reason="Empty prompt"
            )

        # Try to find matching skills
        matches = self.orchestrator.match_task(prompt)

        if not matches:
            return RoutingDecision(
                route_type="agent",
                reason="No skills matched"
            )

        # Tier 1: High-confidence direct routing
        for match in matches:
            if match.confidence >= self.TIER1_CONFIDENCE_THRESHOLD:
                metadata = self.registry.lookup(match.skill_name)
                success_rate = metadata.success_rate if metadata else 0.0

                if success_rate >= self.TIER1_SUCCESS_RATE_THRESHOLD:
                    return RoutingDecision(
                        route_type="direct",
                        skill_name=match.skill_name,
                        confidence=match.confidence,
                        reason=f"High-confidence direct match (confidence={match.confidence:.2f}, success_rate={success_rate:.2%})"
                    )

        # Tier 2: Fallback routing with top candidates
        candidates = [
            match for match in matches
            if match.confidence >= self.TIER2_CONFIDENCE_THRESHOLD
        ][:self.TIER2_CANDIDATE_LIMIT]

        if candidates:
            # Pick the best candidate (highest confidence, or use resolver if tied)
            best = max(candidates, key=lambda m: m.confidence)
            return RoutingDecision(
                route_type="fallback",
                skill_name=best.skill_name,
                confidence=best.confidence,
                reason=f"Fallback candidate (confidence={best.confidence:.2f}, {len(candidates)} candidates)"
            )

        return RoutingDecision(
            route_type="agent",
            reason="No skills met fallback threshold"
        )

    def explain(self, decision: RoutingDecision) -> str:
        """Human-readable explanation of a routing decision."""
        if decision.route_type == "direct":
            return f"🎯 DIRECT: {decision.skill_name} ({decision.confidence:.0%})"
        elif decision.route_type == "fallback":
            return f"📌 FALLBACK: {decision.skill_name} ({decision.confidence:.0%})"
        elif decision.route_type == "agent":
            return f"🤖 AGENT: {decision.reason}"
        else:
            return f"❌ NONE: {decision.reason}"
