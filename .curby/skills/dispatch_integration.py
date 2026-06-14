"""Segment 3: Skill execution integration into dispatch flows."""

from typing import Dict, Any, Optional
from .integration import inject_routing_into_quick_ask_prompt, inject_routing_into_agent_dispatch
from .executor_safe import SafeSkillExecutor, TieredSkillExecutor


class QuickAskSkillDispatcher:
    """Dispatch quick-ask prompts with skill execution."""

    def __init__(self):
        self.executor = SafeSkillExecutor()

    def should_execute_skill(self, prompt: str) -> tuple[bool, Optional[str]]:
        """Check if a prompt should be routed to skill execution (Tier 1).

        Returns (should_execute, skill_name)
        """
        _, system = inject_routing_into_quick_ask_prompt(prompt)
        # In production, check if the routing context shows a direct tier 1 match
        # For now, return False (no direct execution without full integration)
        return False, None

    def dispatch_with_skill_fallback(self, prompt: str) -> Dict[str, Any]:
        """Dispatch a prompt with skill execution fallback.

        Returns dict with:
        - used_skill: bool — whether a skill was executed
        - skill_name: str | None — which skill was executed
        - result: str — response text
        - latency_ms: float
        """
        should_execute, skill_name = self.should_execute_skill(prompt)

        if should_execute and skill_name:
            # Execute skill directly
            exec_result = self.executor.execute_skill(skill_name, prompt)
            if self.executor.validate_result(exec_result):
                return {
                    "used_skill": True,
                    "skill_name": skill_name,
                    "result": exec_result.output,
                    "latency_ms": exec_result.latency_ms,
                    "tier": "tier1",
                }

        # Fall back to normal quick-ask (Claude path)
        return {
            "used_skill": False,
            "skill_name": None,
            "result": None,  # Will be filled by Claude
            "latency_ms": 0,
            "tier": "claude",
        }


class AgentDispatchSkillRunner:
    """Provide skill execution capability to agent dispatch."""

    def __init__(self):
        self.tiered_executor = TieredSkillExecutor()

    def pre_execute(self, prompt: str) -> Dict[str, Any]:
        """Try to execute prompt before agent dispatch.

        Returns dict with:
        - executed: bool — whether execution succeeded
        - tier_used: str — "tier1", "tier2", or None
        - result: str | None — execution output
        - fallback_reason: str | None
        """
        routing_info = inject_routing_into_agent_dispatch(prompt)
        routing_decision = routing_info["routing_decision"]

        if not routing_decision.skill_name:
            return {
                "executed": False,
                "tier_used": None,
                "result": None,
                "fallback_reason": "No matching skill found",
            }

        # Try to execute the matched skill
        exec_info = self.tiered_executor.execute_with_fallback(
            prompt,
            tier1_skill=routing_decision.skill_name if routing_decision.route_type == "direct" else None,
            tier2_skill=routing_decision.skill_name if routing_decision.route_type == "fallback" else None,
            fallback_to_agent=True,
        )

        if exec_info["result"] is not None and exec_info["result"].success:
            return {
                "executed": True,
                "tier_used": exec_info["tier_used"],
                "result": exec_info["result"].output,
                "fallback_reason": None,
            }

        return {
            "executed": False,
            "tier_used": exec_info["tier_used"],
            "result": None,
            "fallback_reason": exec_info["fallback_reason"],
        }

    def get_skill_runner_prompt(self, prompt: str) -> str:
        """Generate a prompt for agents that includes skill availability.

        This tells the agent what skills are available for execution.
        """
        routing_info = inject_routing_into_agent_dispatch(prompt)
        routing_decision = routing_info["routing_decision"]

        if not routing_decision.skill_name:
            return ""

        skill_info = (
            f"Available skill: {routing_decision.skill_name} "
            f"(confidence: {routing_decision.confidence:.0%}, "
            f"tier: {routing_decision.route_type})\n"
            f"You can try executing this skill with the provided skill runner."
        )
        return skill_info


def prepare_quick_ask_for_execution(
    prompt: str,
    system_addendum: str = "",
) -> Dict[str, Any]:
    """Prepare a quick-ask prompt for potential skill execution.

    Returns dict with:
    - prompt: str
    - system_addendum: str (updated)
    - execution_plan: Dict with execution info
    """
    dispatcher = QuickAskSkillDispatcher()
    execution_plan = dispatcher.dispatch_with_skill_fallback(prompt)

    modified_prompt, modified_system = inject_routing_into_quick_ask_prompt(
        prompt,
        system_addendum=system_addendum,
    )

    return {
        "prompt": modified_prompt,
        "system_addendum": modified_system,
        "execution_plan": execution_plan,
        "should_skip_claude": execution_plan["used_skill"],
    }


def prepare_agent_for_execution(
    prompt: str,
    base_system: str = "",
) -> Dict[str, Any]:
    """Prepare an agent dispatch for potential skill execution.

    Returns dict with:
    - prompt: str
    - system: str (updated with skill context)
    - execution_pre_attempt: Dict with pre-execution info
    - agent_should_use_skills: bool
    """
    dispatcher = AgentDispatchSkillRunner()

    # First, try to execute before agent
    pre_attempt = dispatcher.pre_execute(prompt)

    # If pre-execution succeeded, don't send to agent
    if pre_attempt["executed"]:
        return {
            "prompt": prompt,
            "system": base_system,
            "execution_pre_attempt": pre_attempt,
            "agent_should_skip": True,
            "pre_execution_result": pre_attempt["result"],
        }

    # Otherwise, prepare agent with skill context
    routing_info = inject_routing_into_agent_dispatch(prompt, base_system)
    skill_runner_prompt = dispatcher.get_skill_runner_prompt(prompt)

    final_system = routing_info["system"]
    if skill_runner_prompt:
        final_system = f"{final_system}\n\n[Skill Availability]\n{skill_runner_prompt}"

    return {
        "prompt": routing_info["prompt"],
        "system": final_system.strip(),
        "execution_pre_attempt": pre_attempt,
        "agent_should_skip": False,
        "pre_execution_result": None,
        "skill_name": routing_info["skill_name"],
    }
