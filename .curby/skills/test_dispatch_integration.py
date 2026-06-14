"""Tests for Segment 3 — skill execution dispatch integration."""

import pytest
from .dispatch_integration import (
    QuickAskSkillDispatcher,
    AgentDispatchSkillRunner,
    prepare_quick_ask_for_execution,
    prepare_agent_for_execution,
)


class TestQuickAskSkillDispatcher:
    """Quick-ask dispatch with skill execution."""

    def test_dispatcher_init(self):
        """Create a QuickAskSkillDispatcher."""
        dispatcher = QuickAskSkillDispatcher()
        assert dispatcher.executor is not None

    def test_should_execute_skill(self):
        """Check if prompt should execute skill."""
        dispatcher = QuickAskSkillDispatcher()
        should_exec, skill = dispatcher.should_execute_skill("send email to alice")
        assert isinstance(should_exec, bool)
        assert skill is None or isinstance(skill, str)

    def test_dispatch_with_skill_fallback(self):
        """Dispatch prompt with skill fallback."""
        dispatcher = QuickAskSkillDispatcher()
        result = dispatcher.dispatch_with_skill_fallback("some task")

        assert isinstance(result, dict)
        assert "used_skill" in result
        assert "skill_name" in result
        assert "result" in result
        assert "latency_ms" in result
        assert "tier" in result
        assert result["tier"] in ["tier1", "claude"]

    def test_dispatch_result_fields(self):
        """Dispatch result has all required fields."""
        dispatcher = QuickAskSkillDispatcher()
        result = dispatcher.dispatch_with_skill_fallback("test")

        assert isinstance(result["used_skill"], bool)
        assert isinstance(result["latency_ms"], (int, float))
        assert result["latency_ms"] >= 0


class TestAgentDispatchSkillRunner:
    """Agent dispatch with skill execution."""

    def test_runner_init(self):
        """Create an AgentDispatchSkillRunner."""
        runner = AgentDispatchSkillRunner()
        assert runner.tiered_executor is not None

    def test_pre_execute(self):
        """Pre-execute attempt for prompt."""
        runner = AgentDispatchSkillRunner()
        result = runner.pre_execute("some task")

        assert isinstance(result, dict)
        assert "executed" in result
        assert "tier_used" in result
        assert "result" in result
        assert "fallback_reason" in result

    def test_pre_execute_not_executed(self):
        """Pre-execute can return non-executed."""
        runner = AgentDispatchSkillRunner()
        result = runner.pre_execute("xyz abc def obscure task")

        # Likely won't match any skills
        assert isinstance(result["executed"], bool)

    def test_get_skill_runner_prompt(self):
        """Generate skill runner prompt for agent."""
        runner = AgentDispatchSkillRunner()
        prompt = runner.get_skill_runner_prompt("book a restaurant")

        assert isinstance(prompt, str)
        # May be empty if no skill matches

    def test_get_skill_runner_prompt_empty(self):
        """Skill runner prompt can be empty for no-match."""
        runner = AgentDispatchSkillRunner()
        prompt = runner.get_skill_runner_prompt("xyz abc obscure")

        assert isinstance(prompt, str)


class TestPrepareQuickAskForExecution:
    """Integration: prepare quick-ask for execution."""

    def test_prepare_quick_ask_for_execution(self):
        """Prepare quick-ask prompt for execution."""
        result = prepare_quick_ask_for_execution(
            "send email",
            system_addendum="be brief"
        )

        assert isinstance(result, dict)
        assert "prompt" in result
        assert "system_addendum" in result
        assert "execution_plan" in result
        assert "should_skip_claude" in result

    def test_prepare_preserves_prompt(self):
        """Preparation preserves original prompt."""
        original = "my task"
        result = prepare_quick_ask_for_execution(original)
        assert result["prompt"] == original

    def test_prepare_enhances_system(self):
        """Preparation may enhance system addendum."""
        system = "original"
        result = prepare_quick_ask_for_execution("test", system_addendum=system)
        assert isinstance(result["system_addendum"], str)

    def test_prepare_has_execution_plan(self):
        """Result includes execution plan."""
        result = prepare_quick_ask_for_execution("task")
        plan = result["execution_plan"]
        assert "used_skill" in plan
        assert "tier" in plan


class TestPrepareAgentForExecution:
    """Integration: prepare agent for execution."""

    def test_prepare_agent_for_execution(self):
        """Prepare agent dispatch for execution."""
        result = prepare_agent_for_execution(
            "book a restaurant",
            base_system="You are helpful."
        )

        assert isinstance(result, dict)
        assert "prompt" in result
        assert "system" in result
        assert "execution_pre_attempt" in result
        assert "agent_should_skip" in result

    def test_prepare_preserves_agent_prompt(self):
        """Preparation preserves original prompt."""
        original = "do something"
        result = prepare_agent_for_execution(original)
        assert result["prompt"] == original

    def test_prepare_enhances_agent_system(self):
        """Preparation enhances system with skill context."""
        system = "You are helpful."
        result = prepare_agent_for_execution("test", base_system=system)
        assert isinstance(result["system"], str)
        # May have been enhanced with skill info

    def test_prepare_agent_skip_flag(self):
        """Result includes agent_should_skip flag."""
        result = prepare_agent_for_execution("task")
        assert isinstance(result["agent_should_skip"], bool)

    def test_prepare_agent_pre_execution_result(self):
        """Result includes pre_execution_result."""
        result = prepare_agent_for_execution("task")
        assert "pre_execution_result" in result


class TestEndToEndDispatchIntegration:
    """End-to-end dispatch integration scenarios."""

    def test_full_quick_ask_flow(self):
        """Full quick-ask execution flow."""
        result = prepare_quick_ask_for_execution(
            "send an email to alice",
            system_addendum="keep it brief"
        )

        # If skill matched and executed, skip Claude
        if result["should_skip_claude"]:
            assert result["execution_plan"]["result"] is not None
        # Otherwise, Claude will handle it
        else:
            assert result["prompt"] == "send an email to alice"

    def test_full_agent_flow(self):
        """Full agent execution flow."""
        result = prepare_agent_for_execution(
            "book a restaurant for 4",
            base_system="You are a helpful assistant."
        )

        # Pre-attempt may have succeeded
        if result["agent_should_skip"]:
            assert result["pre_execution_result"] is not None
        # Otherwise, agent will run with skill context
        else:
            assert isinstance(result["system"], str)

    def test_both_flows_same_prompt(self):
        """Both flows handle the same prompt."""
        prompt = "what is python"

        qa_result = prepare_quick_ask_for_execution(prompt)
        agent_result = prepare_agent_for_execution(prompt)

        # Both should succeed
        assert qa_result["prompt"] == prompt
        assert agent_result["prompt"] == prompt

    def test_complex_task_prompt(self):
        """Complex task with multiple potential skills."""
        prompt = "book a restaurant and send confirmation email to team"

        qa_result = prepare_quick_ask_for_execution(prompt)
        agent_result = prepare_agent_for_execution(prompt)

        # Complex tasks likely won't have Tier 1 match
        assert isinstance(qa_result["should_skip_claude"], bool)
        assert isinstance(agent_result["agent_should_skip"], bool)

    def test_empty_prompt_handling(self):
        """Empty prompt handling."""
        qa_result = prepare_quick_ask_for_execution("")
        agent_result = prepare_agent_for_execution("")

        # Both should handle gracefully
        assert qa_result["prompt"] == ""
        assert agent_result["prompt"] == ""
        assert isinstance(qa_result["should_skip_claude"], bool)
        assert isinstance(agent_result["agent_should_skip"], bool)
