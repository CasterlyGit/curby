"""Skill loader for retrieving and preparing skills for agent use."""

from pathlib import Path
from typing import Tuple, Optional, Dict, Any
from .manifest import SkillRegistry, SkillCache, SkillMetadata


class SkillLoader:
	"""Load skills from registry and cache."""

	def __init__(self, registry_path: str = None, cache_dir: str = None):
		self.registry = SkillRegistry(registry_path)
		self.cache = SkillCache(cache_dir)

	def load(self, skill_name: str) -> Tuple[Optional[str], Optional[Dict[str, Any]], bool]:
		"""
		Load a skill by name.

		Returns:
			Tuple of (content, metadata, is_cached)
		"""
		# Check cache first
		cached = self.cache.get(skill_name)
		if cached is not None:
			self.cache.hit(skill_name)
			metadata = self.registry.lookup(skill_name)
			return (cached.get("content"), asdict(metadata) if metadata else None, True)

		# Look up in registry
		metadata = self.registry.lookup(skill_name)
		if not metadata:
			return (None, None, False)

		# Load from disk
		skill_path = Path(metadata.path)
		if skill_path.exists():
			with open(skill_path) as f:
				content = f.read()

			# Cache for next time
			self.cache.set(skill_name, {"content": content})
			self.cache.hit(skill_name)

			return (content, asdict(metadata), False)

		return (None, None, False)

	def load_multiple(self, skill_names: list) -> Dict[str, Tuple[Optional[str], Optional[Dict[str, Any]], bool]]:
		"""Load multiple skills at once."""
		return {name: self.load(name) for name in skill_names}

	def list_available(self) -> list:
		"""List all available skills."""
		return [asdict(s) for s in self.registry.all()]

	def search(self, query: str, field: str = "tags") -> list:
		"""Search for skills."""
		results = self.registry.search(query, field)
		return [asdict(s) for s in results]


def asdict(obj):
	"""Convert dataclass to dict."""
	from dataclasses import asdict as dc_asdict
	return dc_asdict(obj) if hasattr(obj, '__dataclass_fields__') else obj
