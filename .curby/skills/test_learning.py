"""Tests for skill learning system: performance tracking and adaptation."""

import tempfile
import json
from pathlib import Path
from .manifest import SkillRegistry, SkillMetadata, SkillCache
from .loader import SkillLoader
from .learning import SkillPerformanceTracker, SkillAdaptationHeuristics, SkillConflictResolver


def test_skill_performance_tracker_record():
	"""Test recording skill executions."""
	with tempfile.TemporaryDirectory() as tmpdir:
		tracker = SkillPerformanceTracker(tmpdir)

		# Record several executions
		tracker.record_execution("test_skill", success=True, tokens_used=100.0, latency_ms=500.0)
		tracker.record_execution("test_skill", success=True, tokens_used=120.0, latency_ms=550.0)
		tracker.record_execution("test_skill", success=False, tokens_used=80.0, latency_ms=400.0)

		# Check stats
		stats = tracker.get_stats("test_skill")

		assert stats is not None
		assert stats["execution_count"] == 3
		assert stats["success_count"] == 2
		assert abs(stats["success_rate"] - 2/3) < 0.01
		assert 90 < stats["avg_tokens"] < 110
		assert 400 < stats["avg_latency_ms"] < 550

	print("✓ Skill performance tracker record works")


def test_skill_performance_tracker_all_stats():
	"""Test retrieving stats for all tracked skills."""
	with tempfile.TemporaryDirectory() as tmpdir:
		tracker = SkillPerformanceTracker(tmpdir)

		# Record for multiple skills
		for skill_name in ["skill_a", "skill_b", "skill_c"]:
			tracker.record_execution(skill_name, success=True, tokens_used=100.0, latency_ms=500.0)
			tracker.record_execution(skill_name, success=True, tokens_used=110.0, latency_ms=510.0)

		# Get all stats
		all_stats = tracker.all_stats()

		assert len(all_stats) == 3
		assert all(s["execution_count"] == 2 for s in all_stats)
		assert all(s["success_rate"] == 1.0 for s in all_stats)

	print("✓ Skill performance tracker all_stats works")


def test_adaptation_heuristics_low_success_rate():
	"""Test flagging skills with low success rate."""
	with tempfile.TemporaryDirectory() as tmpdir:
		tmpdir = Path(tmpdir)
		registry_path = tmpdir / "manifest.json"

		# Setup
		registry = SkillRegistry(str(registry_path))
		skill = SkillMetadata(name="flaky_skill", path="/test.md")
		registry.register(skill)

		tracker = SkillPerformanceTracker(str(tmpdir / "stats"))

		# Record mostly failing executions
		for _ in range(5):
			tracker.record_execution("flaky_skill", success=False, tokens_used=100.0, latency_ms=500.0)
		tracker.record_execution("flaky_skill", success=True, tokens_used=100.0, latency_ms=500.0)

		# Check health
		heuristics = SkillAdaptationHeuristics(registry, tracker)
		health = heuristics.check_health("flaky_skill")

		assert health["status"] == "degraded"
		assert "LOW_SUCCESS_RATE" in health["flags"]
		assert health["success_rate"] < 0.85

	print("✓ Adaptation heuristics low success rate flagging works")


def test_adaptation_heuristics_high_latency():
	"""Test flagging skills with high latency."""
	with tempfile.TemporaryDirectory() as tmpdir:
		tmpdir = Path(tmpdir)
		registry_path = tmpdir / "manifest.json"

		registry = SkillRegistry(str(registry_path))
		skill = SkillMetadata(name="slow_skill", path="/test.md")
		registry.register(skill)

		tracker = SkillPerformanceTracker(str(tmpdir / "stats"))

		# Record slow executions
		for _ in range(3):
			tracker.record_execution("slow_skill", success=True, tokens_used=100.0, latency_ms=6000.0)

		heuristics = SkillAdaptationHeuristics(registry, tracker)
		health = heuristics.check_health("slow_skill")

		assert health["status"] == "degraded"
		assert "HIGH_LATENCY" in health["flags"]

	print("✓ Adaptation heuristics high latency flagging works")


def test_adaptation_heuristics_check_all():
	"""Test checking health of all skills."""
	with tempfile.TemporaryDirectory() as tmpdir:
		tmpdir = Path(tmpdir)
		registry_path = tmpdir / "manifest.json"

		registry = SkillRegistry(str(registry_path))

		# Register some skills
		for i in range(3):
			skill = SkillMetadata(name=f"skill_{i}", path=f"/test_{i}.md")
			registry.register(skill)

		tracker = SkillPerformanceTracker(str(tmpdir / "stats"))

		# Record some bad executions
		tracker.record_execution("skill_0", success=False, tokens_used=100.0, latency_ms=500.0)
		tracker.record_execution("skill_0", success=False, tokens_used=100.0, latency_ms=500.0)

		# Record good executions for others
		for i in range(1, 3):
			tracker.record_execution(f"skill_{i}", success=True, tokens_used=100.0, latency_ms=500.0)

		heuristics = SkillAdaptationHeuristics(registry, tracker)
		findings = heuristics.check_all()

		# Only degraded skills should be in findings
		assert len(findings) > 0
		assert any(f["skill_name"] == "skill_0" for f in findings)

	print("✓ Adaptation heuristics check_all works")


def test_adaptation_heuristics_log_findings():
	"""Test logging health findings to learning.md."""
	with tempfile.TemporaryDirectory() as tmpdir:
		tmpdir = Path(tmpdir)

		registry = SkillRegistry(str(tmpdir / "manifest.json"))
		tracker = SkillPerformanceTracker(str(tmpdir / "stats"))

		heuristics = SkillAdaptationHeuristics(registry, tracker)
		heuristics.learning_log_path = tmpdir / "learning.md"

		findings = [
			{
				"skill_name": "test_skill",
				"status": "degraded",
				"execution_count": 5,
				"success_rate": 0.6,
				"avg_tokens": 120.0,
				"avg_latency_ms": 500.0,
				"flags": ["LOW_SUCCESS_RATE"],
				"recommendations": ["Improve success rate"],
			}
		]

		heuristics.log_findings(findings)

		# Check log was created
		assert heuristics.learning_log_path.exists()

		with open(heuristics.learning_log_path) as f:
			content = f.read()

		assert "test_skill" in content
		assert "LOW_SUCCESS_RATE" in content

	print("✓ Adaptation heuristics logging works")


def test_conflict_resolver_single_skill():
	"""Test conflict resolution with single skill."""
	registry = SkillRegistry()
	tracker = SkillPerformanceTracker()

	matches = [("skill_1", 0.9)]

	chosen = SkillConflictResolver.resolve(matches, registry, tracker)

	assert chosen == "skill_1"

	print("✓ Conflict resolver single skill works")


def test_conflict_resolver_multiple_skills():
	"""Test conflict resolution with multiple skills."""
	with tempfile.TemporaryDirectory() as tmpdir:
		tmpdir = Path(tmpdir)
		registry_path = tmpdir / "manifest.json"

		registry = SkillRegistry(str(registry_path))

		# Register skills with different success rates
		skills = [
			SkillMetadata(name="skill_a", path="/a.md", success_rate=0.95),
			SkillMetadata(name="skill_b", path="/b.md", success_rate=0.70),
			SkillMetadata(name="skill_c", path="/c.md", success_rate=0.85),
		]

		for skill in skills:
			registry.register(skill)

		tracker = SkillPerformanceTracker(str(tmpdir / "stats"))

		# All have similar confidence, but different success rates
		matches = [("skill_a", 0.8), ("skill_b", 0.8), ("skill_c", 0.8)]

		chosen = SkillConflictResolver.resolve(matches, registry, tracker)

		# Should prefer highest success rate (skill_a)
		assert chosen == "skill_a"

	print("✓ Conflict resolver multiple skills works")


def test_end_to_end_learning_cycle():
	"""Test complete learning cycle: track → analyze → log."""
	with tempfile.TemporaryDirectory() as tmpdir:
		tmpdir = Path(tmpdir)

		# Setup
		registry_path = tmpdir / "manifest.json"
		registry = SkillRegistry(str(registry_path))

		skill = SkillMetadata(
			name="learning_skill",
			path="/test.md",
			category="test",
		)
		registry.register(skill)

		tracker = SkillPerformanceTracker(str(tmpdir / "stats"))

		# Simulate execution history
		executions = [
			(True, 100.0, 400.0),
			(True, 110.0, 420.0),
			(False, 90.0, 380.0),
			(False, 105.0, 410.0),
			(True, 115.0, 430.0),
		]

		for success, tokens, latency in executions:
			tracker.record_execution("learning_skill", success, tokens, latency)

		# Analyze
		heuristics = SkillAdaptationHeuristics(registry, tracker)
		heuristics.learning_log_path = tmpdir / "learning.md"

		health = heuristics.check_health("learning_skill")

		# Should flag low success rate (3/5 = 60%)
		assert health["success_rate"] == 0.6
		assert "LOW_SUCCESS_RATE" in health["flags"]

		# Log findings
		findings = heuristics.check_all()
		heuristics.log_findings(findings)

		# Verify learning log
		assert heuristics.learning_log_path.exists()

	print("✓ End-to-end learning cycle works")


if __name__ == "__main__":
	test_skill_performance_tracker_record()
	test_skill_performance_tracker_all_stats()
	test_adaptation_heuristics_low_success_rate()
	test_adaptation_heuristics_high_latency()
	test_adaptation_heuristics_check_all()
	test_adaptation_heuristics_log_findings()
	test_conflict_resolver_single_skill()
	test_conflict_resolver_multiple_skills()
	test_end_to_end_learning_cycle()

	print("\n✅ All learning system tests passed!")
