# Engineering audit — CentrAlign Founding Engineer take-home (Arka / Operator)

> **Reconcile (submission hardening):** This audit describes the freeze-era architecture. It remains accurate that **`InvoicePipeline` is the control plane** and Orchestrator is mostly run-id allocation — that is intentional and documented in README / DECISIONS / LIMITATIONS. Policy numeric params now load from knowledge markdown (`kb_params.py`); `rules.yaml` is permissions-only. INV-1003 proof outcome is `SUBMITTED_AWAITING_MANAGER`. Do not treat evaluator-steering store notes as product claims.

**Subject:** branch `cursor/p0-scaffold-27a9` (historical) · later `fix/submission-hardening`  
**Method:** Read-only code audit of `/workspace` on that branch. No production code modified at audit time.  
**Product claim under test:** Autonomous AI company operator (vague request → completed work with context, tools/browser, human approval, recovery, independent verification). Primary workflow: invoice processing.

## P0 status (implemented)

| # | Item | Status |
|---|------|--------|
| 1 | RPA repair off on `make eval` / a11y path | **Done** — `allow_rpa_repair=False`; only `make eval-rpa` may enable. TRANSIENT a11y recovery hardened so 02 does not need silent heal. |
| 2 | Docs: plan / FakeLLM honesty | **Done** — README, ARCHITECTURE, DECISIONS |
| 3 | Consume `PLAN_REVISED` args | **Done** — `browser_prefs_from_plan` → pipeline / BrowserLoop |

Residual: full contiguous `make eval` not re-run after TRANSIENT fix (02 proven alone with repair off). See store `docs/audit-p0-pass.md`.

---

## Executive verdict (D)

**No** — the current architecture cannot evolve into a **generic Operator Runtime without rewriting the control plane**.

Reusable substrate exists (event store, FSM table, tool registry, browser a11y loop, recovery, budgets/stall, irreversible ledger, verifier isolation pattern). What actually runs end-to-end is `InvoicePipeline` (~1358 LOC): a hardcoded invoice procedure that ignores top-level plan steps, uses LLM outputs mostly as side-channels (structure/events/browser micro-actions), and binds policy/verify/domain/evals to procurement invoices. Evolving to a generic runtime requires replacing/generalizing that control plane and invoice-shaped domain — not a thin plugin. Substrate modules can be kept; the “operator runtime” as shipped cannot.

---

## A. Findings (questions 1–18)

### 1. Genuine generic operator/runtime infrastructure

**Present (reusable, workflow-agnostic enough):**

| Piece | Evidence |
|-------|----------|
| Append-only event store + fold/replay | `ark_operator/events/store.py`, `events/replay.py` |
| Legal FSM transitions | `ark_operator/runtime/fsm.py` (`ALLOWED`, `StateMachine.transition`) |
| Tool registry + BaseTool | `ark_operator/tools/registry.py`, `tools/base.py` |
| Budgets / stall detector | `runtime/budgets.py`, `runtime/stall_detector.py` |
| Recovery taxonomy + retries/relogin | `runtime/recovery.py` (`Recovery.handle`) |
| Irreversible ledger / idempotency | `runtime/idempotency.py` |
| Ask-human approvals | `tools/ask_human.py` + event types |
| a11y observe→one-action loop shell | `runtime/browser_loop.py` (`BrowserLoop.run_submit`) — goal string is invoice-shaped but mechanism is generic |
| LLM client interface + FakeLLM/Anthropic | `llm/base.py`, `llm/fake.py`, `llm/anthropic_client.py` |
| Knowledge FTS + episodic SQLite | `memory/knowledge.py`, `memory/episodic.py` |
| Orchestrator as *generic* phase driver | `runtime/orchestrator.py` (`run_until_idle`, `scripted_demo_handlers`) — **not used by production invoice path** |

**Not generic (control plane is the product):**

- `InvoicePipeline` (`runtime/pipeline.py`) owns all phases; docstring: *“Hiring-grade narrow autonomous path for the invoice demo scenario.”*
- Production entrypoints call `InvoicePipeline.run/resume` only (`cli.py`, `api/app.py`, `demo.py`, `evals/runner.py`).
- `Orchestrator.start()` is used solely for `run_id` allocation (`pipeline.py:166–170`); `run_until_idle` appears only in `tests/unit/test_orchestrator_p2.py`.
- `Executor.run_step` (generic plan-step execution) is **never called** from production code; only `Executor.run_browser_submit` is used (`pipeline.py:905–930`).

### 2. Secretly hard-coded invoices/procurement

**Yes — the measured path is an invoice/procurement procedure, not a request-driven generic operator.**

Evidence:

1. **Request text does not select workflow.** After UNDERSTAND, EXECUTE always lists inbox PDFs, runs `PolicyEngine.decide_invoice`, and acts on invoices (`pipeline.py:_execute` ~389–547, `_load_invoices`). There is no tool-selection from `Interpretation.permitted_actions` / `sources_needed` / `success_criteria` (those fields are written to events then unused for control).
2. **Domain is invoice-native.** `InvoiceRecord`, `InvoiceDecision`, `InvoiceOutcome` (`domain/models.py`, `domain/enums.py`); policy rules in `policy/rules.yaml` + `PolicyEngine.decide_invoice`.
3. **Company world is AcmeCorp Procure.** `company_world/portal/`, `company_world/inbox/INV-*.pdf`, `expected_outcomes.json`, knowledge SOPs for invoices.
4. **Browser loop goal is hardcoded for invoice submit** (`browser_loop.py:49–53`).
5. **FakeLLM default scripts** are invoice-processing plans (`pipeline.py:build_default_fake_llm`).
6. **Evals / scoring** are invoice decision tables (`evals/scoring.py` vs `expected_outcomes.json`).

This is an honest narrow demo if docs say so; it is not a generic operator that happens to demo invoices.

### 3. Exactly where LLM influences execution

| Prompt / call site | Function | Effect on execution |
|--------------------|----------|---------------------|
| `understand` | `Understander.interpret` → `llm.complete("understand")` | Produces `Interpretation`. **Control effect:** only `open_questions` (or `force_clarify`) can divert to CLARIFY / ask_human (`pipeline.py:243–273`). Other fields are logged. |
| `plan_top` | `Planner.create_plan` → `llm.complete("plan_top")` | Produces top-level `Plan`. **Logged** as `PLAN_CREATED`; **not walked** as the EXECUTE step graph. |
| `browser_step` | `BrowserLoop._choose` → `llm.complete("browser_step")` | Chooses **one** a11y action per iteration when `use_browser_loop` is true. Under FakeLLM this is `scripted_browser_step` (deterministic). Under Anthropic, model chooses. |
| `invoice_extract` | `PdfExtractTool._structure` → `llm.complete("invoice_extract")` | Structures fields; FakeLLM script echoes regex hint (`pdf_extract.py:scripted_invoice_extract`). Regex always runs first as hint/fallback. |
| Usage logging | `UsageLoggingLLM` wrapper | Records tokens/cost; no control. |

**LLM does not:** choose invoice decisions, clearance, verify pass/fail, or which invoices to process (filter is config/eval).

### 4. Exactly where deterministic logic influences execution

| Logic | Location | Role |
|-------|----------|------|
| Phase sequencing | `InvoicePipeline._execute` + `StateMachine` | Hardcoded UNDERSTAND→PLAN→EXECUTE→VERIFY→REPORT |
| Invoice decisions | `PolicyEngine.decide_invoice` | Duplicate / blocked / missing PO / mismatch / threshold / submit |
| Submit clearance | `PolicyEngine.clearance_for_submit` | ALLOW / REQUIRE_APPROVAL / DENY before browser write |
| Sub-plan shape | `Planner.create_invoice_subplan` | Pure function of `invoice.decision` (no LLM) |
| Act dispatch | `_act_on_invoice` / `_submit_with_clearance` | Walks subplan step tools OR falls back to decision enums |
| FakeLLM browser driver | `scripted_browser_step` | Observation-reactive fill/click macro |
| RPA shortcut | `BrowserTool._submit_invoice` | Fixed CSS-id form fill + submit |
| Recovery | `Recovery.handle` | Retries / relogin by `FailureKind` |
| Repair | `_repair_missing_submits` | After verifier miss, optional RPA resubmit |
| Verification | `BrowserVerifier.verify_invoices` + `check_invoice_against_portal` | Deterministic criteria |
| Learning selector | `prefer_label_first_from_lessons` | String-match on lesson text |
| Idempotency / ledger | `IrreversibleLedger`, `EventStore.remember_idempotent` | Skip re-work |
| PDF regex | `_parse_invoice_text` | Authoritative when LLM absent/fails |

### 5. Browser actions genuinely LLM-selected from observations

**Only on the real-model a11y path.**

- Path: `InvoicePipeline._browser_submit_loop` → `Executor.run_browser_submit` → `BrowserLoop.run_submit` → observe → `_choose` → `llm.complete("browser_step", …, schema=BrowserActionChoice)` → tool (`browser_loop.py:89–193`, `_choose:304–337`).
- Proven under Anthropic by `tests/integration/test_browser_loop.py::test_real_haiku_a11y_browser_loop` (skip without key) and `make eval-llm` (`evals/runner.py` `--llm`, `real_llm=True`).
- Prompt requires one action from compact a11y tree (`llm/prompts/browser_step.md`).

### 6. Predetermined / macros

| Path | Mechanism | When |
|------|-----------|------|
| FakeLLM a11y | `scripted_browser_step` — fixed form-fill order + submit-id click, branched on URL/obs | **`make eval` default**, demo, most integration tests |
| RPA shortcut | `BrowserTool._submit_invoice` — `#vendor_id`…`#submit-invoice-button` | `use_browser_loop=False` / `make eval-rpa`; also FakeLLM **repair** after verifier miss (`allow_rpa_repair=True`) |
| Label→stable recovery | `BrowserLoop._reresolve_and_click_submit` / `click_submit_resolved` | Hardcoded recovery, not LLM |

README dual-path table matches this. CI 12/12 therefore proves **wiring + policy + portal + verifier + scripted loop**, not model judgment for browser actions.

### 7. What `make eval` actually tests

From `Makefile` → `python -m evals.runner` (no `--llm`):

- **LLM:** `build_default_fake_llm()` + `scripted_browser_step` + `scripted_invoice_extract` (`evals/runner.py:_build_eval_llm`, `real_llm=False`).
- **Browser:** a11y loop (`use_browser_loop=True`).
- **Repair:** `allow_rpa_repair=True` — after verifier miss, may heal via `submit_invoice` shortcut (`pipeline.py:_repair_missing_submits`).
- **Scenarios:** all 12 YAML files under `evals/scenarios/`.
- **Scoring:** `evals/scoring.py` vs `company_world/expected_outcomes.json` — `task_success` = all decisions correct **and** `verification.passed`; also false_success, unsafe, approvals, recoveries.
- **Portal:** ephemeral uvicorn + fault injection per scenario.
- **CI:** `.github/workflows/ci.yml` runs `make eval` (not `eval-llm`).

Committed `evals/results/summary.md`: 12/12 task_success; recoveries 5/1/1 on 02/03/04.

### 8. What `make eval-llm` actually tests

From `Makefile` → `evals.runner --llm`:

- **Requires** `ANTHROPIC_API_KEY` (`_require_anthropic_key`); exit 2, **no FakeLLM fallback**.
- **LLM:** `build_llm(require_anthropic=True)` → `AnthropicClient`.
- **Subset:** `DEFAULT_LLM_SCENARIOS` = 06, 05, 04, 03, 01-happy (`evals/runner.py:42–48`).
- **Happy narrowed:** `INV-1001/1002/1008` only (`LLM_HAPPY_INVOICE_FILTER`).
- **Repair off:** `allow_rpa_repair=False`.
- **Browser:** a11y loop with **model-chosen** `browser_step`.
- Writes `evals/results/summary-llm.md` / `.json` (live run gitignored; template committed).

### 9. Which tests use FakeLLM

| Suite / entry | Mechanism |
|---------------|-----------|
| `make eval` / `operator eval` | FakeLLM scripts |
| `make demo` | `build_default_fake_llm()` (`demo.py`) |
| `tests/integration/test_evals_core.py` | `build_default_fake_llm` |
| `tests/integration/test_learning.py` | same |
| `tests/integration/test_browser_loop.py` (non-skip tests) | `_loop_llm()` → FakeLLM |
| `tests/integration/test_approval_pause.py` | FakeLLM |
| `tests/integration/test_resume_duplicate.py` | FakeLLM |
| `tests/integration/test_pipeline_decisions.py` | FakeLLM path (policy over extracts) |
| `tests/unit/test_browser_loop_script.py` | scripts `scripted_browser_step` directly |
| `tests/unit/test_llm_usage.py`, `test_smoke.py`, `test_orchestrator_p2.py` | FakeLLM |
| Default `build_llm()` without key | falls back to FakeLLM (`pipeline.py:1336–1358`) |

### 10. Which tests use a real model

| Entry | Notes |
|-------|-------|
| `make eval-llm` / `operator eval --llm` | Real Haiku subset; fails closed without key |
| `tests/integration/test_real_llm_p4.py` | Understand+plan via Anthropic; **decisions still PolicyEngine**; skip without key |
| `tests/integration/test_browser_loop.py::test_real_haiku_a11y_browser_loop` | Real Haiku a11y submit; skip without key |
| `tests/unit/test_llm_config.py` | Asserts Anthropic construction / require key (no live completion needed for failure path) |

CI does **not** run real-model tests/evals.

### 11. Evidence plans affect execution

**Weak / mostly audit theater for top-level plans; narrow effect for sub-plans.**

| Claim | Reality | Evidence |
|-------|---------|----------|
| Top-level plan drives EXECUTE | **False.** Pipeline never iterates `self._plan.steps` for tool dispatch. Phases are imperative. | `_execute` after PLAN goes straight to portal master load + invoice loop |
| Per-invoice sub-plan drives act | **Partial.** `_act_on_invoice` walks `plan.steps` and branches on `tool` / step id suffix (`browser`→submit, `ask_human`→ask). Sub-plan is **derived after** `policy.decide_invoice`, so it encodes the decision rather than discovering it. | `planner.py:86–129`, `pipeline.py:456–470`, `692–734` |
| `PLAN_REVISED` rewires runtime | **Mostly false for execution.** `propose_revision` writes args like `prefer_stable_ids`, `relogin_on_auth_expired`, `recover_wrong_page` (`plan_revision.py:115–210`). **No consumer** of those keys exists under `ark_operator/` (grep hits only `plan_revision.py`). Mid-run recovery uses `Recovery` / browser_loop hardcoded paths, not revised plan args. | |
| Lessons → plan revise | Lesson content can emit `PLAN_REVISED` on top plan (`pipeline.py:295–313`); selector flip for browser is applied via `prefer_label_first_from_lessons` at `_setup_tools`, **not** by reading revised plan args. | |

ARCHITECTURE.md line 29: *“Per-invoice sub-plans drive `_act_on_invoice`”* — true only as enum-shaped step dispatch, not as a general plan executor.

### 12. Evidence for recovery

**Real and exercised.**

| Mechanism | Evidence |
|-----------|----------|
| Transient / auth / element retries | `Recovery.handle` (`recovery.py:36–72`) |
| Browser loop AUTH_EXPIRED + TRANSIENT | `browser_loop.py:233–285` (relogin, goto `/invoices/submit`, `RECOVERY_ATTEMPTED`) |
| UI rename label→stable id | `browser_loop.py:194–218`, `BrowserTool.click_submit_resolved` |
| Shortcut-path recovery | `pipeline.py:_browser_submit_shortcut` + `Recovery.handle` |
| Verifier REPAIR cycles | `_execute` VERIFY→REPAIR→`_repair_missing_submits` (`pipeline.py:572–599`) |
| Eval metrics | `summary.md`: 02=5, 03=1, 04=1 recoveries; learning test asserts run1 recoveries ≥1 under `ui_rename` |

### 13. Evidence for independent verification

**Real and material.**

| Property | Evidence |
|----------|----------|
| Fresh Playwright context (not executor cookies) | `BrowserVerifier._probe_isolated_browser` (`browser_verifier.py:64–111`) |
| Fresh `PortalApiTool` session | `BrowserVerifier.__init__` + `verify_invoices` API read |
| Submit-class browser scrape is hard fail | `browser_sees_{invoice}` criterion (`browser_verifier.py:155–182`) — `passed=browser_hit` |
| COMPLETED gated on verify | `_build_report` demotes COMPLETED if `not verification.passed` (`pipeline.py:1230–1233`) |
| Alias | `Verifier = BrowserVerifier` (`browser_verifier.py:210–211`) |

Agent does not grade itself via its own browser session. API remains structured ground truth; scrape is an additional hard check for submit-class invoices.

### 14. Evidence for learning / recovery improvement

**Narrow but real for one lever; not general learning.**

| Mechanism | Evidence |
|-----------|----------|
| Distill from recoveries/security | `EpisodicMemory.distill_from_run` — template strings from `RECOVERY_ATTEMPTED` kinds (`episodic.py:38–110`); no baseline when empty |
| Apply lesson **content** | `prefer_label_first_from_lessons` / `selector_strategy_from_lessons` (`lesson_policy.py`) — not `bool(lessons)` |
| Measurable improvement | `tests/integration/test_learning.py`: run1 under `ui_rename` recovers; run2 with stable-id lesson has **fewer** recoveries |
| Cross-run wiring | `InvoicePipeline.run` retrieves lessons → `_setup_tools(prefer_label_first=…)` |

Limits: hardcoded string templates; topic always `"portal_ui"`; only selector strategy flips; FakeLLM `scripted_browser_step` also encodes prefer-label via hints — learning AC is engineered for this fault.

### 15. Invoice-specific components

- `InvoicePipeline`, `PipelineConfig` (inbox, invoice_filter, crash_after_invoices, allow_rpa_repair)
- `PolicyEngine.decide_invoice` / `clearance_for_submit` / `rules.yaml` thresholds & vendors
- `Planner.create_invoice_subplan`
- `PdfExtractTool` + `InvoiceExtractSchema` + `scripted_invoice_extract`
- `BrowserLoop.run_submit` goal/fields; `BrowserTool._submit_invoice`
- `verify/checks.py` (`expected_portal_status`, duplicate attachment rules)
- Domain: `InvoiceRecord`, decisions/outcomes
- `company_world/*` (portal, inbox PDFs, expected_outcomes, invoice SOPs)
- All 12 eval scenarios + scoring
- FakeLLM default scripts; prompts `invoice_extract.md`, invoice-centric `browser_step.md`
- Episodic lessons naming `#submit-invoice-button` / INV-1010
- Demo / CLI default request string

### 16. What must change for a completely different workflow

Minimum to run e.g. “reconcile last month’s bank feed” or “onboard a vendor” with comparable honesty:

| Layer | Change |
|-------|--------|
| Control plane | Replace or generalize `InvoicePipeline._execute` so phases/tools come from plan or workflow module — not a hardcoded invoice loop |
| Domain | New records/decisions (or generic WorkItem); stop assuming `InvoiceDecision` |
| Policy | New rules engine or rule packs; `decide_invoice` cannot stay central |
| Tools | Domain tools beyond pdf_extract/portal invoice APIs; browser goal/postconditions per workflow |
| Verify | New independent checks (not `check_invoice_against_portal`) |
| World/evals | New company surface + expected outcomes + scenarios |
| Memory/prompts | New knowledge, distill heuristics, prompt ids |
| UI copy | Approval cards / Proof currently invoice-shaped |

**Keepable:** EventStore, FSM table (maybe extended), ToolRegistry, Recovery, Budgets, Stall, IrreversibleLedger pattern, BrowserLoop shell, AskHuman, Anthropic/FakeLLM adapters, Knowledge FTS shell.

### 17. Architecture smells

| Smell | Evidence |
|-------|----------|
| **God module** | `pipeline.py` 1358 LOC owns phases, loading, policy act, browser, repair, report, FakeLLM factory |
| **Dual control planes** | Documented `Orchestrator` phase machine unused in prod; `scripted_demo_handlers` test-only; real path is imperative pipeline |
| **Fake plan executor** | Top-level Plan + `Executor.run_step` unused; sub-plans mirror decisions already taken |
| **Dead plan-revision args** | `prefer_stable_ids` / `relogin_on_auth_expired` / `recover_wrong_page` never read |
| **Hidden coupling** | Learning, FakeLLM script hints, and BrowserTool.prefer_label_first all encode the same ui_rename story |
| **Workflow assumptions in “runtime”** | Package named operator runtime; class is `InvoicePipeline` |
| **Macro-as-LLM** | CI success path uses `scripted_browser_step` — observation-reactive RPA under FakeLLM interface |
| **Silent RPA heal on FakeLLM eval** | `allow_rpa_repair=True` can mask a11y loop failures after VERIFY |
| **Interpretation mostly unused** | Only `open_questions` affects control |
| **Tests that can pass without intent** | Orchestrator P2 AC tests a toy handler path, not `InvoicePipeline`; FakeLLM 12/12 does not prove model browser autonomy (README is mostly honest; DECISIONS sometimes less so) |
| **Coverage doc drift** | DECISIONS claims ≥88%; `Makefile` `--cov-fail-under=82` |

### 18. README/docs claims stronger than implementation proves

| Claim | Status vs code |
|-------|----------------|
| README dual track FakeLLM vs Haiku | **Accurate** |
| README: policy/verify never FakeLLM | **Accurate** |
| README: a11y default; RPA optional; repair off on eval-llm | **Accurate** |
| README Limitations: decisions deterministic | **Accurate** |
| ARCHITECTURE: “Per-invoice sub-plans drive `_act_on_invoice`” | **Overstated** — dispatch only; plans don’t schedule discovery/policy |
| ARCHITECTURE / README “autonomous AI employee” framing | **Marketing-stronger** than control-plane reality (procedure + LLM side-channels) |
| DECISIONS: “FakeLLM scripts understand/plan **structure** only; never … portal writes” | **False** — FakeLLM `browser_step` **does** drive portal writes via the a11y loop; `invoice_extract` also scripted |
| DECISIONS: coverage ≥88% | **Stale** vs Makefile 82% |
| DECISIONS: “Single runtime; Orchestrator only allocates run_id” | **Accurate** (and reveals Orchestrator is not the runtime) |
| PLAN_REVISED “observation-driven” as adaptation | **Partially overstated** — events are real; revised args do not rewire execution |
| Older store docs (e.g. prior strict eval) claiming RPA default / soft browser scrape / no CI | **Obsolete** vs current branch — do not treat as current truth |

---

## B. Prioritized fix list (for CentrAlign submission)

### P0 — must-fix before submission

1. **Kill or quarantine FakeLLM RPA repair on the measured story**  
   Either default `allow_rpa_repair=False` for `make eval`, or clearly fail scenarios that needed repair; do not let shortcut heal a11y misses silently when marketing a11y as the measured path.  
   *Files:* `evals/runner.py` (`run_scenario`), `ark_operator/runtime/pipeline.py` (`PipelineConfig.allow_rpa_repair`, `_repair_missing_submits`).  
   *Why:* CentrAlign will ask what 12/12 proves; silent RPA heal muddies the answer.  
   *Risk:* Some flaky scenarios may fail until loop recovery is solid.  
   *Test:* `make eval`; assert no `repair via submit_invoice shortcut` events on green runs, or score them separately.

2. **Stop overstating plan-driven execution in README/ARCHITECTURE**  
   State explicitly: top-level plan is structural/logging; EXECUTE is `InvoicePipeline` procedure; sub-plans mirror policy decisions.  
   *Files:* `README.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` (FakeLLM boundary row).  
   *Why:* Founding-engineer bar punishes elegant lies more than narrow honesty.  
   *Risk:* Docs-only.  
   *Test:* Human read; greps for “plans drive” consistency.

3. **Either consume `PLAN_REVISED` args or delete the dead fields**  
   Wire `prefer_stable_ids` into browser setup **from the revised plan**, or stop emitting unused args (keep reason/next_steps events).  
   *Files:* `plan_revision.py`, `pipeline.py` (`_emit_plan_revision`, `_browser_submit_loop`).  
   *Why:* Fake abstraction smell in interview walkthrough.  
   *Risk:* Low if behavior preserved via lessons path.  
   *Test:* `tests/unit/test_plan_revision.py`, `tests/integration/test_learning.py`.

### P1 — strongly recommended

4. **Make `Executor.run_step` the EXECUTE unit (or delete it)**  
   Today it is dead API surface. Either schedule sub-plan steps through it, or remove to avoid dual-executor confusion.  
   *Files:* `runtime/executor.py`, `pipeline.py:_act_on_invoice`.  
   *Why:* Shows one control plane.  
   *Risk:* Medium — refactor of act path.  
   *Test:* approval/resume/eval scenarios 05–07, 12.

5. **Shrink `InvoicePipeline` / extract workflow module**  
   Split phase helpers vs invoice workflow so the “runtime” vs “invoice app” boundary is visible in package layout.  
   *Files:* `runtime/pipeline.py` → e.g. `workflows/invoices.py` + thin runtime loop.  
   *Why:* Direct answer to “can this become Operator Runtime?”  
   *Risk:* High churn; keep behavior identical.  
   *Test:* full `make test && make eval`.

6. **Document FakeLLM browser_step as a predetermined driver** in DECISIONS (align with README).  
   *Files:* `docs/DECISIONS.md`.  
   *Risk:* None.

7. **Use Interpretation fields or stop producing unused ones in the happy path**  
   e.g. gate tools by `permitted_actions`, or mark them display-only in UI.  
   *Files:* `understand.py`, `pipeline.py`, UI templates if any.  
   *Risk:* Low–medium.

### P2 — optional

8. Genericize `BrowserLoop.run_submit(goal, postcondition_fn, fields)` signature (remove invoice-only goal string).  
9. Add one non-invoice smoke workflow (even stub) to prove substrate reuse — only if time; else don’t fake it.  
10. Align coverage number in DECISIONS with Makefile.  
11. Expand real-LLM subset or publish cost/flake notes more prominently (README already decent).

---

## C. Proposed changes — file / function detail

| # | Pri | Change | Files / symbols | Why (CentrAlign) | Regression risk | How to test |
|---|-----|--------|-----------------|------------------|-----------------|-------------|
| 1 | P0 | Disable RPA repair on `make eval` or score it | `evals/runner.py:run_scenario`; `PipelineConfig.allow_rpa_repair`; `_repair_missing_submits` | Honest measured path | Medium (scenario flakes) | `make eval`; grep RECOVERY for shortcut repair |
| 2 | P0 | Docs: plan/FakeLLM honesty | `README.md`, `ARCHITECTURE.md`, `DECISIONS.md` | Interview integrity | None | Doc review |
| 3 | P0 | Wire or drop revision args | `plan_revision.propose_revision`; `pipeline._emit_plan_revision`; browser prefer flags | Remove fake adaptation | Low | unit plan_revision + learning IT |
| 4 | P1 | Unify execute path via `Executor.run_step` or delete | `executor.py`; `_act_on_invoice` | One runtime story | Medium | evals 05–07, 12; approval pause IT |
| 5 | P1 | Extract invoice workflow from runtime package | `pipeline.py` split | Generic-runtime narrative | High | `make lint test eval` |
| 6 | P1 | Fix DECISIONS FakeLLM boundary | `DECISIONS.md` | Consistency with code | None | Doc review |
| 7 | P1 | Interpretation control or label display-only | `understand.py`; `_execute` UNDERSTAND | Less theater | Low | clarify scenario 11 |
| 8 | P2 | Parameterize BrowserLoop goal/postcondition | `browser_loop.BrowserLoop.run_submit` | Reuse | Low | browser_loop tests |
| 9 | P2 | Coverage claim sync | `DECISIONS.md` vs `Makefile` | Hygiene | None | n/a |

---

## D. Verdict (standalone)

**Can current architecture evolve into a generic Operator Runtime without a rewrite?**

### **No.**

**Rationale (evidence-based):**

1. Production control plane is `InvoicePipeline` — invoice procedure, not a plan/tool scheduler (`pipeline.py`; Orchestrator handlers unused).
2. Top-level plans and `Executor.run_step` do not drive work; LLM influence is bounded to understand(clarify), browser micro-actions, and extract structure.
3. Policy, verify, domain, company world, and evals are invoice-procurement-specific end-to-end.
4. Substrate (events, FSM, tools, browser loop, recovery, ledger, verifier isolation) **can** be reused incrementally, but that is **extraction + rewrite of the control plane**, not evolution-without-rewrite of the architecture that currently ships green metrics.

A truthful pitch for CentrAlign: *narrow real invoice operator with durable runtime primitives and an honest dual eval track* — not *generic Operator Runtime already*.

---

## Appendix — control-flow sketch (as implemented)

```
request
  → Orchestrator.start (run_id only)
  → InvoicePipeline._execute
       UNDERSTAND: LLM Interpretation (open_questions → CLARIFY?)
       PLAN: LLM top Plan (logged) + optional lesson PLAN_REVISED (args unused)
       EXECUTE: list PDFs → pdf_extract (LLM/regex) → PolicyEngine.decide_invoice
              → create_invoice_subplan(decision) → _act_on_invoice
              → clearance → BrowserLoop (LLM/scripted step) OR submit_invoice RPA
       VERIFY: BrowserVerifier (fresh browser + API)
       REPAIR?: optional RPA heal (FakeLLM eval)
       REPORT + episodic.distill_from_run
```

---

*Audit complete. Store path: `/cursor/stores/self/docs/AUDIT.md` (project store). Branch docs copy attempted separately if docs-only commit allowed.*
