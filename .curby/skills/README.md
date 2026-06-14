# Curvy: Skill Workflow Integration for Curby

Implement a skill-driven workflow engine that registers, caches, and reuses learned skills from Autobrowse and other sources.

## Architecture Overview

### Phase 1: Skill Manifest + Cache (✅ COMPLETE)

**Components:**

1. **SkillManifest** (`manifest.py`)
   - Dataclass: `SkillMetadata` with name, path, category, tags, success_rate, cost, stats
   - Methods: register, lookup, search, all, update_stats
   - Persistence: `.curby/skills/manifest.json`

2. **SkillCache** (`manifest.py`)
   - In-memory + disk cache for skill content
   - Location: `.curby/skills/cache/{skill_name}.cache.json`
   - Tracks cache hits and access patterns

3. **SkillLoader** (`loader.py`)
   - Load skills by name (cache-first, then disk)
   - List available skills
   - Search by category, tags, name
   - Returns: (content, metadata, is_cached)

**Files:**
- `manifest.py` — SkillRegistry + SkillCache
- `loader.py` — SkillLoader
- `__init__.py` — Public API
- `test_manifest.py` — 8 comprehensive tests (all passing ✅)
- `manifest.json` — Skill registry (auto-created)
- `cache/` — Disk cache directory (auto-created)

**Success Criteria (Phase 1):**
- ✅ Register skills with metadata
- ✅ Persist registry to disk
- ✅ Search by category, tags, name
- ✅ Cache skills in memory and disk
- ✅ Track cache hits
- ✅ Update execution stats (success rate, tokens, latency)

---

## Usage

### Register a Skill

```python
from curby.skills import SkillRegistry, SkillMetadata

registry = SkillRegistry()

skill = SkillMetadata(
    name="book_restaurant",
    path="/skills/book_restaurant.md",
    category="web_automation",
    tags=["opentable", "booking"],
)
registry.register(skill)
```

### Load a Skill

```python
from curby.skills import SkillLoader

loader = SkillLoader()
content, metadata, cached = loader.load("book_restaurant")

if cached:
    print("Cache hit!")
else:
    print("Loaded from disk")
```

### Search Skills

```python
# By tag
web_skills = loader.search("automation", field="tags")

# By category
booking_skills = loader.search("web_automation", field="category")

# List all
all_skills = loader.list_available()
```

### Update Stats

```python
# After executing a skill
registry.update_stats(
    "book_restaurant",
    success=True,
    tokens=450.0,
    latency_ms=3500.0
)

# Success rate and other stats are automatically updated
```

---

## Next Steps

### Phase 2: Workflow Wiring (✅ COMPLETE)
- ✅ `WorkflowOrchestrator` — Match tasks to skills (confidence-based)
- ✅ `AgentSkillAdapter` — Inject skills into agent prompts
- ✅ `SkillExecutor` — Execute skill steps from agent output
- ✅ 9 comprehensive integration tests (all passing)

### Phase 3: Skill Learning System (✅ COMPLETE)
- ✅ `SkillPerformanceTracker` — Record and aggregate execution stats
- ✅ `SkillAdaptationHeuristics` — Flag underperforming skills
- ✅ `SkillConflictResolver` — Choose best skill for multi-match scenarios
- ✅ Health checks: success rate, cost, latency monitoring
- ✅ Learning log (learning.md) for audit trail
- ✅ 9 comprehensive tests (all passing)

---

## Test Coverage

**Phase 1 (8 tests):**
- Skill metadata creation
- Skill registry register/lookup
- Skill registry search
- Skill registry stats update
- Skill cache get/set
- Skill cache hit tracking
- Skill loader integration
- Skill loader list/search

**Phase 2 (9 tests):**
- Orchestrator single/multiple skill matching
- Orchestrator workflow composition
- Orchestrator explain workflow
- Agent skill adapter format skill
- Agent skill adapter format workflow prompt
- Skill executor extract usage
- Skill executor execute
- End-to-end workflow pipeline

**Phase 3 (9 tests):**
- Skill performance tracker record execution
- Skill performance tracker aggregated stats
- Adaptation heuristics low success rate detection
- Adaptation heuristics high latency detection
- Adaptation heuristics check all skills
- Adaptation heuristics log findings
- Conflict resolver single skill
- Conflict resolver multiple skills
- End-to-end learning cycle

Run all tests:
```bash
pytest .curby/skills/ -v
```

---

## Implementation Status

| Component | Status | Tests |
|-----------|--------|-------|
| **Phase 1: Manifest + Cache** | **✅ Complete** | **8/8 passing** |
| SkillMetadata | ✅ Complete | 1/8 |
| SkillRegistry | ✅ Complete | 3/8 |
| SkillCache | ✅ Complete | 2/8 |
| SkillLoader | ✅ Complete | 2/8 |
| **Phase 2: Workflow Wiring** | **✅ Complete** | **9/9 passing** |
| WorkflowOrchestrator | ✅ Complete | 4/9 |
| AgentSkillAdapter | ✅ Complete | 2/9 |
| SkillExecutor | ✅ Complete | 2/9 |
| End-to-end integration | ✅ Complete | 1/9 |
| **Phase 3: Skill Learning** | **✅ Complete** | **9/9 passing** |
| SkillPerformanceTracker | ✅ Complete | 2/9 |
| SkillAdaptationHeuristics | ✅ Complete | 4/9 |
| SkillConflictResolver | ✅ Complete | 2/9 |
| End-to-end learning cycle | ✅ Complete | 1/9 |
| **TOTAL PHASES 1-3** | **✅ Complete** | **26/26 passing** |
| **Segment 2: Fast-Path Routing** | **✅ Complete** | **42/42 passing** |
| FastPathRouter (Tier 1-2) | ✅ Complete | 18/42 |
| QuickAskRouter integration | ✅ Complete | 6/42 |
| AgentDispatchRouter integration | ✅ Complete | 6/42 |
| Integration hooks (end-to-end) | ✅ Complete | 12/42 |

**Curvy + Fast-Path Status:** ✅ **FULLY COMPLETE** — Phases 1-3 + Segment 2, 68/68 tests passing, production-ready

---

## Segment 2: Fast-Path Routing (✅ COMPLETE)

**Goal:** Integrate Curvy's skill learning system into actual task dispatch flows (quick-ask + agent spawn) to route high-confidence tasks directly to skills, bypassing redundant deliberation.

### Architecture

**Tier 1 (Direct Routing):**
- When confidence ≥ 0.95 AND success_rate ≥ 0.9, route directly to skill
- Execute skill immediately, bypass agent entirely
- Use case: Highly-practiced, low-risk automations (e.g., "send email to alice")

**Tier 2 (Fallback Routing):**
- When confidence ≥ 0.7, offer skill as candidate to agent
- If skill fails, fall back to standard agent dispatch
- Use case: Medium-confidence matches where skill may be applicable

**Tier 3 (Standard):**
- No matching skill, use standard agent dispatch
- Use case: Novel or complex tasks

### Components

1. **FastPathRouter** (`router.py`)
   - Core routing logic (Tier 1-2 analysis)
   - Thresholds: confidence, success rate, candidate limits
   - Returns: `RoutingDecision` with route_type, skill_name, confidence, reason

2. **QuickAskRouter** (`integration.py`)
   - Adapts fast-path routing for quick-ask (voice → text → voice) flows
   - Methods: `analyze_prompt()`, `should_skip_claude()`, `skill_context_for_prompt()`
   - Injects routing context into system prompts (Tier 2 fallback)

3. **AgentDispatchRouter** (`integration.py`)
   - Adapts fast-path routing for agent-spawn (Ctrl+Shift+Space) flows
   - Methods: `pre_route()`, generates agent context for Tier 1-2
   - Pre-seeds agent with skill availability before dispatch

4. **Integration Hooks** (`integration.py`)
   - `inject_routing_into_quick_ask_prompt()` — use in quick_ask.run_quick_ask()
   - `inject_routing_into_agent_dispatch()` — use in agent_runner.spawn()

### Usage

**Quick-Ask with Fast-Path:**
```python
from curby.skills import inject_routing_into_quick_ask_prompt

prompt = "send email to alice@example.com"
modified_prompt, modified_system = inject_routing_into_quick_ask_prompt(
    prompt,
    system_addendum="be shorter"
)
# If a Tier 1 match: consider skipping Claude entirely, execute skill directly
# If a Tier 2 match: inject skill context into system prompt, let Claude decide
```

**Agent Dispatch with Fast-Path:**
```python
from curby.skills import inject_routing_into_agent_dispatch

prompt = "book a restaurant for 6 people tonight"
routing_info = inject_routing_into_agent_dispatch(prompt)
# routing_info["use_skill_only"] — if True, skip agent, execute skill directly
# routing_info["system"] — includes pre-matched skill context
# routing_info["skill_name"] — suggested skill (if any)
```

**Direct Router Usage:**
```python
from curby.skills import FastPathRouter

router = FastPathRouter()
decision = router.route("send an email to bob")

if decision.route_type == "direct":
    # Execute skill immediately
    execute_skill(decision.skill_name)
elif decision.route_type == "fallback":
    # Offer skill to agent; agent can choose to use it
    pass
else:
    # Standard agent dispatch
    pass
```

### Tuning

Adjust routing thresholds by modifying FastPathRouter constants:
```python
FastPathRouter.TIER1_CONFIDENCE_THRESHOLD = 0.95  # default
FastPathRouter.TIER1_SUCCESS_RATE_THRESHOLD = 0.9  # default
FastPathRouter.TIER2_CONFIDENCE_THRESHOLD = 0.7  # default
FastPathRouter.TIER2_CANDIDATE_LIMIT = 3  # default
```

### Test Coverage

**Segment 2 Tests (42 tests):**
- FastPathRouter (18): Tier 1-2 routing logic, decision handling, explanations, thresholds
- QuickAskRouter (6): prompt analysis, skill context generation, Claude-skip logic
- AgentDispatchRouter (6): pre-routing, agent context, skill selection
- Integration hooks (12): quick-ask flow, agent dispatch flow, end-to-end scenarios

Run tests:
```bash
pytest .curby/skills/test_router.py .curby/skills/test_integration.py -v
```

---

## References

- Design: `../../approver/Design-Curvy-Integration-2026-06-14.md`
- Roadmap: `../../approver/IMPLEMENTATION-ROADMAP-2026-06-14.md`
- GitHub Issue: CasterlyGit/curby#47
