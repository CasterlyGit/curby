"""Tests for workflow orchestration, skill adaptation, and execution."""

import tempfile
from pathlib import Path
from .manifest import SkillRegistry, SkillMetadata, SkillCache
from .loader import SkillLoader
from .orchestrator import WorkflowOrchestrator, AgentSkillAdapter, SkillExecutor


def test_orchestrator_match_single_skill():
	"""Test matching a task to a single skill."""
	with tempfile.TemporaryDirectory() as tmpdir:
		tmpdir = Path(tmpdir)

		# Setup
		registry_path = tmpdir / "manifest.json"
		registry = SkillRegistry(str(registry_path))

		skill = SkillMetadata(
			name="book_restaurant",
			path="/skills/book_restaurant.md",
			category="web_automation",
			tags=["opentable", "booking", "restaurant"],
		)
		registry.register(skill)

		loader = SkillLoader(str(registry_path))
		orchestrator = WorkflowOrchestrator(loader)

		# Match task
		matches = orchestrator.match_task("book a restaurant reservation")

		assert len(matches) > 0
		assert matches[0].skill_name == "book_restaurant"
		assert matches[0].confidence > 0.5

	print("✓ Orchestrator single skill match works")


def test_orchestrator_match_multiple_skills():
	"""Test matching a task to multiple skills."""
	with tempfile.TemporaryDirectory() as tmpdir:
		tmpdir = Path(tmpdir)

		# Setup
		registry_path = tmpdir / "manifest.json"
		registry = SkillRegistry(str(registry_path))

		skills = [
			SkillMetadata(
				name="book_restaurant",
				path="/book.md",
				category="web_automation",
				tags=["booking"],
			),
			SkillMetadata(
				name="send_email",
				path="/email.md",
				category="communication",
				tags=["email", "send"],
			),
			SkillMetadata(
				name="book_hotel",
				path="/hotel.md",
				category="web_automation",
				tags=["booking", "hotel"],
			),
		]

		for skill in skills:
			registry.register(skill)

		loader = SkillLoader(str(registry_path))
		orchestrator = WorkflowOrchestrator(loader)

		# Match task that could use multiple skills
		matches = orchestrator.match_task("book a restaurant and send confirmation email")

		skill_names = [m.skill_name for m in matches]
		assert "book_restaurant" in skill_names
		assert "send_email" in skill_names

	print("✓ Orchestrator multiple skill match works")


def test_orchestrator_compose_workflow():
	"""Test composing a workflow from task description."""
	with tempfile.TemporaryDirectory() as tmpdir:
		tmpdir = Path(tmpdir)

		registry_path = tmpdir / "manifest.json"
		registry = SkillRegistry(str(registry_path))

		for i, name in enumerate(["book_restaurant", "send_email", "get_weather"]):
			skill = SkillMetadata(
				name=name,
				path=f"/{name}.md",
				category="utility",
				tags=[name.split("_")[0]],
			)
			registry.register(skill)

		loader = SkillLoader(str(registry_path))
		orchestrator = WorkflowOrchestrator(loader)

		# Compose workflow
		workflow = orchestrator.compose_workflow("book restaurant and send confirmation")

		assert len(workflow) > 0
		assert "book_restaurant" in workflow or "send_email" in workflow

	print("✓ Orchestrator workflow composition works")


def test_orchestrator_explain_workflow():
	"""Test explaining workflow choices."""
	with tempfile.TemporaryDirectory() as tmpdir:
		tmpdir = Path(tmpdir)

		registry_path = tmpdir / "manifest.json"
		registry = SkillRegistry(str(registry_path))

		skill = SkillMetadata(
			name="test_skill",
			path="/test.md",
			category="test",
			tags=["test", "utility"],
		)
		registry.register(skill)

		loader = SkillLoader(str(registry_path))
		orchestrator = WorkflowOrchestrator(loader)

		# Get explanation
		explanation = orchestrator.explain_workflow("test something with test skill")

		assert "matches" in explanation
		assert "task" in explanation
		assert len(explanation["matches"]) > 0

	print("✓ Orchestrator explain_workflow works")


def test_agent_skill_adapter_format_skill():
	"""Test formatting a skill for agent prompt."""
	with tempfile.TemporaryDirectory() as tmpdir:
		tmpdir = Path(tmpdir)

		# Create skill file
		skills_dir = tmpdir / "skills"
		skills_dir.mkdir()
		skill_file = skills_dir / "test_skill.md"
		skill_file.write_text("# Test Skill\n\n1. Step 1\n2. Step 2")

		# Register skill
		registry_path = tmpdir / "manifest.json"
		registry = SkillRegistry(str(registry_path))
		skill = SkillMetadata(
			name="test_skill",
			path=str(skill_file),
			category="test",
		)
		registry.register(skill)

		loader = SkillLoader(str(registry_path))
		adapter = AgentSkillAdapter(loader)

		# Format skill
		formatted = adapter.format_skill_block("test_skill")

		assert formatted is not None
		assert "test_skill" in formatted
		assert "Test Skill" in formatted
		assert "Step 1" in formatted

	print("✓ Agent skill adapter format_skill works")


def test_agent_skill_adapter_format_workflow_prompt():
	"""Test formatting a full workflow prompt."""
	with tempfile.TemporaryDirectory() as tmpdir:
		tmpdir = Path(tmpdir)

		# Create skill files
		skills_dir = tmpdir / "skills"
		skills_dir.mkdir()

		for name in ["skill_1", "skill_2"]:
			skill_file = skills_dir / f"{name}.md"
			skill_file.write_text(f"# {name.title()}\n\nInstructions here")

		# Register skills
		registry_path = tmpdir / "manifest.json"
		registry = SkillRegistry(str(registry_path))

		for name in ["skill_1", "skill_2"]:
			skill = SkillMetadata(
				name=name,
				path=str(skills_dir / f"{name}.md"),
				category="test",
			)
			registry.register(skill)

		loader = SkillLoader(str(registry_path))
		adapter = AgentSkillAdapter(loader)

		# Format workflow prompt
		prompt = adapter.format_workflow_prompt(["skill_1", "skill_2"], "Test task")

		assert "Test task" in prompt
		assert "Available Skills" in prompt
		assert "skill_1" in prompt or "Skill 1" in prompt
		assert "Instructions:" in prompt

	print("✓ Agent skill adapter format_workflow_prompt works")


def test_skill_executor_extract_usage():
	"""Test extracting skill usage from agent response."""
	with tempfile.TemporaryDirectory() as tmpdir:
		tmpdir = Path(tmpdir)

		registry_path = tmpdir / "manifest.json"
		registry = SkillRegistry(str(registry_path))

		skills = ["book_restaurant", "send_email"]
		for name in skills:
			skill = SkillMetadata(name=name, path=f"/{name}.md")
			registry.register(skill)

		loader = SkillLoader(str(registry_path))
		executor = SkillExecutor(loader)

		# Simulate agent response
		agent_response = "I'll use book_restaurant to book the table, then send_email to confirm."

		used = executor.extract_skill_usage(agent_response, skills)

		assert "book_restaurant" in used
		assert "send_email" in used

	print("✓ Skill executor extract_usage works")


def test_skill_executor_execute():
	"""Test executing a workflow."""
	with tempfile.TemporaryDirectory() as tmpdir:
		tmpdir = Path(tmpdir)

		# Create skill files
		skills_dir = tmpdir / "skills"
		skills_dir.mkdir()

		skills = ["book_restaurant", "send_email"]
		for name in skills:
			skill_file = skills_dir / f"{name}.md"
			skill_file.write_text(f"# {name.title()}\n\nSteps...")

		# Register and load
		registry_path = tmpdir / "manifest.json"
		registry = SkillRegistry(str(registry_path))

		for name in skills:
			skill = SkillMetadata(
				name=name,
				path=str(skills_dir / f"{name}.md"),
				category="test",
			)
			registry.register(skill)

		loader = SkillLoader(str(registry_path))
		executor = SkillExecutor(loader)

		# Execute
		agent_response = "Using book_restaurant and send_email skills."
		result = executor.execute(agent_response, skills)

		assert "skills_referenced" in result
		assert "executions" in result
		assert len(result["executions"]) > 0

	print("✓ Skill executor execute works")


def test_end_to_end_workflow():
	"""Test full orchestration pipeline: match → compose → adapt → execute."""
	with tempfile.TemporaryDirectory() as tmpdir:
		tmpdir = Path(tmpdir)

		# Setup
		skills_dir = tmpdir / "skills"
		skills_dir.mkdir()

		registry_path = tmpdir / "manifest.json"
		registry = SkillRegistry(str(registry_path))

		# Create and register skills
		skill_names = ["book_restaurant", "send_email"]
		for name in skill_names:
			skill_file = skills_dir / f"{name}.md"
			skill_file.write_text(f"# {name.title()}\n\nStep 1\nStep 2")

			skill = SkillMetadata(
				name=name,
				path=str(skill_file),
				category="test",
				tags=[name.split("_")[0]],
			)
			registry.register(skill)

		loader = SkillLoader(str(registry_path))

		# Step 1: Orchestrate (match)
		orchestrator = WorkflowOrchestrator(loader)
		matches = orchestrator.match_task("book a restaurant and send confirmation")
		assert len(matches) > 0

		# Step 2: Compose workflow
		workflow = orchestrator.compose_workflow("book a restaurant and send confirmation")
		assert len(workflow) > 0

		# Step 3: Adapt for agent
		adapter = AgentSkillAdapter(loader)
		prompt = adapter.format_workflow_prompt(workflow, "Book restaurant and confirm")
		assert "Available Skills" in prompt

		# Step 4: Execute (simulate agent response)
		executor = SkillExecutor(loader)
		agent_response = "I used book_restaurant to book and send_email to confirm."
		execution_result = executor.execute(agent_response, workflow)

		assert len(execution_result["executions"]) > 0
		assert execution_result["task_response"] == agent_response

	print("✓ End-to-end workflow pipeline works")


if __name__ == "__main__":
	test_orchestrator_match_single_skill()
	test_orchestrator_match_multiple_skills()
	test_orchestrator_compose_workflow()
	test_orchestrator_explain_workflow()
	test_agent_skill_adapter_format_skill()
	test_agent_skill_adapter_format_workflow_prompt()
	test_skill_executor_extract_usage()
	test_skill_executor_execute()
	test_end_to_end_workflow()

	print("\n✅ All orchestration tests passed!")
