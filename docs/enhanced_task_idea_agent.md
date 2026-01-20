# K8s Task Idea Agent - Enhanced with Rich Variations

## Overview
The enhanced `k8s_task_idea_agent` now generates **comprehensive Kubernetes learning concepts** with **3 task variations each** (Beginner → Intermediate → Advanced).

## Key Improvements

### 1. Rich Task Concept Generation
Instead of generating just task names, the agent now:
- Reads Kubernetes documentation
- Identifies core learning concepts
- Creates 3 task variations with **increasing difficulty**
- Stores full descriptions, objectives, and learning outcomes

### 2. Memory Structure (Enhanced)
Previously: `{"ideas": ["001_create_namespace", "002_deploy_pod"]}`

Now:
```json
{
  "ideas": {
    "**pod_disruption_budgets_(pdbs)**": {
      "concept": "Pod Disruption Budgets (PDBs)",
      "description": "Detailed description...",
      "variations": [
        "071_pod_disruption_budget_basic",
        "072_pod_disruption_budget_intermediate", 
        "073_pod_disruption_budget_advanced"
      ],
      "difficulty": "Mixed (Beginner→Intermediate→Advanced)",
      "tags": ["scheduling", "policies", "availability"]
    }
  }
}
```

### 3. Task Progression Path
Each concept generates a **learning progression**:

**Example: Pod Disruption Budgets (PDBs)**
1. **BEGINNER (071)** — 30 min
   - Understand what PDBs are and why they matter
   - Create basic PDB with `minAvailable`
   - Observe behavior during node drain
   
2. **INTERMEDIATE (072)** — 45 min
   - Use `maxUnavailable` vs `minAvailable`
   - Coordinate PDBs with rolling updates
   - Troubleshoot misconfigurations
   
3. **ADVANCED (073)** — 75 min
   - Design PDBs for multi-tier applications
   - Combine with StatefulSets and topology constraints
   - Handle cluster-scale disruption scenarios

### 4. Duplicate Prevention
- Checks by **concept name**, not just task ID
- Memory context injected: "Do NOT suggest these concepts: [list]"
- Prevents generating similar topics (e.g., "Pod Disruption Budgets" twice)

## Memory Storage Format

```json
{
  "ideas": {
    "concept_key": {
      "concept": "Human-readable concept name",
      "description": "Multi-sentence description explaining the concept",
      "variations": [
        "###_concept_level_one",
        "###_concept_level_two",
        "###_concept_level_three"
      ],
      "difficulty": "Mixed (Beginner→Intermediate→Advanced)",
      "tags": ["tag1", "tag2", "tag3"]
    }
  }
}
```

## Generated Example Concepts

### 1. Pod Disruption Budgets (PDBs)
- **Tasks:** 071, 072, 073
- **Tags:** scheduling, policies, availability, reliability
- **Progression:** Basic → Intermediate → Advanced

### 2. Topology Spread Constraints  
- **Tasks:** 041, 042, 043
- **Tags:** scheduling, high-availability, resilience, workloads
- **Progression:** Basic distribution → Multi-zone → Advanced failure modes

## Usage

### Generate Concepts
```bash
cd /home/developer/Documents/data-disk/k8s-game-rule-builder
source .venv/bin/activate
python -m agents.k8s_task_idea_agent
```

### Output Shows
```
Round 1: Generating New Kubernetes Concept with Variations
✅ Stored concept: Pod Disruption Budgets (PDBs)
   Variations (Tasks): 071_pod_disruption_budget_basic, 
                       072_pod_disruption_budget_intermediate,
                       073_pod_disruption_budget_advanced
   Tags: scheduling, policies, availability, reliability
```

### Check Memory
```bash
cat .task_ideas_memory.json | python -m json.tool
```

## Integration with Workflow

The idea agent feeds into the **task generator**:
1. **Idea Agent** → Generates 3 variations of a concept
2. **Task Generator** → Creates full task YAML files (setup, answer, tests)
3. **Pytest Agent** → Validates the generated tasks

```python
# Extract concept and variations from idea agent
concept = "Pod Disruption Budgets (PDBs)"
variations = [
    "071_pod_disruption_budget_basic",
    "072_pod_disruption_budget_intermediate",
    "073_pod_disruption_budget_advanced"
]

# Pass to task generator to create 3 full tasks
for task_id in variations:
    # Create tests/game02/{task_id}/ with templates
```

## Benefits

✅ **Comprehensive Learning Paths** — 3 difficulty levels per concept  
✅ **Rich Content** — Full descriptions, objectives, skills, time estimates  
✅ **No Duplicates** — Memory prevents similar concepts  
✅ **Scalable** — Can generate 100+ unique concepts systematically  
✅ **Production-Grade** — Includes real-world scenarios in ADVANCED tasks  

## Next Steps

- Chain with task generator to create full tasks from variations
- Build interactive pathway UI showing concept progressions
- Add concept recommendations based on student progress
- Export variations as curriculum structure

