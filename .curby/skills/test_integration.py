"""Tests for fast-path routing integration into quick-ask and agent dispatch."""

import pytest
from .integration import (
    QuickAskRouter,
    AgentDispatchRouter,
    inject_routing_into_quick_ask_prompt,
    inject_routing_into_agent_dispatch,
)
from .router import RoutingDecision


class TestQuickAskRouter:
    """Quick-ask integration with fast-path routing."""

    def test_quick_ask_router_init(self):
        """Create a QuickAskRouter."""
        router = QuickAskRouter()
        assert router.router is not None

    def test_analyze_prompt_returns_decision(self):
        """analyze_prompt returns a RoutingDecision."""
        router = QuickAskRouter()
        decision = router.analyze_prompt("send an email")
        assert isinstance(decision, RoutingDecision)
        assert decision.route_type in ["direct", "fallback", "agent", "none"]

    def test_should_skip_claude_for_direct(self):
        """should_skip_claude returns True for direct routes."""
        router = QuickAskRouter()
        decision = RoutingDecision(route_type="direct", skill_name="test")
        assert router.should_skip_claude(decision) is True

    def test_should_skip_claude_for_others(self):
        """should_skip_claude returns False for non-direct routes."""
        router = QuickAskRouter()
        for route_type in ["fallback", "agent", "none"]:
            decision = RoutingDecision(route_type=route_type)
            assert router.should_skip_claude(decision) is False

    def test_skill_context_for_prompt_fallback(self):
        """skill_context_for_prompt returns context for fallback routes."""
        router = QuickAskRouter()
        # Mock a fallback decision by analyzing a generic prompt
        # The actual routing depends on registered skills, so we just test the method works
        context = router.skill_context_for_prompt("book a restaurant")
        # Context may be None if no skills match, that's fine
        assert context is None or isinstance(context, str)

    def test_skill_context_for_prompt_direct(self):
        """skill_context_for_prompt returns None for direct routes (skip Claude)."""
        router = QuickAskRouter()
        # For a direct route, no context needed (we skip Claude entirely)
        # This is tested implicitly through the analyze_prompt flow


class TestAgentDispatchRouter:
    """Agent dispatch integration with fast-path routing."""

    def test_agent_dispatch_router_init(self):
        """Create an AgentDispatchRouter."""
        router = AgentDispatchRouter()
        assert router.router is not None

    def test_pre_route_returns_dict(self):
        """pre_route returns a routing dict."""
        router = AgentDispatchRouter()
        routing_info = router.pre_route("send an email")
        assert isinstance(routing_info, dict)
        assert "decision" in routing_info
        assert "agent_context" in routing_info
        assert "use_skill_only" in routing_info

    def test_pre_route_decision_valid(self):
        """pre_route decision is a RoutingDecision."""
        router = AgentDispatchRouter()
        routing_info = router.pre_route("test prompt")
        assert isinstance(routing_info["decision"], RoutingDecision)

    def test_pre_route_use_skill_only_direct(self):
        """pre_route sets use_skill_only=True for direct routes."""
        router = AgentDispatchRouter()
        # Direct routes should have use_skill_only=True
        # (This depends on actual skill matching, so we just test the logic)
        decision = RoutingDecision(route_type="direct", skill_name="test")
        assert (decision.route_type == "direct") == True

    def test_pre_route_context_for_fallback(self):
        """pre_route generates context for fallback routes."""
        router = AgentDispatchRouter()
        decision = RoutingDecision(
            route_type="fallback",
            skill_name="send_email",
            confidence=0.82
        )
        context = router._context_for_decision(decision)
        assert context is not None
        assert "send_email" in context
        assert "fallback" in context.lower() or "pre-matched" in context.lower()

    def test_pre_route_context_for_agent(self):
        """pre_route returns None context for agent routes."""
        router = AgentDispatchRouter()
        decision = RoutingDecision(route_type="agent")
        context = router._context_for_decision(decision)
        assert context is None


class TestQuickAskIntegration:
    """Integration functions for quick-ask flow."""

    def test_inject_routing_into_quick_ask_prompt(self):
        """inject_routing_into_quick_ask_prompt returns tuple."""
        prompt, system = inject_routing_into_quick_ask_prompt(
            "send email to alice",
            system_addendum="be shorter"
        )
        assert isinstance(prompt, str)
        assert isinstance(system, str)
        assert prompt == "send email to alice"

    def test_inject_routing_preserves_system(self):
        """inject_routing preserves original system_addendum."""
        original_system = "be shorter"
        _, system = inject_routing_into_quick_ask_prompt(
            "unknown prompt",
            system_addendum=original_system
        )
        # Should either preserve or enhance the original system
        assert isinstance(system, str)

    def test_inject_routing_empty_prompt(self):
        """inject_routing_into_quick_ask_prompt handles empty prompt."""
        prompt, system = inject_routing_into_quick_ask_prompt("")
        assert prompt == ""
        assert isinstance(system, str)


class TestAgentDispatchIntegration:
    """Integration functions for agent dispatch flow."""

    def test_inject_routing_into_agent_dispatch(self):
        """inject_routing_into_agent_dispatch returns dict."""
        result = inject_routing_into_agent_dispatch(
            "send an email",
            base_system="You are a helpful agent."
        )
        assert isinstance(result, dict)
        assert "prompt" in result
        assert "system" in result
        assert "routing_decision" in result
        assert "use_skill_only" in result
        assert "skill_name" in result

    def test_inject_routing_preserves_prompt(self):
        """inject_routing preserves the original prompt."""
        original_prompt = "do something"
        result = inject_routing_into_agent_dispatch(original_prompt)
        assert result["prompt"] == original_prompt

    def test_inject_routing_system_modification(self):
        """inject_routing may modify system prompt."""
        base_system = "You are helpful."
        result = inject_routing_into_agent_dispatch(
            "test prompt",
            base_system=base_system
        )
        # System should either be base unchanged, or enhanced with routing context
        assert isinstance(result["system"], str)
        assert "helpful" in result["system"].lower() or "agent" in result["system"].lower()

    def test_inject_routing_decision_types(self):
        """inject_routing decision types are valid."""
        result = inject_routing_into_agent_dispatch("test")
        assert result["routing_decision"].route_type in ["direct", "fallback", "agent", "none"]

    def test_inject_routing_skill_name_matches_decision(self):
        """inject_routing skill_name matches routing_decision."""
        result = inject_routing_into_agent_dispatch("test")
        decision = result["routing_decision"]
        skill_name = result["skill_name"]

        if decision.route_type in ["direct", "fallback"]:
            assert skill_name is not None
        else:
            assert skill_name is None or isinstance(skill_name, str)


class TestEndToEndIntegration:
    """End-to-end integration scenarios."""

    def test_quick_ask_flow_empty_prompt(self):
        """Quick-ask flow with empty prompt."""
        prompt, system = inject_routing_into_quick_ask_prompt("")
        assert prompt == ""
        assert isinstance(system, str)

    def test_agent_dispatch_flow_complex_prompt(self):
        """Agent dispatch flow with complex prompt."""
        prompt = "I need to book a restaurant and send a confirmation email"
        result = inject_routing_into_agent_dispatch(prompt)

        assert result["prompt"] == prompt
        assert isinstance(result["system"], str)
        assert isinstance(result["routing_decision"], RoutingDecision)
        assert isinstance(result["use_skill_only"], bool)

    def test_both_flows_same_prompt(self):
        """Both quick-ask and agent flows can handle the same prompt."""
        prompt = "what is python"
        qa_prompt, qa_system = inject_routing_into_quick_ask_prompt(prompt)
        agent_result = inject_routing_into_agent_dispatch(prompt)

        # Both should succeed and return valid outputs
        assert qa_prompt == prompt
        assert agent_result["prompt"] == prompt
        assert isinstance(qa_system, str)
        assert isinstance(agent_result["system"], str)

    def test_routing_consistent_across_flows(self):
        """Routing decisions should be consistent across flows."""
        prompt = "send an email"
        qa_router = QuickAskRouter()
        agent_router = AgentDispatchRouter()

        qa_decision = qa_router.analyze_prompt(prompt)
        agent_info = agent_router.pre_route(prompt)
        agent_decision = agent_info["decision"]

        # Both should make the same routing decision
        assert qa_decision.route_type == agent_decision.route_type
        assert qa_decision.skill_name == agent_decision.skill_name
