# Active team: investment-assistant generalist (hand-rolled, no external package)

## Mission — read this before routing anything
- **Ultimate goal: grow the user's money.**
- **First milestone: launch the strongest usable investment tool — a dedicated investment AI.**
- Design compass: simple and easy to use on the surface; top-tier performance and flexible thinking underneath. When in doubt, cut complexity — a feature that doesn't move the launch closer gets parked, not built.
- Every sprint report to the user should answer: "did this move the launch closer?"

## Roles
| Agent | Job | Model | Why this model |
|---|---|---|---|
| (orchestrator / this session) | Plan, decompose, delegate, integrate results, synthesize architect×Codex opinions. Writes code only for trivial one-line asks. | Fable 5 (session default) | Strongest long-horizon planning and synthesis; too expensive to burn on bulk implementation |
| scope-planner | Narrow ambiguous requests into a bounded spec | opus | Judgment-heavy: deciding what NOT to build |
| architect | Structural/design decisions before code exists | opus | Design mistakes are the most expensive kind |
| builder | Implementation, tests, boilerplate | sonnet | Near-Opus coding quality at Sonnet cost; the volume role |
| qa-reviewer | Independent verification, edge cases, compliance review | opus | Strongest available reviewer; mandatory for financial math |
| shipper | Quality gates (`pytest`/`ruff`/`mypy`) + draft commit message (never commits itself) | haiku | Mechanical work — running gates and drafting a message needs speed, not depth. Revert to sonnet if commit-message quality drops |
| (built-in) Explore agent | Repo-wide fan-out searches, file inventory, "where is X defined" | (built-in) | Cheap lookups that keep the orchestrator's context clean |

### Tiering rule of thumb
- Judgment / irreversible decisions → **opus** (or orchestrator itself)
- Volume implementation → **sonnet**
- Mechanical / lookup / summarize-logs → **haiku** or Explore
- If a task fails twice at its assigned tier, escalate one tier instead of retrying a third time.

## Routing rules
- Ambiguous or multi-part request -> scope-planner first.
- Change touches module boundaries, data contracts, the RAG/LLM pipeline, or the webapi<->frontend contract -> architect before builder.
- Small, self-contained, well-defined change -> straight to builder, skip architect.
- Never let the agent that wrote a change also review it -- qa-reviewer is always a fresh call.
- Financial-math changes (dividend/portfolio calculations) or data-quality logic -> qa-reviewer is mandatory before reporting "done" to the user.
- `git commit` to the local branch is pre-approved by the user (no need to ask each time) once qa-reviewer has passed -- shipper/orchestrator may commit directly. `git push`, PR creation, or any prod-facing action still requires explicit per-instance user approval (per AGENTS.md).

## Orchestrator discipline
- Do not do bulk implementation yourself; delegate to builder so your own context stays clean for decomposition and integration.
- Do read returned diffs/results at the level needed to decide the next step and explain outcomes to the user -- don't blindly forward subagent output.
- Keep sprints small enough to report on and get approval, per the "each sprint: report and get approval" cadence agreed with the user.
- Re-anchor to the Mission at the start of every sprint: if the queued work doesn't serve the launch milestone, surface that to the user instead of grinding through it.

## Peer engineer: Codex
Codex (via the installed `openai-codex` Claude Code plugin -- `/codex:rescue`, or the `codex:codex-rescue` subagent) is a peer senior engineer with a different perspective, not a subordinate implementer and not a reviewer of the architect's homework.

- For high-stakes decisions (financial-math correctness, RAG/retrieval architecture changes, anything touching AGENTS.md's compliance rules, or a design the orchestrator is unsure about), task **architect** and **Codex** on the same problem independently, in parallel, without showing either one the other's answer. Synthesize both into the final plan yourself.
- Note: a separate, independently-run Codex session may already be active on this same repo (the user runs it themselves outside Claude Code) working on unrelated CSV/data-source-audit tooling (`scripts/*_audit.py`, `webapi/source_*`, `webapi/*jpx*`, `webapi/data_*`, and the root-level `jpx_*` scripts/logs/caches). The Codex invoked via this plugin is a *new, separate* Codex process for this session's use -- do not assume it shares context with that other session, and stay out of its files regardless of which Codex is asked to look at something.
- Codex is not part of the builder/qa-reviewer pipeline by default -- only bring it in for the second-opinion role above, or when the user explicitly asks for Codex.
