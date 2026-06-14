"""Safe skill execution wrapper with timeout, error handling, and result validation."""

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any


@dataclass
class ExecutionResult:
    """Result of a skill execution attempt."""
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    tokens_estimate: float = 0.0  # Estimated tokens used


class SkillExecutionError(Exception):
    """Raised when skill execution fails."""
    pass


class SafeSkillExecutor:
    """Execute skills with timeout, error handling, and validation."""

    DEFAULT_TIMEOUT_MS = 30000  # 30 seconds

    def __init__(self, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        self.timeout_ms = timeout_ms

    def execute_skill(
        self,
        skill_name: str,
        task_description: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ExecutionResult:
        """Execute a skill safely with timeout and error handling.

        Args:
            skill_name: Name of the skill to execute
            task_description: Human-readable task description for the skill
            context: Optional context dict to pass to the skill

        Returns:
            ExecutionResult with success/output/error/latency
        """
        start_time = time.time()
        context = context or {}

        try:
            # Build skill invocation command
            # For now, this is a placeholder that would invoke the skill
            # In production, this would call the actual skill runner
            result = self._invoke_skill(skill_name, task_description, context)

            latency_ms = (time.time() - start_time) * 1000
            return ExecutionResult(
                success=True,
                output=result,
                latency_ms=latency_ms,
                tokens_estimate=self._estimate_tokens(result),
            )

        except subprocess.TimeoutExpired:
            latency_ms = (time.time() - start_time) * 1000
            return ExecutionResult(
                success=False,
                error=f"Skill execution timed out after {self.timeout_ms}ms",
                latency_ms=latency_ms,
            )

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return ExecutionResult(
                success=False,
                error=f"Skill execution failed: {str(e)}",
                latency_ms=latency_ms,
            )

    def _invoke_skill(
        self,
        skill_name: str,
        task_description: str,
        context: Dict[str, Any],
    ) -> str:
        """Invoke a skill. Placeholder for actual skill runner integration.

        In production, this would:
        1. Load the skill definition from manifest
        2. Call the skill runner (Claude Code agent or direct executor)
        3. Capture output
        4. Validate result format
        """
        # For now, return a mock success
        # Real implementation would invoke the actual skill system
        return f"Executed skill '{skill_name}': {task_description}"

    def _estimate_tokens(self, output: str) -> float:
        """Estimate tokens used in skill execution.

        Rough heuristic: ~4 characters per token (Claude tokenizer).
        """
        return len(output) / 4.0

    def validate_result(self, result: ExecutionResult) -> bool:
        """Validate that a skill execution result is valid."""
        if not result.success:
            return False
        if not result.output:
            return False
        if result.latency_ms < 0:
            return False
        return True


class TieredSkillExecutor:
    """Execute skills with fallback chain: Tier 1 → Tier 2 → Agent."""

    def __init__(self, timeout_ms: int = SafeSkillExecutor.DEFAULT_TIMEOUT_MS):
        self.executor = SafeSkillExecutor(timeout_ms)

    def execute_with_fallback(
        self,
        prompt: str,
        tier1_skill: Optional[str] = None,
        tier2_skill: Optional[str] = None,
        fallback_to_agent: bool = True,
    ) -> Dict[str, Any]:
        """Execute with fallback chain.

        Returns dict with:
        - tier_used: "tier1", "tier2", "agent", or "none"
        - result: ExecutionResult from the successful tier
        - fallback_reason: str explaining why previous tier failed
        """
        # Try Tier 1
        if tier1_skill:
            result = self.executor.execute_skill(
                tier1_skill,
                prompt,
                context={"tier": 1},
            )
            if self.executor.validate_result(result):
                return {
                    "tier_used": "tier1",
                    "skill_used": tier1_skill,
                    "result": result,
                    "fallback_reason": None,
                }
            else:
                tier1_failure = result.error or "Validation failed"

        # Try Tier 2
        if tier2_skill:
            result = self.executor.execute_skill(
                tier2_skill,
                prompt,
                context={"tier": 2},
            )
            if self.executor.validate_result(result):
                return {
                    "tier_used": "tier2",
                    "skill_used": tier2_skill,
                    "result": result,
                    "fallback_reason": tier1_failure if tier1_skill else None,
                }
            else:
                tier2_failure = result.error or "Validation failed"

        # Fall back to agent
        if fallback_to_agent:
            return {
                "tier_used": "agent",
                "skill_used": None,
                "result": None,
                "fallback_reason": (
                    f"Tier 1 ({tier1_skill}): {tier1_failure}. "
                    f"Tier 2 ({tier2_skill}): {tier2_failure}."
                ) if tier1_skill and tier2_skill else (
                    f"Tier 2 ({tier2_skill}): {tier2_failure}."
                ) if tier2_skill else "No skills available",
            }

        return {
            "tier_used": "none",
            "skill_used": None,
            "result": None,
            "fallback_reason": "No tiers available and fallback disabled",
        }
