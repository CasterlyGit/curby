"""Tests for skill manifest and cache infrastructure."""

import json
import tempfile
from pathlib import Path
from .manifest import SkillRegistry, SkillCache, SkillMetadata
from .loader import SkillLoader


def test_skill_metadata_creation():
	"""Test creating skill metadata."""
	skill = SkillMetadata(
		name="book_restaurant",
		path="/skills/book_restaurant.md",
		category="web_automation",
		tags=["opentable", "booking"],
	)

	assert skill.name == "book_restaurant"
	assert skill.category == "web_automation"
	assert "opentable" in skill.tags
	assert skill.success_rate == 1.0
	print("✓ Skill metadata creation works")


def test_skill_registry_register_and_lookup():
	"""Test registering and looking up skills."""
	with tempfile.TemporaryDirectory() as tmpdir:
		registry_path = Path(tmpdir) / "manifest.json"
		registry = SkillRegistry(str(registry_path))

		# Register a skill
		skill = SkillMetadata(
			name="test_skill",
			path="/skills/test.md",
			category="test",
			tags=["test"],
		)
		registry.register(skill)

		# Look it up
		found = registry.lookup("test_skill")
		assert found is not None
		assert found.name == "test_skill"
		assert found.category == "test"

		# Verify it persists
		registry2 = SkillRegistry(str(registry_path))
		found2 = registry2.lookup("test_skill")
		assert found2 is not None
		assert found2.name == "test_skill"

	print("✓ Skill registry register/lookup works")


def test_skill_registry_search():
	"""Test searching skills."""
	with tempfile.TemporaryDirectory() as tmpdir:
		registry_path = Path(tmpdir) / "manifest.json"
		registry = SkillRegistry(str(registry_path))

		# Register multiple skills
		for i in range(3):
			skill = SkillMetadata(
				name=f"skill_{i}",
				path=f"/skills/skill_{i}.md",
				category="web_automation" if i < 2 else "email",
				tags=["automation", "web"] if i < 2 else ["email", "notification"],
			)
			registry.register(skill)

		# Search by tag
		web_skills = registry.search("automation", "tags")
		assert len(web_skills) >= 2
		assert any(s.name == "skill_0" for s in web_skills)

		# Search by category
		email_skills = registry.search("email", "category")
		assert len(email_skills) == 1
		assert email_skills[0].name == "skill_2"

	print("✓ Skill registry search works")


def test_skill_registry_update_stats():
	"""Test updating execution stats."""
	with tempfile.TemporaryDirectory() as tmpdir:
		registry_path = Path(tmpdir) / "manifest.json"
		registry = SkillRegistry(str(registry_path))

		skill = SkillMetadata(name="test", path="/test.md")
		registry.register(skill)

		# Simulate executions
		registry.update_stats("test", success=True, tokens=100.0, latency_ms=500.0)
		registry.update_stats("test", success=True, tokens=120.0, latency_ms=550.0)
		registry.update_stats("test", success=False, tokens=80.0, latency_ms=400.0)

		updated = registry.lookup("test")
		assert updated.execution_count == 3
		assert updated.success_rate == 2 / 3  # 2 successes out of 3
		assert 90 < updated.avg_tokens < 110  # ~100 avg
		assert 400 < updated.avg_latency_ms < 550  # ~483 avg

	print("✓ Skill registry stats update works")


def test_skill_cache_get_set():
	"""Test in-memory and disk cache."""
	with tempfile.TemporaryDirectory() as tmpdir:
		cache_dir = Path(tmpdir)
		cache = SkillCache(str(cache_dir))

		# Set a skill in cache
		test_data = {
			"name": "test_skill",
			"content": "# Test Skill\n\nThis is a test.",
		}
		cache.set("test_skill", test_data)

		# Get from memory (should be instant)
		retrieved = cache.get("test_skill")
		assert retrieved is not None
		assert retrieved["name"] == "test_skill"

		# Create new cache instance (tests disk persistence)
		cache2 = SkillCache(str(cache_dir))
		retrieved2 = cache2.get("test_skill")
		assert retrieved2 is not None
		assert retrieved2["name"] == "test_skill"

	print("✓ Skill cache get/set works")


def test_skill_cache_hits():
	"""Test cache hit tracking."""
	with tempfile.TemporaryDirectory() as tmpdir:
		cache_dir = Path(tmpdir)
		cache = SkillCache(str(cache_dir))

		test_data = {"name": "test_skill", "content": "Test"}
		cache.set("test_skill", test_data)

		# Record hits
		cache.hit("test_skill")
		cache.hit("test_skill")

		# Check cache file for hits
		cache_file = Path(tmpdir) / "test_skill.cache.json"
		with open(cache_file) as f:
			data = json.load(f)
		assert data["hits"] == 2

	print("✓ Skill cache hit tracking works")


def test_skill_loader_integration():
	"""Test full loader integration."""
	with tempfile.TemporaryDirectory() as tmpdir:
		tmpdir = Path(tmpdir)

		# Create skill file
		skills_dir = tmpdir / "skills"
		skills_dir.mkdir()
		skill_file = skills_dir / "test_skill.md"
		skill_file.write_text("# Test Skill\n\nContent here")

		# Set up registry and cache
		registry_path = tmpdir / "manifest.json"
		cache_dir = tmpdir / "cache"

		registry = SkillRegistry(str(registry_path))
		skill = SkillMetadata(
			name="test_skill",
			path=str(skill_file),
			category="test",
			tags=["test"],
		)
		registry.register(skill)

		# Load via loader
		loader = SkillLoader(str(registry_path), str(cache_dir))
		content, metadata, cached = loader.load("test_skill")

		assert content is not None
		assert "Test Skill" in content
		assert metadata is not None
		assert metadata["name"] == "test_skill"
		assert not cached  # First load, not from cache

		# Load again (should be cached)
		content2, metadata2, cached2 = loader.load("test_skill")
		assert content2 == content
		assert cached2  # Second load, from cache

	print("✓ Skill loader integration works")


def test_skill_loader_list_and_search():
	"""Test listing and searching with loader."""
	with tempfile.TemporaryDirectory() as tmpdir:
		tmpdir = Path(tmpdir)

		registry_path = tmpdir / "manifest.json"
		registry = SkillRegistry(str(registry_path))

		# Register several skills
		for i in range(3):
			skill = SkillMetadata(
				name=f"skill_{i}",
				path=f"/skill_{i}.md",
				category="test",
				tags=["test", "automation"],
			)
			registry.register(skill)

		loader = SkillLoader(str(registry_path))

		# Test list
		all_skills = loader.list_available()
		assert len(all_skills) == 3

		# Test search
		results = loader.search("automation", "tags")
		assert len(results) == 3  # All have "automation" tag

	print("✓ Skill loader list/search works")


if __name__ == "__main__":
	test_skill_metadata_creation()
	test_skill_registry_register_and_lookup()
	test_skill_registry_search()
	test_skill_registry_update_stats()
	test_skill_cache_get_set()
	test_skill_cache_hits()
	test_skill_loader_integration()
	test_skill_loader_list_and_search()

	print("\n✅ All tests passed!")
