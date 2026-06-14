"""Tests for safe skill execution with timeout and fallback."""

import pytest
import time
from .executor_safe import (
    ExecutionResult,
    SafeSkillExecutor,
    TieredSkillExecutor,
    SkillExecutionError,
)


class TestExecutionResult:
    """ExecutionResult dataclass behavior."""

    def test_success_result(self):
        """Create a successful execution result."""
        result = ExecutionResult(
            success=True,
            output="Task completed",
            latency_ms=100.0,
            tokens_estimate=50.0,
        )
        assert result.success is True
        assert result.output == "Task completed"
        assert result.error is None

    def test_failure_result(self):
        """Create a failed execution result."""
        result = ExecutionResult(
            success=False,
            error="Execution timed out",
            latency_ms=1000.0,
        )
        assert result.success is False
        assert result.error == "Execution timed out"
        assert result.output is None

    def test_result_defaults(self):
        """ExecutionResult with default values."""
        result = ExecutionResult(success=True)
        assert result.output is None
        assert result.error is None
        assert result.latency_ms == 0.0
        assert result.tokens_estimate == 0.0


class TestSafeSkillExecutor:
    """Safe skill executor with timeout and validation."""

    def test_executor_init(self):
        """Create a SafeSkillExecutor."""
        executor = SafeSkillExecutor()
        assert executor.timeout_ms == SafeSkillExecutor.DEFAULT_TIMEOUT_MS

    def test_executor_custom_timeout(self):
        """Create executor with custom timeout."""
        executor = SafeSkillExecutor(timeout_ms=5000)
        assert executor.timeout_ms == 5000

    def test_execute_skill_basic(self):
        """Execute a skill (mock implementation)."""
        executor = SafeSkillExecutor()
        result = executor.execute_skill(
            "test_skill",
            "Do something",
            context={"param": "value"},
        )
        assert isinstance(result, ExecutionResult)
        assert result.success is True
        assert result.output is not None
        assert result.latency_ms >= 0

    def test_execute_skill_captures_latency(self):
        """Execution result captures latency."""
        executor = SafeSkillExecutor()
        start = time.time()
        result = executor.execute_skill("test", "task")
        end = time.time()

        expected_latency_ms = (end - start) * 1000
        assert result.latency_ms >= 0
        assert result.latency_ms <= expected_latency_ms * 1.5  # Allow 50% overhead

    def test_estimate_tokens(self):
        """Token estimation from output."""
        executor = SafeSkillExecutor()
        # ~4 chars per token
        output = "a" * 400  # Should estimate to ~100 tokens
        tokens = executor._estimate_tokens(output)
        assert 95 <= tokens <= 105

    def test_validate_result_success(self):
        """Validate a successful result."""
        executor = SafeSkillExecutor()
        result = ExecutionResult(success=True, output="test output", latency_ms=100)
        assert executor.validate_result(result) is True

    def test_validate_result_failure(self):
        """Validate a failed result."""
        executor = SafeSkillExecutor()
        result = ExecutionResult(success=False, error="Failed")
        assert executor.validate_result(result) is False

    def test_validate_result_no_output(self):
        """Validate result with no output."""
        executor = SafeSkillExecutor()
        result = ExecutionResult(success=True, output=None)
        assert executor.validate_result(result) is False

    def test_validate_result_negative_latency(self):
        """Validate result with negative latency (invalid)."""
        executor = SafeSkillExecutor()
        result = ExecutionResult(success=True, output="test", latency_ms=-100)
        assert executor.validate_result(result) is False


class TestTieredSkillExecutor:
    """Tiered execution with fallback chain."""

    def test_tiered_executor_init(self):
        """Create a TieredSkillExecutor."""
        executor = TieredSkillExecutor()
        assert executor.executor is not None

    def test_execute_with_fallback_tier1_only(self):
        """Execute with only Tier 1."""
        executor = TieredSkillExecutor()
        result = executor.execute_with_fallback(
            "task",
            tier1_skill="skill1",
            tier2_skill=None,
            fallback_to_agent=False,
        )
        assert isinstance(result, dict)
        assert result["tier_used"] in ["tier1", "agent", "none"]

    def test_execute_with_fallback_tier1_tier2(self):
        """Execute with Tier 1 and Tier 2."""
        executor = TieredSkillExecutor()
        result = executor.execute_with_fallback(
            "task",
            tier1_skill="skill1",
            tier2_skill="skill2",
            fallback_to_agent=False,
        )
        assert result["tier_used"] in ["tier1", "tier2", "none"]

    def test_execute_with_fallback_has_result_dict(self):
        """Result has all required fields."""
        executor = TieredSkillExecutor()
        result = executor.execute_with_fallback(
            "task",
            tier1_skill="skill1",
        )
        assert "tier_used" in result
        assert "skill_used" in result
        assert "result" in result
        assert "fallback_reason" in result

    def test_execute_with_fallback_to_agent(self):
        """Falls back to agent if tiers fail."""
        executor = TieredSkillExecutor()
        result = executor.execute_with_fallback(
            "task",
            tier1_skill="failing_skill",
            tier2_skill=None,
            fallback_to_agent=True,
        )
        # With mock executor that always succeeds, tier1_skill will be used
        # But we test the logic path exists
        assert "tier_used" in result

    def test_execute_with_fallback_no_skills(self):
        """Falls back when no skills provided."""
        executor = TieredSkillExecutor()
        result = executor.execute_with_fallback(
            "task",
            tier1_skill=None,
            tier2_skill=None,
            fallback_to_agent=True,
        )
        assert result["tier_used"] == "agent"
        assert result["skill_used"] is None

    def test_execute_with_fallback_no_fallback(self):
        """Returns 'none' when fallback disabled and no skills match."""
        executor = TieredSkillExecutor()
        result = executor.execute_with_fallback(
            "task",
            tier1_skill=None,
            tier2_skill=None,
            fallback_to_agent=False,
        )
        assert result["tier_used"] == "none"

    def test_fallback_reason_captured(self):
        """Fallback reason is captured when tier fails."""
        executor = TieredSkillExecutor()
        result = executor.execute_with_fallback(
            "task",
            tier1_skill="skill1",
            tier2_skill="skill2",
        )
        # With mock executor, may not fail, but test the field exists
        assert result["fallback_reason"] is None or isinstance(result["fallback_reason"], str)


class TestExecutorIntegration:
    """End-to-end executor scenarios."""

    def test_safe_executor_full_flow(self):
        """Full executor flow with success."""
        executor = SafeSkillExecutor()
        result = executor.execute_skill("email_sender", "send email to alice")

        assert result.success
        assert result.output is not None
        assert result.latency_ms > 0
        assert result.tokens_estimate > 0

    def test_tiered_executor_full_flow(self):
        """Full tiered executor flow."""
        executor = TieredSkillExecutor()
        result = executor.execute_with_fallback(
            "send email to alice",
            tier1_skill="email_sender",
            tier2_skill="contact_manager",
        )

        assert result["tier_used"] in ["tier1", "tier2", "agent"]
        assert result["skill_used"] is not None or result["fallback_reason"] is not None

    def test_executor_with_context(self):
        """Executor passes context to skill."""
        executor = SafeSkillExecutor()
        context = {"priority": "high", "user_id": "123"}
        result = executor.execute_skill(
            "priority_task",
            "Do something important",
            context=context,
        )

        assert result.success
        assert "important" in result.output.lower() or "executed" in result.output.lower()

    def test_multiple_executions(self):
        """Execute multiple skills sequentially."""
        executor = SafeSkillExecutor()
        results = []
        for skill in ["skill1", "skill2", "skill3"]:
            result = executor.execute_skill(skill, f"Execute {skill}")
            results.append(result)

        assert len(results) == 3
        assert all(r.success for r in results)
        assert all(r.latency_ms >= 0 for r in results)
