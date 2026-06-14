"""Workflow orchestrator: match tasks to skills and compose workflows."""

from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class SkillMatch:
	"""A potential skill match for a task."""

	skill_name: str
	confidence: float
	reason: str
	category: str
	matched_keywords: List[str]


class WorkflowOrchestrator:
	"""Match tasks to skills and compose multi-step workflows."""

	def __init__(self, loader):
		"""Initialize with a SkillLoader instance."""
		self.loader = loader
		self.skill_keyword_map = self._build_keyword_map()

	def _build_keyword_map(self) -> dict:
		"""Build a map of skills to their keywords (name, category, tags)."""
		keyword_map = {}
		for skill in self.loader.list_available():
			name_with_spaces = skill["name"].replace("_", " ")
			name_words = skill["name"].replace("_", " ").split()
			category = skill["category"]
			tags = skill.get("tags", [])

			# Flatten: include the full name, individual words, category, and tags
			all_keywords = [name_with_spaces] + name_words + [category] + tags
			all_keywords = list(set(kw.lower() for kw in all_keywords))  # Deduplicate

			keyword_map[skill["name"]] = {
				"keywords": all_keywords,
				"category": category,
				"tags": tags,
				"success_rate": skill.get("success_rate", 1.0),
			}

		return keyword_map

	def match_task(self, task_description: str) -> List[SkillMatch]:
		"""
		Match a task description to available skills.

		Returns:
			List of SkillMatch sorted by confidence (highest first)
		"""
		task_words = set(task_description.lower().split())
		matches = []

		for skill_name, skill_info in self.skill_keyword_map.items():
			matched = []
			for keyword in skill_info["keywords"]:
				# Allow partial word matches (e.g., "book" matches "booking")
				for task_word in task_words:
					if keyword in task_word or task_word in keyword:
						matched.append(keyword)
						break

			if matched:
				# Calculate confidence: more matched keywords = higher confidence
				# Min threshold: 1 matched keyword gives at least 0.3 confidence
				# Formula: sqrt(matched / total_keywords) * success_rate
				keyword_score = min(1.0, (len(matched) ** 0.5) / (len(skill_info["keywords"]) ** 0.5))
				confidence = keyword_score * skill_info["success_rate"]

				match = SkillMatch(
					skill_name=skill_name,
					confidence=confidence,
					reason=f"Matched keywords: {', '.join(set(matched))}",
					category=skill_info["category"],
					matched_keywords=list(set(matched)),
				)
				matches.append(match)

		# Sort by confidence (descending)
		matches.sort(key=lambda m: m.confidence, reverse=True)
		return matches

	def compose_workflow(self, task_description: str, min_confidence: float = 0.5) -> List[str]:
		"""
		Compose a workflow (ordered list of skill names) for a task.

		Returns:
			List of skill names in execution order
		"""
		matches = self.match_task(task_description)

		# Filter by minimum confidence
		qualified = [m for m in matches if m.confidence >= min_confidence]

		# Return skill names in order
		return [m.skill_name for m in qualified]

	def explain_workflow(self, task_description: str) -> dict:
		"""
		Explain the workflow composition for a task (for debugging).

		Returns:
			Dict with matched skills and confidence scores
		"""
		matches = self.match_task(task_description)

		return {
			"task": task_description,
			"matches": [
				{
					"skill_name": m.skill_name,
					"confidence": m.confidence,
					"reason": m.reason,
					"category": m.category,
				}
				for m in matches
			],
		}


class AgentSkillAdapter:
	"""Inject loaded skills into agent prompts."""

	def __init__(self, loader):
		"""Initialize with a SkillLoader instance."""
		self.loader = loader

	def format_skill_block(self, skill_name: str) -> Optional[str]:
		"""Format a skill as a prompt block for the agent."""
		content, metadata, _ = self.loader.load(skill_name)

		if not content or not metadata:
			return None

		# Format as a markdown block
		return f"""## Available Skill: {metadata['name']}

**Purpose:** {metadata.get('description', 'No description')}
**Category:** {metadata['category']}
**Success Rate:** {metadata['success_rate']:.1%}
**Cost Estimate:** ${metadata['cost_estimate']:.2f}

### Instructions:
{content}

---
"""

	def format_workflow_prompt(self, skill_names: List[str], task_description: str) -> str:
		"""Format a prompt with multiple skills for the agent."""
		prompt = f"Task: {task_description}\n\n"
		prompt += "## Available Skills\n\n"

		for skill_name in skill_names:
			skill_block = self.format_skill_block(skill_name)
			if skill_block:
				prompt += skill_block

		prompt += """
## Instructions:
1. Review the available skills above
2. Use them to complete the task in the most efficient way
3. If a skill doesn't quite match, adapt it or fall back to manual steps
4. Report success/failure and any deviations from the original skill plan
"""

		return prompt


class SkillExecutor:
	"""Execute skills based on agent output."""

	def __init__(self, loader):
		"""Initialize with a SkillLoader instance."""
		self.loader = loader

	def extract_skill_usage(self, agent_response: str, skill_names: List[str]) -> List[str]:
		"""
		Extract which skills the agent used from its response.

		Returns:
			List of skill names mentioned in the response
		"""
		used_skills = []
		for skill_name in skill_names:
			# Check if skill name appears in the response
			if skill_name.replace("_", " ") in agent_response.lower() or skill_name in agent_response.lower():
				used_skills.append(skill_name)

		return used_skills

	def execute(self, agent_response: str, skill_names: List[str]) -> dict:
		"""
		Execute skills referenced in agent output.

		Returns:
			Dict with execution results
		"""
		used_skills = self.extract_skill_usage(agent_response, skill_names)

		results = {
			"task_response": agent_response,
			"skills_referenced": used_skills,
			"executions": [],
		}

		# In a real implementation, this would execute each skill
		# For now, we track which skills were referenced
		for skill_name in used_skills:
			content, metadata, cached = self.loader.load(skill_name)
			if content and metadata:
				results["executions"].append({
					"skill_name": skill_name,
					"loaded_from_cache": cached,
					"success_rate": metadata["success_rate"],
				})

		return results
