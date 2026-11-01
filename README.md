# v1.9 — Conflict-Aware Recovery Optimization Lab (NEW)

DisruptionIQ now includes an actual **deterministic, exact 0/1 mixed-integer
portfolio optimizer**, written in Python (standard library only) and surfaced in
Reflex as **Optimization lab**. No new non-Reflex Python dependency is required.

The decision variables choose at most one of the prevalidated recovery plays per
at-risk order. The engine selects the portfolio that maximizes **modeled avoided
SLA loss minus recovery spend**, subject to:

- Shared available inventory per warehouse and SKU (on_hand - reserved - safety_stock)
- Synthetic supplier-SKU capacity (80 units per supplier/SKU initially; persisted)
- At most one expedition against each physical shipment in a portfolio
- Scenario-specific maximum budget and inter-warehouse transfer units
- A single recovery action per order, plus exclusion of orders already being recovered

The solver is a bounded, exact branch-and-bound over **binary decisions** for up
to 12 affected orders (max nine eligible plays each). It is a working small-data
MILP-style optimizer, **not** a general-purpose industrial MILP engine. The
objective's modeled SLA loss is 18% of at-risk order value, risk-weighted,
with a separate late-salvage assumption. It is a **synthetic proxy**, not a
verified contractual fine or financial forecast.

## v1.9 demo workflow

1. Sign in as `analyst`, fire **Ocean Carrier Delay** and **Supplier Disruption**.
2. Open **Optimization lab**. Select `BALANCED` / `SLA_FIRST` / `COST_FIRST`,
   enter your budget (e.g. `30000`) and transport limit (e.g. `120`).
3. Click **RUN WHAT-IF OPTIMIZER**. Review the 3 scenario comparisons,
   conflict detection, chosen cross-order allocations, on-time recovery counts,
   expected costs and modeled avoidance (read-only).
4. To show a constrained tradeoff, rerun with budget `1500`, transfer limit `70`:
   fewer orders can be recovered under the shared limitations.
5. As Analyst, click **PROPOSE OPTIMIZED PORTFOLIO**. The engine atomically
   re-solves against current stock, validates a matching result signature, and
   creates independently approvable pending recovery plans.
6. Switch to `manager` to approve REALLOCATE / EXPEDITE / SPLIT proposals.
   Switch to `procurement` to approve REORDER proposals. **No self approval**.
7. Approved plans need a separate **SIMULATE EXECUTION → YES, EXECUTE** step;
   source inventory and supplier capacity are revalidated inside SQLite
   transactions. Audit and notifications record the changes.

A successful What-If preview does not reserve or mutate inventory. Approval
also does not move goods. Separately executed plans can become stale if other
operational changes occur; they are always checked again before execution.
This is deliberately not described as a guaranteed atomic batch dispatch.

## v1.9 deployment on Windows CMD

Stop the old Reflex server first (`Ctrl+C`). Download the v1.9 ZIP and **use CMD
syntax**, not PowerShell backtick continuation syntax:

```cmd
cd /d "your directory"
powershell.exe -NoProfile -Command "Expand-Archive -LiteralPath '%USERPROFILE%\Downloads\DisruptionIQ_Optimization_Patch_v1.9.zip' -DestinationPath '.' -Force"
python -m unittest discover -s tests -v
reflex run
```

To test the optimizer even when Windows npm/Rolldown blocks Reflex, run:

```cmd
python scripts\optimize_demo.py --demo-events --budget 1500 --transfer 70
```

This only simulates disruptions if you pass `--demo-events`; the optimizer
itself is read-only. It prints the constrained allocation and conflicts.

The existing SQLite file is **not deleted**. `init_db()` adds a synthetic
supplier capacity table, an optimization run table, and one nullable foreign key
column to `plans` if absent. `REFLEX_USE_NPM` and the prior Windows Rolldown
`EBUSY` errors are separate from this optimization feature.

---

# DISRUPTIONIQ / Recovery Command System

## v1.5: Role-aware approval buttons and independent signoff

The approval screen now displays **APPROVE / REJECT / REQUEST CHANGES** only for the current authenticated database user when their role matches the recovery kind and they are **not** the original proposer. The original proposer can resubmit a requested change. Confirmed execution is shown only to an eligible approver for an independently approved plan. All backend checks in `engine.approve_or_reject()`, `engine.resubmit()` and `engine.execute_plan()` remain authoritative and unchanged.

Required source files: `disruption_iq/engine.py`, `disruption_iq/schemas.py`, `disruption_iq/disruption_iq.py` plus new regression test `tests/test_approval_visibility.py`. No database migration or reset is required.

**Windows npm EBUSY is separate:** it originates from Reflex/npm trying to update a generated Rolldown `.node` binary in `.web/node_modules` while it is locked. This can occur during frontend refresh and does not prove that the approval handler executed. Stop all Reflex and Node.js sessions, verify none remain, rename/delete only the generated `.web` directory, and rerun with Bun (`$env:REFLEX_USE_NPM = "0"`) if available. Check `reflex.lock` for a leftover `package-lock.json` if Reflex keeps using npm. Do not delete the SQLite database. If the generated directory itself cannot be removed, restart Windows before trying again.

**Domain:** Logistics and supply chain • **Stack:** Python 3.11+, [Reflex](https://reflex.dev), Python standard-library `sqlite3`, HTML/CSS via Reflex • **Frontend:** Reflex, no user-authored JavaScript • **Database:** persistent SQLite.

An end-to-end demo of upstream carrier dependency tracing and **independent dual-control approvals**. Synthetic data is generated automatically on first launch. A single cargo delay propagates through the **shipment → purchase order → supplier → warehouse/SKU → stock available by SLA → impacted customer order** graph in SQL. Recovery candidates use inventory and lead-time checks; real AI can explain and recommend among those constrained candidates.

## v1.3: Reflex `UntypedVarError` fix (2026-10-28)

Reflex requires concrete value types in collections used by `rx.foreach`.
The old `list[dict[str, Any]]` state annotations caused errors such as:

```
UntypedVarError: Cannot foreach on untyped var 'State.disruptions'
```

The new `disruption_iq/schemas.py` contains `TypedDict` view models for every
collection shown in a list/table: disruptions, orders, approvals, shipments,
warehouse inventory, suppliers, recovery options, audit, notifications, tasks,
lineage records and risk bars. In `state.py`, each `list[dict[str, Any]]` is
replaced by the relevant `list[TypedDictName]`. The `signal_card` kind label is
precomputed in Python instead of applying a string transformation to an
untyped client-side value.

**Required files for the minimal update:**
- `disruption_iq/state.py` (replace)
- `disruption_iq/schemas.py` (new)
- `disruption_iq/disruption_iq.py` (replace: uses precomputed kind label)

Do not replace or delete `disruption_iq.sqlite3`—it contains persistent data.
After copying files stop Reflex (`Ctrl+C`), run
`python -m unittest discover -s tests -v` and then `reflex run`.

The packaged backend and source-contract tests pass, but a live Reflex
frontend compilation could not be run in the packaging environment (Reflex
was unavailable). Reflex v0.10.x is the intended framework family. If you see
incompatible dependency behavior on Python 3.15, use Python 3.12 in a new venv.

## Reflex 0.9+/0.10 setter compatibility fix (2026-10-28)

The UI uses explicit setters for `username`, `password`, `message`, `decision_note`,
`modify_qty`, and `webhook_json`. Reflex 0.9+ no longer generates these `set_<var>`
methods by default. The event handlers are defined in `disruption_iq/state.py`.
This avoids the compile-time error `AttributeError: type object 'State' has no
attribute 'set_message'` and analogous errors for the other input fields.

After updating the files, stop the running server and restart it:

```powershell
# From the DisruptionIQ project folder, in your Python virtual environment
python -m unittest discover -s tests -v
reflex run
```

If you have Python 3.15 and experience unrelated dependency/runtime issues,
try a clean virtual environment with Python 3.12 or 3.13. The missing-setter
error itself does **not** require changing Python versions.

The domain tests and static event-binding checks run without Reflex installed.
A live Reflex compilation still needs Reflex and its frontend dependencies.

## 1. Run locally

```bash
# Python 3.11+ / 3.12+ recommended, from this project directory
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate
pip install -r requirements.txt

# Optional genuine AI recommendation narrative, instead of labeled rules-only mode:
# Linux/macOS: export OPENAI_API_KEY="your_api_key"
# Windows PowerShell: $env:OPENAI_API_KEY="your_api_key"

# Required only when testing the external webhook endpoint:
# Linux/macOS: export CARRIER_WEBHOOK_TOKEN="a-long-random-secret"
# Windows PowerShell: $env:CARRIER_WEBHOOK_TOKEN="a-long-random-secret"

reflex run
```

Open **http://localhost:3000**. The Reflex Python backend normally runs at **http://localhost:8000**. UI styles are in `assets/styles.css`; no npm project or custom JavaScript is required. `reflex run` may require Node.js to be installed or may provision its dependencies during setup; follow its terminal instructions. The SQLite file `disruption_iq.sqlite3` is created when the app starts, and survives restarts.

If using `python scripts/init_data.py`, run it from the project root (the same directory as `rxconfig.py`). To reset the demo, stop the app and delete `disruption_iq.sqlite3` plus any `-wal`/`-shm` sidecar files, then relaunch. **Never reset a real database this way.**

## 2. Demo login accounts (synthetic identities)

| Username | Password | Role | Intended actions |
|---|---|---|---|
| `analyst` | `Analyst#2026` | Operations Analyst | Trigger scenarios, inspect cascade, import, propose and resubmit recovery |
| `manager` | `Manager#2026` | Supply Chain Manager | Approve/reject/request changes for reallocation, expedite, split; confirm dispatch |
| `warehouse` | `Warehouse#2026` | Warehouse Operator | Warehouse fulfillment tasks, stock shortage reports |
| `procurement` | `Procure#2026` | Procurement Approver | Approve/reject/request changes for alternative-supplier POs; confirm procurement dispatch |
| `admin` | `Admin#2026` | Administrator | View, import, simulate, administer data; **no automatic approval bypass** |

Accounts use a salted PBKDF2-SHA256 password hash. Logged-in identity is held in backend-only Reflex State; the backend reads role from the user table on each mutation. Accounts/passwords are intentionally PUBLIC DEMO credentials and **must be replaced before any production use**. Changing the username displayed in the UI does not change backend access rights.

## 3. Requirements coverage

| Problem requirement | Implemented in |
|---|---|
| CSV / JSON import, schema validation and atomic rollback | `engine.import_data`, `validate_import_record`, UI *Data ingestion* |
| Simulated carrier webhook, plus actual HTTP endpoint | `scenario_carrier`, `webhook.carrier_api`, `scripts/send_webhook.py` |
| Linked suppliers, shipments, warehouses, inventory, POs, customer orders | SQLite schema + indexed FK joins in `engine.py` |
| Carrier, supplier, stock shortage alerts and downstream impact | `ingest_carrier`, `simulate_supplier_delay`, `simulate_stock_shortage`, `recompute_impacts`, `trace` |
| Explainable risk rank (0–100) | `projection` + `recompute_impacts`; explanatory 4-factor breakdown |
| Recovery alternatives | `recovery_options` — REALLOCATE, EXPEDITE, REORDER, SPLIT |
| AI summaries and recommendations | `ai.summarize` using stdlib HTTPS request to OpenAI if configured; no-API-key fallback labeled non-AI |
| Separate propose, approve/reject/modify, confirm/execute | `propose`, `approve_or_reject`, `resubmit`, `execute_plan` |
| Role-based access and prohibition on self-approval | `actor` authoritative DB lookup; compare `uid != proposed_by`, deny and audit |
| Notifications and audit | `notifications` table and append-only `audit` table, UI *Audit ledger* |
| Dashboard, outstanding approvals, progress | *Command center*, *Approvals*, *Network topology* |
| Duplicate, stale, conflict and invalid data controls | uniqueness `(source,event_id)`, SHA-256 payload digest, monotonic carrier revision, timestamps, atomic transactions, FK/CHECK constraints |
| At least two scenarios | Ocean carrier + supplier production delay, plus stock shortage |

## 4. Webhook contract

This app adds an ASGI route **without a separate application framework dependency** by using Reflex's `api_transformer`. The endpoint requires the carrier secret in `CARRIER_WEBHOOK_TOKEN` and matching HTTP `x-carrier-token` header; it fails closed if the environment variable is absent.

```bash
export CARRIER_WEBHOOK_TOKEN='your-long-random-secret'
python scripts/send_webhook.py 1
# Repeat command -> DUPLICATE (200; no mutation)
# New higher revision -> accepted. A stale / same revision with new event ID -> ignored.
```

Sample JSON body (timestamps must be valid ISO-8601 with timezone; `occurred_at` must be within 90 days):

```json
{
  "event_id": "carrier-2026-1001",
  "tracking": "SHP-1001",
  "revision": 1,
  "eta": "2026-11-05T12:00:00+00:00",
  "occurred_at": "2026-10-28T12:00:00+00:00"
}
```

**Idempotency policy:** same event ID + same normalized payload → `DUPLICATE`; same event ID + changed content → HTTP 422; lower or equal revision with another event ID → `STALE_IGNORED` (recorded and audited); unknown shipment or bad time/quantity → HTTP 422 with no business mutation. A newer revision with a genuinely later ETA creates a disruption. If the ETA improves, the shipping record is updated but no new delay incident is invented.

**Security:** use a long, randomly generated token and TLS in production; implement upstream carrier HMAC signature validation and rate limiting before real deployment. The demo uses an opaque shared secret, not a carrier-specific signed protocol.

## 5. Linked data / impact calculation

```text
Incoming webhook (event ID, tracking, revision, new ETA)
            |
            v
Shipments (tracking -> shipment ID -> linked purchase order)
            |
            v
Purchase order (supplier, SKU, quantity, destination warehouse)
            |
            v
Warehouse inventory (on_hand - reserved - safety_stock)
            |
            v
Order queue by customer SLA deadline (cumulative committed demand)
            |
            v
Inbound units due before that order's SLA (+ supplier delay)
            |
            v
Short units / delivery urgency / contract value / SLA priority
            |
            v
Risk score + affected customer order + traceable explanation
```

**Risk score** = `shortage_factor [0..28] + urgency_factor [6/20/30] + value_factor [3/12/22] + priority_factor [4/12/20]` capped at 100. The `explanation` field stores each contribution. Inventory is never reserved merely by evaluating risk. Actual mutations occur only when an approved action passes the separate execution confirmation and is revalidated inside a SQLite `BEGIN IMMEDIATE` transaction.

**Lead-time check:** every option has `meets_sla` and a deterministic `sla_note`. Options that mitigate a disruption but are still projected after the customer SLA are explicitly flagged for escalation — the LLM cannot change this calculation.

## 6. Dual-control state machine

```text
                PROPOSE (Operations Analyst or other allowed proposer)
                                   |
                                   v
                     PENDING_MANAGER_APPROVAL   <--- RESUBMIT (original proposer)
                        /        |       \                      ^
                       /         |        \                     |
               REJECT         APPROVE     MODIFY (qty + reason) -- CHANGES_REQUESTED
                 |                |
                 v                v
              REJECTED         APPROVED
                                  |
                         CONFIRM EXECUTE (separate UI action)
                                  |
                                  v
                               EXECUTED
                                  |
                            fulfillment tasks (for SPLIT)
                                  |
                                  v
                               FULFILLED
```

**Approval matrix** is not a frontend convention:

- `REALLOCATE`, `EXPEDITE`, and `SPLIT` require a **Supply Chain Manager**.
- `REORDER` requires a **Procurement Approver**.
- `proposed_by == approver.id` is **always blocked**, even if the proposer has a manager role.
- Managers can request a change; the plan enters `CHANGES_REQUESTED`, and only the proposer can resubmit. Approval and execution are separate transitions; neither a button hack nor an API event can skip backend state validation.
- The **Administrator is not granted an implicit approval override**.
- A Warehouse Operator can complete confirmed fulfillment tasks, but cannot approve recovery plans.

Note: this is a scenario-oriented workflow, not a full production warehouse management system. Reallocation transfers stock between modeled hubs; expedite updates a modeled ETA; alternative supplier execution creates a simulated PO and inbound shipment; split fulfillment creates reserved warehouse tasks. No real carrier/supplier is contacted and no real goods are shipped.

## 7. AI boundary / deterministic guardrails

The only AI-produced material is **explanatory prose and selection of a recommended candidate among backend-validated actions**. `ai.py` uses Python `urllib.request` with the OpenAI Chat Completions HTTPS API; it cannot perform business transactions, set scores, choose arbitrary quantities, update inventory, approve plans, or change deadlines. It receives a small selected subset of synthetic operational context. An absent/failed API key causes a **clearly labeled rules-only fallback**, never a false claim of AI reasoning.

To use a different model with the same API, configure `OPENAI_MODEL`. No OpenAI Python SDK is required.

## 9. Tests

```bash
python -m unittest discover -s tests -v
```

The standard-library unit tests cover linked cascade and two independent disruptions; password/RBAC; duplicate, stale, contradictory and malformed webhooks; approval with correct and incorrect roles; manager self-approval denial; modification/resubmission/rejection; execution confirmation and idempotency; stock reconfirmation; role-gated warehouse fulfillment; importer atomic rollback; supplier PO execution; shortage constraints. They do not require an OpenAI API key or Reflex server to run.

## 10. Source tree

```text
DisruptionIQ/
  rxconfig.py                   Reflex config
  requirements.txt              Reflex only
  .env.example                  Environment config example
  assets/styles.css             Bespoke charcoal/acid-lime control-room UI
  disruption_iq/
    __init__.py
    disruption_iq.py            Reflex UI + app registration
    state.py                    Authenticated UI events / workflow orchestration
    engine.py                   SQLite schema, synthetic seed, business logic
    ai.py                       Optional true AI narrative/recommendation
    webhook.py                  Pure-Python ASGI carrier webhook extension
  scripts/
    init_data.py                Seed SQLite without starting UI
    send_webhook.py             Test signed-token external webhook
  sample_imports/
    warehouses.csv
    supplier_skus.json
  tests/test_engine.py
```

## 11. Deployment notes / limitations

This is a **runnable project for local, single-machine demonstration**. To promote it to multi-user production, use a managed relational database (PostgreSQL), a secure identity provider/session manager, protected secrets, queue-based webhook ingestion, rate limiting, real-time push or polling for other clients, improved stock forecasting, carrier-specific signature validation, structured monitoring, migrations, and operational disaster recovery. Demo role accounts are not a substitute for SSO. SQL transactions, role checks and separation of duties are enforced server-side for the implemented operations, but the code is not a formally audited enterprise application.

The provided unit tests validate backend logic. The Reflex UI could not be browser-tested in the artifact-generation environment (the Reflex package could not be downloaded there), so run `reflex run` in a normal Python development environment to validate rendering and integration with your selected Reflex version.

## Windows fix: IndentationError in `state.py` (v1.2)

If a previous local edit produces `IndentationError: unexpected indent` at `@rx.event` in `disruption_iq/state.py`, **replace that file completely** with the `disruption_iq/state.py` supplied here. Do not paste new methods before the class definition or append duplicate setters elsewhere. The 6 setter handlers are indented inside `class State(rx.State):`.

From your DisruptionIQ project directory, check Python syntax before launching the web UI:

```powershell
python -m py_compile .\disruption_iq\state.py
python -m unittest discover -s tests -v
reflex run
```

No output from `py_compile` means the file's syntax and indentation are valid. Note that the unit tests and syntax check do not substitute for compiling with your installed Reflex version.

## v1.4 — Selected-disruption detail runtime type fix

`State.selected_disruption_info` now uses a compact `DisruptionDetailRow` view
model instead of the full `DisruptionRow` dashboard-card model. The handler
projects `engine.trace()['disruption']` through
`schemas.to_disruption_detail()` so a raw SQL record never gets assigned into a
state field requiring derived dashboard properties (`kind_label`, `impacted`,
`max_risk`). This fixes the runtime `Expected field State.selected_disruption_info`
validation error after clicking **TRACE CASCADE**.

A new suite `tests/test_reflex_runtime_shapes.py` validates actual SQLite rows
for the carrier, supplier, stock, recovery-plan and task paths. The local test
suite passes (24/24). Live Reflex compilation/runtime is unverified here.

If updating a v1.3 installation, apply `DisruptionIQ_Reflex_Runtime_Patch_v1.4.zip`
from the project root and **keep** your existing `disruption_iq.sqlite3` file.

---

## v1.7 — Repeated disruption cards / webhook incident consolidation

**Why it happened:** Older versions created a new disruption row each time a
new demo carrier event ID was generated, even if the ETA still showed the same
day. The supplier scenario also created a new row per click.

**New behavior:** The same shipment, supplier, or warehouse/SKU has one active
incident card; subsequent material changes update the same incident. Every
accepted carrier webhook remains in `carrier_events`, including no-change
updates; the audit log records material updates. Replaying a demo stock
shortage no longer deducts stock again. Real new physical stock count
adjustments are still recorded individually in the audit log.

**Clean up your existing duplicates** (do this once, after stopping Reflex):

```powershell
cd "your directory"
python scripts\consolidate_disruptions.py
python scripts\consolidate_disruptions.py --apply
reflex run
```

The first command is a dry run. `--apply` creates a timestamped SQLite backup,
then marks duplicate active incidents as `SUPERSEDED`. No disruption rows,
carrier events, purchase orders, recovery plans, impacts, or audit events are
deleted. An incident with an executed or approved plan is preferentially kept
active. Partial unique SQL indexes guarantee one active incident for each
shipment, supplier, and warehouse/SKU. Approvals already recorded remain
unchanged. The dashboard shows **active incidents**, while historical items
remain available in SQLite and the audit ledger.

To check regression tests:

```powershell
python -m unittest discover -s tests -v
```
