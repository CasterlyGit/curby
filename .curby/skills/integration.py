"""Integration hooks for fast-path routing into quick-ask and agent dispatch flows."""

from typing import Optional, Dict, Any
from .router import FastPathRouter, RoutingDecision


class QuickAskRouter:
    """Route quick-ask prompts through fast-path tier 1-2 logic."""

    def __init__(self):
        self.router = FastPathRouter()

    def analyze_prompt(self, prompt: str) -> RoutingDecision:
        """Analyze a prompt and return routing decision.

        Can be used in quick_ask.run_quick_ask() to decide whether to:
        - Execute a skill directly (Tier 1)
        - Seed the agent with skill context (Tier 2)
        - Use standard agent dispatch (fallback)
        """
        return self.router.route(prompt)

    def should_skip_claude(self, decision: RoutingDecision) -> bool:
        """Check if we should skip Claude and execute skill directly."""
        return decision.route_type == "direct"

    def skill_context_for_prompt(self, prompt: str) -> Optional[str]:
        """Generate skill context to prepend to Claude's system prompt (Tier 2)."""
        decision = self.router.route(prompt)

        if decision.route_type == "fallback" and decision.skill_name:
            return (
                f"A pre-matched skill is available for this task:\n"
                f"- Skill: {decision.skill_name}\n"
                f"- Confidence: {decision.confidence:.0%}\n"
                f"- Reason: {decision.reason}\n"
                f"Consider using this skill if it's appropriate for the task."
            )

        return None


class AgentDispatchRouter:
    """Route agent-spawn tasks through fast-path logic."""

    def __init__(self):
        self.router = FastPathRouter()

    def pre_route(self, prompt: str) -> Dict[str, Any]:
        """Pre-route an agent dispatch task.

        Returns a dict with routing info:
        - decision: RoutingDecision
        - agent_context: str | None — context to inject into agent prompt
        - use_skill_only: bool — if True, don't spawn agent, just execute skill
        """
        decision = self.router.route(prompt)

        return {
            "decision": decision,
            "agent_context": self._context_for_decision(decision),
            "use_skill_only": decision.route_type == "direct",
        }

    def _context_for_decision(self, decision: RoutingDecision) -> Optional[str]:
        """Generate context for the agent based on routing decision."""
        if decision.route_type == "direct":
            return f"Execute skill '{decision.skill_name}' directly (pre-matched)."
        elif decision.route_type == "fallback":
            return (
                f"A pre-matched skill is available:\n"
                f"- Skill: {decision.skill_name}\n"
                f"- Confidence: {decision.confidence:.0%}\n"
                f"Try this skill first. If it fails, proceed with standard dispatch."
            )
        return None


def inject_routing_into_quick_ask_prompt(
    original_prompt: str,
    system_addendum: str = ""
) -> tuple[str, str]:
    """Analyze a quick-ask prompt and inject routing context.

    Returns (possibly_modified_prompt, modified_system_addendum).

    If Tier 1 route detected, the caller should consider skipping Claude entirely.
    If Tier 2 route detected, context is injected into system_addendum.
    """
    router = QuickAskRouter()
    decision = router.analyze_prompt(original_prompt)

    skill_context = router.skill_context_for_prompt(original_prompt)
    if skill_context:
        system_addendum = f"{system_addendum}\n\n{skill_context}".strip()

    return original_prompt, system_addendum


def inject_routing_into_agent_dispatch(
    original_prompt: str,
    base_system: str = ""
) -> Dict[str, Any]:
    """Analyze an agent dispatch prompt and inject routing context.

    Returns a dict with:
    - prompt: str (original, unmodified)
    - system: str (possibly modified with routing context)
    - routing_decision: RoutingDecision
    - use_skill_only: bool
    - skill_name: str | None
    """
    dispatcher = AgentDispatchRouter()
    routing_info = dispatcher.pre_route(original_prompt)
    decision = routing_info["decision"]

    system = base_system
    if routing_info["agent_context"]:
        system = f"{system}\n\n[Routing Context]\n{routing_info['agent_context']}"

    return {
        "prompt": original_prompt,
        "system": system.strip(),
        "routing_decision": decision,
        "use_skill_only": routing_info["use_skill_only"],
        "skill_name": decision.skill_name if decision.skill_name else None,
    }
