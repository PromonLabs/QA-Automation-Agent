# Graph Report - .  (2026-06-24)

## Corpus Check
- Corpus is ~44,852 words - fits in a single context window. You may not need a graph.

## Summary
- 478 nodes · 812 edges · 38 communities (31 shown, 7 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 62 edges (avg confidence: 0.69)
- Token cost: 1,800 input · 1,950 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]

## God Nodes (most connected - your core abstractions)
1. `BrowserAgent` - 27 edges
2. `Orchestrator` - 23 edges
3. `ExecutionResult` - 21 edges
4. `compilerOptions` - 16 edges
5. `cn()` - 15 edges
6. `Header()` - 13 edges
7. `Sidebar()` - 13 edges
8. `QA Automation Agent` - 13 edges
9. `_read_json()` - 10 edges
10. `ConnectionManager` - 9 edges

## Surprising Connections (you probably didn't know these)
- `Ralph Loop Session (Backend) - flow upload test 5 iterations` --references--> `QA Automation Agent`  [INFERRED]
  backend/.claude/ralph-loop.local.md → README.md
- `FastAPI` --references--> `FastAPI 0.115.6`  [INFERRED]
  README.md → backend/requirements.txt
- `Uvicorn` --references--> `Uvicorn Standard 0.32.1`  [INFERRED]
  README.md → backend/requirements.txt
- `Playwright` --references--> `Playwright 1.49.1`  [INFERRED]
  README.md → backend/requirements.txt
- `python-jose JWT Auth` --references--> `python-jose cryptography 3.3.0`  [INFERRED]
  README.md → backend/requirements.txt

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Backend Authentication Stack** — readme_python_jose, readme_passlib, requirements_python_jose, requirements_passlib [INFERRED 0.85]
- **Backend Core Runtime (FastAPI + Uvicorn + Playwright)** — requirements_fastapi, requirements_uvicorn, requirements_playwright, readme_backend [INFERRED 0.85]
- **Local LLM Browser Automation Platform** — readme_ollama, readme_qwen25_7b, readme_playwright, readme_qa_automation_agent [EXTRACTED 1.00]

## Communities (38 total, 7 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.07
Nodes (43): FlowEditInner(), Message, FlowCard(), ExecutionViewerPage(), ItemCard(), SHOT_LABELS, AgentStatus, Header() (+35 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (37): BackgroundTasks, BaseModel, authenticate_user(), create_access_token(), verify_token(), Enum, HTTPAuthorizationCredentials, ExecutionLog (+29 more)

### Community 2 - "Community 2"
Cohesion: 0.08
Nodes (19): BrowserAgent, _now(), Browser Use + Playwright browser agent.  Windows note: Playwright requires Pro, Strip decorative dashes/stars and extra whitespace from targets like         '-, Find an interactive input element across all frames., Run steps against self._context / self._page (already set up)., Playwright session — must run in ProactorEventLoop on Windows., On Windows: Playwright needs ProactorEventLoop for subprocess support. (+11 more)

### Community 3 - "Community 3"
Cohesion: 0.12
Nodes (33): _add_screenshot_to_story(), _duration(), _find_final_screenshot(), _find_named_screenshot(), _fmt_dt(), generate_pdf(), PDF Report Generator — clean invoice style. Simple centred layout with final sc, Add a labelled screenshot block to the story. (+25 more)

### Community 4 - "Community 4"
Cohesion: 0.06
Nodes (34): dependencies, axios, class-variance-authority, clsx, date-fns, lucide-react, next, @radix-ui/react-dialog (+26 more)

### Community 5 - "Community 5"
Cohesion: 0.08
Nodes (34): create_disk_flow(), CreateDiskFlowRequest, delete_disk_flow(), DiskFlow, DiskFlowContent, EnvPayload, EnvVar, _flow_id_to_stem() (+26 more)

### Community 6 - "Community 6"
Cohesion: 0.11
Nodes (25): analyse_and_save(), list_memories(), load_memory(), _memory_path(), _now(), Flow Memory Store — saves LLM insights per flow in local JSON files.  When a f, Call LLM to analyse the flow and save insights.     Falls back to basic extract, Convert a flow name to a safe filename slug. (+17 more)

### Community 7 - "Community 7"
Cohesion: 0.11
Nodes (15): _extract_json(), LLMClient, _parse_step(), LLM client — supports Ollama (local) and Claude API (Anthropic cloud). Includes, Extract a list of step dicts from any task format:     - Full JSON flow file: {, Try LLM first (if USE_FLOW_AGENT=true), fall back to direct NL parsing., Call Anthropic Claude API for LLM planning., Call local Ollama model for LLM planning. (+7 more)

### Community 8 - "Community 8"
Cohesion: 0.13
Nodes (18): _clean_step_line(), _extract_steps_from_task(), _is_screenshot_step(), _load_flow_env_file(), _now(), Orchestrator, Execution Orchestrator — coordinates LLM planning + browser execution + artifact, Clean a single line that may still have JSON formatting:       "Click the butto (+10 more)

### Community 9 - "Community 9"
Cohesion: 0.13
Nodes (17): cancel_execution(), cancel_exec(), cleanup_artifacts(), ConnectionManager, delete_report(), download_report(), get_execution(), get_logs() (+9 more)

### Community 10 - "Community 10"
Cohesion: 0.11
Nodes (22): Ralph Loop Session (Backend) - flow upload test 5 iterations, Ralph Loop Session (Root) - test.md completion-promise, Python Backend, FastAPI, Local LLM Browser Automation Platform, Next.js Frontend, Ollama, passlib bcrypt (+14 more)

### Community 11 - "Community 11"
Cohesion: 0.10
Nodes (19): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+11 more)

### Community 12 - "Community 12"
Cohesion: 0.19
Nodes (16): _bulk_path(), BulkEnvUpdate, BulkRunRequest, BulkSubscriberInput, _execute_bulk(), get_bulk_env(), get_bulk_run(), _load() (+8 more)

### Community 13 - "Community 13"
Cohesion: 0.47
Nodes (5): main(), _make_plan(), Execute the full flow once and return a result summary dict., Construct the full Tusass TopUp Talk automation plan as a BrowserAgent-ready dic, run_once()

## Knowledge Gaps
- **78 isolated node(s):** `SHOT_LABELS`, `Message`, `inter`, `metadata`, `AgentStatus` (+73 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `BrowserAgent` connect `Community 2` to `Community 8`, `Community 1`, `Community 13`?**
  _High betweenness centrality (0.107) - this node is a cross-community bridge._
- **Why does `Orchestrator` connect `Community 8` to `Community 1`, `Community 2`, `Community 3`, `Community 5`, `Community 9`, `Community 12`?**
  _High betweenness centrality (0.094) - this node is a cross-community bridge._
- **Why does `ExecutionResult` connect `Community 3` to `Community 8`, `Community 1`, `Community 5`, `Community 9`?**
  _High betweenness centrality (0.063) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `BrowserAgent` (e.g. with `ExecutionLog` and `Orchestrator`) actually correct?**
  _`BrowserAgent` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 17 inferred relationships involving `Orchestrator` (e.g. with `BrowserAgent` and `ExecutionLog`) actually correct?**
  _`Orchestrator` has 17 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `ExecutionResult` (e.g. with `Orchestrator` and `CreateDiskFlowRequest`) actually correct?**
  _`ExecutionResult` has 9 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Browser Use + Playwright browser agent.  Windows note: Playwright requires Pro`, `Schedule a coroutine in the MAIN loop from any thread (fire-and-forget).`, `Strip decorative dashes/stars and extra whitespace from targets like         '-` to the rest of the system?**
  _157 weakly-connected nodes found - possible documentation gaps or missing edges._