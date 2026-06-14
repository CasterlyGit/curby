"""Curvy skill management system."""

from .manifest import SkillRegistry, SkillCache, SkillMetadata
from .loader import SkillLoader
from .orchestrator import WorkflowOrchestrator, AgentSkillAdapter, SkillExecutor
from .learning import SkillPerformanceTracker, SkillAdaptationHeuristics, SkillConflictResolver
from .router import FastPathRouter, RoutingDecision
from .integration import (
	QuickAskRouter,
	AgentDispatchRouter,
	inject_routing_into_quick_ask_prompt,
	inject_routing_into_agent_dispatch,
)

__all__ = [
	"SkillRegistry",
	"SkillCache",
	"SkillMetadata",
	"SkillLoader",
	"WorkflowOrchestrator",
	"AgentSkillAdapter",
	"SkillExecutor",
	"SkillPerformanceTracker",
	"SkillAdaptationHeuristics",
	"SkillConflictResolver",
	"FastPathRouter",
	"RoutingDecision",
	"QuickAskRouter",
	"AgentDispatchRouter",
	"inject_routing_into_quick_ask_prompt",
	"inject_routing_into_agent_dispatch",
]
