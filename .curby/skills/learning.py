"""Skill learning system: track performance, adapt, and auto-update skills."""

import json
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from .manifest import SkillRegistry


class SkillPerformanceTracker:
	"""Track execution stats and performance metrics for skills."""

	def __init__(self, stats_dir: str = None):
		"""Initialize tracker."""
		if stats_dir is None:
			stats_dir = Path(__file__).parent / "stats"
		self.stats_dir = Path(stats_dir)
		self.stats_dir.mkdir(parents=True, exist_ok=True)

	def record_execution(
		self,
		skill_name: str,
		success: bool,
		tokens_used: float,
		latency_ms: float,
		notes: str = "",
	) -> None:
		"""Record a skill execution."""
		stats_file = self.stats_dir / f"{skill_name}.stats.json"

		# Load existing stats
		if stats_file.exists():
			with open(stats_file) as f:
				stats = json.load(f)
		else:
			stats = {
				"skill_name": skill_name,
				"executions": [],
				"created_at": datetime.now().isoformat(),
			}

		# Append execution record
		stats["executions"].append({
			"success": success,
			"tokens_used": tokens_used,
			"latency_ms": latency_ms,
			"notes": notes,
			"timestamp": datetime.now().isoformat(),
		})

		# Save
		with open(stats_file, "w") as f:
			json.dump(stats, f, indent=2)

	def get_stats(self, skill_name: str) -> Optional[dict]:
		"""Get aggregated stats for a skill."""
		stats_file = self.stats_dir / f"{skill_name}.stats.json"

		if not stats_file.exists():
			return None

		with open(stats_file) as f:
			stats = json.load(f)

		executions = stats.get("executions", [])

		if not executions:
			return None

		successes = sum(1 for e in executions if e["success"])
		total = len(executions)
		success_rate = successes / total
		avg_tokens = sum(e["tokens_used"] for e in executions) / total
		avg_latency = sum(e["latency_ms"] for e in executions) / total

		return {
			"skill_name": skill_name,
			"execution_count": total,
			"success_count": successes,
			"success_rate": success_rate,
			"avg_tokens": avg_tokens,
			"avg_latency_ms": avg_latency,
			"last_execution": executions[-1]["timestamp"],
		}

	def all_stats(self) -> List[dict]:
		"""Get stats for all tracked skills."""
		all_stats = []
		for stats_file in self.stats_dir.glob("*.stats.json"):
			skill_name = stats_file.stem.replace(".stats", "")
			stats = self.get_stats(skill_name)
			if stats:
				all_stats.append(stats)
		return all_stats


class SkillAdaptationHeuristics:
	"""Apply heuristics to flag underperforming skills."""

	def __init__(self, registry: SkillRegistry = None, tracker: SkillPerformanceTracker = None):
		"""Initialize with registry and tracker."""
		self.registry = registry or SkillRegistry()
		self.tracker = tracker or SkillPerformanceTracker()
		self.learning_log_path = Path(__file__).parent / "learning.md"

	def check_health(self, skill_name: str) -> dict:
		"""Check health of a skill based on execution stats."""
		stats = self.tracker.get_stats(skill_name)

		if not stats:
			return {"skill_name": skill_name, "status": "no_executions", "flags": []}

		flags = []
		recommendations = []

		# Check success rate
		if stats["success_rate"] < 0.85:
			flags.append("LOW_SUCCESS_RATE")
			recommendations.append(f"Success rate {stats['success_rate']:.1%} < 85% threshold")

		# Check token cost
		registry_skill = self.registry.lookup(skill_name)
		if registry_skill and registry_skill.cost_estimate > 0:
			cost_increase = (stats["avg_tokens"] - registry_skill.cost_estimate) / registry_skill.cost_estimate
			if cost_increase > 0.2:
				flags.append("HIGH_TOKEN_COST")
				recommendations.append(f"Tokens increased {cost_increase:.0%}")

		# Check latency
		if stats["avg_latency_ms"] > 5000:
			flags.append("HIGH_LATENCY")
			recommendations.append(f"Latency {stats['avg_latency_ms']:.0f}ms > 5s")

		# Check staleness (not executed in 7 days)
		if stats["execution_count"] == 0:
			flags.append("NEVER_EXECUTED")
			recommendations.append("Skill has never been successfully executed")

		return {
			"skill_name": skill_name,
			"status": "healthy" if not flags else "degraded",
			"execution_count": stats["execution_count"],
			"success_rate": stats["success_rate"],
			"avg_tokens": stats["avg_tokens"],
			"avg_latency_ms": stats["avg_latency_ms"],
			"flags": flags,
			"recommendations": recommendations,
		}

	def check_all(self) -> List[dict]:
		"""Check health of all skills."""
		all_skills = self.registry.all()
		results = []

		for skill in all_skills:
			health = self.check_health(skill.name)
			if health["flags"]:
				results.append(health)

		return results

	def log_findings(self, findings: List[dict]) -> None:
		"""Log health check findings to learning.md."""
		if not findings:
			return

		timestamp = datetime.now().isoformat()
		log_entry = f"\n## Health Check — {timestamp}\n\n"

		for finding in findings:
			log_entry += f"### {finding['skill_name']}\n"
			log_entry += f"- **Status:** {finding['status']}\n"
			log_entry += f"- **Executions:** {finding['execution_count']}\n"
			log_entry += f"- **Success Rate:** {finding['success_rate']:.1%}\n"
			log_entry += f"- **Avg Tokens:** {finding['avg_tokens']:.0f}\n"
			log_entry += f"- **Avg Latency:** {finding['avg_latency_ms']:.0f}ms\n"

			if finding["flags"]:
				log_entry += f"- **Flags:** {', '.join(finding['flags'])}\n"

			if finding["recommendations"]:
				log_entry += "- **Recommendations:**\n"
				for rec in finding["recommendations"]:
					log_entry += f"  - {rec}\n"

			log_entry += "\n"

		# Append to learning log
		if self.learning_log_path.exists():
			with open(self.learning_log_path) as f:
				content = f.read()
			content += log_entry
		else:
			content = "# Skill Learning Log\n" + log_entry

		with open(self.learning_log_path, "w") as f:
			f.write(content)


class SkillConflictResolver:
	"""Resolve conflicts when multiple skills match a task."""

	@staticmethod
	def resolve(
		matches: List[tuple],  # [(skill_name, confidence), ...]
		registry: SkillRegistry,
		tracker: SkillPerformanceTracker,
	) -> str:
		"""
		Resolve which skill to use when multiple match.

		Preference order:
		1. Highest success rate
		2. Most recent execution
		3. Lowest cost estimate
		4. Highest confidence match

		Returns:
			Chosen skill name
		"""
		if not matches:
			return None

		if len(matches) == 1:
			return matches[0][0]

		# Score each match
		scored = []
		for skill_name, confidence in matches:
			score = confidence

			# Boost by success rate
			registry_skill = registry.lookup(skill_name)
			if registry_skill:
				score *= (1 + registry_skill.success_rate)

			# Boost by lower cost
			if registry_skill and registry_skill.cost_estimate > 0:
				score *= (1.0 / (1.0 + registry_skill.cost_estimate / 100))

			# Check execution stats
			stats = tracker.get_stats(skill_name)
			if stats:
				score *= (1 + stats["success_rate"])

			scored.append((skill_name, score))

		# Return highest scored
		return max(scored, key=lambda x: x[1])[0]
