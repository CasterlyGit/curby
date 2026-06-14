"""Skill manifest and registry management for curvy workflow integration."""

import json
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any


@dataclass
class SkillMetadata:
	"""Metadata for a registered skill."""

	name: str
	path: str
	category: str = "general"
	tags: List[str] = field(default_factory=list)
	success_rate: float = 1.0
	cost_estimate: float = 0.0
	last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
	execution_count: int = 0
	avg_tokens: float = 0.0
	avg_latency_ms: float = 0.0


class SkillRegistry:
	"""Manages skill manifest and metadata."""

	def __init__(self, registry_path: str = None):
		if registry_path is None:
			registry_path = os.path.join(
				os.path.dirname(__file__), "manifest.json"
			)
		self.registry_path = Path(registry_path)
		self.registry_path.parent.mkdir(parents=True, exist_ok=True)
		self._load_registry()

	def _load_registry(self):
		"""Load registry from disk."""
		if self.registry_path.exists():
			with open(self.registry_path) as f:
				data = json.load(f)
				self.skills = {
					sk["name"]: SkillMetadata(**sk)
					for sk in data.get("skills", [])
				}
				self.updated = data.get("updated")
		else:
			self.skills: Dict[str, SkillMetadata] = {}
			self.updated = datetime.now().isoformat()

	def _save_registry(self):
		"""Save registry to disk."""
		data = {
			"skills": [asdict(s) for s in self.skills.values()],
			"updated": datetime.now().isoformat(),
		}
		with open(self.registry_path, "w") as f:
			json.dump(data, f, indent=2)

	def register(self, skill: SkillMetadata) -> None:
		"""Register a new skill."""
		self.skills[skill.name] = skill
		self._save_registry()

	def lookup(self, name: str) -> Optional[SkillMetadata]:
		"""Look up a skill by name."""
		return self.skills.get(name)

	def search(self, query: str, field: str = "tags") -> List[SkillMetadata]:
		"""Search skills by query in a given field."""
		results = []
		for skill in self.skills.values():
			if field == "tags":
				if any(query.lower() in tag.lower() for tag in skill.tags):
					results.append(skill)
			elif field == "category":
				if query.lower() in skill.category.lower():
					results.append(skill)
			elif field == "name":
				if query.lower() in skill.name.lower():
					results.append(skill)
		return results

	def all(self) -> List[SkillMetadata]:
		"""Return all registered skills."""
		return list(self.skills.values())

	def update_stats(self, name: str, success: bool, tokens: float, latency_ms: float) -> None:
		"""Update execution stats for a skill."""
		if skill := self.skills.get(name):
			skill.execution_count += 1
			skill.avg_tokens = (skill.avg_tokens * (skill.execution_count - 1) + tokens) / skill.execution_count
			skill.avg_latency_ms = (skill.avg_latency_ms * (skill.execution_count - 1) + latency_ms) / skill.execution_count

			# Update success rate
			prev_successes = int(skill.success_rate * (skill.execution_count - 1))
			total_successes = prev_successes + (1 if success else 0)
			skill.success_rate = total_successes / skill.execution_count

			skill.last_updated = datetime.now().isoformat()
			self._save_registry()


class SkillCache:
	"""In-memory + disk cache for skills."""

	def __init__(self, cache_dir: str = None):
		if cache_dir is None:
			cache_dir = os.path.join(os.path.dirname(__file__), "cache")
		self.cache_dir = Path(cache_dir)
		self.cache_dir.mkdir(parents=True, exist_ok=True)
		self._memory_cache: Dict[str, Any] = {}

	def get(self, skill_name: str) -> Optional[Any]:
		"""Get skill from memory cache, then disk."""
		# Check memory
		if skill_name in self._memory_cache:
			return self._memory_cache[skill_name]

		# Check disk
		cache_file = self.cache_dir / f"{skill_name}.cache.json"
		if cache_file.exists():
			with open(cache_file) as f:
				data = json.load(f)
				self._memory_cache[skill_name] = data
				return data

		return None

	def set(self, skill_name: str, data: Any) -> None:
		"""Cache skill in memory and disk."""
		self._memory_cache[skill_name] = data

		cache_file = self.cache_dir / f"{skill_name}.cache.json"
		with open(cache_file, "w") as f:
			json.dump(
				{
					**data,
					"cached_at": datetime.now().isoformat(),
					"hits": 0,
				},
				f,
				indent=2,
			)

	def hit(self, skill_name: str) -> None:
		"""Record a cache hit."""
		cache_file = self.cache_dir / f"{skill_name}.cache.json"
		if cache_file.exists():
			with open(cache_file) as f:
				data = json.load(f)
			data["hits"] = data.get("hits", 0) + 1
			with open(cache_file, "w") as f:
				json.dump(data, f, indent=2)
