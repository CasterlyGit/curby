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

### Phase 2: Workflow Wiring (1h, Segment 2)
- `WorkflowOrchestrator` — Match tasks to skills
- `AgentSkillAdapter` — Inject skills into agent prompts
- `SkillExecutor` — Execute skill steps
- Integration tests

### Phase 3: Skill Learning System (1h, Segment 2)
- `SkillPerformanceTracker` — Monitor success rates
- `SkillAdaptationHeuristics` — Flag underperforming skills
- Auto-update skill cache on new learning
- Conflict resolution (prefer higher success rate)

---

## Test Coverage

All Phase 1 components tested:
```
✓ Skill metadata creation
✓ Skill registry register/lookup
✓ Skill registry search
✓ Skill registry stats update
✓ Skill cache get/set
✓ Skill cache hit tracking
✓ Skill loader integration
✓ Skill loader list/search
```

Run tests:
```bash
pytest .curby/skills/test_manifest.py -v
```

---

## Implementation Status

| Component | Status | Tests |
|-----------|--------|-------|
| SkillMetadata | ✅ Complete | 1/8 |
| SkillRegistry | ✅ Complete | 3/8 |
| SkillCache | ✅ Complete | 2/8 |
| SkillLoader | ✅ Complete | 2/8 |
| **Total Phase 1** | **✅ Complete** | **8/8 passing** |

**Next:** Phase 2 workflow wiring (Segment 2, week of 2026-06-16)

---

## References

- Design: `../../approver/Design-Curvy-Integration-2026-06-14.md`
- Roadmap: `../../approver/IMPLEMENTATION-ROADMAP-2026-06-14.md`
- GitHub Issue: CasterlyGit/curby#47
