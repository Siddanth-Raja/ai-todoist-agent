# Personal Chief of Staff (PCOS)

## Canonical Engineering and Product Handoff

**Status:** Active development / pre-alpha

**Owner:** Siddanth Raja

**Canonical handoff date:** July 2026

> This document is the canonical engineering and product reference for PCOS. It separates current implementation from active direction and future ideas. Product vision must not be interpreted as a claim that the corresponding architecture or feature is already implemented.

---

# 1. Executive Summary

Personal Chief of Staff (PCOS) is an AI-assisted personal operating system intended to reduce the amount of life and project context its user must manually remember, reconcile, and re-enter across separate tools.

The repository began as an AI planning MVP around Todoist and Google Calendar. The current product direction is substantially broader: PCOS should become the intelligence and coordination layer above the systems that already contain the user's work and life data.

Todoist, Google Calendar, Linear, email, financial accounts, code repositories, and future health or asset sources are not the product by themselves. They are providers and sources of state.

PCOS's job is to understand the combined state, preserve context, identify what matters, explain why it matters, and execute approved changes through the appropriate provider.

The product's core promise is:

> **PCOS remembers and coordinates the operational details so the user can spend more attention living, building, and creating.**

The desired experience is not “chat with my task list.” It is closer to having a personal Chief of Staff with a continuously improving model of the user's projects, commitments, people, preferences, and important life systems.

PCOS should eventually be able to answer questions such as:

- What deserves my attention right now?
- What is blocking Nebulo?
- What changed across my coding projects?
- What do I need to prepare for before my next commitment?
- Which important email needs action?
- What is the most important executable task in each active project?
- What am I forgetting?
- How is an important area of my life doing?

The answer should be grounded in connected state rather than improvised from a language model's assumptions.

---

# 2. Product Vision

## 2.1 Personal Chief of Staff

A real Chief of Staff does more than answer questions.

They maintain context, understand priorities, notice conflicts, surface risks, track follow-through, and coordinate systems that would otherwise require repeated manual attention.

PCOS should behave similarly.

It should understand that a meeting with Ashwin and Charlie is related to XO when the system has evidence for that relationship.

It should understand that a high-priority executable child task may matter more than its parent roadmap container.

It should notice when a calendar commitment is approaching instead of recommending a large free-time task as though the rest of the day were empty.

The system should increasingly move from passive retrieval toward grounded coordination:

1. Observe connected state.
2. Resolve entities and project context.
3. Compute a trustworthy current model.
4. Identify attention, blockers, and next moves.
5. Explain recommendations.
6. Execute approved actions through provider-specific tools.
7. Record meaningful activity so later reasoning has continuity.

The goal is not maximum autonomy.

The goal is useful, trustworthy delegation.

## 2.2 Personal Operating System

PCOS is becoming a Personal Operating System rather than a conventional productivity application.

This does **not** mean rebuilding every external product inside PCOS.

Google Calendar should remain a calendar provider.

Todoist can remain a lightweight execution and reminder surface.

Linear is the planned deeper project-management system.

Email remains email.

Future finance providers remain the source of financial records.

PCOS sits above those systems and connects them.

Conceptually:

```text
External providers and personal state
    Todoist
    Google Calendar
    Linear [planned]
    Email [planned]
    Code repositories / Codex catch-ups [planned]
    Finance and investing sources [future]
    Health sources [future]
    Asset and vehicle state [future]
                │
                ▼
        PCOS intelligence layer
    memory + entity resolution + project context
    ranking + calendar intelligence + activity
    recommendations + action execution
                │
                ▼
             Surfaces
    Today / Projects / Chat / Calendar
    future native apps / widgets / Live Activities
    Vision Pro and ambient surfaces
```

The long-term value is the connected model.

A task, calendar event, email, code change, and project blocker should not remain five unrelated records if they all describe the same project.

## 2.3 Project Brain

The latest architectural and product direction is that Project Brain should become the canonical intelligence model for project state.

A project brain should be able to represent, at minimum:

- Identity and classification.
- Status and health.
- Executable tasks and task hierarchy.
- Next move.
- Blockers.
- Upcoming calendar commitments.
- People.
- Memories and durable context.
- Recent activity.
- Recommendations and the evidence behind them.

The intended downstream model is:

```text
Connected providers
        ↓
Project Brain
        ↓
Today
Projects
Chat
Recommendations
Notifications
Future native surfaces
```

Important current-state distinction: this is the target architecture and a major product decision, but the repository does not yet implement it completely.

Project Brain V1 exists, while Today and some recommendation behavior still compute state through separate paths.

Consolidating those paths is active roadmap work and must not be documented as already complete.

The purpose of this direction is to eliminate multiple conflicting “opinions” about the same project.

Today, Projects, Chat, and recommendation surfaces should not independently decide that four different tasks are the next move for Freelance.

They should consume the same computed project state and render it for different contexts.

## 2.4 The Product Is Not Chat

Chat is an interface to PCOS, not the product itself.

The early project naturally centered on `/chat` because natural language was the easiest way to prove Todoist and Google Calendar actions.

That direction has been superseded by a broader application model.

The product now needs durable visual surfaces for state and direct manipulation:

- Today for immediate attention.
- Projects for project state and drill-down.
- Calendar for time and commitments.
- Tasks for execution and recommendation inspection.
- Memory for durable context.
- Settings for provider health and operational trust.
- Future native surfaces for proactive and glanceable interactions.

Chat remains valuable for ambiguous commands, cross-system questions, and natural-language actions.

It should not become the only way to use the system.

## 2.5 The Product Is Not a Todoist Wrapper

The repository and some internal names still reflect the project’s origin as ai-todoist-agent.

That name describes history, not the current product boundary.

Todoist is currently an implemented task provider.

The latest product-management decision is:

- Linear should hold deeper project planning, detailed issues, blockers, and roadmap state for PCOS, XO, Nebulo, and Freelance.
- Todoist should remain lighter-weight: quick-glance execution, reminders, and personal tasks where appropriate.
- PCOS should understand both and coordinate across them rather than forcing all project detail into Todoist subtasks.

The earlier direction of expanding Todoist into the detailed project-management backbone has therefore been superseded.

---

# 3. Product Principles

## 3.1 Trust Beats Cleverness

Accuracy is a product feature.

PCOS previously produced experiences where stale or incorrectly computed calendar state made a polished Today page actively misleading.

Past free blocks appeared current.

An event was described as hours away when it was approaching.

Incorrect event times undermined otherwise reasonable recommendations.

That failure established a hard product rule:

A beautiful wrong answer is worse than a plain correct answer.

When PCOS lacks sufficient evidence, it should expose uncertainty, request classification, or avoid the action.

It should not confidently guess a project, person relationship, time, or system state merely to keep the interaction flowing.

## 3.2 Recommendations Must Be Explainable

A recommendation is incomplete without a reason.

The user should be able to understand why PCOS selected one task over another.

Relevant evidence may include:

- Priority.
- Urgency.
- Task age.
- Project momentum.
- Unblocking value.
- Foundation or setup value.
- An approaching event.
- Other explicit ranking signals.

The product should prefer:

> Build the web scraping tool — higher priority and unlocks future client outreach.

Instead of:

> Contact more clients.

Explainability is required both for trust and for debugging the recommendation system itself.

## 3.3 The Assistant Should Change the System, Not Narrate the System

When the user approves a concrete action, the UI should execute the action and transform into the resulting state.

A confirmation button should not send a synthetic yes message through chat and ask the model to reinterpret the conversation.

It should call the confirmation or action path directly.

Prefer:

> ✓ Calendar event updated

Over:

```text
User: yes
Assistant: I updated your calendar event.
```

The same principle applies to project recognition.

Internal resolution may determine that Ashwin and Charlie map to XO, but repetitive prose such as “I recognized this as XO” is unnecessary when a project badge, action card, or correctly routed result can communicate the same fact.

## 3.4 Integrations Are Providers, Not the Product

Provider-specific behavior should not define the core product model.

Todoist supplies tasks.

Google Calendar supplies calendar state.

Linear will supply deeper project-management state.

Email will supply communication and action candidates.

PCOS should normalize and reason over those sources while preserving the external system’s role as source of truth where appropriate.

The internal database should store state that only PCOS owns, such as durable memory, activity, intelligence metadata, and future computed or reviewed state.

It should not blindly clone every external provider.

## 3.5 Memory Exists to Reduce Cognitive Load

Memory is not a novelty feature and should not become an uncurated transcript archive.

Its purpose is to preserve durable context that improves future decisions and removes repeated explanation.

Useful memory includes:

- Project relationships.
- People and groups.
- Stable preferences.
- Rules.
- Patterns.
- Context that materially changes how PCOS interprets a request.

The standard is simple:

PCOS should remember the boring operational context so the user does not have to keep carrying it.

## 3.6 One Intelligence Model, Multiple Surfaces

Today, Projects, Chat, recommendations, future notifications, and native app surfaces should not independently invent state.

The target is one computed intelligence model rendered differently according to the interaction.

A project may appear as:

- A compact live dashboard on Today.
- A detailed workspace on Projects.
- An answer to “what’s blocking Nebulo?” in Chat.
- A proactive notification when a blocker changes.
- A widget or Live Activity on iPhone.

Those surfaces should share the same underlying truth.

## 3.7 Tasks Are Execution; Projects Are Context

A task answers:

What can be done?

A project answers:

What is happening, why does it matter, what is blocked, who is involved, and what should happen next?

Parent tasks that merely contain a roadmap should not outrank executable child tasks.

Detailed project planning should increasingly live in Linear and Project Brain rather than being flattened into a large Todoist hierarchy.

## 3.8 Proactive Does Not Mean Noisy

The long-term product should monitor important systems, but it should surface attention selectively.

Email Intelligence, calendar intelligence, project monitoring, finance, vehicle maintenance, and future health integrations are valuable because the user does not want to manually remember or check everything.

The system should detect meaningful changes and action candidates without turning every signal into an alert.

The goal is confidence that PCOS is watching the operational details, not a larger notification burden.

## 3.9 The UI Should Feel Calm, Premium, and Alive

The current visual direction is a premium dark application with spacious hierarchy and low clutter.

The user explicitly prefers the quality and polish of products such as Origin and paid Notion-style dashboards.

Future Apple-platform experiences should lean into native glass and system capabilities where appropriate.

The UI should communicate:

Everything important is under control.

Visual polish matters, but it never outranks trustworthy state.

## 3.10 Build for the User’s Real Workflow

PCOS is being built because the user currently falls back to Todoist and Google Calendar when PCOS creates more friction than using the source apps directly.

That is the practical product test.

A PCOS workflow is successful when it is faster, clearer, or more intelligent than manually opening the underlying provider.

Features that require restarting local servers, repairing OAuth from a terminal, correcting guessed project categories, or re-explaining known context create operational friction and weaken adoption.

The product should progressively remove those reasons to leave PCOS.

---

# 4. Latest Product Direction

The latest direction can be summarized as follows:

1. Stabilize trust and reliability before adding broad autonomy. Calendar correctness, provider health, classification, and action execution are foundational.
2. Consolidate intelligence around Project Brain. Today and other surfaces should become projections of shared backend-computed state rather than maintaining separate recommendation logic.
3. Move deep project management toward Linear. Todoist remains useful, but it should not carry the full detailed roadmap for software and creative projects.
4. Expand PCOS through connected life systems. Email Intelligence and code/repository catch-ups are nearer-term examples. Finance, investing, assets, vehicle maintenance, health, and ambient/native surfaces are later modules.
5. Turn PCOS into an actual application. The current local web app proves the systems and interaction model. The long-term experience should exist across Mac, iPhone, iPad, and potentially Vision Pro, with native capabilities such as widgets and Live Activities where they provide real value.
6. Preserve one brain across every surface. A future iPhone app, Dynamic Island or Live Activity, smart mirror, or Vision Pro panel should not become a separate product with separate logic. Each should consume the same PCOS intelligence layer.

The long-term ambition is broad, but roadmap sequencing must remain practical:

Make the current system trustworthy.

Centralize project intelligence.

Integrate the systems the user already relies on.

Then widen the operating-system surface area.

---

# 5. Scope and Status Language

This handoff uses the following status language consistently:

- Implemented: present in the audited repository.
- Partially implemented: meaningful code exists, but the intended behavior is incomplete or split across competing paths.
- Active direction: an accepted product or architecture decision that current work should move toward.
- Planned: discussed and accepted for the roadmap, but not implemented in the audited repository.
- Future: a real product idea discussed for PCOS, but intentionally not near-term work.
- Superseded: an earlier direction replaced by a later decision.

Future sections must preserve the distinction between what the repository does today and what PCOS is intended to become.

# 6. Current Repository Architecture

This section describes the implementation present in the audited `ai-todoist-agent` repository uploaded in July 2026.

Unlike the earlier product-vision sections, this section is intended to describe current code rather than target architecture.

The audited repository contains one FastAPI backend, one Next.js frontend, local SQLite state, provider integration modules, backend tests, OAuth utilities, and root scripts for starting and stopping the local development stack.

The repository name still reflects the project's original Todoist-agent scope:

`ai-todoist-agent`

The product itself is now referred to as Personal Chief of Staff, or PCOS.

---

## 6.1 Repository Layout

The relevant top-level structure is:

```text
ai-todoist-agent/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── agent.py
│   │   ├── calendar_intelligence.py
│   │   ├── calendar_tools.py
│   │   ├── config.py
│   │   ├── main.py
│   │   ├── planner.py
│   │   ├── project_brain.py
│   │   ├── project_registry.py
│   │   ├── recommendation_service.py
│   │   ├── storage.py
│   │   ├── todoist_work_adapter.py
│   │   ├── todoist_tools.py
│   │   └── work_domain.py
│   ├── scripts/
│   │   ├── debug_google_auth.py
│   │   └── google_oauth_setup.py
│   ├── tests/
│   │   ├── test_agent_examples.py
│   │   ├── test_app_surfaces.py
│   │   ├── test_calendar_intelligence.py
│   │   ├── test_project_brain_service.py
│   │   ├── test_project_registry.py
│   │   ├── test_recommendation_service.py
│   │   └── test_work_domain.py
│   ├── README.md
│   ├── requirements.txt
│   └── personal_chief_of_staff.sqlite3
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── calendar/
│   │   │   ├── chat/
│   │   │   ├── habits/
│   │   │   ├── memory/
│   │   │   ├── projects/
│   │   │   ├── settings/
│   │   │   ├── tasks/
│   │   │   ├── today/
│   │   │   ├── globals.css
│   │   │   ├── layout.tsx
│   │   │   └── page.tsx
│   │   ├── components/
│   │   │   ├── app-shell.tsx
│   │   │   ├── chat-panel.tsx
│   │   │   ├── placeholder-page.tsx
│   │   │   └── settings-panel.tsx
│   │   └── lib/
│   │       ├── api.ts
│   │       └── settings.ts
│   ├── package.json
│   ├── package-lock.json
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   └── tsconfig.json
├── docs/
│   ├── product-spec.md
│   ├── product-spec-v2.md
│   └── PCOS-handoff.md
├── shortcuts/
│   └── README.md
├── README.md
├── start.sh
└── stop.sh
```

The uploaded ZIP also contained generated and local-development artifacts including `.git`, `.next`, `node_modules`, `.run`, Python bytecode, the backend `.env`, and a local macOS virtual environment.

Those generated or secret-bearing files are not architectural components and should not be used as documentation sources for secrets.

No API keys, provider tokens, refresh tokens, or other credentials belong in this handoff.

---

# 7. Tech Stack

## 7.1 Backend

The backend uses:

- Python
- FastAPI
- Pydantic
- Uvicorn
- `python-dotenv`
- `requests`
- Google API Python Client
- Google Auth libraries
- SQLite from the Python standard library

The backend dependencies currently declared in `backend/requirements.txt` are:

```text
fastapi
uvicorn[standard]
python-dotenv
requests
google-api-python-client
google-auth
google-auth-httplib2
google-auth-oauthlib
```

There is currently no ORM.

SQLite access is implemented directly through `sqlite3`.

There is currently no separate job worker, message queue, Redis layer, or scheduled background execution service in the audited repository.

## 7.2 Frontend

The frontend uses:

- Next.js App Router
- React 19
- TypeScript
- Tailwind CSS 3
- Lucide React icons
- PostCSS
- Autoprefixer

The audited `frontend/package.json` identifies the application as:

`personal-chief-of-staff-frontend`

The frontend dev script runs Next.js on port `3010`:

`next dev -H localhost -p 3010`

The frontend is currently a web application.

There is no Tauri, SwiftUI, React Native, Electron, iOS, iPadOS, watchOS, or visionOS application in the audited repository.

Native Apple applications remain planned future work.

## 7.3 Database

The current internal database is SQLite.

The default database path is `backend/personal_chief_of_staff.sqlite3`. It can be overridden through `APP_DB_PATH` or `APP_DATABASE_PATH`.

The internal database currently stores five classes of PCOS-owned state:

1. memory entries;
2. habit definitions;
3. habit check-ins;
4. activity logs.
5. canonical project metadata, aliases, classification hints, and provider mappings.

It does not currently mirror the complete Todoist or Google Calendar datasets.

That behavior is consistent with the product direction that external providers remain sources of truth while SQLite stores PCOS-specific state.

---

# 8. Backend Architecture

The backend still concentrates substantial orchestration in `backend/app/main.py` and `backend/app/agent.py`, although Project Brain now has a dedicated service boundary.

This architecture works for the current prototype but has accumulated large modules.

At audit time:

```text
backend/app/agent.py       ~3,500 lines
backend/app/main.py        ~2,000 lines
backend/app/storage.py       600+ lines
backend/app/planner.py       500+ lines
backend/app/calendar_tools.py 500+ lines
backend/app/todoist_tools.py  500+ lines
```

The current codebase therefore has meaningful modularization by provider and subsystem. Project Brain has been extracted, while the primary agent and remaining API orchestration are still large.

Further splitting orchestration, action execution, schemas, and conversation state into dedicated modules remains technical-debt work rather than part of this completed Project Brain extraction.

---

## 8.1 `backend/app/config.py`

`config.py` owns environment-backed application settings.

The `Settings` dataclass currently contains:

- Todoist API token.
- Google OAuth client ID.
- Google OAuth client secret.
- Google refresh token.
- Google Calendar ID.
- User timezone.
- OpenAI API key.
- OpenAI model.
- PCOS agent API key.

The backend loads `backend/.env` first and then calls the default `load_dotenv()` behavior as a fallback.

The default timezone is `America/Chicago`. It can be overridden through `USER_TIMEZONE` or the older `TIMEZONE`.

The default OpenAI model in the audited code is `gpt-4o-mini` unless `OPENAI_MODEL` is explicitly configured.

The Google Calendar ID defaults to `primary`.

Configuration is cached through `functools.lru_cache`.

---

## 8.2 `backend/app/main.py`

`main.py` currently performs several responsibilities:

- FastAPI application construction.
- CORS configuration.
- API request and response schemas.
- API authentication helpers.
- Provider health diagnostics.
- Memory routes.
- Habit routes.
- Task API routes.
- Today aggregation.
- Calendar API route.
- Activity routes.

`main.py` delegates `GET /projects` and `GET /projects/{project_key}` to `backend/app/project_brain.py`. Project Brain reads canonical project definitions and aliases from the SQLite-backed registry in `backend/app/project_registry.py`, then owns provider aggregation, project classification, Todoist hierarchy and container handling, blockers, status, diagnostics, and next-recommendation behavior. The HTTP module retains the Project Brain response schemas and route adapters.

The FastAPI application metadata currently describes PCOS as `Personal Chief of Staff` with application version `0.2.0`.

The current FastAPI description still refers to the application as a planning MVP for Todoist, Google Calendar, Memory, Habits, and local activity.

That description is historically accurate but narrower than the current product vision.

### Current CORS behavior

The backend allows development origins matching:

```text
localhost on any port
127.0.0.1 on any port
*.ngrok-free.app
```

This is intended for local frontend development and temporary ngrok testing.

The allowed method list is currently limited to `GET`, `POST`, and `OPTIONS`. The application also exposes authenticated `PATCH` and `DELETE` routes for Memory and Habits, so those mutations can fail browser preflight when the frontend and backend are on different origins. This is a current implementation defect, not intended policy.

---

## 8.3 `backend/app/agent.py`

`agent.py` is the central natural-language orchestration module.

It currently owns or participates in:

- chat handling;
- session conversation state;
- follow-up resolution;
- deterministic capture detection;
- Todoist task creation decisions;
- calendar action decisions;
- OpenAI structured-output requests;
- memory context construction;
- memory-based entity resolution;
- project resolution;
- confirmation handling;
- pending-action validation;
- bulk roadmap parsing;
- bulk subtask parsing;
- task-content cleanup;
- due-date extraction;
- Todoist section resolution;
- calendar lookup behavior;
- calendar update parsing;
- calendar-intelligence confirmation flow;
- dual-write calendar/Todoist decisions;
- action execution;
- response formatting.

The file is the most complex module in the current repository.

This is both a strength and a technical-debt signal.

The project has accumulated real behavioral coverage in one place, but future Linear, Email Intelligence, additional provider actions, and richer Project Brain reasoning should not continue expanding a single 3,500-line agent module indefinitely.

### Deterministic logic versus model reasoning

The current agent intentionally combines deterministic logic and OpenAI reasoning.

Deterministic logic is used for cases where known rules should be more trustworthy than free-form model behavior.

Examples include:

- clear task-capture requests;
- section aliases;
- due-date extraction;
- parent/subtask parsing;
- some calendar updates;
- affirmative or negative confirmation handling;
- known memory/entity relationships;
- action validation.

OpenAI structured output is used where broader natural-language interpretation is useful.

This hybrid approach is an important current architecture decision.

PCOS should not delegate behavior to the LLM when deterministic application logic can produce a more trustworthy result.

---

## 8.4 `backend/app/planner.py`

`planner.py` contains the backend task enrichment and ranking logic used by planning surfaces.

The module currently models:

- estimated task duration;
- low-energy and high-energy user language;
- low-energy and high-energy task keywords;
- quick-task language;
- long-task language;
- shopping and personal-task keywords;
- project/category inference;
- free-block reasoning;
- task enrichment;
- task ranking.

`main.py` imports `enrich_task` and `rank_tasks` from this module.

The current planner is primarily task-oriented.

It does not yet constitute the unified multi-provider recommendation engine described in the long-term product vision.

The richer Tasks page also contains frontend-side recommendation ranking behavior, creating two recommendation paths that must eventually be consolidated.

---

## 8.5 `backend/app/todoist_tools.py`

`todoist_tools.py` is the current Todoist provider module.

It currently targets the Todoist API v1 base URL and handles v1 paginated result envelopes.

It contains:

- Todoist API interaction.
- Life-area to section mapping.
- Section aliases and normalization.
- Active-task listing.
- Section lookup.
- Parent task lookup.
- Single-task creation.
- Subtask creation.
- Bulk task creation.
- Bulk subtask creation.
- Duplicate child-title handling.
- Parent ID normalization.
- Life-area resolution from Todoist section names.

The currently documented life-area model is:

```text
A&M
XO
Freelance
Nebulo
Personal
Misc
```

The actual Todoist section names may differ from the normalized PCOS life-area names.

The mapping layer exists so PCOS can reason in normalized life-area terms while using actual Todoist sections for writes.

The current architecture still embeds significant Todoist assumptions into agent behavior.

The accepted future direction is to introduce a provider abstraction before Linear becomes a core project-management source.

---

## 8.6 `backend/app/calendar_tools.py`

`calendar_tools.py` owns direct Google Calendar provider behavior and calendar normalization.

Its responsibilities include:

- Google OAuth credential construction.
- Google Calendar API service construction.
- authentication diagnostics;
- event listing;
- upcoming-event listing;
- remaining-today event listing;
- event creation;
- event updates;
- calendar-event normalization;
- event-category logic;
- blocking/busy interpretation;
- category conflict behavior.

Google Calendar currently serves as the source of truth for scheduled commitments.

Calendar state feeds:

- chat;
- Today;
- Project Brain;
- free-block logic;
- calendar intelligence;
- the Calendar page.

---

## 8.7 `backend/app/calendar_intelligence.py`

Calendar Intelligence is already implemented in the audited repository.

This corrects an earlier handoff assumption that treated Calendar Intelligence as entirely future work.

The module defines structured calendar analysis and logic for evaluating a proposed calendar change against existing events.

It supports issue concepts including:

- true event overlap;
- tight buffers;
- travel buffers;
- informational overlap.

It also models severity and suggested fixes.

The implemented calendar-intelligence direction includes rules for event categories such as:

- hard;
- flexible;
- informational;
- social.

Its intended behavior includes reasoning such as:

- informational or all-day events should not create normal blocking conflicts;
- a new hard commitment overlapping a flexible event may justify moving the flexible event;
- a flexible event immediately after an interview may have an insufficient buffer;
- travel or preparation indicators can require extra time.

Calendar Intelligence is integrated into agent calendar-action handling.

However, the existence of the module does not mean every calendar conversation is fully reliable.

Multi-turn conversation state, exact event lookup, travel-time data, and more general calendar reasoning still have known gaps documented later in this handoff.

---

## 8.8 `backend/app/storage.py`

`storage.py` is the SQLite persistence layer.

It directly manages database initialization and CRUD operations.

### Current tables

The audited code creates:

```text
memory_entries
habit_definitions
habit_checkins
activity_logs
canonical_projects
canonical_project_aliases
canonical_project_classification_hints
canonical_project_provider_mappings
```

### `memory_entries`

Stored fields:

```text
id
type
title
content
confidence
enabled
created_at
updated_at
```

### `habit_definitions`

Stored fields:

```text
id
name
description
enabled
created_at
updated_at
```

### `habit_checkins`

Stored fields:

```text
id
habit_id
habit
status
note
timestamp
created_at
```

Allowed statuses are:

```text
yes
no
partial
```

### `activity_logs`

Stored fields include:

```text
id
action_type
title
detail
payload
source
created_at
```

Activity payloads are serialized into the database.

### Canonical project registry

`canonical_projects` stores durable internal project IDs, stable route keys, display names, descriptions, enabled state, and ordering.

The related alias and classification-hint tables preserve current route resolution and keyword, person, and life-area classification behavior without keeping user-project definitions in Project Brain code.

`canonical_project_provider_mappings` associates a canonical project ID with a provider, provider resource type, and provider reference. It can represent Todoist sections now and future Linear project or repository mappings without implementing those providers.

Needs Classification is intentionally absent from these tables. `project_registry.py` synthesizes it as a non-editable system/unresolved state.

### Startup seeding

Database initialization seeds default habits, default memories, and the six current canonical projects.

Default habits are currently:

```text
Gym
Running
Work
```

The current Habits product direction has superseded this simple tracker model, but these definitions remain implemented in the audited repository.

Default memories currently include project, person, group, classification-rule, and preference context.

Examples include:

```text
A&M
XO
Nebulo
Freelance
Personal
Brandon
Ashwin
Charlie
Nikhil
Andy
Kamden
Sam
Jai
Krrish
A&M roommates
Carrollton house / UTD group
```

Classification memories also encode known routing rules for:

- shopping, gym, health, car, and life administration;
- college/TAMU/Blinn;
- XO and Ashwin/Charlie;
- Nebulo and Brandon;
- freelance client/work language;
- DDN ambiguity;
- Misc as fallback.

The seed path is idempotent by memory type and title.

Seeding has no tombstone model. Default habits are recreated by their fixed IDs, and default memories are recreated by type and title during a later database initialization if the user deleted them. The delete routes work immediately, but deletion of seeded records is not durable across backend restart.

Canonical project seeding uses stable IDs and insert-only initialization. It is idempotent and does not overwrite later display, description, ordering, or enabled-state edits.

---

# 9. Current API Surface

The audited FastAPI application exposes the following application routes.

Except for `/health`, protected application routes use the PCOS agent API-key authentication mechanism.

## 9.1 Public health route

`GET /health`

Purpose:

- basic backend reachability;
- lightweight health response.

The health route remains public.

---

## 9.2 Provider health diagnostics

`GET /settings/health`

Purpose:

Report operational health for:

- Todoist;
- Google Calendar;
- OpenAI.

This endpoint backs the provider portion of the Settings health-check UI. The frontend checks backend reachability separately through public `GET /health`.

It is particularly important because provider availability has repeatedly affected trust and day-to-day usability.

---

## 9.3 Chat

`POST /chat`

Request fields include:

```text
message
session_id
current_time
```

The response model includes:

```text
answer
intent
actions_taken
needs_confirmation
confirmation_prompt
pending_action
free_block
recommended_tasks
calendar_events
conversation_state
mode
errors
```

Chat is currently the most feature-rich action interface.

---

## 9.4 Confirmation execution

`POST /confirm`

The confirmation request contains:

```text
session_id
pending_action
current_time
```

The route executes supported pending actions directly.

This route implements the product decision that confirmation cards should execute application actions instead of sending synthetic affirmative chat messages.

That preferred path is implemented, but confirmation is not fully modernized. The legacy affirmative-message path through `POST /chat` can still execute a process-global pending action, and the `pending_action` accepted by `POST /confirm` is only strictly validated for selected action types. Durable, session-scoped typed actions remain planned.

---

## 9.5 Confirmation cancellation

`POST /confirm-cancel`

Purpose:

Record cancellation of a pending action in activity state.

The current route logs the cancellation but does not clear the legacy process-global pending action or conversation state. Cancellation therefore has an unresolved state-management gap.

---

## 9.6 Memory

```text
GET /memory
POST /memory
PATCH /memory/{memory_id}
DELETE /memory/{memory_id}
```

Supported behavior includes:

- listing memories;
- creating memory;
- editing memory fields;
- enabling or disabling memory;
- deleting memory.

Memory entries contain `type`, `title`, `content`, `confidence`, and `enabled`, plus IDs and timestamps.

The storage API supports these mutations, but the current CORS method restriction can block cross-origin browser `PATCH` and `DELETE` requests. Same-origin or direct API behavior should not be confused with a fully working browser mutation path.

A second caveat applies to seeded defaults: deleting a seeded memory works immediately but startup initialization recreates it by type and title because deletion tombstones are not stored.

---

## 9.7 Habits

```text
GET /habits
POST /habits
PATCH /habits/{habit_id}
DELETE /habits/{habit_id}
```

These routes manage habit definitions.

Deleting a seeded default habit works immediately but startup initialization recreates it by fixed ID because deletion tombstones are not stored.

The current frontend still exposes a Habits page.

The accepted product direction is to redesign this system around Health and Daily Review rather than preserve the current Yes/Partial/No tracker as the final experience.

---

## 9.8 Habit check-ins

```text
GET /habit-checkins
POST /habit-checkins
```

Check-ins use `yes`, `no`, and `partial` status values.

This is implemented infrastructure, but the current interaction model is not considered the final product design.

---

## 9.9 Tasks

`GET /tasks`

The Tasks endpoint reads active Todoist tasks and returns normalized task state for the frontend.

The Todoist provider normalizes `created_at`, and the API schema includes it, but the current `main.py` response mapper omits the value. Pydantic therefore returns `created_at: null` from `GET /tasks`, which disables the Tasks page's intended task-age ranking signal.

Todoist remains the currently implemented task provider.

The endpoint supports the existing Tasks command-center surface.

Linear is not implemented in the audited repository.

---

## 9.10 Today

`GET /today`

The Today endpoint currently computes its own live view using Todoist and Google Calendar state.

It returns backend-computed information including:

```text
now
next_event
minutes_until_next_event
current_free_block
today_remaining_events
recommendation
```

It also returns life-area state used by the Today frontend.

### Important architectural limitation

Today does **not** currently consume Project Brain as its sole source of project intelligence.

This is a key gap between implementation and accepted architecture direction.

Today and Project Brain currently have overlapping aggregation and recommendation responsibilities.

Today ranks the enriched task set independently and does not apply Project Brain's parent-container/leaf-task filtering, so a roadmap container can still become Today's recommendation.

Unifying these paths is active roadmap work.

---

## 9.11 Projects

```text
GET /projects
GET /projects/{project_key}
```

These endpoints expose Project Brain V1.

The currently defined project keys are:

```text
pcos-ai-todoist-agent
nebulo
xo
freelance
am
personal
needs-classification
```

The `needs-classification` project is a safety bucket for work that cannot be confidently assigned to a real project.

Project responses include fields such as:

```text
key
name
description
status
task_count
next_recommendation
blockers
tasks
task_groups
classification_diagnostics
upcoming_events
people
memories
recent_activity
```

Project Brain currently aggregates data from:

- Todoist;
- Google Calendar;
- Memory;
- Activity.

Todoist tasks enter Project Brain through `TodoistWorkAdapter` as typed `NormalizedWorkItem` records. Project Brain uses typed provider identity, project reference, status, priority, hierarchy, container, executable, blocked, dependency, timestamp, and provider-metadata fields internally.

The existing planner inputs and Project Brain API response objects are produced through narrow compatibility projections. No normalized-work fields are added to the public `/projects` contract.

Task aggregation preserves Todoist parent-child relationships.

Parent tasks with active children can be treated as containers so executable leaf tasks are eligible for next-move ranking.

Project Brain is computed live per request by the dedicated backend service rather than read from a persisted project model. The current response is also bounded to 12 tasks, 12 task groups, eight blockers, eight upcoming events, eight memories, and eight recent activity records per project response; the overall `task_count` still reflects all matched active tasks.

---

## 9.12 Calendar

`GET /calendar`

Purpose:

Return normalized calendar state for the frontend Calendar surface.

The current Calendar page supports visual calendar views documented in the frontend section.

Calendar writes are primarily performed through agent actions rather than a large direct calendar CRUD API exposed to the frontend.

---

## 9.13 Activity

```text
GET /activity
POST /activity
```

The activity API exposes the current internal activity timeline.

Some actions are automatically recorded through backend application logic.

Current automatic coverage includes single task creation, calendar creation and update, confirmed bulk-subtask execution, confirmation requested/completed/cancelled events, Memory mutations, and habit check-ins. Bulk top-level task creation, single-subtask creation, habit-definition CRUD, ordinary chat, reads, and health checks are not automatically logged.

The POST route also allows explicit activity creation.

Activity remains an early foundation for:

- project history;
- universal timeline;
- planned daily review;
- planned weekly review;
- future “what changed?” reasoning.

---

# 10. API Authentication and Frontend Connection Model

The backend supports an application-level API key through:

`AGENT_API_KEY`

Protected frontend requests send:

`Authorization: Bearer <AGENT_API_KEY>`

The frontend stores connection and client-only presentation state in browser `localStorage`, including:

```text
pcos.backendUrl
pcos.apiKey
pcos.chatHistory
pcos.taskRecommendations.v1
```

The default backend URL is:

`http://127.0.0.1:8000`

The frontend API wrapper lives in:

`frontend/src/lib/api.ts`

The settings persistence helper lives in:

`frontend/src/lib/settings.ts`

The API wrapper refuses protected requests when no API key has been saved in frontend Settings.

This is currently a local-development authentication model.

It is not a production multi-user authentication system.

There is currently no user-account model, session login, OAuth login to PCOS itself, organization model, or hosted production authorization layer in the audited repository.

Those concerns must be addressed before PCOS becomes a public multi-user product.

---

# 11. Frontend Architecture

The frontend uses the Next.js App Router.

The root layout is `frontend/src/app/layout.tsx`. It imports `frontend/src/app/globals.css` and wraps every route in `AppShell` from `frontend/src/components/app-shell.tsx`.

The HTML root is forced into dark mode through:

`className="dark"`

The metadata title is:

`Personal Chief of Staff`

The current metadata description still refers to a mobile-first command center for planning, chat, tasks, and memory.

Like the backend application description, that text is narrower than the latest product direction.

---

## 11.1 App Shell

`frontend/src/components/app-shell.tsx` implements the shared application navigation and viewport layout.

The current navigation order is:

```text
Today
Projects
Chat
Calendar
Tasks
Habits
Memory
Settings
```

The desktop layout uses a left sidebar on extra-large screens.

Smaller layouts use a fixed bottom navigation bar.

The shell uses:

- full-screen height;
- hidden outer overflow;
- an internal scroll area for normal pages;
- a special non-page-scrolling layout for Chat.

Chat is intentionally treated differently:

```text
/chat -> main content overflow hidden
other routes -> internal vertical scrolling
```

This implements the earlier UX decision that the chat conversation itself should scroll rather than forcing the entire application page and navigation chrome to move.

---

## 11.2 Current Routes

The audited frontend contains:

```text
/
/today
/projects
/projects/[projectKey]
/chat
/calendar
/tasks
/habits
/memory
/settings
```

The root route redirects to `/today`.

The major product surfaces are described below.

---

## 11.3 Today

File:

`frontend/src/app/today/page.tsx`

Today currently renders backend-provided day state.

The page is no longer based on the original static design placeholders.

It renders information such as:

- greeting and current context;
- current free block;
- next event;
- time until commitment;
- recommendation;
- remaining calendar state;
- life areas.

The life-area cards are clickable. Resolved A&M, XO, Nebulo, Freelance, and Personal areas link to their Project Workspaces, while Misc links to the Projects index.

### Current limitation

The Today page is visually connected to Projects but is not yet architecturally driven by Project Brain as the only project-state source.

This difference matters.

A clickable Project card does not mean Today and Projects share identical ranking and aggregation logic.

The current accepted direction is to make Today a projection of Project Brain.

The page fetches `GET /today` and `GET /activity?limit=5` once when it mounts. Only the local clock updates every 30 seconds; provider-derived free blocks, events, recommendations, life areas, and Activity do not auto-refresh or poll.

---

## 11.4 Projects

Files:

```text
frontend/src/app/projects/page.tsx
frontend/src/app/projects/[projectKey]/page.tsx
```

The Projects index displays Project Brain summaries.

Project cards expose project-level state including:

- project identity;
- status;
- description;
- next move;
- task count;
- event count;
- blocker count.

Project detail pages render more complete Project Brain information.

Current project detail surfaces include:

- project hero and status;
- summary metrics;
- next move;
- blockers;
- upcoming events;
- tasks;
- expandable task groups;
- people;
- memories;
- recent activity where data exists.

The detail view also exposes classification diagnostics. The backend returns the full diagnostic list, while the frontend renders only the first 40 records.

Parent tasks with active children can be displayed as expandable task groups.

This functionality was added specifically because Todoist roadmap parent tasks previously caused Project Brain to hide the actual executable work.

The current Projects feature is the first implemented Project Brain surface.

It is not yet the complete “brain for my projects” product vision.

GitHub state, Linear issues, files, project milestones, explicit dependency graphs, email state, and Codex repo catch-ups are not yet integrated.

---

## 11.5 Chat

Files:

```text
frontend/src/app/chat/page.tsx
frontend/src/components/chat-panel.tsx
```

The route itself is thin.

Most chat rendering and action-card behavior lives in:

`chat-panel.tsx`

The current chat panel supports:

- user and assistant messages;
- API-backed `/chat` calls;
- confirmation cards;
- direct `/confirm` execution;
- cancellation;
- action cards;
- calendar creation results;
- calendar update results;
- Todoist task results;
- bulk subtask previews and results;
- development/debug error details.

Chat history persists the most recent 80 messages in `pcos.chatHistory`. The client generates a session ID when the component mounts, so conversation identity is not durable across every remount or device.

The file is approximately 900 lines and now contains significant action-specific UI logic.

As the provider surface grows, action-card rendering may need to be separated into dedicated components.

### Current product decision

Action cards are the preferred visual representation of executed system changes.

If PCOS moves a gym event, the product should show a structured green `Calendar event updated` result card.

The assistant should not merely claim in prose that it changed the system.

---

## 11.6 Calendar

File:

`frontend/src/app/calendar/page.tsx`

Calendar V1 is implemented.

The page consumes normalized backend calendar data and provides visual calendar modes.

The implemented frontend was built around the discussed Agenda, Day, and Week direction.

It renders real Google Calendar data rather than static example events.

The page offers Agenda, Day, and Week views and refreshes on initial load or manual request; it does not poll continuously. It also infers display-only project labels from event title and location text in the frontend, another current client-side classification path that should not become canonical intelligence.

Calendar correctness remains more important than feature depth.

Drag-and-drop scheduling and a full native calendar editing experience are not implemented in the audited repository.

---

## 11.7 Tasks

File:

`frontend/src/app/tasks/page.tsx`

The Tasks page is a Todoist-backed command center.

It contains significantly more logic than a simple provider list.

The page includes views and filters around:

- Today;
- Upcoming;
- By Life Area;
- all tasks;
- due-today tasks;
- overdue tasks;
- high-priority tasks.

The current frontend also implements explainable per-life-area recommendation ranking.

Ranking signals in the Tasks page include concepts such as:

- Todoist priority;
- task age;
- due urgency;
- unblocking or foundation language;
- project momentum.

The page flattens and ranks the returned tasks without Project Brain's parent-container filtering. In addition, `GET /tasks` currently returns `created_at: null`, so the age branch exists in frontend code but does not receive the source value it needs.

The page persists recommendation timing/state in `localStorage` and can show recommendation changes.

It includes expand/collapse behavior for life areas.

### Architectural limitation

This frontend-side ranking is not the same implementation as the backend planner ranking.

PCOS currently therefore has multiple recommendation paths.

This is a concrete example of the architecture problem described earlier:

```text
Tasks frontend recommendation logic
        ≠
backend planner ranking
        ≠
Project Brain aggregation
        ≠
Today recommendation path
```

The exact behaviors overlap but are not yet one shared intelligence model.

Consolidating this is a high-value architectural issue.

---

## 11.8 Habits

File:

`frontend/src/app/habits/page.tsx`

The current Habits page implements the existing habit-definition and habit-check-in infrastructure.

The current interaction uses `Yes`, `Partial`, and `No` for habits such as `Gym`, `Running`, and `Work`.

The page also displays recent logs and allows habit definitions to be added, edited, enabled, or deleted.

Deleting one of the three seeded default habits is not durable: database initialization recreates it by fixed ID after backend restart because there is no tombstone for an intentionally removed default.

### Superseded product direction

The current Habits experience is implemented but is not considered the final product direction.

The user explicitly does not use the current tracker and considers it too manual and passive.

The accepted redesign direction is Health + Daily Review, with planned concepts including:

- daily review;
- planned versus actual;
- context for why a habit or commitment was missed;
- automatic detection where provider data supports it;
- later Apple Health and Apple Watch integration;
- behavioral insights rather than a raw checkbox log.

The current habit database and APIs may remain useful infrastructure, but the user experience requires redesign.

---

## 11.9 Memory

File:

`frontend/src/app/memory/page.tsx`

The Memory Center manages durable PCOS context.

The current page supports memory creation and editing around types such as:

- project;
- person;
- group;
- classification rule;
- preference;
- pattern;
- sensitive habit.

The current form values are `project`, `person`, `group`, `classification_rule`, `preference`, `pattern`, and `sensitive_habit`. Agent context normalizes `classification_rule` to `rule`; display grouping also recognizes `routine` and `goal` entries if they exist.

The backend accepts arbitrary non-empty memory type strings rather than enforcing one strict database enum.

The memory UI should therefore be understood as the current product taxonomy rather than a hard storage-level enum.

Memory supports:

- creation;
- editing;
- confidence;
- enable/disable state;
- deletion.

These operations exist end to end at the storage and route layers. Cross-origin browser edit and delete requests can nevertheless fail because backend CORS currently omits `PATCH` and `DELETE` from the allowed methods.

Deleting a seeded default memory succeeds for the current process, but startup initialization recreates it by type and title because the schema has no deletion tombstone.

Enabled memory entries are used by the agent before OpenAI requests and in deterministic resolution logic.

The planned Memory Inbox for AI-suggested memories is not implemented in the audited repository.

---

## 11.10 Settings

Files:

```text
frontend/src/app/settings/page.tsx
frontend/src/components/settings-panel.tsx
```

Settings stores:

- backend URL;
- PCOS agent API key.

It also exposes provider health checks for:

- backend;
- Todoist;
- Google Calendar;
- OpenAI.

Backend reachability is checked independently from the provider payload. Health checks are manual/button-driven rather than continuously polled.

The Google Calendar failure state currently presents reconnect instructions.

This diagnostics surface was added after repeated provider failures made it difficult to distinguish an intelligence bug from a disconnected integration.

The current Google reconnect experience is still developer-oriented and requires a local OAuth script.

A true in-product reconnect flow is not implemented.

---

# 12. Current Data Flow

The current application does not yet have one universal Project Brain pipeline.

Instead, data flows through several overlapping paths.

A simplified current-state model is:

```text
Todoist
   ├── /tasks ────────────────> Tasks page
   ├── planner.py ────────────> Chat / Today ranking
   └── Project aggregation ───> Project Brain

Google Calendar
   ├── /calendar ─────────────> Calendar page
   ├── Today aggregation ─────> Today
   ├── agent.py ──────────────> Chat and actions
   ├── Calendar Intelligence ─> conflict/buffer analysis
   └── Project aggregation ───> Project Brain

SQLite Memory
   ├── Memory Center
   ├── agent context
   ├── entity/project resolution
   └── Project Brain

SQLite Activity
   ├── Activity API
   └── Project Brain recent activity

Frontend Tasks ranking
   └── Tasks recommendation UI
```

This is the most important current architecture fact for future development:

> **PCOS has the ingredients of a shared intelligence layer, but several surfaces still compute overlapping state independently.**

The next architecture phase should not create another parallel recommendation engine.

It should consolidate existing logic.

The intended direction is:

```text
Providers
    ↓
normalized source state
    ↓
shared project/intelligence aggregation
    ↓
Project Brain and cross-project intelligence
    ↓
Today / Projects / Chat / Tasks / notifications / native clients
```

---

# 13. Current Source-of-Truth Boundaries

The current source-of-truth model is:

## 13.1 Todoist

Source of truth for currently integrated task records.

PCOS reads and writes Todoist tasks.

Todoist is not intended to remain the exclusive deep-project planning provider.

## 13.2 Google Calendar

Source of truth for currently integrated calendar events.

PCOS reads, creates, and updates Google Calendar events.

## 13.3 SQLite

Source of truth for PCOS-owned:

- memories;
- habit definitions;
- habit check-ins;
- activity logs.

## 13.4 Frontend `localStorage`

Currently stores local client connection configuration and some frontend recommendation state.

This is not an appropriate long-term source of cross-device product state.

Any intelligence needed consistently across Mac, iPhone, iPad, or future surfaces should eventually move behind the backend.

## 13.5 Project Brain

Project Brain remains a computed backend aggregation, while canonical project identity and matching metadata are now durable SQLite state.

The backend loads an enabled registry snapshot, appends Needs Classification as a system state, and derives Project Brain responses from provider and internal state.

The registry now persists provider links and canonical project identities. Richer future project intelligence may still require persisted metadata for:

- provider links;
- canonical project identities;
- milestones;
- explicit dependencies;
- manual project state;
- intelligence snapshots;
- reviewed blockers;
- project-specific settings.

Those broader project-intelligence records have not yet been implemented.

---

# 14. Important Current Architectural Gaps

The following are architecture gaps visible directly in the audited repository.

They are documented here without yet converting them into roadmap issues; the Linear roadmap appears later in this handoff.

## 14.1 Project Brain is not yet the universal intelligence source

Today, Tasks, backend planning, and Project Brain still contain overlapping logic.

This can produce inconsistent recommendations.

## 14.2 The agent module is too large

`agent.py` has accumulated parsing, conversation state, structured model calls, routing, memory resolution, calendar behavior, Todoist behavior, action execution, and response formatting.

Future providers will worsen this without decomposition.

## 14.3 Project Brain service extraction is complete, but schemas remain in `main.py`

Project definitions and aliases now come from the durable registry. Task aggregation, project classification, hierarchy, blockers, diagnostics, and next-move computation remain in `backend/app/project_brain.py`.

`main.py` still owns the HTTP response schemas and route adapters, while Today remains a separate aggregation path. Moving schemas is optional cleanup; consolidating Today is separate roadmap work and was intentionally not combined with the service extraction.

## 14.4 Provider abstraction is incomplete

Todoist behavior remains deeply represented in the agent and task models.

Linear migration should be preceded or accompanied by a normalized task/work provider boundary.

## 14.5 Frontend business logic exists in Tasks

The Tasks page implements meaningful recommendation scoring in the frontend.

This conflicts with the accepted principle that multiple clients should consume shared backend intelligence.

## 14.6 Authentication is local-development only

`AGENT_API_KEY` is sufficient for the current personal local app.

It is not sufficient for a public product or multi-device hosted system.

## 14.7 Google OAuth reconnect is operationally fragile

The current reconnect flow uses local scripts and refresh-token configuration.

Repeated `RefreshError: invalid_grant` failures have already affected use.

Provider health diagnostics exist, but reconnect is not yet a polished application flow.

## 14.8 Background monitoring does not exist

PCOS currently responds to requests and page loads.

It does not yet have a background scheduler or worker continuously monitoring:

- email;
- repositories;
- project changes;
- calendar conditions;
- finance;
- vehicle state.

Proactive monitoring features require a new execution model rather than another frontend page.

## 14.9 Native clients do not exist

The current application is web-only.

Mac, iPhone, iPad, Apple Watch, Dynamic Island or Live Activity, and Vision Pro concepts are future work.

All native clients should consume shared backend intelligence rather than reimplement PCOS logic locally.

## 14.10 Browser mutation CORS is incomplete

The backend exposes Memory and Habits `PATCH` and `DELETE` routes but currently permits only `GET`, `POST`, and `OPTIONS` through CORS. Cross-origin browser edits and deletes can therefore fail even when the API implementation itself is valid.

## 14.11 Task ranking inputs and priority semantics are inconsistent

The Todoist provider normalizes creation time, but `GET /tasks` currently drops it, disabling the Tasks page's age signal. Priority is also interpreted through several incompatible scales across Todoist normalization, planner logic, Today, Project Brain, and deterministic capture. A normalized work model must define one explicit priority contract rather than preserve these accidental translations.

## 14.12 Pending actions are process-local and only partly typed

Direct `POST /confirm` execution is implemented, but a legacy process-global pending action remains reachable through affirmative chat messages. Cancellation logs activity without clearing that legacy state, and only selected pending-action variants receive strict field validation. This is acceptable prototype plumbing, not a durable multi-session action model.

---

# 15. Architecture Direction From This Point

Near-term architecture work should preserve the current working product while moving toward:

```text
Provider adapters
    Todoist
    Linear
    Google Calendar
    Email
    GitHub / repo intelligence
        ↓
Normalized domain models
    Task / Issue
    Project
    Event
    Person
    Memory
    Activity
    Action candidate
        ↓
Intelligence services
    Project Brain
    Recommendation Engine
    Calendar Intelligence
    Entity Resolution
    Memory
    Future attention / monitoring engine
        ↓
Action execution layer
    create
    update
    move
    cancel
    confirm
        ↓
API
        ↓
Web and future native surfaces
```

This is an active direction, not a claim that these layers already exist as separate modules.

The next engineering work should use this model to avoid adding new cross-provider behavior directly into `agent.py` or frontend page components without a shared backend abstraction.

# 16. Current Integration Status

This section records the integration state present in the audited repository.

The distinction between an implemented provider and a discussed future provider is important. PCOS has a broad product vision, but only Todoist, Google Calendar, OpenAI, local Memory, local Activity, and the current habit infrastructure are implemented as operational data sources or subsystems.

---

## 16.1 Todoist

**Status:** Implemented

Todoist is the current task provider.

PCOS can currently:

- authenticate to Todoist using the configured provider token;
- read active tasks;
- read provider task metadata including priority and creation time;
- resolve Todoist sections;
- normalize sections into PCOS life areas;
- create tasks;
- create subtasks;
- create multiple tasks in one action;
- create multiple subtasks under an existing parent;
- locate parent tasks;
- normalize parent IDs;
- skip duplicate child titles during bulk creation;
- use Todoist task state in Today;
- use Todoist task state in Tasks;
- use Todoist task state in Project Brain;
- rank tasks using backend planning logic;
- execute supported Todoist pending actions in the backend agent;
- directly confirm single-task and bulk-subtask actions through current Chat cards;
- render single-task and bulk-subtask action results in the frontend;
- record some task actions in Activity.

The backend executable set also includes single-subtask and bulk top-level task actions. The current `chat-panel.tsx` confirmation whitelist omits those two variants, so the normal UI presents them as non-executable; they require a direct API call or the legacy affirmative Chat path. Backend capability should not be mistaken for complete action-card coverage.

### Bulk roadmap creation

The agent supports deterministic parsing of roadmap-style input.

This capability was built after the user wanted to paste a complete PCOS roadmap into Chat and turn it into many Todoist subtasks under:

`Personal -> ai todoist agent -> subtasks`

The implementation supports:

- parsing multiple roadmap items from one message;
- finding the requested parent task;
- previewing a large bulk action;
- requesting confirmation;
- executing the confirmed action through `POST /confirm`;
- creating child tasks;
- skipping duplicate child titles;
- reporting created and skipped tasks.

Bulk helpers execute sequential provider calls and do not roll back earlier writes if a later item fails. Batches above 20 items receive a warning rather than a hard limit. If the requested parent is missing, the confirmation path can create that parent, but it does not retain and automatically continue the original child list.

This feature proved that PCOS can convert natural-language planning artifacts into provider actions rather than only creating one task per message.

### Current Todoist limitations

Todoist remains heavily represented in agent and task logic.

The provider currently reads sections from the canonical Todoist project named `To-Do`.

The current code does not expose a generalized work-provider abstraction shared by Todoist and Linear.

Todoist hierarchy also created a Project Brain issue: parent roadmap tasks could be ranked as the project’s next move while the actual executable work existed in child tasks.

Project Brain V1 was later updated to preserve task hierarchy and treat parents with active children as containers unless the parent explicitly opts back into executable ranking with a `completeable`, `completable`, or `leaf-task` marker.

### Latest product decision

Todoist is no longer intended to become the detailed project-management backbone for PCOS.

The accepted direction is:

```text
Linear -> detailed project work
Todoist -> lightweight execution and personal reminders
PCOS -> intelligence and coordination across both
```

The previously implemented bulk Todoist roadmap system remains valid completed history and useful task infrastructure, but it should not dictate the future project-management architecture.

---

## 16.2 Google Calendar

**Status:** Implemented, operationally fragile

Google Calendar is the current scheduling and commitment provider.

PCOS can currently:

- authenticate through Google OAuth credentials and a refresh token;
- read calendar events;
- normalize event state;
- read upcoming events;
- read remaining events for the current day;
- create calendar events;
- update calendar events;
- use calendar events in Chat;
- use calendar events in Today;
- use calendar events in Project Brain;
- expose normalized calendar data through `/calendar`;
- display real events in the Calendar frontend;
- calculate free blocks;
- evaluate some proposed changes through Calendar Intelligence;
- render calendar creation and update action cards.

Google Calendar defaults to `primary` unless another calendar ID is configured.

### Calendar action behavior

Natural-language calendar requests are handled through the agent.

The agent contains logic for:

- identifying calendar intent;
- extracting calendar changes;
- finding candidate existing events;
- creating events;
- updating events;
- requesting confirmation;
- evaluating proposed changes with Calendar Intelligence;
- executing approved actions.

The preferred frontend path executes confirmations directly through `POST /confirm`.

This fixes the normal action-card flow that previously sent a synthetic `yes` message and asked the model to interpret the conversation again. The legacy affirmative path still exists inside `POST /chat` and uses process-global pending state, so the migration is not complete.

### Calendar Intelligence

Calendar Intelligence's deterministic analyzer is implemented; end-to-end coordination is partially implemented.

It can reason about structured issue types including:

- true overlap;
- tight buffer;
- travel buffer;
- informational overlap.

The system also models event categories including:

- hard;
- flexible;
- informational;
- social.

The intended implemented rules include distinctions such as:

- informational events should not behave like ordinary blocking commitments;
- all-day informational events should not consume the entire day as busy time;
- flexible events may be candidates for movement around hard commitments;
- insufficient time between commitments can be surfaced as a buffer issue;
- travel or preparation indicators can justify additional buffer time.

Calendar Intelligence is not a general autonomous scheduling engine. It is currently a deterministic analysis layer integrated into selected proposed-event creation flows.

The integration uses fixed assumptions for some travel/preparation cases, does not yet use its `user_context` input, and does not create a separate buffer event. A proposed fix that moves an existing flexible event also does not automatically create the user's originally requested new event. These are coordination limitations around a real analyzer, not evidence that the analyzer is absent.

### Google OAuth failure history

Google Calendar has repeatedly failed because the configured refresh token became invalid or revoked.

A confirmed diagnostic failure was:

```text
RefreshError: invalid_grant
Token has been expired or revoked.
```

The repository includes `backend/scripts/debug_google_auth.py` and `backend/scripts/google_oauth_setup.py`.

The auth diagnostic script checks:

- Calendar ID;
- loaded client ID prefix;
- refresh-token presence;
- configured scopes;
- token refresh success;
- calendar read success;
- the target calendar's reported access role.

The health check does not perform a destructive probe write or prove that the OAuth token grants the `calendar.events` scope. Its `write_permission_status` result is a non-destructive capability inference from successful target-calendar lookup and the calendar's reported access role.

A prior diagnostic confirmed that:

- a refresh token was present;
- token refresh failed;
- calendar read failed;
- the configured token did not provide a usable write path.

A new token had to be generated using the OAuth setup script.

### Provider health

Google Calendar health is now surfaced through `GET /settings/health` and the Settings frontend.

When Calendar fails, Settings provides reconnect guidance using `backend/scripts/google_oauth_setup.py`.

### Current Calendar limitations

The reconnect flow is still developer plumbing.

The user must currently understand local environment configuration and OAuth scripts.

This is unacceptable as a final product experience.

Calendar reasoning also has historical trust failures.

At different points, PCOS:

- showed past free blocks as though they were current;
- described an approaching event as hours away;
- displayed or reasoned from an incorrect event time;
- produced generic advice to “check your schedule” despite having Calendar access.

These failures directly shaped the product principle:

A beautiful wrong answer is worse than a plain correct answer.

Calendar correctness remains foundational work.

---

## 16.3 OpenAI

**Status:** Implemented

OpenAI is the current model provider used by the agent.

The backend configuration supports `OPENAI_API_KEY` and `OPENAI_MODEL`.

The audited code defaults to `gpt-4o-mini` when no model override is configured.

The project initially used an API key associated with a different OpenAI account.

The configured API key was later replaced with a key from the intended paid OpenAI account.

No key value should be recorded in this handoff.

### Current model usage

The agent uses OpenAI where broader natural-language interpretation is useful.

The current architecture intentionally does not make every behavior model-driven.

Deterministic application logic handles cases where known rules can provide more reliable behavior.

The broad model is:

```text
clear known behavior
        ↓
deterministic application logic

ambiguous natural language
        ↓
structured OpenAI interpretation
```

OpenAI is used alongside:

- deterministic capture detection;
- memory context;
- project/entity resolution;
- action schemas;
- action validation;
- provider-specific execution.

### Structured behavior

The agent uses the OpenAI Chat Completions API with a strict JSON-schema response format for model-mediated decisions.

The application validates actions before provider execution.

The model should therefore be understood as part of the reasoning and interpretation layer, not as unrestricted direct access to Todoist or Google Calendar.

### Current OpenAI limitations

The current agent can still lose or mishandle context in some multi-turn interactions.

An example failure pattern discussed during development was:

```text
User: Move gym to 5.
PCOS: [proposes action]
User: I have an interview tomorrow.
PCOS: generic interview advice
```

The response told the user to check the schedule rather than answering from the connected schedule. This was considered a major product failure because PCOS already had access to the user's calendar and should have grounded the answer in actual state.

The problem is not simply model quality.

It reflects orchestration, context, retrieval, and trust architecture.

Future work should not assume that changing to a more capable model alone solves these issues.

## 16.4 Memory

**Status:** Implemented

PCOS has a local durable Memory subsystem backed by SQLite.

Memory is stored in `memory_entries` and exposed through:

```text
GET /memory
POST /memory
PATCH /memory/{memory_id}
DELETE /memory/{memory_id}
```

Memory entries contain:

- type;
- title;
- content;
- confidence;
- enabled state;
- creation timestamp;
- update timestamp.

The current frontend includes a Memory Center.

Users can:

- create memories;
- edit memories;
- adjust confidence;
- enable or disable memories;
- delete memories.

The current seed contains 27 memories: five projects, nine people, two groups, seven classification rules, and four preferences. The database accepts arbitrary non-empty type strings; the current UI taxonomy is a product convention rather than a storage enum.

The routes implement edits and deletes, but browser use across the frontend/backend origin boundary is currently affected by the missing CORS allowances for `PATCH` and `DELETE`.

### Current memory use

Enabled memories participate in agent context and deterministic resolution.

Memory is currently used for concepts including:

- projects;
- people;
- groups;
- classification rules;
- preferences;
- patterns.

Seeded context includes known entities and relationships relevant to the user’s actual workflow.

Examples include:

- A&M;
- XO;
- Nebulo;
- Freelance;
- Personal;
- Brandon;
- Ashwin;
- Charlie;
- Nikhil;
- Andy;
- Kamden;
- Sam;
- Jai;
- Krrish;
- A&M roommates;
- Carrollton house / UTD group.

Classification memories encode known routing behavior.

Examples include:

- college, TAMU, and Blinn language mapping toward A&M;
- Ashwin and Charlie context mapping toward XO where evidence supports it;
- Brandon context mapping toward Nebulo;
- freelance client and work language mapping toward Freelance;
- shopping, gym, health, car, and life-administration language mapping toward Personal;
- DDN remaining ambiguous until explicitly classified;
- Misc serving as a fallback rather than a confident project assignment.

The DDN decision is correct in Project Brain, but it is not enforced consistently across every capture path. A bare deterministic capture such as `DDN follow-up` can currently match the seeded DDN memory's `Freelance` text and be routed to Freelance. That behavior is a bug; absent explicit evidence, DDN must remain unresolved.

### Memory product decision

Memory exists to reduce repeated explanation and cognitive load.

It should not become a raw archive of every conversation.

The accepted direction is to preserve context that materially improves later reasoning.

### Planned Memory Inbox

An AI-suggested Memory Inbox was discussed.

The intended concept is:

1. PCOS detects potentially durable context.
2. PCOS proposes a memory.
3. The user reviews it.
4. Approved memory becomes durable state.

This is not implemented in the audited repository.

---

## 16.5 Activity

**Status:** Implemented foundation

PCOS stores internal activity records in SQLite.

Activity is exposed through `GET /activity` and `POST /activity`.

The current storage model includes:

- action type;
- title;
- detail;
- serialized payload;
- source;
- creation timestamp.

Automatic records currently cover single task creation, calendar creation and update, confirmed bulk-subtask execution, confirmation requested/completed/cancelled events, Memory add/edit/disable/delete actions, and habit check-ins.

Coverage is not universal. Bulk top-level task creation, a single subtask creation, habit-definition CRUD, ordinary chat, reads, and health checks are not automatically logged.

Project Brain can include recent activity associated with a project.

### Current Activity role

Activity is currently an early system-history layer.

It is not yet a complete universal event stream.

The accepted future direction is for Activity to support:

- project history;
- “what changed?” reasoning;
- Daily Review;
- Weekly Review;
- provider change summaries;
- code/repository catch-ups;
- future proactive intelligence.

The current implementation is therefore foundational but incomplete relative to the product vision.

---

## 16.6 Habits

**Status:** Implemented infrastructure, product direction superseded

The current repository contains:

- habit definitions;
- habit check-ins;
- habit CRUD APIs;
- a Habits frontend;
- default habits;
- recent check-in history.

The default habits are `Gym`, `Running`, and `Work`.

Check-ins use `yes`, `no`, and `partial`.

The current Habits page allows manual tracking and management.

### Product status

The user explicitly does not use the current Habits experience and considers the interaction too manual and unhelpful.

The current Habits product direction has therefore been superseded.

The accepted direction is closer to Health + Daily Review.

PCOS should eventually reason about:

- what was planned;
- what actually happened;
- why something was missed;
- patterns across days;
- automatically observed health or activity signals where available.

Apple Health and Apple Watch were discussed as future sources.

The existing habit database and check-in infrastructure may be reused.

The current Yes/Partial/No interface should not be treated as the final product.

## 16.7 Linear

**Status:** Planned, not implemented

Linear is the accepted future provider for deeper project management.

The user is moving project-management detail into Linear for:

- PCOS;
- XO;
- Nebulo;
- Freelance.

The reason for the change is that detailed roadmaps and large subtask trees create too much clutter in Todoist.

The desired division is:

```text
Linear
    detailed issues
    milestones
    blockers
    project status
    deeper implementation planning

Todoist
    personal tasks
    quick-glance execution
    reminders
    lightweight actionable work

PCOS
    understands both
    computes project state
    recommends next moves
    identifies blockers
    coordinates actions
```

PCOS should eventually answer questions such as “What's blocking Nebulo?” using real Linear project state combined with other PCOS context.

Linear is not present as an implemented provider in the audited repository.

No Linear API adapter, normalized Linear issue model, sync path, or Linear action execution exists yet.

## 16.8 Email

**Status:** Planned, not implemented

Email Intelligence is a major planned integration.

The user has explicitly described being bad at keeping up with email and wants PCOS to monitor both:

- personal email;
- A&M email.

The desired behavior is not simply an email inbox embedded in PCOS.

PCOS should detect messages that are even moderately important to the user’s responsibilities and surface action candidates.

Examples include:

- a deadline;
- a form that must be submitted;
- an advisor request;
- an interview or scheduling message;
- a payment or administrative requirement;
- an important project communication;
- something that should become a task;
- something the user should explicitly review.

The intended workflow is conceptually:

```text
Email arrives
      ↓
PCOS evaluates relevance and urgency
      ↓
Important?
   ├── no -> remain quiet
   └── yes
          ↓
   summarize why it matters
          ↓
   propose attention or action
          ↓
   optionally create task / connect project
```

Email Intelligence is not implemented in the audited repository.

There is currently no Gmail, IMAP, Microsoft Graph, or A&M email provider module.

A background monitoring execution model will be required for the proactive experience.

## 16.9 GitHub and Codex Repository Catch-Ups

**Status:** Planned, not implemented

A scheduled Codex or repository catch-up workflow was discussed.

The idea is for PCOS to receive periodic structured updates about coding repositories and incorporate them into Project Brain.

The motivating problem is that the user works across multiple repositories and ChatGPT/Codex sessions.

Project state can change significantly in code without being reflected in Todoist or Memory.

The desired concept is:

```text
Repository changes
        ↓
Codex / repository analysis
        ↓
structured "catch me up"
        ↓
PCOS Activity + Project Brain
        ↓
current status / blockers / next move
```

A catch-up should eventually help PCOS understand:

- recent commits;
- meaningful file changes;
- completed implementation work;
- current work in progress;
- failing tests;
- blockers;
- technical debt;
- likely next engineering step.

The user specifically proposed scheduling Codex to perform a “catch me up” across coding repositories and feed the result into PCOS.

This is not implemented in the audited repository.

There is currently no GitHub provider, Codex ingestion endpoint, scheduled repository worker, or canonical repo-summary schema.

## 16.10 Finance and Investing

**Status:** Future

Finance and investing are accepted long-term PCOS modules but are intentionally not current implementation priorities.

The product direction was influenced by the user’s interest in the visual quality and connected financial experience of Origin.

The desired Finance module may eventually reason about:

- spending;
- budgets;
- cash flow;
- account balances;
- recurring charges;
- financial obligations.

Potential future financial sources discussed include:

- Bank of America;
- Webull;
- Apple Card data where legitimately accessible.

The user is currently an Apple Card participant under a parent’s account arrangement.

The product discussion established that this spending may still be useful personal context even if the underlying money or primary account belongs to the parents.

Any future implementation must preserve actual account ownership and access boundaries rather than pretending the user owns an account they do not control.

### Investing direction

The investing module should not be designed as an AI stock picker.

The accepted philosophy is:

AI that helps the user become a better investor.

Potential future capabilities discussed include:

- portfolio tracking;
- allocation analysis;
- company research;
- watchlists;
- earnings summaries;
- company comparisons;
- valuation models;
- backtesting;
- investment journal;
- AI-generated research reports;
- risk analysis;
- position sizing;
- rebalancing suggestions.

The desired system could eventually answer questions such as:

```text
How's my portfolio?
Research Microsoft.
```

It could also surface concentration and allocation observations based on the user's own goals and holdings.

This is future work.

No banking, brokerage, Apple Card, or market-data integration exists in the audited repository.

---

## 16.11 Vehicle Maintenance and Mileage

**Status:** Future

Vehicle state was discussed as another example of PCOS remembering operational details so the user can focus on enjoying the asset.

The user’s current maintenance model includes:

- oil approximately every 5,000 miles;
- tire rotation approximately every 5,000 miles;
- engine air filter approximately every 20,000–30,000 miles;
- cabin filter yearly;
- transmission drain/fill approximately every 50,000–60,000 miles;
- brake fluid approximately every three years;
- coolant around 100,000 miles;
- spark plugs around 120,000 miles.

The desired PCOS behavior is to remember:

- current mileage;
- service history;
- next maintenance threshold;
- time-based maintenance;
- upcoming maintenance needs.

Automatic mileage ingestion was discussed.

An OBD-II-based hardware or data source was identified as technically plausible.

The product concept is:

```text
Vehicle mileage/state
        ↓
PCOS asset intelligence
        ↓
maintenance schedule
        ↓
upcoming service attention
```

No OBD-II integration, vehicle database, mileage ingestion, or maintenance engine exists in the audited repository.

This remains future work.

---

## 16.12 Smart Mirror and Ambient Surfaces

**Status:** Future

A smart floor-mirror PCOS surface was discussed.

The concept was inspired by ambient dashboards displaying information such as:

- walk time to class;
- drive time to class;
- upcoming events;
- travel time home;
- other immediately relevant daily state.

The mirror should be understood as a future PCOS surface, not a separate intelligence system.

It should consume the same backend state as Today and future native clients.

No smart-mirror software or hardware integration exists in the audited repository.

---

## 16.13 Native Apple Surfaces

**Status:** Future

The desired long-term product should be available across:

- Mac;
- iPhone;
- iPad;
- potentially Apple Watch;
- potentially Vision Pro.

The user specifically wants the future iPhone experience to feel native, premium, and glass-forward.

Potential system surfaces discussed include:

- widgets;
- Live Activities;
- Dynamic Island presentation where appropriate;
- proactive upcoming-event state;
- action cards;
- glanceable project or day intelligence.

A future Dynamic Island or Live Activity experience could expose upcoming relevant state without requiring the user to open PCOS.

The current repository is web-only.

No native Apple client is implemented.

---

# 17. Implemented Feature Inventory

The following features are present in the current PCOS implementation or confirmed completed development history.

This section intentionally records completed work separately from the future roadmap.

---

## 17.1 Initial Planning MVP

The original backend MVP established the core Todoist and Google Calendar planning loop.

Implemented capabilities included:

- reading Todoist tasks;
- reading Google Calendar events;
- finding free blocks;
- enriching tasks;
- ranking tasks;
- low-energy mode;
- structured action handling;
- Todoist task creation;
- Google Calendar event creation.

The early MVP test suite reached:

```text
8 / 8 tests passing
```

This was the initial proof that PCOS could combine task state and calendar state to answer:

What should I work on now?

The product has since expanded substantially beyond this scope.

---

## 17.2 Next.js Frontend Foundation

A Next.js frontend was created under `frontend/`.

The frontend evolved into the current PCOS web application with:

- shared App Shell;
- desktop sidebar;
- mobile bottom navigation;
- dark visual system;
- Today;
- Projects;
- Chat;
- Calendar;
- Tasks;
- Habits;
- Memory;
- Settings.

The current application is no longer a chat-only prototype.

## 17.3 Chat Action Execution

Chat can interpret and execute supported provider actions.

Completed behavior includes:

- natural-language task capture;
- natural-language calendar actions;
- confirmation requests;
- direct confirmation execution;
- cancellation;
- structured action result rendering;
- conversation state;
- error reporting.

The confirmation architecture was improved so frontend confirmation buttons call `POST /confirm` directly.

This avoids routing a synthetic yes message back through the language model.

The older affirmative-message execution path remains in backend Chat handling, so this item records completion of the frontend/direct endpoint path rather than completion of durable action-state architecture.

---

## 17.4 Memory Center

Durable Memory storage, API routes, UI, and reasoning integration are implemented, with the browser-mutation and seeded-deletion limitations documented above.

Completed components include:

- SQLite memory storage;
- seeded memories;
- memory API;
- Memory frontend;
- create;
- edit;
- confidence adjustment;
- enable/disable;
- delete;
- agent memory context;
- deterministic memory/entity resolution.

Memory is already part of PCOS reasoning.

---

## 17.5 Entity and Project Resolution

PCOS contains deterministic context for known project and person relationships.

This was built to reduce repetitive classification narration and improve routing.

The system can use known memory evidence when resolving entities and projects.

DDN is intentionally treated as ambiguous in the accepted product decision and Project Brain classification.

The current deterministic capture path can still misclassify a bare DDN task through seeded-memory keyword matching. That regression is documented in Known Bugs and does not reverse the decision.

A Needs Classification path was introduced for unclear work rather than forcing confident assignment.

Project classification diagnostics can expose:

- task title;
- parent;
- section;
- resolved project;
- priority;
- include or exclude reason.

This diagnostics behavior was added after project tasks failed to appear where the user expected them.

---

## 17.6 Recommendation Engine V1

An explainable per-life-area recommendation system was implemented in the Tasks frontend.

Ranking signals include:

- Todoist priority;
- task age;
- unblocking or foundation language;
- project momentum;
- due urgency.

The system can produce reasons such as:

This unlocks future client outreach.

Closest task to external progress.

One-time setup with long-term benefit.

The Tasks page also supports:

- per-area expand and collapse;
- ranked task inspection;
- recommendation refresh;
- persisted recommendation timestamp;
- Updated X minutes ago;
- previous/current recommendation change callouts;
- change reasons such as Higher-priority task added.

Todoist `created_at` data was added to provider normalization and the API type surface so task age could participate in ranking.

The current `main.py` task mapper now omits that value, causing `GET /tasks` to emit `created_at: null`. The historical age-ranking implementation is complete, but its current data path is regressed and must be repaired during consolidation.

At the completion of this feature, verification included `npm run build` and `backend/.venv/bin/python -m unittest discover backend/tests`, with 56 backend tests passing at that stage of development.

The recommendation architecture is now known to be fragmented across multiple paths and requires consolidation, but Recommendation Engine V1 remains completed history.

---

## 17.7 Calendar Intelligence

Calendar Intelligence is implemented as a dedicated backend module.

Completed behavior includes structured analysis of:

- overlaps;
- buffers;
- travel-related buffer concerns;
- informational overlap.

Calendar category behavior distinguishes:

- hard;
- flexible;
- informational;
- social.

Calendar Intelligence is integrated into calendar action handling.

The dedicated test module is `backend/tests/test_calendar_intelligence.py`.

Calendar Intelligence is implemented but not considered complete autonomous calendar management.

---

## 17.8 Calendar V1

The Calendar frontend is implemented using real Google Calendar data.

The Calendar experience was designed around:

- Agenda;
- Day;
- Week.

The page consumes `GET /calendar` and renders normalized calendar state.

This replaced placeholder-only calendar UI.

---

## 17.9 Tasks V1

The Tasks frontend is implemented as a Todoist-backed command center.

Completed views and behavior include:

- Today;
- Upcoming;
- By Life Area;
- task filters;
- due-today visibility;
- overdue visibility;
- high-priority visibility;
- recommendation inspection;
- per-area ranking.

Tasks V1 is implemented.

Its frontend-side recommendation logic is now an architecture consolidation target.

---

## 17.10 Local Development Pass

The local-development workflow was improved after PCOS repeatedly conflicted with other projects using port 3000.

The frontend dev server was moved to `localhost:3010`.

The root repository gained `start.sh` and `stop.sh`.

Runtime logs and PID state are stored under ignored `.run/`.

The README quickstart was updated around `./start.sh`, followed by opening `http://localhost:3010`.

The local stack was smoke-tested by:

- starting the backend;
- starting the frontend;
- confirming backend health on port 8000;
- confirming the frontend on port 3010;
- stopping both through `./stop.sh`.

This removed the recurring need to manually start backend and frontend processes separately.

---

## 17.11 Provider Health Diagnostics

Provider diagnostics are implemented.

The backend exposes `GET /settings/health`.

The Settings frontend checks:

- backend;
- Todoist;
- Google Calendar;
- OpenAI.

Google Calendar failures surface reconnect guidance.

This feature was built specifically because provider failures were previously difficult to distinguish from PCOS reasoning failures.

---

## 17.12 Multi-Task and Subtask Creation

PCOS supports creating multiple tasks and subtasks from one command.

Completed backend behavior includes:

- parent task lookup;
- single subtask creation;
- bulk task helpers;
- bulk subtask helpers;
- duplicate child-title skipping;
- parent ID normalization.

Completed agent behavior includes:

- bulk action types;
- subtask action types;
- deterministic roadmap parsing;
- executable `/confirm` handling;
- missing-parent confirmation;
- large-batch warnings;
- duplicate reporting;
- success text.

Completed frontend behavior includes:

- bulk subtask confirmation cards;
- bulk subtask success cards;
- direct confirmation execution for single-task and bulk-subtask cards;
- created task counts;
- created and skipped result display.

The backend and agent also support single-subtask and bulk top-level task actions. Those action types are not in the current frontend confirmation whitelist and do not have the same dedicated result cards.

At completion of this work, verification reached:

```text
75 backend tests passing
npm run build passing
```

## 17.13 Project Brain V1

Project Brain V1 is implemented.

The backend exposes `GET /projects` and `GET /projects/{project_key}`.

The frontend contains `/projects` and `/projects/[projectKey]`.

Project Brain V1 aggregates:

- Todoist tasks;
- Google Calendar events;
- Memory entries;
- people;
- Activity;
- blockers;
- project status;
- next recommendation.

The implemented project keys are:

```text
pcos-ai-todoist-agent
nebulo
xo
freelance
am
personal
needs-classification
```

Today life-area cards were made clickable into project pages.

Project detail pages expose project state and drill-down.

At the initial Project Brain V1 completion point, verification reached:

```text
85 backend tests passing
npm run build passing
```

## 17.14 Project Brain Task Hierarchy Fix

Project Brain was later corrected to include active Todoist subtasks and preserve parent-child hierarchy.

Before this fix, detailed roadmap tasks under `ai todoist agent` were not properly represented.

The fix added:

- active subtask inclusion;
- parent-child task groups;
- parent container detection;
- executable leaf-task ranking;
- subtask-inclusive task counts;
- high-priority subtask surfacing;
- standalone task ranking;
- Needs Classification handling;
- classification diagnostics;
- expandable parent task groups in the frontend.

This specifically addressed the case where the user had a higher-priority DDN task and many PCOS roadmap subtasks but Project Brain failed to surface the expected executable work.

Verification after the fix reached:

```text
86 backend tests passing
npm run build passing
git diff --check passing
```

## 17.15 Dedicated Project Brain Service

Project Brain definitions, aliases, classification, aggregation, hierarchy, container handling, blockers, status, diagnostics, and next-recommendation behavior were extracted from `backend/app/main.py` into `backend/app/project_brain.py`.

The `/projects` and `/projects/{project_key}` route contracts remain in `main.py` and delegate to `ProjectBrainService`.

The extraction intentionally preserved the then-current definitions and provider-specific work shape. The canonical registry and normalized work model were completed afterward; the shared recommendation service, Today consolidation, Linear integration, agent decomposition, and Calendar changes remain separate roadmap work.

Focused service-level coverage was added for project keys and aliases, provider aggregation, Needs Classification diagnostics, parent-container hierarchy, executable leaf ranking, blockers, people, memories, Activity, and Calendar commitments.

Verification after the extraction reached:

```text
90 backend tests passing
npm run build passing
git diff --check passing
```

## 17.16 Durable Canonical Project Registry

Canonical project identity is now stored in SQLite rather than in `main.py` or `project_brain.py` dictionaries.

The registry stores stable internal IDs, stable route keys, display metadata, enabled state, aliases, classification hints, and provider mappings. It seeds PCOS, Nebulo, XO, Freelance, A&M, and Personal with the existing behavior-preserving metadata.

Needs Classification remains a synthesized system state with no editable project row or durable ID.

Project Brain consumes a registry snapshot while preserving existing response contracts, stable keys and aliases, classification diagnostics, hierarchy, blockers, and next-move behavior. A future normal project can be created through storage and participate in Project Brain without editing application dictionaries.

The provider-mapping boundary uses `(provider, resource_type, provider_ref)` to resolve a durable `canonical_project_id`. SID-125 can place that nullable ID on normalized work while preserving provider and provider-record identity separately.

Verification after the registry implementation reached:

```text
95 backend tests passing
npm run build passing
git diff --check passing
```

## 17.17 Normalized Work Model and Todoist Adapter

`backend/app/work_domain.py` defines the typed provider-neutral work contract used by Project Brain.

The model represents provider identity, provider record ID, nullable canonical project ID, title, description, normalized and original status, normalized and original priority, due date/time, parent provider record ID, container and executable state, explicit blocked state, dependency references, timestamps, provider URL/reference, and preserved provider metadata.

Normalized priority uses one direction across providers:

```text
0 = none
1 = low
2 = medium
3 = high
4 = urgent
```

Higher always means more important. Todoist's native `1–4` priority maps directly and remains separately available as `original_provider_priority`.

Normalized status is `open`, `completed`, or `canceled`. Completed and canceled work cannot be executable, and container work cannot be executable.

`backend/app/todoist_work_adapter.py` enriches Todoist source records, resolves canonical project IDs from registry provider mappings, preserves source metadata, and finalizes hierarchy across each provider batch. A parent with active children becomes a non-executable container unless it is explicitly marked completable. Completed children do not make an otherwise executable parent a container.

Todoist does not provide explicit dependency or blocked-state semantics, so the adapter emits no dependencies and `is_blocked = false`. Existing Project Brain keyword-based blocker presentation remains outside the normalized model only to preserve current behavior; it must not be mistaken for provider-grounded dependency state.

Normalized work is computed in memory and is not persisted or synchronized. The shared recommendation service now consumes it for Project Brain; Linear adapters and the Today, Tasks, and Chat migrations remain separate work.

The existing `/tasks` created-at omission and legacy API priority fields are intentionally unchanged. Project Brain retains a narrow compatibility projection only at its existing response boundary.

Verification after the normalized work implementation reached:

```text
100 backend tests passing
npm run build passing
git diff --check passing
```

## 17.18 Action Cards

The Chat frontend renders structured action results.

Implemented examples include `Calendar event updated` and dedicated bulk-subtask creation results. Other supported action variants can fall back to a generic completion card.

The visual direction is that system changes should appear as application state transitions rather than verbose assistant narration.

This is an implemented UI pattern and an accepted product principle.

## 17.19 Activity Logging

Activity logging is implemented as local PCOS state.

Some meaningful system actions are recorded.

Bulk subtask creation was explicitly added to Activity.

Project Brain can consume recent activity.

The Activity system is not yet a complete provider-wide timeline, but the storage and API foundation are implemented.

## 17.20 Linear Read Provider and Normalized Adapter

SID-133 adds the initial read-only Linear provider boundary without feeding Linear into Project Brain.

`backend/app/linear_client.py` owns Linear transport. It uses Linear's supported GraphQL endpoint, personal API-key authentication through the raw `Authorization: <API_KEY>` header, a 15-second timeout, Relay cursor pagination for projects and issues, continuation pagination for issue relations, and structured errors. GraphQL error bodies are not returned to callers, and the configured token is never logged or included in health output.

Local configuration is optional:

```text
LINEAR_API_KEY=<personal Linear API key>
```

When the variable is absent, PCOS still starts. Settings health reports Linear as `warning` with provider state `not_configured`. Configured connections distinguish `connected`, `authentication_failure`, and `provider_failure`; authentication and permission failures do not expose the credential.

The read client retrieves Linear project identity, name, state, URL, priority, start and target dates, and timestamps. Issue reads preserve UUID and human identifier, title and description, workflow state name and type, priority, project, parent, direct and inverse relations, project milestone, assignee, team, created/updated/completed/canceled timestamps, due date, and URL. Malformed or incomplete provider envelopes fail closed.

`backend/app/linear_work_adapter.py` converts issues to `NormalizedWorkItem` records in memory. The stable issue UUID is `provider_record_id`; the human identifier remains in provider metadata; the Linear project UUID is `provider_reference` and provider metadata. `canonical_project_id` intentionally remains nullable.

Linear priority is explicitly inverted into the canonical higher-is-more-important scale:

```text
Linear 0 None   -> PCOS NONE
Linear 4 Low    -> PCOS LOW
Linear 3 Medium -> PCOS MEDIUM
Linear 2 High   -> PCOS HIGH
Linear 1 Urgent -> PCOS URGENT
```

Workflow normalization uses Linear's documented workflow-state `type`: `completed` becomes completed, `canceled` becomes canceled, and backlog/unstarted/started states remain open. Completed and canceled records are non-executable. Active parents with active children follow the canonical normalized-work container rule and become non-executable containers.

Only explicit Linear `blocks` relations become normalized `blocks` or `blocked_by` dependencies. Blocked state is true only when an explicit inbound `blocks` relation exists. Titles, descriptions, milestone order, and workflow-state names do not invent dependencies or blocker state. Milestone, assignee, workflow, project, team, and relation data remain available in provider metadata.

SID-133 does not create canonical Linear project mappings, combine Linear and Todoist records, change Project Brain or recommendations, add writes or synchronization, or persist mirrored issues. Linking Linear projects to canonical PCOS projects remains SID-134. Feeding mapped Linear work into Project Brain remains SID-135.

Verification for SID-133 reached 129 backend tests passing, including 16 focused mocked Linear tests. Python compilation, the Next.js 15.5.19 production build, `git diff --check`, and a no-credential runtime health smoke check passed. No local `LINEAR_API_KEY` was available, so live authenticated GraphQL verification remains pending and no credential was manufactured.

## 17.21 Durable Linear Project Mappings

SID-134 links the four initial Linear projects to canonical PCOS project identity through the existing `canonical_project_provider_mappings` table:

```text
pcos       -> linear / project / 8622937e-f05d-48b7-ba54-43604a8aa733
xo         -> linear / project / 6752d640-2f40-423f-b86f-ef11e0c4deda
nebulo     -> linear / project / d9fdfe44-3e66-4dc0-b564-b2bcb646e635
freelance  -> linear / project / 2bde590c-a8ab-4f4e-81eb-f7a8da8c1833
```

The `pcos` reference resolves through the existing alias to the durable canonical key `pcos-ai-todoist-agent` and ID `project-pcos-ai-todoist-agent`. No new project row or mapping store was created.

Initialization uses the registry's existing `INSERT OR IGNORE` seed convention. Mapping IDs are deterministic, so initialization is idempotent and a mapping edited through the durable API is not reset on the next startup. `get_canonical_project_provider_mapping` and `update_canonical_project_provider_mapping` provide data-layer inspection and updates without source edits.

`ProjectRegistrySnapshot` continues to resolve exact `(provider, resource_type, provider_ref)` identity and now exposes diagnostics for:

- `mapped`;
- `unmapped_provider_ref`;
- `canonical_project_unmapped`;
- `unknown_canonical_project`.

Resolution never accepts a provider project name. Renaming a Linear project therefore does not break its UUID mapping, and a duplicate or similar name with an unknown UUID cannot create or resolve another canonical project.

A&M, Personal, and the synthesized Needs Classification state have no Linear mapping. Existing Todoist section mappings remain unchanged.

Live read-only verification used the configured local `LINEAR_API_KEY` without exposing it. Linear returned PCOS, XO VR, Nebulo, and Freelance with the exact UUIDs above; all four resolved to their durable canonical IDs. A deliberately unknown UUID returned `unmapped_provider_ref` with no canonical ID. The local registry contained exactly four Linear project mappings.

SID-134 does not call Linear from Project Brain, combine Linear and Todoist work, or change recommendations or frontend behavior. Feeding mapped normalized Linear work into Project Brain remains exclusively SID-135.

Verification for SID-134 reached 134 backend tests passing. Focused registry tests, Python compilation, the Next.js 15.5.19 production build, `git diff --check`, ignored-secret checks, and the live mapping smoke check passed.

## 17.22 Mapped Linear Project Brain Ingestion and Project Work Packages

SID-135 makes Linear the second work provider consumed by Project Brain while preserving the existing Todoist, Calendar, Memory, Activity, task, hierarchy, blocker-wording, and route contracts.

Project Brain resolves the requested canonical project through `ProjectRegistrySnapshot`, retrieves only its exact `(linear, project, provider_ref)` mapping, and asks `LinearClient` for issues through an exact Linear project UUID filter. Linear project names never participate in ingestion identity. Returned records are checked again at the service boundary; an issue whose `project.id` differs from the mapped UUID causes that Linear read to fail closed instead of crossing project boundaries.

Normalized Linear records receive the mapped `canonical_project_id` in memory and retain their provider identity, stable issue UUID, human identifier, provider project UUID, original and normalized workflow state and priority, milestone, hierarchy, explicit dependency relations, timestamps, and URL. Project-level recommendation candidates then combine exact mapped Linear work with relevant Todoist work and use the existing shared recommendation service and weights. Same-title records remain distinct through `(provider, provider_record_id)` identity.

`backend/app/project_work_packages.py` is the dedicated typed read-model boundary for Project Work Packages. Initial package semantics are deliberately narrow:

- a Linear project milestone is the package backbone;
- only open mapped issues explicitly assigned to that milestone are included;
- each open unmilestoned issue becomes a single-item fallback package;
- completed and canceled issues do not contribute current work;
- parent containers and explicitly blocked issues cannot become next actions;
- membership and blocker state are never inferred from titles, descriptions, status names, or milestone order;
- the existing recommendation service selects and explains each package's executable next action;
- deterministic ordering favors packages with executable actions and returns at most three options.

The additive Project Brain contract exposes `work_packages` plus a `linear_diagnostic`. A diagnostic distinguishes `connected`, `not_mapped`, `not_configured`, `authentication_failure`, `provider_failure`, and `malformed_response`. Linear failure never masquerades as a successful empty roadmap and does not remove Todoist, Calendar, Memory, or Activity results.

Mapped project pages add a focused `Work on [Project] now?` section. It shows at most three package choices with milestone or fallback title, context, open and explicitly blocked action counts, selected next action and explanation, availability state, and a Linear link. Unmapped A&M, Personal, and Needs Classification pages do not invent or display Linear packages. There is no package selection persistence or Linear write path.

Live read-only verification used the ignored local `LINEAR_API_KEY` and produced the following exact-project results without cross-project records:

| Canonical project | Linear project UUID | Issues read | Example grounded package | Selected next action |
| --- | --- | ---: | --- | --- |
| PCOS | `8622937e-f05d-48b7-ba54-43604a8aa733` | 56 | Milestone 2 — Calendar Trust and Provider Reliability | SID-131, Build In-App Google Calendar Reconnect |
| XO | `6752d640-2f40-423f-b86f-ef11e0c4deda` | 30 | Deployment & VR Testing | SID-91, Fix Quest VR Rig and Locomotion |
| Nebulo | `d9fdfe44-3e66-4dc0-b564-b2bcb646e635` | 9 | Demo 1 | SID-103, Verify and recover the provider-extraction source of truth |
| Freelance | `2bde590c-a8ab-4f4e-81eb-f7a8da8c1833` | 34 | Milestone 2 — Produce One Sendable Real Audit | No next action because its only open action was explicitly blocked |

Linear health reported `connected`. The live GraphQL project filter, issue pagination, relation reads, milestone parsing, normalization, package construction, and Project Brain boundary were compatible with the current Linear schema. No Linear writes were performed.

Verification for SID-135 reached 149 backend tests passing, including 38 focused Linear, package, and Project Brain tests, plus 3 focused frontend presentation tests. Python compilation, the Next.js 15.5.19 production build, `git diff --check`, ignored-secret checks, and live read-only package verification passed.

SID-136 remains the boundary for grounded project-level blocker interpretation and presentation. SID-135 preserves explicit dependencies and prevents blocked work from becoming a next action, but it does not add milestone-order inference, keyword reinterpretation of Linear work, or a new blocker scoring path.

## 17.23 Trustworthy Linear Dependency Evaluation

SID-136 replaces raw relation-presence blocking with a shared typed dependency evaluator. The evaluator runs once after mapped Linear normalization and before Project Brain recommendations, Project Work Packages, project status, and project next-action selection. Every consumer therefore sees the same executable state.

For each explicit Linear `blocked_by` relation, the evaluator preserves the raw provider relation and produces structured evidence containing the relation identity, blocked and blocking work UUIDs and human identifiers, titles, workflow statuses, URLs, canonical project associations, evaluation state, and a human-readable explanation. Evaluation is intentionally conservative:

```text
blocking issue open                  -> active; downstream is non-executable
blocking issue completed             -> resolved; downstream may execute
blocking issue canceled              -> needs_review; downstream is non-executable
blocking issue missing or malformed  -> needs_review; downstream is non-executable
```

Resolved relationships remain available in the additive API evidence for traceability but are omitted from the current blocker UI. Titles, descriptions, milestone sequence, milestone names, and status wording never create dependency evidence. Cross-project relationships retain both canonical project associations; they do not move either work item into another project.

Project status now follows explicit state. A project is `Blocked` only when it has no executable work and at least one active explicit dependency. It is `Needs attention` when an explicit relationship needs review, or when active dependencies coexist with executable work elsewhere. Existing Todoist and Calendar overdue, stale, keyword, follow-up, and scheduling observations are exposed separately as additive `attention_signals`; they are not provider-backed blockers and cannot override an executable Linear recommendation.

Project Work Packages expose active and needs-review counts separately. Available executable work remains preferred, active dependencies produce `explicitly_blocked`, and conservative dependency uncertainty produces `needs_review`. The Project Workspace renders only current active or needs-review dependency evidence, distinguishes the two states, and links to underlying Linear records where URLs are available.

Live read-only verification exercised the exact UUID-mapped projects with the ignored local credential and current Linear GraphQL schema:

| Canonical project | Linear project UUID | Issues read | Dependency evaluation | Grounded result |
| --- | --- | ---: | --- | --- |
| PCOS | `8622937e-f05d-48b7-ba54-43604a8aa733` | 56 | 54 active, 35 resolved, 0 needs review | Calendar Trust, Canonical Project Intelligence, and Linear PM Integration remained grounded current packages |
| XO | `6752d640-2f40-423f-b86f-ef11e0c4deda` | 30 | 8 active, 0 resolved, 0 needs review | SID-91 remained executable while Product Direction retained explicit blocking evidence |
| Nebulo | `d9fdfe44-3e66-4dc0-b564-b2bcb646e635` | 9 | 8 active, 0 resolved, 0 needs review | Demo 1 selected SID-103 and kept its seven downstream actions blocked |
| Freelance | `2bde590c-a8ab-4f4e-81eb-f7a8da8c1833` | 34 | 23 active, 4 resolved, 1 needs review | SID-173 resolved SID-174; SID-174 became executable while SID-175 through SID-178 remained blocked |

All four reads remained exact-project scoped with zero cross-project issue leakage. Linear health reported `connected`; relation URLs, workflow states, priorities, milestones, parents, and timestamps remained schema-compatible. The verification performed no Linear writes and exposed no credential.

SID-136 does not add Linear writes, synchronization, SQLite mirroring, Chat changes, milestone-order dependencies, or new recommendation weights. Controlled Linear actions remain a later boundary.

Verification for SID-136 reached 163 backend tests passing, including focused dependency, Linear provider, package, Project Brain, and API tests, plus 5 frontend presentation tests. Python compilation, the Next.js 15.5.19 production build, `git diff --check`, ignored-secret checks, and live read-only verification passed.

---

# 18. Current Verification History

The repository has been repeatedly verified during implementation.

Recorded development checkpoints include:

| Checkpoint | Backend | Frontend | Diff check |
| --- | --- | --- | --- |
| Initial planning MVP | 8 / 8 tests passing | Not recorded | Not recorded |
| Recommendation Engine V1 | 56 tests passing | Build passing | Not recorded |
| Multi-task and subtask creation | 75 tests passing | Build passing | Not recorded |
| Project Brain V1 | 85 tests passing | Build passing | Not recorded |
| Project Brain aggregation fix | 86 tests passing | Build passing | Passing |
| Dedicated Project Brain service | 90 tests passing | Build passing | Passing |
| Durable canonical project registry | 95 tests passing | Build passing | Passing |
| Normalized work model | 100 tests passing | Build passing | Passing |
| Shared recommendation service | 113 tests passing | Build passing | Passing |
| Linear read provider and adapter | 129 tests passing | Build passing | Passing |
| Durable Linear project mappings | 134 tests passing | Build passing | Passing |
| Mapped Linear Project Brain and work packages | 149 tests passing | 3 frontend tests and build passing | Passing |
| Trustworthy Linear dependency evaluation | 163 tests passing | 5 frontend tests and build passing | Passing |

The current pre-edit audit for this repair also passed all 86 backend tests and the frontend production build. Its initial `git diff --check` reported only two trailing-whitespace errors in this handoff's metadata; those formatting defects were removed during repair.

The current backend test suite includes:

- `backend/tests/test_agent_examples.py`
- `backend/tests/test_app_surfaces.py`
- `backend/tests/test_calendar_intelligence.py`
- `backend/tests/test_project_brain_service.py`
- `backend/tests/test_project_registry.py`
- `backend/tests/test_recommendation_service.py`
- `backend/tests/test_work_domain.py`
- `backend/tests/test_linear_provider.py`
- `backend/tests/test_project_work_packages.py`

Common verification commands are:

```bash
backend/.venv/bin/python -m unittest discover backend/tests
cd frontend
npm run build
cd ..
git diff --check
```

Local stack smoke testing has used `./start.sh`, with backend health checked at `http://127.0.0.1:8000/health` and the frontend checked at `http://localhost:3010`, followed by `./stop.sh`.

The passing-test counts above are historical verified checkpoints from development.

They should not be treated as a guarantee that the current working tree remains green after later unverified edits.

Before beginning new implementation work, the next engineer or ChatGPT Work session should rerun the full backend suite, frontend build, and `git diff --check`.

# 19. Active Work

This section describes the accepted work that should be treated as current rather than as distant product vision.

The immediate objective is not to add every discussed life integration.

The current objective is to make PCOS's existing intelligence architecture coherent enough to support Linear and future providers without creating additional parallel recommendation systems.

---

## 19.1 Consolidate Intelligence Around Project Brain

**Status:** Active direction / highest-priority architecture work

Project Brain V1 exists, but it is not yet the canonical source of project intelligence across PCOS.

Today, Tasks, backend planning, and Project Brain still compute overlapping state through different paths.

The current fragmentation is conceptually:

```text
Tasks frontend ranking
        !=
backend planner ranking
        !=
Today recommendation logic
        !=
Project Brain next-move logic
```

This creates a risk that different PCOS surfaces disagree about the same project.

For example:

- Tasks may recommend one Freelance task.
- Today may surface another.
- Projects may identify a third next move.
- Chat may independently reason toward a fourth answer.

The accepted architecture direction is:

```text
Providers
        ↓
normalized source state
        ↓
Project Brain / shared intelligence
        ↓
Today
Projects
Chat
Tasks
future notifications
future native surfaces
```

Project Brain should become the canonical backend-computed model of project state.

This does not mean every page must render the same UI.

It means every surface should consume the same underlying project truth.

### Required consolidation behavior

The shared project model should determine:

- project identity;
- project status;
- executable work;
- task or issue hierarchy;
- next move;
- recommendation reason;
- blockers;
- upcoming commitments;
- people;
- memories;
- recent activity;
- classification confidence or unresolved classification state.

Today should consume compact project summaries derived from this state.

Projects should consume detailed project state.

Chat should answer project questions from this state before improvising from raw provider records.

Tasks should inspect executable work and ranking evidence from backend intelligence rather than maintaining a separate frontend recommendation engine.

### Important constraint

Do not rewrite every existing subsystem at once.

The existing Project Brain V1, planner, Today aggregation, and Tasks ranking contain working behavior and verified history.

The consolidation should preserve working behavior while progressively moving the source of intelligence into shared backend services.

---

## 19.2 Introduce a Work Provider Boundary

**Status:** Normalized model and Todoist adapter implemented / Linear adapter planned

Todoist is currently deeply represented in agent behavior and project aggregation.

This was acceptable when PCOS was primarily an AI Todoist agent.

It is no longer sufficient for the accepted product direction.

Project Brain now consumes typed normalized Todoist work while preserving the existing response contract. PCOS still needs to add a second work system:

- Todoist;
- Linear.

The systems serve different purposes.

Todoist is intended for:

- personal tasks;
- reminders;
- quick execution;
- lightweight actionable work.

Linear is intended for:

- detailed project issues;
- milestones;
- blockers;
- deeper project planning;
- software and creative project state.

PCOS should not pretend that a Todoist task and a Linear issue are identical provider records.

However, the intelligence layer needs a normalized concept of executable work.

The future boundary should allow Project Brain to reason over concepts such as:

- provider;
- provider record ID;
- project;
- title;
- status;
- priority;
- due date;
- parent or hierarchy;
- blocked state;
- dependencies;
- executable state;
- source URL or provider reference;
- creation and update time.

The exact schema is not implemented.

This is architecture work required before or alongside Linear integration.

### Important migration rule

Do not remove Todoist support when Linear is introduced.

The accepted product decision is coordination across both providers.

Linear does not replace every Todoist use case.

---

## 19.3 Linear Integration

**Status:** Planned next major provider integration

The user is actively moving deeper project management into Linear.

The projects explicitly discussed for Linear are:

- PCOS;
- XO;
- Nebulo;
- Freelance.

PCOS should eventually use Linear as the primary source of detailed project execution state for these projects.

The initial Linear integration should focus on reading trustworthy project state before broad write automation.

The first useful integration should allow PCOS to understand:

- Linear projects;
- project status;
- issues;
- issue status;
- issue priority;
- milestones where available;
- parent-child relationships where relevant;
- blockers and dependencies where represented;
- recently changed work.

Project Brain should then combine this state with:

- Google Calendar commitments;
- PCOS Memory;
- PCOS Activity;
- remaining Todoist work.

The product test is whether PCOS can answer questions such as:

```text
What's blocking Nebulo?
What should I work on next for XO?
What changed in PCOS?
```

It should answer without requiring the user to manually restate Linear state.

### Initial Linear scope constraint

Do not begin by building a full Linear clone inside PCOS.

Linear remains the detailed project-management provider.

PCOS should ingest and reason over its state.

Write actions can be introduced after the read and normalization path is trustworthy.

---

## 19.4 Today as a Project Brain Projection

**Status:** Active direction

The Today page currently computes its own live state.

Its life-area cards are clickable into Projects, but that visual connection should not be confused with architectural integration.

Today should become a context-specific projection of shared intelligence.

The intended Today role is:

What matters now?

It should combine:

- current time;
- next calendar commitment;
- current usable free block;
- cross-project priority;
- project next moves;
- urgent personal execution;
- relevant attention items.

Today should not reproduce the entire Projects interface.

A Project Brain summary on Today may contain:

- project status;
- next move;
- blocker indicator;
- meaningful change indicator.

The underlying project next move should match the detailed Project Workspace unless Today has an explicit contextual reason to choose something else.

For example, a 20-minute free block may make a smaller executable task more appropriate than the project's canonical next move.

If Today overrides the canonical project next move for contextual reasons, the reason should be explicit and deterministic.

---

## 19.5 Recommendation Engine Consolidation

**Status:** Shared service implemented for Project Brain / remaining consumers planned

PCOS currently has useful ranking behavior but no single recommendation engine.

Existing ranking signals include:

- Todoist priority;
- due urgency;
- task age;
- unblocking language;
- foundation or setup value;
- project momentum;
- free-block fit;
- energy mode.

These signals should not be discarded.

They should be consolidated into shared backend intelligence.

The target recommendation model should distinguish:

1. canonical project next move;
2. context-aware current recommendation.

A canonical project next move answers:

What is the most important executable action advancing this project?

A current recommendation answers:

Given the user's current time, commitments, available block, and context, what should they do now?

These answers may differ.

That difference should be intentional rather than the result of separate implementations.

### Recommendation evidence

Every recommendation should preserve evidence.

A recommendation result should be capable of explaining signals such as:

- highest-priority executable issue;
- blocks multiple downstream issues;
- deadline approaching;
- project has been inactive;
- fits current free block;
- external commitment approaching;
- foundation work unlocks future execution.

The UI may render this explanation concisely.

The backend should preserve enough structured evidence for debugging.

### Existing recommendation-path audit

The shared-service implementation began by auditing all four existing paths. They remain present until their dedicated migration issues:

- `backend/app/planner.py` enriches raw task dictionaries and scores due urgency, Todoist priority, estimated-duration/free-block fit, inferred task energy versus inferred user energy, and Calendar focus category. It still serves existing planner and Today callers.
- `backend/app/project_brain.py` previously projected normalized Todoist work back into planner dictionaries, ranked executable leaves through `rank_tasks`, and formatted the first result as `Work next: ...`. It now sends typed `NormalizedWorkItem` records to the shared service while retaining the same public wording and response shape.
- `backend/app/main.py` Today aggregation still has a separate orchestration path. It prioritizes preparation inside 60 minutes of an upcoming commitment, computes a current free block, invokes planner ranking, filters for fit, and emits task/calendar/open fallback responses. SID-127 owns this migration.
- `frontend/src/app/tasks/page.tsx` still computes per-life-area recommendations using normalized Todoist priority, task age, due urgency, foundation/unblocking language, and project momentum. It also preserves recommendation-change snapshots in localStorage. SID-128 owns the backend migration, and localStorage change behavior is intentionally not ported by the shared-service issue.

This audit avoids creating a fifth ranking path: the new backend service is the canonical destination, Project Brain is its first consumer, and the other three paths remain compatibility consumers until their dedicated issues.

### Implemented recommendation contract

`backend/app/recommendation_service.py` now defines typed models for:

- recommendation purpose: canonical `project_next_move` or context-aware `current_action`;
- action distinction: `do_work` or `resolve_blocker`;
- selected provider and provider-record identity;
- canonical project ID where available;
- deterministic score and concise explanation;
- structured evidence with signal name, source value, score delta, and explanation;
- up to three considered alternatives;
- computation timestamp and the exact supplied context.

Context can include current time, usable free-block minutes, energy, upcoming commitment title/time, and explicit project-momentum work IDs. Missing free-block, energy, or commitment context stays `None` and produces no invented signal.

### Deterministic scoring and filtering

The service consumes normalized priority only; provider-specific priority conversion stays in provider adapters. Current deterministic weights preserve the useful existing planner behavior while adding the audited Tasks signals:

- due urgency: overdue `+100`, today `+80`, tomorrow `+50`, within seven days `+20`;
- normalized priority: urgent `+40`, high `+25`, medium `+10`, low/none `+0`;
- task age: `+0.25` per day, capped at 30 days;
- foundation/unblocking language and visible project-momentum language: explicit additive evidence using the audited Tasks vocabulary;
- supplied free-block fit: fits `+25`, almost fits `+5`, exceeds block `-30`;
- supplied energy fit: exact match `+15`, low-energy/high-requirement mismatch `-70`, high-energy/low-requirement mismatch `-5`;
- supplied commitment within 60 minutes: work that preserves a ten-minute transition receives `+15`; work that does not fit receives `-40`.

Completed, canceled, container, non-executable, and explicitly blocked records are excluded from `do_work`. If no unblocked executable work exists, an explicitly blocked executable record can produce a `resolve_blocker` recommendation with preserved dependency evidence. Todoist still supplies no explicit dependencies or blocked state, so the service does not infer either from keywords.

Tie-breaking is stable: score, due date, creation timestamp, action, provider, provider record ID, and title. With the same records, supplied context, and computation time, output is deterministic regardless of input order.

---

# 20. Known Bugs and Trust Failures

The following issues have either been directly observed during development or are visible consequences of the current architecture.

These are not hypothetical future features.

---

## 20.1 Google Calendar Refresh Tokens Can Become Invalid

**Status:** Known operational bug / provider fragility

Observed error:

```text
RefreshError: invalid_grant
Token has been expired or revoked.
```

When this occurs:

- token refresh fails;
- calendar reads fail;
- calendar writes cannot be trusted;
- PCOS loses a foundational source of current state.

The current recovery path requires `backend/scripts/google_oauth_setup.py` and local environment configuration.

Provider health diagnostics now expose the failure.

The reconnect experience remains unfinished.

### Required behavior

PCOS should clearly distinguish Calendar disconnected from Calendar connected but no events found, and from PCOS reasoning failed.

The final product should provide an in-application reconnect flow.

---

## 20.2 Calendar State Has Previously Been Temporally Wrong

**Status:** Known trust failure

Observed behavior has included:

- past free blocks appearing as current;
- an approaching event being described as hours away;
- incorrect event timing;
- recommendations behaving as though the remaining day were more open than it actually was.

These failures are particularly severe because Today presents computed state with high visual confidence.

### Required behavior

All calendar-derived intelligence must consistently use:

- the configured user timezone;
- a trustworthy current-time value;
- normalized event timestamps;
- remaining-today filtering;
- correct all-day handling;
- correct informational-event handling.

Regression tests should cover the exact historical failure classes.

---

## 20.3 Chat Has Produced Generic Advice Despite Connected Calendar State

**Status:** Partially fixed; regression risk remains

Observed failure: PCOS gave generic interview preparation advice and told the user to check the schedule instead of answering from the connected calendar.

This was unacceptable because PCOS had Calendar access.

The system effectively told the user to manually inspect a provider PCOS was supposed to understand.

### Root problem

This is an orchestration and grounding problem.

Date-scoped exact event lookup and terse follow-up handling are now implemented and covered by tests, so the original failure is partially fixed. The broader path still does not consistently distinguish disconnected-provider state from empty or unmatched state, and model fallbacks remain a regression risk.

Possible contributing architecture includes:

- insufficient retrieval of relevant events;
- weak follow-up context handling;
- model fallback behavior;
- provider state not being injected into the relevant decision path.

### Required behavior

When a connected provider contains the answer, PCOS should retrieve and use that state.

If Calendar is unavailable, PCOS should say that Calendar is unavailable.

It should not imply that the user should manually check Calendar while presenting itself as though Calendar context is connected.

---

## 20.4 Project Brain Previously Ranked Parent Containers

**Status:** Fixed, regression risk remains

Project Brain previously surfaced parent roadmap tasks as next moves even when the executable work existed in child tasks.

The hierarchy fix now:

- includes active subtasks;
- preserves parent-child relationships;
- treats parents with active children as containers;
- ranks executable leaf tasks.

This behavior is implemented and verified.

It should receive regression coverage as the work-provider model changes.

Linear hierarchy must not reintroduce the same conceptual bug.

---

## 20.5 DDN and Ambiguous Work Can Be Misclassified

**Status:** Partially addressed

A high-priority DDN task failed to appear where expected because project classification could not confidently map DDN.

The current system includes:

- Needs Classification;
- classification diagnostics;
- explicit DDN ambiguity in seeded memory.

This is safer than confidently assigning DDN to the wrong project.

Project Brain currently leaves an unqualified DDN task in Needs Classification, while an explicitly Freelance DDN task can remain Freelance. However, the deterministic capture path is still inconsistent: a bare capture such as `DDN follow-up` can match `Freelance` text inside the seeded DDN memory and be routed to Freelance. That current bug is why this issue remains only partially addressed.

The broader classification problem remains.

### Required behavior

Unknown acronyms, people, and work contexts should not be force-mapped based on weak keyword overlap.

PCOS should:

- preserve the source record;
- expose unresolved classification;
- allow classification;
- remember approved durable mappings where appropriate.

---

## 20.6 Project Intelligence Can Disagree Across Surfaces

**Status:** Known architecture bug

Because Today, Tasks, planner logic, and Project Brain do not use one canonical recommendation path, the system can produce inconsistent next moves.

Even if each local ranking algorithm is individually reasonable, disagreement damages the Chief of Staff experience.

The user should not need to decide which PCOS page is correct.

This is the primary reason Project Brain consolidation is active work.

---

## 20.7 Local Development Still Requires a Running Local Stack

**Status:** Known product friction

The local-development pass improved startup substantially.

The user can now run `./start.sh` and stop the stack with `./stop.sh`.

The frontend also moved from port 3000 to 3010 to avoid conflicts with XO VR and other development projects.

However, PCOS is still a local application requiring a development stack.

If the backend is not running, PCOS is unavailable.

If the frontend is not running, the web surface is unavailable.

This is one of the reasons the user still falls back to Todoist and Google Calendar directly.

The current scripts solve development friction.

They do not solve application deployment or cross-device availability.

---

## 20.8 Stale Next.js Development State Has Broken Styling

**Status:** Observed development issue

The Projects route previously appeared without expected styling.

The confirmed cause was a stale frontend development server.

A prior Next.js build regenerated `.next` while an older dev server remained bound to port 3010.

The stale server then served a broken or incorrect response for `/projects`.

Verification confirmed:

- `app/layout.tsx` imported `globals.css`;
- only the intended root layout existed;
- `/projects` was inside AppShell;
- Tailwind content paths included app and components;
- the build included `/projects`;
- `/projects` returned 200;
- generated HTML included the layout CSS;
- AppShell markers were present.

A clean restart resolved the issue.

### Development implication

When a route unexpectedly loses global styling after builds or server changes, verify the active dev process and `.next` state before rewriting layout or Tailwind configuration.

---

## 20.9 Bulk Roadmap Parsing Is Tied to Todoist-era Workflow

**Status:** Implemented behavior with superseded product assumptions

The bulk roadmap parser successfully converts roadmap text into Todoist subtasks.

This was useful and verified.

The deeper product-management direction has since moved toward Linear.

The parser should not be expanded into a larger Todoist project-management DSL without reconsidering the provider architecture.

The existing capability can remain supported.

Future roadmap ingestion should likely target normalized work actions and allow the correct provider to own the resulting work.

---

## 20.10 Browser Memory and Habits Mutations Can Fail CORS Preflight

**Status:** Known implementation bug

The API exposes `PATCH` and `DELETE` for Memory and Habits, but backend CORS allows only `GET`, `POST`, and `OPTIONS`. Direct API calls can work while cross-origin browser edits and deletes fail before reaching the route.

The fix should align CORS policy with the authenticated application methods and add browser-level regression coverage.

---

## 20.11 Tasks Age Ranking Is Currently Disconnected

**Status:** Known regression

Todoist normalization preserves `created_at`, and the frontend type and ranking branch expect it. The `main.py` mapper used by `GET /tasks` currently omits the field, so the API emits `created_at: null` and the age signal contributes nothing.

The shared recommendation migration should restore the source value and test it explicitly rather than assuming the historical feature remains wired.

---

## 20.12 Priority Semantics Are Inconsistent

**Status:** Known architecture bug

Todoist normalization, deterministic capture, backend planner logic, Today, Project Brain, and frontend Tasks do not all use the same priority scale or direction. A value called “high priority” in one path can be interpreted differently in another.

The normalized work model must define provider priority, normalized priority, ordering direction, and display semantics explicitly before Linear is added.

---

## 20.13 Deleted Seeded Memory and Habits Reappear After Restart

**Status:** Known persistence bug

Startup initialization recreates default habits by fixed ID and default memories by type and title. The delete routes remove them immediately, but the database stores no tombstone indicating that a seeded default was intentionally removed.

Deleting a seeded habit or memory therefore does not survive the next backend initialization. Future seeding should distinguish first-run defaults from user-owned durable deletion.

---

# 21. Technical Debt

The following technical debt is visible in the current implementation and should influence future implementation decisions.

---

## 21.1 `agent.py` Is Monolithic

`backend/app/agent.py` is approximately 3,500 lines.

It contains responsibilities spanning:

- conversation state;
- intent handling;
- deterministic parsing;
- OpenAI calls;
- memory context;
- entity resolution;
- Todoist behavior;
- Calendar behavior;
- action validation;
- action execution;
- bulk roadmap parsing;
- response formatting.

Adding Linear, email, repository intelligence, and future provider actions directly into this file would create a serious maintenance problem.

### Direction

Extract behavior by domain.

Potential subsystem boundaries include:

- conversation orchestration;
- entity and project resolution;
- action schemas;
- action execution;
- Todoist actions;
- Calendar actions;
- work-provider actions;
- structured model interpretation.

Do not perform a blind rewrite.

Move tested behavior behind clearer boundaries incrementally.

---

## 21.2 `main.py` Still Owns Broad Application Logic

`backend/app/main.py` is approximately 2,000 lines.

It currently combines:

- application setup;
- schemas;
- authentication;
- health diagnostics;
- Today aggregation;
- memory routes;
- habit routes;
- task routes;
- calendar routes;
- activity routes.

Project Brain no longer grows inside the HTTP application module, but the remaining route, schema, Today, and provider-health responsibilities still make `main.py` broad.

### Direction

Continue moving shared application logic behind dedicated services without folding the separate Today, normalized work model, registry, or recommendation consolidation into unrelated refactors.

HTTP routes should primarily validate requests, invoke application services, and return schemas.

---

## 21.3 Recommendation Logic Exists in the Frontend

The Tasks page contains meaningful scoring and recommendation behavior.

This prevents future clients from sharing identical intelligence.

A future iPhone application should not need to port a TypeScript ranking algorithm from the web Tasks page.

### Direction

Move recommendation computation and evidence to the backend.

The frontend should render:

- recommendation;
- ranking evidence;
- alternatives where appropriate;
- refresh or recomputation state.

---

## 21.4 Provider Models Are Partially Normalized

Project Brain now has a typed normalized work model and a Todoist adapter. Provider identity, original status and priority, provider record IDs, and provider metadata are preserved.

Today, Tasks, Chat, and agent behavior still consume older task dictionaries, and Linear has no adapter yet. Provider normalization is therefore implemented for Project Brain but not universal across PCOS.

### Direction

Extend the existing model through provider-specific adapters where shared intelligence needs them.

Preserve provider-specific fields and IDs.

Do not flatten provider behavior so aggressively that important Linear or Todoist semantics disappear.

The normalized layer exists for PCOS reasoning, not to erase provider identity.

---

## 21.5 Conversation State Is Process-local

The agent maintains session conversation state in backend runtime memory.

It also retains a legacy pending action in one process-global variable. That action is not keyed by session, and `POST /confirm-cancel` does not clear it.

This is appropriate for the prototype.

It is not durable across:

- backend restarts;
- multiple backend processes;
- future hosted deployment;
- future devices.

### Direction

Conversation state required for reliable multi-turn actions should eventually use durable backend state.

Pending actions and confirmation context are especially important.

Do not rely on a future native client preserving critical action state locally.

---

## 21.6 SQLite Is Sufficient Now but Not a Production Multi-device Data Layer

SQLite currently stores PCOS-owned state successfully.

It is simple and appropriate for the local prototype.

The long-term product requires:

- Mac;
- iPhone;
- iPad;
- potentially Watch and Vision Pro;
- background monitoring;
- hosted provider connections.

A local SQLite file on one Mac cannot serve as the final shared state architecture.

### Direction

Do not prematurely migrate the database solely for architectural aesthetics.

A hosted backend and multi-device requirements should drive the eventual persistence migration.

The existing SQLite schema is useful for defining PCOS-owned domain state.

---

## 21.7 Frontend Connection State Lives in `localStorage`

The frontend stores:

- backend URL;
- agent API key;
- the last 80 Chat messages;
- recommendation state.

This is development-oriented state.

It is not appropriate for production account authentication or shared cross-device intelligence.

### Direction

Backend intelligence and durable user state should eventually move behind authenticated APIs.

Frontend-local persistence should be limited to genuinely client-local presentation preferences.

---

## 21.8 Action Card Rendering Is Growing Inside `chat-panel.tsx`

`chat-panel.tsx` is approximately 900 lines and contains multiple action-specific rendering paths.

As Linear, email, and future providers introduce more action types, this component can become the frontend equivalent of `agent.py`.

### Direction

Introduce typed action-result components or a structured action-card registry before the number of provider actions expands significantly.

Preserve the current action-card product pattern.

The problem is component organization, not the pattern itself.

---

## 21.9 Activity Is Not Yet a Complete Event Model

Activity currently records some meaningful PCOS actions.

It does not yet capture every important provider or project change.

The system therefore cannot reliably answer all versions of:

What changed?

### Direction

Define what constitutes meaningful PCOS activity.

Potential sources include:

- approved PCOS actions;
- important provider state changes;
- Linear issue transitions;
- repository catch-ups;
- reviewed memory changes;
- future email action candidates.

Avoid recording every low-level API read or UI click.

Activity should describe meaningful operational history.

---

## 21.10 Canonical Project Identity Is Durable; Broader Project State Is Not

Normal canonical projects now use durable SQLite records.

The implemented set includes:

- pcos-ai-todoist-agent;
- nebulo;
- xo;
- freelance;
- am;
- personal;

Needs Classification is a system/unresolved state rather than a normal project record.

Aliases, classification hints, enabled state, and provider mappings are durable. New normal projects can be added through storage without changing Project Brain dictionaries.

### Direction

The next architecture step is to let normalized work reference the durable project ID while preserving provider-specific record identity.

A project may need links to:

- Linear project;
- Todoist sections or tasks;
- repositories;
- people;
- email contexts;
- calendar patterns.

Do not turn the registry into a multi-user project-management database or store normalized work rows before SID-125 defines that model.

---

# 22. Unfinished Plumbing

The following work is neither a broad future idea nor a fully implemented feature.

These are incomplete infrastructure paths needed to support the accepted product direction.

---

## 22.1 In-product Google Calendar Reconnect

Provider health detection exists.

OAuth setup scripts exist.

The missing layer is a user-facing reconnect flow.

The desired experience is conceptually:

```text
Calendar connection expired
        ↓
Reconnect Google Calendar
        ↓
Google OAuth
        ↓
provider health rechecked
        ↓
Calendar connected
```

The user should not need to:

- open Terminal;
- run a Python script;
- copy refresh-token state;
- edit `.env`;
- restart PCOS.


This plumbing is unfinished.

---

## 22.2 Canonical Project Registry

**Status:** Implemented foundation

Project Brain now reads user-project definitions and classification behavior from the durable SQLite registry.

The implemented registry represents:

- canonical project ID;
- display name;
- description;
- enabled state and ordering;
- provider links;
- Linear project identity;
- Todoist mappings;
- repository mappings;
- people classification hints;
- aliases;
- classification hints;
- enabled state.

The provider mapping boundary stores provider, resource type, and provider reference against a durable canonical project ID. Exact Linear project UUID mappings are implemented for PCOS, XO, Nebulo, and Freelance, and SID-135 now consumes those mappings in Project Brain. Repository mappings remain available through the same boundary when needed.

Needs Classification is synthesized outside the editable registry as a system/unresolved state.

---

## 22.3 Shared Work Model

**Status:** Typed model and Todoist adapter implemented

Project Brain now consumes typed normalized Todoist work.

Linear issues are planned.

The model can represent Linear-style dependencies and blocked state, but the Todoist adapter intentionally leaves those fields empty/false because Todoist does not provide them.

The remaining plumbing is a Linear adapter and any later migration of Today, Tasks, or Chat. Normalized provider work is intentionally not persisted or synchronized.

---

## 22.4 Shared Recommendation Service

**Status:** Implemented for typed domain computation and Project Brain

The typed shared service now owns canonical project-next-move and context-aware current-action computation over `NormalizedWorkItem` records. Project Brain is the first migrated consumer and preserves its existing response contract.

Compatibility logic remains split across:

- `planner.py`;
- Today aggregation;
- Project Brain;
- Tasks frontend logic.

Today, Tasks, and Chat migrations remain assigned to SID-127, SID-128, and SID-129. `planner.py` remains because existing callers still depend on it.

---

## 22.5 Background Execution

PCOS has no worker or scheduler.

This blocks truly proactive versions of:

- Email Intelligence;
- repository catch-ups;
- project change detection;
- daily review generation;
- weekly review generation;
- future finance monitoring;
- future vehicle monitoring.

A background execution model must eventually support:

- scheduled jobs;
- provider polling or webhooks;
- durable job state;
- retries;
- provider failure isolation;
- deduplication;
- meaningful activity creation.

The exact infrastructure has not been selected.

---

## 22.6 Durable Action and Conversation Context

Pending action and conversation state currently depend heavily on process-local state and frontend-provided pending-action data.

This works for the local prototype.

A robust multi-device product needs durable action context.

The system should be able to know:

- what action was proposed;
- why it was proposed;
- which provider records it targets;
- whether it was confirmed;
- whether it executed;
- what result occurred.

This is particularly important for future proactive actions originating from email or background monitoring.

---

## 22.7 Provider Sync and Change Detection

PCOS currently reads provider state when application paths request it.

There is no generalized provider synchronization or change-detection layer.

Project Brain therefore computes current state but does not maintain a rich history of provider changes.

This blocks reliable questions such as “What changed in XO since yesterday?” unless the change was already recorded in PCOS Activity.

Repository catch-ups and Linear integration will make this limitation more visible.

---

## 22.8 Production Deployment

The application is currently designed around:

- local backend;
- local frontend;
- local SQLite;
- local environment credentials;
- local startup scripts.

There is no documented production deployment architecture.

A hosted or continuously available backend will eventually be required for:

- iPhone;
- iPad;
- background monitoring;
- provider webhooks;
- proactive intelligence;
- Live Activities;
- remote access.

Production deployment is unfinished infrastructure, not an implemented feature.

---

# 23. Features Discussed but Not Yet Built

This section records accepted or explicitly discussed product capabilities that do not exist in the audited repository.

It intentionally excludes ideas that were never discussed.

---

## 23.1 Linear-backed Project Intelligence

PCOS should ingest Linear state for:

- PCOS;
- XO;
- Nebulo;
- Freelance.

Desired intelligence includes:

- project status;
- detailed issues;
- priorities;
- milestones;
- blockers;
- dependencies;
- recent changes;
- executable next work.

This should feed Project Brain.

Not implemented.

---

## 23.2 Email Intelligence

PCOS should monitor:

- personal email;
- A&M email.

It should identify messages that deserve attention or action.

Potential outputs include:

- important email attention item;
- deadline extraction;
- task proposal;
- calendar-action proposal;
- project association;
- explicit review request.

The user specifically wants help because email is an area they are bad at consistently monitoring.

The system should err toward catching potentially important administrative or academic messages without turning every email into a notification.

Not implemented.

---

## 23.3 Codex and Repository Catch-Ups

The user proposed scheduled repository catch-ups.

The desired workflow is:

```text
repositories
        ↓
Codex or repository analysis
        ↓
structured catch-up
        ↓
Activity and Project Brain
```

Catch-ups should summarize:

- meaningful changes;
- completed work;
- work in progress;
- test state;
- blockers;
- technical debt;
- likely next engineering step.

Not implemented.

---

## 23.4 Daily Review

Daily Review was discussed as part of the Habits redesign and broader PCOS intelligence direction.

The desired experience should reason about:

- what was planned;
- what happened;
- what was completed;
- what slipped;
- why something may have slipped;
- important project changes;
- relevant behavioral patterns.

This should not be a manual Yes/Partial/No checklist.

Not implemented.

---

## 23.5 Weekly Review

Activity and future project intelligence were discussed as foundations for a Weekly Review.

A useful Weekly Review may eventually summarize:

- project progress;
- blockers;
- neglected areas;
- meaningful calendar patterns;
- completed work;
- important email or administrative follow-through;
- changes across repositories.

Not implemented.

---

## 23.6 Health and Automatic Habit Context

The current Habits tracker is superseded.

The accepted future direction includes:

- Health;
- Daily Review;
- automatic context where available;
- Apple Health;
- Apple Watch.

The product should eventually understand more of what actually happened instead of requiring manual check-ins for everything.

Not implemented.

---

## 23.7 Memory Inbox

PCOS should eventually propose durable memories when it detects context worth preserving.

The intended flow is:

```text
detected durable context
        ↓
memory suggestion
        ↓
user review
        ↓
approved durable memory
```

The system should avoid automatically turning every conversation detail into permanent memory.

Not implemented.

---

## 23.8 Finance Intelligence

The user wants PCOS to eventually connect important financial state.

Discussed concepts include:

- spending;
- budget;
- cash flow;
- balances;
- recurring charges;
- financial obligations.

Potential sources discussed include:

- Bank of America;
- Webull;
- Apple Card data where legitimately accessible.

The product should preserve actual account ownership and access boundaries.

Not implemented.

---

## 23.9 Investing Intelligence

The accepted direction is not an AI stock picker.

The goal is an investing research and decision-support system.

Discussed capabilities include:

- portfolio tracking;
- allocation analysis;
- company research;
- watchlists;
- earnings summaries;
- company comparison;
- valuation models;
- backtesting;
- investment journal;
- AI-generated research reports;
- risk analysis;
- position sizing;
- rebalancing suggestions.

The system may eventually personalize observations based on the user's long-term goals and existing portfolio.

Not implemented.

---

## 23.10 Vehicle Maintenance Intelligence

PCOS should eventually remember vehicle maintenance state.

Discussed maintenance categories include:

- oil;
- tire rotation;
- engine air filter;
- cabin filter;
- transmission service;
- brake fluid;
- coolant;
- spark plugs.

Desired state includes:

- current mileage;
- service history;
- next threshold;
- time-based maintenance;
- upcoming maintenance attention.

Not implemented.

---

## 23.11 Automatic Vehicle Mileage

Automatic mileage ingestion was discussed.

An OBD-II-based source was identified as technically plausible.

The purpose is not a car telemetry dashboard for its own sake.

The purpose is to remove manual mileage remembering from maintenance intelligence.

Not implemented.

---

## 23.12 Smart Mirror Surface

A future PCOS smart-mirror surface was discussed.

Desired glanceable state includes:

- walk time to class;
- drive time to class;
- upcoming events;
- travel time home;
- relevant daily context.

The mirror should consume shared PCOS intelligence.

It should not contain separate reasoning logic.

Not implemented.

---

## 23.13 Native Mac, iPhone, and iPad Applications

The user wants PCOS to become an actual application available across:

- Mac;
- iPhone;
- iPad.

The desired iPhone visual direction is premium, native, and glass-forward.

The current web application is a product and architecture prototype.

No native clients exist.

---

## 23.14 Apple Watch, Widgets, Live Activities, and Dynamic Island

Potential Apple-platform surfaces discussed include:

- Apple Watch;
- widgets;
- Live Activities;
- Dynamic Island presentation.

Relevant state may include:

- approaching commitments;
- current focus;
- upcoming event context;
- action cards;
- glanceable day intelligence.

These surfaces should be selective and useful.

Dynamic Island should not be used merely because it is visually interesting.

Not implemented.

---

## 23.15 Vision Pro Surface

Vision Pro was discussed as a possible PCOS surface.

The broader product rule remains:

Vision Pro should consume the same PCOS intelligence layer.

It should not become a separate PCOS brain.

No visionOS client exists.

---

# 24. Superseded Directions

The following earlier product directions have been explicitly replaced or materially changed.

Future work should follow the newer direction.

---

## 24.1 Todoist as the Detailed Project-Management Backbone

**Earlier direction:**

Store detailed roadmaps as large Todoist parent tasks with many subtasks.

**Latest direction:**

Use Linear for deeper project management.

Use Todoist for lighter execution, reminders, and personal tasks.

Use PCOS to coordinate across both.

The bulk Todoist roadmap feature remains valid completed functionality.

It should not define future project architecture.

---

## 24.2 Chat as the Primary Product

**Earlier direction:**

PCOS centered heavily on a natural-language chat experience.

**Latest direction:**

Chat is one interface.

Today, Projects, Calendar, Tasks, Memory, Settings, and future native surfaces are first-class product surfaces.

PCOS itself is the intelligence and coordination layer.

---

## 24.3 Manual Habit Tracking as the Health Product

**Earlier direction:**

Users manually mark Gym, Running, and Work as Yes, Partial, or No.

**Latest direction:**

The Habits product should evolve toward Health and Daily Review.

PCOS should compare planned and actual state, preserve context, detect patterns, and eventually use automatic health signals where available.

---

## 24.4 Independent Recommendation Logic Per Surface

**Earlier implementation reality:**

Different surfaces developed their own ranking behavior as the product expanded.

**Latest architecture direction:**

Project Brain and shared backend intelligence should become the source of project state and recommendation evidence.

Surface-specific context may affect presentation or current recommendations.

It should not create unrelated definitions of project truth.

---

## 24.5 More Model Intelligence as the Primary Fix for Bad Answers

**Earlier temptation:**

Treat generic or incorrect assistant behavior primarily as a model-quality problem.

**Latest understanding:**

The major failures are often caused by:

- provider retrieval;
- stale state;
- orchestration;
- conversation context;
- duplicated intelligence paths;
- weak action architecture.

A better model may improve interpretation.

It does not replace trustworthy application architecture.

---

# 25. Immediate Engineering Sequence

The recommended sequence for continuing PCOS is:

1. Establish a clean current baseline.
2. Extract Project Brain Into a Dedicated Backend Service.
3. Create a Durable Canonical Project Registry while co-designing the Normalized Work Model.
4. Define the Normalized Work Model.
5. Build Shared Recommendation Service.
6. Run the Calendar trust track in parallel: Harden Calendar Time and Free-Block Correctness, and Fix Connected-State Grounding in Calendar Conversations.
7. Make Today a Projection of Shared Intelligence after its Calendar-derived fields satisfy the trust contract.
8. Move Tasks Recommendation Logic to the Backend.
9. Ground Chat Project Questions in Project Brain.
10. Implement Linear Provider Connection and Read Adapter.
11. Feed Linear Work Into Project Brain.
12. Compute Trustworthy Project Blockers From Linear State across PCOS, XO, Nebulo, and Freelance.
13. Build Typed and Durable Pending Action Architecture.
14. Add Linear write actions only after read intelligence is trustworthy.
15. Co-design background execution requirements with Production PCOS Deployment Architecture.
16. Begin Email Intelligence and repository catch-up ingestion.

Before implementation begins, rerun:

```bash
backend/.venv/bin/python -m unittest discover backend/tests
cd frontend
npm run build
cd ..
git diff --check
```

The current working tree may contain development changes beyond the historical verification checkpoints documented earlier.

Do not assume the last recorded count of 86 backend tests represents the exact current working-tree state until the suite is rerun.

---

# 26. Definition of the Current PCOS Phase

PCOS is no longer in the original MVP phase.

The original MVP proved:

Can Todoist and Google Calendar be combined to answer what the user should work on?

That question has been answered.

The current phase is:

Can PCOS maintain one trustworthy operational model of the user's projects and immediate life state across multiple providers?

Project Brain V1, Memory, Activity, Calendar Intelligence, Todoist actions, and the visual application provide the foundation.

The next phase should turn those foundations into one coherent intelligence architecture.

Linear is the first major test of whether PCOS can expand beyond its original provider assumptions without becoming a collection of disconnected integrations.

Email Intelligence and repository catch-ups are the first major tests of proactive awareness.

Native Apple surfaces are the eventual test of whether PCOS can become a real daily operating system rather than a development dashboard.

The immediate priority is therefore not maximum feature count.

It is making the brain coherent enough that every future integration makes PCOS more intelligent instead of merely making the codebase larger.

# 27. Proposed Linear Roadmap

This roadmap converts the accepted PCOS direction into proposed Linear milestones and issues.

It intentionally separates:

- completed development history;
- active architecture work;
- near-term provider integrations;
- product expansion;
- future platform work.

This is not intended to create one Linear issue for every file or implementation detail.

Issues are grouped around meaningful engineering and product outcomes.

The roadmap should preserve the current working application while progressively moving PCOS toward one coherent intelligence architecture.

Roadmap metadata uses the following conventions:

- `Done` records completed history.
- `In Progress` means the current repository satisfies part, but not all, of the issue outcome.
- `Todo` is accepted active or planned work that has not reached the issue outcome.
- `Backlog` is intentionally deferred future work.
- Priorities use `Urgent`, `High`, `Medium`, `Low`, or `No priority (historical)`. Future placement belongs in milestone/status metadata rather than in a nonstandard priority value.

---

# 28. Milestone 0 — Completed Foundation

**Milestone status:** Completed history

**Purpose:** Preserve the work that established the current PCOS application.

These issues should be imported as completed if historical project context is useful in Linear.

They should not be treated as active implementation work.

---

## Issue: Build Todoist and Google Calendar Planning MVP

**Status:** Done

**Priority:** No priority (historical)

**Description:**

Build the original PCOS planning loop capable of reading Todoist tasks and Google Calendar events, finding usable free blocks, enriching tasks, ranking work, and answering what the user should work on.

This issue represents the original proof of concept from which PCOS evolved.

**Dependencies / blockers:**

None.

**Acceptance criteria:**

- Todoist tasks can be read.
- Google Calendar events can be read.
- Free blocks can be computed.
- Tasks can be enriched and ranked.
- Low-energy mode is supported.
- Structured actions can create Todoist tasks.
- Structured actions can create Google Calendar events.
- Original backend MVP tests pass.

**Historical verification:**

8 / 8 tests passed at the original MVP checkpoint.

---

## Issue: Build PCOS Web Application Foundation

**Status:** Done

**Priority:** No priority (historical)

**Description:**

Create the Next.js application and evolve PCOS from a chat-only prototype into a multi-surface web application.

The completed application foundation includes the shared shell and the major current navigation surfaces.

**Dependencies / blockers:**

Planning MVP.

**Acceptance criteria:**

- Next.js App Router application exists.
- Shared App Shell exists.
- Desktop sidebar exists.
- Mobile bottom navigation exists.
- Dark visual system exists.
- Today route exists.
- Projects route exists.
- Chat route exists.
- Calendar route exists.
- Tasks route exists.
- Habits route exists.
- Memory route exists.
- Settings route exists.

---

## Issue: Implement Durable PCOS Memory

**Status:** Done

**Priority:** No priority (historical)

**Description:**

Implement SQLite-backed durable Memory so PCOS can preserve project, person, group, rule, preference, and pattern context across interactions.

Memory should participate in agent reasoning and deterministic entity resolution.

**Dependencies / blockers:**

Backend and SQLite foundation.

**Acceptance criteria:**

- Memory entries persist in SQLite.
- Memory CRUD API exists.
- Memory Center exists.
- Memories can be enabled or disabled.
- Confidence can be edited.
- Enabled memories are included in agent context.
- Deterministic resolution can use memory.
- Default project and relationship context is seeded idempotently.

**Current repository audit:**

The current seed operation is idempotent while a record exists, but deletion has no tombstone. A deleted seeded memory is recreated by type and title on a later backend initialization; that restart behavior is tracked as a current persistence bug.

---

## Issue: Implement Direct Action Confirmation

**Status:** Done

**Priority:** No priority (historical)

**Description:**

Replace synthetic affirmative chat confirmation with direct application action execution.

Confirmation cards should execute approved pending actions through a dedicated backend path.

**Dependencies / blockers:**

Chat action architecture.

**Acceptance criteria:**

- `/confirm` exists.
- Current executable confirmation cards call `/confirm` directly.
- Pending action types are allowlisted before execution; Calendar update and bulk-subtask variants receive additional field-level validation.
- Current cards directly execute a single Todoist task, bulk Todoist subtasks, Calendar create, and Calendar update.
- A cancellation endpoint and frontend action exist; clearing legacy process-global state remains unresolved.
- Supported action results render as structured or generic completion cards.

**Current repository audit:**

The backend agent also supports single-subtask and bulk top-level task actions, but those variants are absent from the frontend confirmation whitelist. Direct confirmation is implemented history; fully typed, durable, session-scoped action architecture remains planned.

---

## Issue: Implement Calendar Intelligence V1

**Status:** Done

**Priority:** No priority (historical)

**Description:**

Build deterministic calendar analysis for proposed schedule changes.

Calendar Intelligence should identify meaningful conflict and buffer conditions without pretending to be a fully autonomous scheduling engine.

**Dependencies / blockers:**

Google Calendar integration.

**Acceptance criteria:**

- True overlap can be identified.
- Tight buffers can be identified.
- Travel-buffer concerns can be represented.
- Informational overlap can be distinguished.
- Hard events are modeled.
- Flexible events are modeled.
- Informational events are modeled.
- Social events are modeled.
- Calendar Intelligence participates in supported calendar-action flows.
- Dedicated Calendar Intelligence tests exist.

---

## Issue: Implement Explainable Task Recommendations V1

**Status:** Done

**Priority:** No priority (historical)

**Description:**

Build the first explainable per-life-area recommendation experience for Todoist tasks.

This issue represents the completed Tasks frontend recommendation implementation.

Its logic is now a consolidation target and should not be expanded as a separate frontend intelligence engine.

**Dependencies / blockers:**

Todoist task API.

**Acceptance criteria:**

- Todoist priority influences ranking.
- Task age can influence ranking.
- Due urgency can influence ranking.
- Unblocking or foundation language can influence ranking.
- Project momentum can influence ranking.
- Recommendation reasons are displayed.
- Life-area recommendations can be inspected.
- Recommendation refresh state exists.
- Recommendation change callouts exist.

**Historical verification:**

56 backend tests passed at the recorded feature checkpoint.

Frontend build passed.

---

## Issue: Implement Bulk Todoist Roadmap Actions

**Status:** Done

**Priority:** No priority (historical)

**Description:**

Allow one roadmap-style command to produce multiple Todoist subtasks under an existing parent task.

This capability proved PCOS can convert larger planning artifacts into structured provider actions.

The later Linear decision supersedes Todoist as the preferred destination for detailed project roadmaps.

**Dependencies / blockers:**

Todoist integration.

Direct confirmation execution.

**Acceptance criteria:**

- Multiple roadmap items can be parsed.
- Parent task lookup works.
- Subtasks can be created.
- Bulk subtask creation works.
- Duplicate child titles are skipped.
- Missing-parent behavior requests confirmation or correction.
- Large batches receive confirmation.
- Created and skipped items are reported.
- Bulk creation is recorded in Activity.

**Historical verification:**

75 backend tests passed at the recorded feature checkpoint.

Frontend build passed.

---

## Issue: Improve Local Development Workflow

**Status:** Done

**Priority:** No priority (historical)

**Description:**

Reduce friction caused by manually running the PCOS stack and port conflicts with other projects.

**Dependencies / blockers:**

Existing local frontend and backend.

**Acceptance criteria:**

- Frontend development runs on port 3010.
- Root `start.sh` exists.
- Root `stop.sh` exists.
- Runtime logs and PID state use `.run/`.
- Backend starts on port 8000.
- Frontend starts on port 3010.
- `/health` returns successfully after startup.
- Stop script terminates the local stack.
- README documents the current quickstart.

---

## Issue: Implement Provider Health Diagnostics

**Status:** Done

**Priority:** No priority (historical)

**Description:**

Expose provider health so PCOS can distinguish backend, Todoist, Google Calendar, and OpenAI failures.

This issue was motivated by repeated Calendar OAuth failures being mistaken for broader intelligence bugs.

**Dependencies / blockers:**

Current provider integrations.

**Acceptance criteria:**

- `/settings/health` exists.
- Backend health is reported.
- Todoist health is reported.
- Google Calendar health is reported.
- OpenAI health is reported.
- Settings renders provider health.
- Calendar failures expose reconnect guidance.

---

## Issue: Build Project Brain V1

**Status:** Done

**Priority:** No priority (historical)

**Description:**

Build the first backend-computed project intelligence aggregation and Projects application surface.

Project Brain V1 combines Todoist, Google Calendar, Memory, and Activity state.

**Dependencies / blockers:**

Todoist.

Google Calendar.

Memory.

Activity.

**Acceptance criteria:**

- `/projects` exists.
- `/projects/{project_key}` exists.
- Project summaries are computed.
- Project detail state is computed.
- Tasks are included.
- Calendar events are included.
- People are included.
- Memories are included.
- Activity can be included.
- Blockers can be surfaced.
- A next recommendation can be computed.
- Projects index exists.
- Project Workspace exists.
- Today life-area cards can link into Projects.

**Historical verification:**

85 backend tests passed at the recorded initial Project Brain checkpoint.

Frontend build passed.

---

## Issue: Preserve Work Hierarchy in Project Brain

**Status:** Done

**Priority:** No priority (historical)

**Description:**

Fix Project Brain so parent Todoist roadmap containers do not hide or outrank their executable child tasks.

Add classification diagnostics and a safe unresolved-classification path.

**Dependencies / blockers:**

Project Brain V1.

Todoist subtask support.

**Acceptance criteria:**

- Active subtasks are included in project task state.
- Parent-child hierarchy is preserved.
- Parent tasks with active children are treated as containers.
- Executable leaf tasks can become the project next move.
- Task counts include active subtasks.
- High-priority subtasks are surfaced.
- Needs Classification exists.
- Classification diagnostics expose relevant routing evidence.

**Historical verification:**

86 backend tests passed at the recorded checkpoint.

Frontend build passed.

`git diff --check` passed.

---

# 29. Milestone 1 — Canonical Project Intelligence

**Milestone status:** Active / highest priority

**Purpose:**

Turn Project Brain from one aggregation surface into the shared project intelligence subsystem used across PCOS.

This milestone is the current architecture priority.

Do not begin broad finance, native app, vehicle, or smart-mirror work before this foundation is coherent.

---

## Issue: Extract Project Brain Into a Dedicated Backend Service

**Status:** Implemented

**Priority:** Urgent

**Description:**

Move Project Brain aggregation out of the large FastAPI application module and establish it as a dedicated backend subsystem.

The goal is not a rewrite.

The existing Project Brain behavior should be preserved while giving shared project intelligence a clear service boundary.

The service should own computation of:

- project identity;
- project status;
- project work state;
- hierarchy;
- executable work;
- next move;
- blockers;
- upcoming commitments;
- people;
- memories;
- recent activity;
- classification diagnostics.

`main.py` should primarily expose HTTP routes and schemas rather than contain the Project Brain implementation.

**Dependencies / blockers:**

Current Project Brain V1.

Current backend test suite must establish a clean baseline before refactoring.

**Acceptance criteria:**

- Project Brain aggregation lives outside `main.py`.
- `/projects` behavior remains available.
- `/projects/{project_key}` behavior remains available.
- Existing project keys continue to resolve.
- Task hierarchy behavior is preserved.
- Parent-container behavior is preserved.
- Needs Classification behavior is preserved.
- Classification diagnostics are preserved.
- Project next-move behavior does not regress.
- Existing backend tests pass.
- New service-level tests cover Project Brain aggregation.
- Frontend Projects pages build without API contract regressions.
- `git diff --check` passes.

---

## Issue: Create a Durable Canonical Project Registry

**Status:** Implemented

**Priority:** High

**Description:**

Replace the long-term dependency on hard-coded project definitions with durable project metadata.

The registry should represent the projects PCOS understands and provide a home for provider mappings.

Initial projects should preserve the currently implemented project set:

- PCOS;
- Nebulo;
- XO;
- Freelance;
- A&M;
- Personal.

Needs Classification should remain a system state or unresolved bucket rather than being treated as an ordinary user project.

The project registry should support future links to Linear projects and repositories without requiring another hard-coded project key in backend application code.

**Dependencies / blockers:**

Dedicated Project Brain service.

Schema design should account for Linear and repository mappings.

**Acceptance criteria:**

- Canonical projects have durable IDs.
- Project display names are stored.
- Project descriptions can be stored.
- Project enabled state can be represented.
- Project aliases or classification hints can be represented.
- Provider mappings can be associated with a project.
- Existing PCOS, Nebulo, XO, Freelance, A&M, and Personal identities are migrated or seeded.
- Existing Project Workspace routes continue to resolve stable project identifiers.
- Unknown work can remain unresolved.
- Adding a future project does not require editing a hard-coded project dictionary in `main.py`.
- Project registry behavior is tested.

---

## Issue: Define the Normalized Work Model

**Status:** Implemented

**Priority:** Urgent

**Description:**

Create the shared backend representation Project Brain will use to reason over actionable work from multiple providers.

The immediate providers are Todoist and planned Linear.

The model should preserve provider identity while exposing the common fields needed for PCOS intelligence.

The normalized work model should support concepts including:

- provider;
- provider record ID;
- canonical project;
- title;
- status;
- priority;
- due date;
- parent;
- hierarchy;
- executable state;
- blocked state;
- dependencies;
- creation time;
- update time;
- provider reference or URL.

Do not force Todoist and Linear into identical provider semantics.

The normalized model exists for PCOS reasoning.

Provider-specific adapters should preserve additional source metadata where required.

**Dependencies / blockers:**

Project Brain service boundary.

Canonical Project Registry should be designed alongside this issue.

**Acceptance criteria:**

- A normalized work domain model exists.
- Todoist tasks can be converted into normalized work records.
- Provider identity is preserved.
- Provider record IDs are preserved.
- Parent-child hierarchy can be represented.
- Executable versus container work can be represented.
- Blocked state can be represented.
- Dependencies can be represented without inventing them for Todoist.
- Priority can be normalized while preserving source priority metadata.
- Due dates can be represented.
- Project Brain can consume normalized Todoist work.
- Existing Todoist behavior does not regress.
- Model and adapter tests exist.

---

## Issue: Build Shared Recommendation Service

**Status:** Implemented

**Priority:** Urgent

**Description:**

Consolidate recommendation computation into shared backend intelligence.

The current system has overlapping recommendation paths in:

- `planner.py`;
- Today;
- Project Brain;
- Tasks frontend.

The new service should distinguish:

1. canonical project next move;
2. context-aware current recommendation.

A canonical project next move answers:

What is the most important executable action advancing this project?

A context-aware current recommendation answers:

Given the user's current time, commitments, usable free block, and context, what should they do now?

The service should preserve useful existing ranking signals rather than replacing them with opaque LLM judgment.

Relevant signals include:

- provider priority;
- due urgency;
- task age;
- unblocking value;
- foundation or setup value;
- project momentum;
- free-block fit;
- energy mode.

Every recommendation should preserve structured evidence.

**Dependencies / blockers:**

Normalized Work Model.

Project Brain service.

Existing ranking behavior must be audited before removal from frontend or planner paths.

**Acceptance criteria:**

- Backend recommendation domain model exists.
- Canonical project next move can be computed.
- Context-aware current recommendation can be computed.
- Recommendation evidence is structured.
- Priority can influence ranking.
- Due urgency can influence ranking.
- Task age can influence ranking.
- Unblocking or foundation value can influence ranking.
- Project momentum can influence ranking.
- Free-block fit can influence current recommendations.
- Energy context can influence current recommendations where supplied.
- Parent containers cannot become executable recommendations.
- Blocked work cannot be recommended as immediately executable unless the recommendation explicitly concerns resolving the blocker.
- Ranking behavior has dedicated backend tests.
- Recommendation output can explain why an item was selected.

---

## Issue: Make Today a Projection of Shared Intelligence

**Status:** Todo

**Priority:** High

**Description:**

Replace Today-specific project recommendation computation with shared Project Brain and recommendation-service output.

Today should remain context-aware.

It may choose a different current action from a project's canonical next move when the current time or available block makes that appropriate.

That difference must come from the shared recommendation architecture and explicit contextual evidence rather than a separate ranking implementation.

**Dependencies / blockers:**

Project Brain service.

Shared Recommendation Service.

Hardened Calendar time and free-block behavior for Today fields. This trust work can proceed in parallel, but Today should not be marked done while it still reproduces the Calendar regressions owned by Milestone 2.

**Acceptance criteria:**

- Today consumes Project Brain project summaries.
- Today consumes backend recommendation output.
- Today does not independently recompute project next moves.
- Current free block is still represented.
- Next calendar commitment is still represented.
- Remaining-today event logic is preserved.
- Project cards continue linking to Project Workspaces.
- Project status displayed on Today matches Project Brain.
- Canonical project next moves match Project Workspaces.
- Contextual recommendation overrides include a reason.
- Calendar-derived fields satisfy the shared Calendar correctness contract and its regression suite.
- Frontend build passes.

---

## Issue: Move Tasks Recommendation Logic to the Backend

**Status:** Todo

**Priority:** High

**Description:**

Remove the Tasks page as an independent recommendation engine.

The current Tasks frontend contains meaningful ranking logic and local recommendation state.

Future clients should not need to reproduce this TypeScript scoring implementation.

Tasks should render backend-computed recommendations and ranking evidence.

The existing explainable recommendation experience should be preserved.

**Dependencies / blockers:**

Shared Recommendation Service.

**Acceptance criteria:**

- Task ranking is computed by the backend.
- Tasks frontend does not own the canonical scoring algorithm.
- Per-life-area recommendations remain available.
- Recommendation reasons remain visible.
- Ranked alternatives can still be inspected.
- Recommendation refresh remains supported.
- Recommendation change state remains supported where useful.
- Existing ranking signals are either preserved or explicitly superseded.
- iPhone or another future client could consume the same recommendation API without porting frontend ranking code.
- Frontend build passes.

---

## Issue: Ground Chat Project Questions in Project Brain

**Status:** Todo

**Priority:** High

**Description:**

Make Project Brain the first source for project-state questions in Chat.

Project Brain should ground questions such as:

- What's blocking Nebulo?
- What should I work on next for XO?
- What's going on with PCOS?
- Who is involved in this project?

The model should use computed project state before it improvises from raw provider records or generic context.

The model may summarize or explain Project Brain state.

It should not independently invent a competing project interpretation.

**Dependencies / blockers:**

Project Brain service.

Shared Recommendation Service for next-move questions.

**Acceptance criteria:**

- Project-state intents can be identified.
- Canonical project resolution is used.
- Project Brain state is retrieved.
- Blocker questions use Project Brain blockers.
- Next-move questions use canonical project recommendations.
- People questions use Project Brain people/context.
- Unknown project names can trigger classification or clarification.
- Chat does not silently invent project state absent from the computed model.
- Project answers can include the evidence behind recommendations.
- Tests cover PCOS, XO, Nebulo, and Freelance project questions.

---

# 30. Milestone 2 — Calendar Trust and Provider Reliability

**Milestone status:** Near-term

**Purpose:**

Make PCOS trustworthy enough to depend on every day.

Calendar correctness and provider availability are foundational because incorrect time state can invalidate otherwise intelligent recommendations.

---

## Issue: Harden Calendar Time and Free-Block Correctness

**Status:** In Progress

**Priority:** Urgent

**Description:**

Create regression coverage and shared time-normalization behavior for the historical Calendar trust failures.

PCOS has previously:

- shown past free blocks as current;
- described an approaching event as hours away;
- reasoned from incorrect event timing;
- treated the remaining day as more open than it actually was.

Calendar-derived intelligence must use one trustworthy temporal model.

**Current repository audit:**

The current tests already cover past-event filtering, a 45-minute free block, all-day behavior, and timezone-sensitive Calendar cases. Shared normalization across every Today and Chat path is not complete, so the outcome remains in progress rather than done.

**Dependencies / blockers:**

Current Google Calendar integration.

Current Calendar Intelligence.

Coordination with Today consolidation.

**Acceptance criteria:**

- User timezone is applied consistently.
- Current time is represented consistently.
- Event timestamps are normalized before reasoning.
- Past events do not influence remaining-today state as future commitments.
- Past free blocks cannot be returned as the current free block.
- Minutes until next event is correct.
- All-day informational events do not consume the entire day as busy.
- Informational events follow intended blocking rules.
- Tests reproduce and prevent the historical past-free-block failure.
- Tests reproduce and prevent the approaching-event timing failure.
- Today and Chat consume the same normalized time behavior.

---

## Issue: Build In-App Google Calendar Reconnect

**Status:** Todo

**Priority:** High

**Description:**

Replace the developer-oriented Google Calendar token repair workflow with a user-facing reconnect flow.

The current system can detect Calendar health failures but still requires the user to run `backend/scripts/google_oauth_setup.py` and repair local configuration.

The final workflow should begin from PCOS Settings.

**Dependencies / blockers:**

Google OAuth architecture.

Deployment direction may affect redirect URI and credential storage decisions.

**Acceptance criteria:**

- Settings distinguishes disconnected Calendar from an empty Calendar.
- Invalid or revoked credentials produce a reconnect state.
- A Reconnect Google Calendar action exists.
- OAuth can be initiated from the application experience.
- Successful authorization updates the provider connection.
- Provider health is rechecked after reconnect.
- Successful reconnect restores Calendar reads.
- Calendar write capability is verified where required.
- The normal reconnect path does not require Terminal.
- The normal reconnect path does not require manually editing `.env`.
- Secrets are not exposed to the frontend.

---

## Issue: Fix Connected-State Grounding in Calendar Conversations

**Status:** In Progress

**Priority:** High

**Description:**

Prevent Chat from producing generic calendar advice when the connected Calendar contains the answer.

The historical interview response is the canonical failure case.

PCOS told the user to check their schedule for the exact interview time despite already having Calendar access.

The correct behavior is:

- retrieve relevant Calendar state;
- answer from it;
- or explicitly report Calendar unavailability.

**Current repository audit:**

Date-scoped exact event lookup and terse follow-up resolution are implemented and tested. The disconnected-provider distinction and full orchestration guarantee in the acceptance criteria are not complete, so the issue remains in progress.

**Dependencies / blockers:**

Calendar time correctness.

Provider health state.

Agent orchestration cleanup may be required.

**Acceptance criteria:**

- Calendar-related questions retrieve relevant event state.
- Event lookup supports relevant date and title context.
- Follow-up conversation context can preserve the subject of the interaction.
- If Calendar contains the answer, Chat uses it.
- If Calendar is disconnected, Chat states that Calendar is unavailable.
- Chat does not tell the user to manually check Calendar while silently failing to retrieve connected state.
- Tests cover the historical interview-style failure.
- Tests cover disconnected-provider behavior.

---

# 31. Milestone 3 — Linear Project Management Integration

**Milestone status:** Planned next major provider integration

**Purpose:**

Make Linear the deeper project-management source for PCOS, XO, Nebulo, and Freelance while preserving Todoist for lighter execution and personal work.

The first goal is trustworthy read intelligence.

Do not begin by cloning Linear or enabling broad autonomous writes.

---

## Issue: Implement Linear Provider Connection and Read Adapter

**Status:** Done

**Priority:** High

**Description:**

Connect PCOS to Linear and build the initial read-only provider adapter.

The adapter should retrieve the project and issue state needed by Project Brain.

Initial project scope:

- PCOS;
- XO;
- Nebulo;
- Freelance.

The adapter should preserve Linear identity and provider-specific metadata while producing normalized work records for shared intelligence.

**Dependencies / blockers:**

Normalized Work Model.

Canonical Project Registry.

Linear authentication and API access.

**Acceptance criteria:**

- Linear provider connection is configurable.
- Provider health can be checked.
- Linear projects can be read.
- Linear issues can be read.
- Issue status can be read.
- Issue priority can be read.
- Project association can be read.
- Parent-child relationships are preserved where available.
- Dependency or blocker relationships are preserved where available.
- Milestone or equivalent project planning state is read where supported and relevant.
- Update timestamps are preserved.
- Source references or URLs are preserved.
- Linear issues can be converted into normalized work records.
- Read adapter tests exist.
- No broad Linear write automation is introduced in this issue.

---

## Issue: Link Linear Projects to Canonical PCOS Projects

**Status:** Done

**Priority:** High

**Description:**

Map the user's Linear project structure to canonical PCOS projects.

Initial mappings should cover:

- PCOS;
- XO;
- Nebulo;
- Freelance.

Mappings should live in durable project metadata rather than keyword guesses.

**Dependencies / blockers:**

Canonical Project Registry.

Linear read adapter.

**Acceptance criteria:**

- PCOS can store a Linear project mapping.
- XO can store a Linear project mapping.
- Nebulo can store a Linear project mapping.
- Freelance can store a Linear project mapping.
- The registry resolves each Linear UUID to the intended canonical project.
- Renaming a Linear project does not silently create a second PCOS project when provider identity remains stable.
- Missing mappings are diagnosable.
- Provider mappings can be changed without editing backend source code.

Project Brain ingestion was intentionally deferred from SID-134 and is now implemented by SID-135, `Feed Linear Work Into Project Brain`.

---

## Issue: Feed Linear Work Into Project Brain

**Status:** Done

**Priority:** Urgent

**Description:**

Integrate only exact UUID-mapped normalized Linear issue state into Project Brain and expose grounded Project Work Packages.

For Linear-backed projects, Project Brain should understand detailed executable work, hierarchy, status, priorities, blockers, and dependencies from Linear while continuing to combine Calendar, Memory, Activity, and relevant Todoist state.

Each package is backed by a Linear milestone or one unmilestoned fallback issue and provides a bounded current-work choice followed by the next executable action selected by the shared recommendation service.

**Dependencies / blockers:**

Linear Read Adapter.

Linear project mappings.

Normalized Work Model.

Project Brain service.

**Acceptance criteria:**

- PCOS Project Brain includes Linear work.
- XO Project Brain includes Linear work.
- Nebulo Project Brain includes Linear work.
- Freelance Project Brain includes Linear work.
- Linear issue hierarchy is represented.
- Non-executable project containers do not become next moves.
- Completed or canceled issues are excluded from executable recommendations.
- Explicitly blocked issues are not treated as immediately executable.
- Dependency evidence is available to blocker reasoning.
- Todoist work can coexist with Linear work.
- Calendar events continue contributing project context.
- Memory continues contributing project context.
- Activity continues contributing project context.
- Project Workspace identifies work provider where useful.
- Project Brain tests cover mixed Todoist and Linear state.
- Project Work Packages expose at most three deterministic current-work options.
- A package with no open work is not current, and explicitly blocked or container work cannot become its next action.
- Missing mapping, missing key, authentication failure, and provider failure preserve all existing Project Brain sources and return additive diagnostics.
- A&M, Personal, and Needs Classification do not receive invented Linear work.

Grounded project-level blocker interpretation remains deferred to SID-136. SID-135 preserves explicit dependency evidence and executable-state safety but does not infer milestone dependencies or replace the existing blocker presentation model.

---

## Issue: Compute Trustworthy Project Blockers From Linear State

**Status:** Done

**Priority:** High

**Description:**

Evaluate explicit Linear relationships against the blocking issue's normalized workflow state before Project Brain, package, status, and recommendation decisions. Preserve grounded evidence, distinguish active, resolved, and needs-review relationships, and keep heuristic attention signals separate from provider-backed blockers.

**Dependencies / blockers:**

Linear-fed Project Brain.

Shared Recommendation Service.

**Acceptance criteria:**

- Explicit Linear blocked relationships are recognized.
- Completed dependencies release downstream work.
- Canceled, missing, and malformed dependencies require review and remain fail-closed.
- Blocked work is associated with the correct canonical project.
- Project Workspace displays meaningful blockers.
- Blocker evidence identifies the underlying work records.
- Keyword-based attention is distinguishable from explicit provider evidence.
- PCOS does not invent a blocker when evidence is absent.
- Nebulo blocker questions have dedicated tests.

---

## Issue: Add Linear Action Cards and Controlled Write Actions

**Status:** Todo

**Priority:** Medium

**Description:**

After Linear read intelligence is trustworthy, introduce a limited set of explicit Linear write actions through PCOS.

The initial goal is not autonomous project management.

Actions should follow the existing PCOS pattern:

```text
proposal -> structured action -> confirmation when required -> provider execution -> result card -> Activity
```

Potential initial actions include:

- create issue;
- update issue status;
- update issue priority;
- add a clearly specified issue to a mapped project.

Do not introduce large roadmap-generation writes until the normalized provider action architecture is stable.

**Dependencies / blockers:**

Linear read integration proven trustworthy.

Project Brain Linear integration.

Build Typed and Durable Pending Action Architecture.

**Acceptance criteria:**

- Supported Linear actions have typed action schemas.
- Actions validate canonical project/provider mappings.
- Confirmation is required for actions according to established action policy.
- Confirmed actions execute directly.
- Issue creation can be supported.
- Issue status updates can be supported.
- Issue priority updates can be supported.
- Provider errors are surfaced.
- Successful actions render structured result cards.
- Successful actions are recorded in Activity.
- Project Brain reflects updated Linear state after provider refresh.
- Tests cover supported Linear actions.

---

# 32. Milestone 4 — Project Awareness and Change Intelligence

**Milestone status:** Planned

**Purpose:**

Allow PCOS to understand not only current provider state but what meaningfully changed.

This milestone supports repository catch-ups, better Activity, Daily Review, Weekly Review, and proactive project intelligence.

---

## Issue: Define the PCOS Meaningful Activity Model

**Status:** Todo

**Priority:** High

**Description:**

Define which changes deserve durable PCOS Activity records.

Activity should describe meaningful operational history.

It should not become a raw log of every API request, provider read, or UI click.

Meaningful events may include:

- approved PCOS actions;
- project issue completion;
- blocker changes;
- important provider state transitions;
- repository catch-ups;
- reviewed memory changes;
- future email action candidates.

**Dependencies / blockers:**

Project Brain service.

Linear integration will provide important real-world change cases.

**Acceptance criteria:**

- Meaningful activity event categories are defined.
- Activity events can reference canonical projects.
- Activity events can reference provider records.
- Activity payload structure is documented.
- Low-level provider reads are not recorded as user-facing Activity.
- Project Brain can consume project Activity.
- Activity supports future “what changed?” queries.
- Existing Activity records remain readable or receive a migration strategy.

---

## Issue: Build Provider Change Detection Foundation

**Status:** Todo

**Priority:** High

**Description:**

Introduce the infrastructure required to compare meaningful provider state over time.

Current Project Brain computes current state but does not maintain sufficient provider history to reliably answer:

What changed in XO since yesterday?

The system needs durable checkpoints, provider change events, or another explicit change-detection model.

Do not blindly snapshot entire providers without a retention and normalization strategy.

**Dependencies / blockers:**

Meaningful Activity Model.

Normalized Work Model.

Linear integration provides the first target provider.

**Acceptance criteria:**

- A provider change-detection strategy is documented.
- Relevant normalized provider state can be compared over time.
- Newly created work can be detected.
- Status transitions can be detected.
- Priority changes can be detected.
- Blocker changes can be detected where provider data supports them.
- Duplicate change events are avoided.
- Change events can create meaningful Activity records.
- Project Brain can retrieve recent project changes.
- Tests cover duplicate detection and state transitions.

---

## Issue: Build Repository Catch-Up Ingestion Foundation

**Status:** Todo

**Priority:** High

**Description:**

Define the structured format and ingestion boundary PCOS uses for repository catch-ups, including the first Activity and Project Brain wiring.

The user specifically wants scheduled Codex-style “catch me up” analysis across coding repositories.

A catch-up should describe meaningful engineering state rather than paste a raw Git diff into Memory.

The contract should support:

- repository identity;
- canonical project;
- analysis window;
- meaningful completed work;
- current work in progress;
- test or verification state;
- blockers;
- technical debt;
- likely next engineering step;
- relevant commit or source references.

The ingestion architecture should not assume Codex is the only future producer.

**Dependencies / blockers:**

Canonical Project Registry.

Meaningful Activity Model.

Repository mapping design.

**Acceptance criteria:**

- Structured repository catch-up schema exists.
- Catch-ups can map to a canonical project.
- Repository identity is preserved.
- Completed work can be represented.
- Work in progress can be represented.
- Test state can be represented.
- Blockers can be represented.
- Technical debt can be represented.
- Suggested next engineering step can be represented.
- Catch-ups can create meaningful Activity.
- Project Brain can consume the latest relevant catch-up.
- Raw repository analysis is not automatically stored as durable Memory.

---

## Issue: Integrate GitHub Repository State

**Status:** Todo

**Priority:** Medium

**Description:**

Connect repository identity and relevant GitHub state to canonical PCOS projects.

Initial repositories should be linked only where the project relationship is known.

The immediate goal is project awareness, not a GitHub clone.

Relevant state may include:

- repository;
- recent commits;
- branches where relevant;
- pull requests where relevant;
- issues where relevant;
- recent repository activity.

Repository state should support catch-up generation and Project Brain context.

**Dependencies / blockers:**

Canonical Project Registry.

Repository Catch-Up Ingestion Foundation.

Provider/change-detection architecture.

**Acceptance criteria:**

- Repositories can be linked to canonical projects.
- Repository identity uses durable provider IDs where available.
- Recent commit metadata can be retrieved.
- Relevant pull-request state can be retrieved where applicable.
- Project Brain can identify linked repositories.
- Repository state can be passed into the catch-up analysis workflow.
- Provider errors do not break unrelated Project Brain sources.
- Tests cover repository-to-project mapping.

---

## Issue: Schedule Repository Catch-Ups

**Status:** Todo

**Priority:** Medium

**Description:**

Create scheduled execution for repository catch-up generation.

The desired workflow is:

```text
repository state
        ↓
scheduled analysis
        ↓
structured catch-up
        ↓
Activity
        ↓
Project Brain
```

The schedule should avoid generating meaningless updates when a repository has not materially changed.

**Dependencies / blockers:**

Background execution foundation. The catch-up contract and manual ingestion can be built in Milestone 4, but this scheduled-execution issue cannot be completed until the Milestone 6 runtime exists.

GitHub repository integration.

Repository Catch-Up Ingestion Foundation.

Provider change detection.

**Acceptance criteria:**

- Catch-up jobs can run on a schedule.
- Linked repositories can be evaluated.
- Repositories without meaningful changes can be skipped.
- Changed repositories can produce structured catch-ups.
- Failed analysis can be retried safely.
- Duplicate catch-ups are avoided.
- Successful catch-ups create Activity.
- Project Brain exposes relevant catch-up state.
- The user can identify when a catch-up was last generated.

---

# 33. Milestone 5 — Email Intelligence

**Milestone status:** Planned

**Purpose:**

Help the user reliably catch important personal and A&M email without creating another noisy inbox.

Email Intelligence should surface attention and action candidates.

It should not attempt to replace the email client.

---

## Issue: Define Email Attention and Action Candidate Model

**Status:** Todo

**Priority:** High

**Description:**

Define the structured PCOS model for important email.

The system needs to distinguish:

- informational email;
- important attention item;
- deadline;
- explicit action request;
- scheduling request;
- administrative requirement;
- project communication;
- possible task candidate;
- possible calendar candidate.

The model should preserve uncertainty.

PCOS should not convert every email into a task.

**Dependencies / blockers:**

Build Typed and Durable Pending Action Architecture.

Meaningful Activity Model.

**Acceptance criteria:**

- Email attention candidate schema exists.
- Importance can be represented.
- Urgency can be represented.
- Deadline evidence can be represented.
- Requested action can be represented.
- Project association can be represented.
- Task-action proposal can be represented.
- Calendar-action proposal can be represented.
- Uncertainty or confidence can be represented.
- Original email/provider reference is preserved.
- Classification behavior is documented.

---

## Issue: Connect Personal Email

**Status:** Todo

**Priority:** High

**Description:**

Connect the user's personal email account as the first Email Intelligence provider.

The integration should retrieve the message metadata and content required for attention analysis.

The first implementation should prioritize read intelligence over broad email write actions.

**Dependencies / blockers:**

Email Attention Model.

Provider authentication design.

Background execution foundation for proactive monitoring. Initial connection and read validation can proceed before that runtime; continuous monitoring cannot.

**Acceptance criteria:**

- Personal email provider can be connected.
- Provider health can be checked.
- Recent messages can be retrieved.
- Message identity is preserved.
- Thread context can be retrieved where required.
- Sender is preserved.
- Subject is preserved.
- Message time is preserved.
- Relevant body content can be analyzed.
- Provider failures are isolated.
- Email data is not copied into Memory by default.

---

## Issue: Connect A&M Email

**Status:** Todo

**Priority:** High

**Description:**

Connect the user's A&M email account and feed it into the same Email Intelligence model.

Academic and administrative email is a major motivation for the feature.

The system should be particularly capable of identifying:

- registration requirements;
- payment or billing requirements;
- advisor requests;
- forms;
- deadlines;
- class or academic administration;
- required student actions.

**Dependencies / blockers:**

Email Attention Model.

Supported authentication/provider path for the A&M account.

Personal Email integration can establish the provider architecture.

**Acceptance criteria:**

- A&M email can be connected through a supported provider path.
- Provider health can be checked.
- Recent messages can be retrieved.
- Academic and administrative action candidates can be represented.
- Deadlines preserve source evidence.
- Email source is distinguishable from personal email.
- A&M email can feed the shared attention model.
- Provider failures do not break personal email intelligence.

---

## Issue: Build Email Importance and Action Analysis

**Status:** Todo

**Priority:** High

**Description:**

Analyze connected email and identify messages that deserve the user's attention.

The user explicitly wants PCOS to err toward catching messages that are even somewhat important to responsibilities while avoiding a notification for every email.

Analysis should combine deterministic evidence and model interpretation.

Potential deterministic signals include:

- known school domains;
- explicit deadlines;
- action verbs;
- forms;
- payment language;
- registration language;
- scheduling language;
- known project people;
- repeated unread important threads.

Model interpretation may summarize why a message matters.

**Dependencies / blockers:**

Personal Email connection.

A&M Email connection.

Email Attention Model.

**Acceptance criteria:**

- Recent email can be analyzed.
- Important messages produce attention candidates.
- Low-value messages can remain quiet.
- Deadline evidence is preserved.
- Explicit requested actions are represented.
- Known project context can influence association.
- Ambiguous project associations remain unresolved rather than guessed.
- Analysis explains why a message matters.
- Duplicate attention candidates are avoided.
- Tests cover academic administration, scheduling, project communication, and low-value email.

---

## Issue: Surface Email Attention in Today

**Status:** Todo

**Priority:** Medium

**Description:**

Add important email attention to the Today intelligence experience.

Today should not become an inbox.

It should surface only messages that currently deserve action or explicit review.

**Dependencies / blockers:**

Email Importance Analysis.

Today shared-intelligence consolidation.

**Acceptance criteria:**

- Important email attention can appear on Today.
- Email attention explains why the message matters.
- Deadline or urgency is shown where supported.
- The source account is identifiable.
- The user can open or review the source message.
- Task proposals are visually distinct from completed task creation.
- Calendar proposals are visually distinct from completed calendar creation.
- Dismissed or resolved attention does not repeatedly reappear without new evidence.
- Low-value email does not clutter Today.

---

## Issue: Add Email-to-Task and Email-to-Calendar Proposals

**Status:** Todo

**Priority:** Medium

**Description:**

Allow Email Intelligence to propose provider actions from grounded email evidence.

Examples include:

- create a Todoist task for a required form;
- create an appropriate work item where provider policy supports it;
- add a confirmed deadline or appointment to Calendar.

PCOS should propose the action rather than silently execute important changes.

**Dependencies / blockers:**

Email Attention Analysis.

Build Typed and Durable Pending Action Architecture.

Todoist and Calendar actions.

Future Linear actions where relevant.

**Acceptance criteria:**

- Email attention can produce a structured task proposal.
- Email attention can produce a structured calendar proposal.
- Proposed actions preserve source email evidence.
- The user can confirm the action.
- Confirmed actions execute directly.
- Successful actions render structured result cards.
- Successful actions create meaningful Activity.
- Duplicate provider records are avoided where detectable.
- PCOS does not silently create work from uncertain email interpretation.

---

# 34. Milestone 6 — Proactive PCOS Foundation

**Milestone status:** Planned

**Purpose:**

Create the execution infrastructure required for PCOS to monitor systems without the application being manually opened.

This milestone is required for Email Intelligence monitoring, repository catch-ups, Daily Review, Weekly Review, and later life-system modules.

Milestone 6 and the production-architecture design in Milestone 9 are intentionally co-designed. Background job requirements come first; the production design selects the durable worker/runtime architecture; background implementation can then proceed before the full hosted deployment is complete.

---

## Issue: Design and Implement Background Execution

**Status:** Todo

**Priority:** High

**Description:**

Introduce a durable background execution model for PCOS.

The system must support scheduled and recurring work without coupling jobs to a browser page load or one FastAPI request.

The exact infrastructure has not been selected.

The implementation should support:

- scheduled jobs;
- provider polling or future webhook processing;
- durable job state;
- retries;
- deduplication;
- provider failure isolation;
- meaningful Activity creation.

**Dependencies / blockers:**

Documented background requirements and an early Production Deployment Architecture decision for worker runtime, persistence, credentials, and hosting constraints. Full hosted deployment is not a blocker.

Provider jobs should use shared domain services rather than frontend logic.

**Acceptance criteria:**

- Background jobs can execute independently of the frontend.
- Scheduled jobs are supported.
- Job state is durable.
- Failed jobs can retry.
- Retry behavior is bounded.
- Duplicate execution can be detected or safely handled.
- One provider failure does not stop unrelated jobs.
- Job results can create meaningful Activity.
- Job health is diagnosable.
- At least one real PCOS workflow runs through the background system.

---

## Issue: Build Typed and Durable Pending Action Architecture

**Status:** Todo

**Priority:** High

**Description:**

Create one typed provider-action boundary and move critical pending-action and confirmation state out of process-local conversation memory.

The current system mixes arbitrary action dictionaries, selected field-level validators, provider execution branches inside `agent.py`, and a legacy process-global pending action. The target should define action variants, validation, confirmation policy, execution, and result state without requiring each new provider to expand the same orchestration switch indefinitely.

A proposed action should survive:

- backend restart;
- frontend refresh;
- future device switching.

The system should know what was proposed, why it was proposed, whether it was confirmed, whether it executed, and what result occurred.

**Dependencies / blockers:**

Existing direct-confirmation and provider-execution behavior.

Persistence design.

**Acceptance criteria:**

- Pending action variants have typed schemas.
- A shared action registry or equivalent boundary owns validation, confirmation policy, and executor dispatch.
- New provider actions do not require embedding all execution behavior directly in `agent.py`.
- Pending actions have durable IDs.
- Proposed action payload is stored.
- Action reason or evidence can be stored.
- Target provider records can be referenced.
- Confirmation status is stored.
- Execution status is stored.
- Result or failure state is stored.
- Backend restart does not silently erase pending actions.
- Confirmation cannot execute an already-completed action twice.
- Legacy process-global pending state is removed or made unreachable.
- Frontend can retrieve pending action state.
- Tests cover variant validation, executor dispatch, duplicate prevention, and restart-safe action state at the persistence/service level.

---

## Issue: Persist Required Conversation Context

**Status:** Todo

**Priority:** Medium

**Description:**

Replace critical process-local conversation state with durable conversation context where multi-turn action correctness depends on it.

This does not require permanently storing every chat message as Memory.

The goal is to preserve operational context required for reliable follow-ups.

**Dependencies / blockers:**

Build Typed and Durable Pending Action Architecture.

Conversation orchestration must be separable from the action registry; broader agent decomposition is not required for this issue.

**Acceptance criteria:**

- Session conversation context required for follow-up resolution can persist.
- Backend restart does not destroy active operational context.
- Pending action context is linked to the relevant conversation/session.
- Durable conversation context is distinct from long-term Memory.
- Context retention behavior is documented.
- Sensitive provider data is not unnecessarily duplicated.
- Tests cover a multi-turn follow-up after context reload.

---

# 35. Milestone 7 — Daily and Weekly Intelligence

**Milestone status:** Planned

**Purpose:**

Replace the current manual Habits interaction with useful reflection and operational review.

This milestone should use Activity, Calendar, Project Brain, and future observed state.

---

## Issue: Redesign Habits as Health and Daily Review

**Status:** Todo

**Priority:** Medium

**Description:**

Replace the current Habits product experience with the accepted Health and Daily Review direction.

The current Yes/Partial/No tracker is implemented but is not useful enough to the user.

The redesign should focus on:

- what was planned;
- what actually happened;
- what slipped;
- relevant context;
- patterns worth noticing.

The existing habit tables may be reused where appropriate.

Do not preserve the current UI merely because the database already exists.

**Dependencies / blockers:**

Activity foundation.

Project Brain consolidation.

Calendar correctness.

**Acceptance criteria:**

- Product navigation and naming reflect the accepted redesign.
- The redesign defines a first-class Daily Review entry point and product contract; full review behavior belongs to the separate Daily Review V1 issue.
- Planned commitments can be represented.
- Observed completion evidence can be represented where available.
- The user can add context when PCOS cannot know why something happened.
- The experience does not require manually marking every habit Yes/Partial/No.
- Existing habit data receives a preservation or migration strategy.
- Current manual tracker is removed from the primary product experience or clearly superseded.

---

## Issue: Build Daily Review V1

**Status:** Todo

**Priority:** Medium

**Description:**

Generate a grounded daily review from current PCOS state.

Daily Review should compare plan and observed operational state.

Initial sources may include:

- Calendar;
- Todoist;
- Linear;
- Activity;
- Project Brain.

The system should avoid claiming an activity occurred merely because it was scheduled.

**Dependencies / blockers:**

Health and Daily Review redesign.

Linear Project Brain integration.

Meaningful Activity Model.

**Acceptance criteria:**

- Daily Review can identify planned commitments.
- Completed work evidence can be included.
- Slipped or unresolved work can be included.
- Important project changes can be included.
- Calendar events are not automatically treated as proof of real-world completion.
- Uncertain actual-state conclusions are labeled.
- The user can add missing context.
- Review output can create durable insight only through an explicit Memory proposal or other reviewed path.

---

## Issue: Build Weekly Review V1

**Status:** Todo

**Priority:** Low

**Description:**

Create a weekly operational review using Project Brain and meaningful Activity.

The review should help the user understand momentum and neglected areas rather than produce a generic productivity score.

Potential content includes:

- project progress;
- completed work;
- blocker changes;
- inactive projects;
- meaningful calendar patterns;
- important email follow-through;
- repository catch-ups.

Only currently integrated sources should be used.

**Dependencies / blockers:**

Daily Review foundation.

Meaningful Activity.

Provider change detection.

Email and repository state can enrich the feature when available.

**Acceptance criteria:**

- Weekly Review uses a defined time window.
- Project progress can be summarized.
- Completed work can be summarized.
- Blocker changes can be summarized.
- Inactive or neglected projects can be identified using explicit evidence.
- Important unresolved attention can be surfaced.
- Review claims preserve source evidence.
- Missing integrations are not simulated.

---

# 36. Milestone 8 — Memory Intelligence

**Milestone status:** Planned

**Purpose:**

Allow PCOS to improve durable context without turning Memory into an automatic transcript archive.

---

## Issue: Build Memory Inbox

**Status:** Todo

**Priority:** Medium

**Description:**

Allow PCOS to propose durable memories for user review.

The system should identify context that may materially improve future reasoning.

Examples include:

- a new project relationship;
- a stable person/project association;
- a durable preference;
- a repeated pattern;
- an explicit user rule.

The system should not automatically save every conversational detail.

**Dependencies / blockers:**

Current Memory system.

Meaningful Activity may provide additional candidate sources.

**Acceptance criteria:**

- Memory candidates have a structured schema.
- Candidate type is represented.
- Proposed title is represented.
- Proposed content is represented.
- Reason for preserving the memory is represented.
- Confidence is represented.
- Memory Inbox UI exists.
- User can approve a candidate.
- User can edit a candidate before approval.
- User can reject a candidate.
- Approved candidates become durable Memory.
- Rejected candidates do not repeatedly reappear without materially new evidence.
- No candidate becomes durable Memory without the intended review path.

---

# 37. Milestone 9 — Hosted and Multi-Device PCOS

**Milestone status:** Future platform work

**Purpose:**

Move PCOS beyond a Mac-local development stack and establish the backend required by native and proactive surfaces.

Do not treat this as merely “deploy the Next.js app.”

The current backend owns credentials, provider state, SQLite data, conversation state, and actions.

The production architecture must account for those responsibilities.

---

## Issue: Design Production PCOS Deployment Architecture

**Status:** Todo

**Priority:** Medium

**Description:**

Define the production architecture required for a continuously available personal operating system.

The design should account for:

- hosted API;
- durable database;
- provider credentials;
- OAuth;
- background execution;
- authentication;
- iPhone and iPad clients;
- proactive notifications;
- provider webhooks where available.

The existing local stack should remain usable during migration.

**Dependencies / blockers:**

Documented background execution requirements, not a completed background runtime. This design issue selects the worker architecture that Milestone 6 implements.

Durable action requirements.

Google OAuth reconnect design.

**Acceptance criteria:**

- Hosting architecture is documented.
- Backend deployment target is selected.
- Durable database strategy is selected.
- Secret storage strategy is selected.
- User authentication strategy is selected.
- Provider credential storage is defined.
- Background worker architecture is defined.
- Local development workflow is preserved.
- Migration from SQLite-owned state is documented.
- Production architecture does not expose provider secrets to clients.

---

## Issue: Deploy Continuously Available PCOS Backend

**Status:** Todo

**Priority:** Medium

**Description:**

Deploy the PCOS backend and required persistence so intelligence and provider actions are available without manually running `./start.sh` on the user's Mac.

This is a prerequisite for a useful iPhone application and proactive monitoring.

**Dependencies / blockers:**

Production Deployment Architecture.

Database migration strategy.

Authentication.

Background execution architecture.

**Acceptance criteria:**

- Hosted backend is continuously reachable.
- Production authentication is enforced.
- PCOS-owned durable state persists.
- Provider credentials are stored securely.
- Provider health is available.
- Background execution can run.
- Local development can target a local environment.
- Production and local configuration are clearly separated.
- The user no longer needs the Mac development stack running for normal PCOS access.

---

# 38. Milestone 10 — Native Apple Surfaces

**Milestone status:** Future

**Purpose:**

Turn PCOS into the actual cross-device application the user wants after the intelligence backend is continuously available.

The first native surface should consume existing PCOS intelligence.

It should not rebuild Project Brain locally.

---

## Issue: Build Native iPhone PCOS V1

**Status:** Todo

**Priority:** Low

**Description:**

Create the first native iPhone PCOS client.

The visual direction should feel premium, native, calm, and glass-forward.

The initial product should focus on the highest-value mobile PCOS state rather than recreating every web administration page.

Likely initial surfaces include:

- Today;
- attention;
- next commitment;
- current recommendation;
- project next moves;
- action cards;
- Chat.

The exact native technology decision has not been made in the current project history.

**Dependencies / blockers:**

Hosted PCOS backend.

Production authentication.

Shared backend intelligence.

Typed and durable pending-action requirements.

**Acceptance criteria:**

- Native iPhone application exists.
- User can authenticate.
- Today consumes backend intelligence.
- Project state consumes Project Brain.
- Recommendations use backend recommendation evidence.
- Action cards are supported.
- Confirmed actions use durable backend actions.
- Chat can access shared PCOS intelligence.
- The client does not implement a separate recommendation engine.
- Visual design follows the accepted premium native direction.

---

## Issue: Add Widgets and Live Activity Intelligence

**Status:** Todo

**Priority:** Low

**Description:**

Expose selective glanceable PCOS state through appropriate iPhone system surfaces.

Dynamic Island or Live Activities should only be used for state that benefits from persistent temporal visibility.

Potential examples include:

- approaching commitment;
- active focus context;
- relevant travel or preparation window;
- current time-sensitive action.

Do not use Dynamic Island as a general PCOS dashboard.

**Dependencies / blockers:**

Native iPhone application.

Hosted backend.

Notification and push architecture.

Reliable calendar timing.

**Acceptance criteria:**

- Widget use cases are explicitly defined.
- Live Activity use cases are explicitly defined.
- Only time-relevant state is eligible for persistent Live Activity presentation.
- State comes from shared PCOS intelligence.
- Calendar timing is trustworthy.
- Expired state is removed.
- Dynamic Island is not used for static project information merely for visual novelty.

---

## Issue: Extend PCOS to iPad and Mac Native Experiences

**Status:** Todo

**Priority:** Low

**Description:**

Extend the native PCOS experience to iPad and Mac after the iPhone client and shared backend model are proven.

The larger surfaces may support deeper Project Workspace and review interactions.

Do not fork the intelligence architecture by platform.

**Dependencies / blockers:**

Native iPhone architecture.

Hosted backend.

Shared design system direction.

**Acceptance criteria:**

- iPad experience consumes shared backend intelligence.
- Mac experience consumes shared backend intelligence.
- Project Brain is not reimplemented per platform.
- Recommendation logic is not reimplemented per platform.
- Platform-specific UI takes advantage of available screen size.
- Shared action state remains consistent across devices.

---

# 39. Milestone 11 — Future Life-System Modules

**Milestone status:** Future

**Purpose:**

Expand PCOS into additional important life systems only after the shared intelligence and proactive architecture are stable.

These issues represent discussed product directions.

They are not near-term implementation priorities.

---

## Issue: Build Finance Intelligence Foundation

**Status:** Backlog

**Priority:** Low

**Description:**

Introduce financial state as a PCOS life-system module.

The goal is connected financial awareness, not rebuilding a bank.

Discussed state includes:

- spending;
- budgets;
- cash flow;
- balances;
- recurring charges;
- financial obligations.

Potential sources discussed include Bank of America, Webull, and legitimately accessible Apple Card data.

Account ownership and access boundaries must be preserved.

**Dependencies / blockers:**

Hosted secure backend.

Production authentication.

Secure provider credential architecture.

Background monitoring.

Financial provider feasibility and supported APIs.

**Acceptance criteria:**

- Financial domain boundaries are documented.
- Supported providers are selected based on legitimate API access.
- Account ownership metadata is preserved.
- Balances can be represented.
- Transactions can be represented.
- Recurring charges can be represented.
- Cash-flow state can be computed from supported records.
- PCOS does not claim ownership of accounts the user does not own.
- Financial data is protected appropriately.
- Finance state can feed shared attention intelligence without exposing raw data unnecessarily.

---

## Issue: Build Investing Intelligence Foundation

**Status:** Backlog

**Priority:** Low

**Description:**

Build an investing research and decision-support module.

The product should help the user become a better investor.

It should not present itself as a guaranteed stock picker.

Discussed capabilities include:

- portfolio tracking;
- allocation analysis;
- company research;
- watchlists;
- earnings summaries;
- company comparison;
- valuation models;
- backtesting;
- investment journal;
- AI-generated research reports;
- risk analysis;
- position sizing;
- rebalancing suggestions.

**Dependencies / blockers:**

Finance/security architecture.

Supported brokerage and market-data providers.

Hosted backend.

**Acceptance criteria:**

- Portfolio holdings can be represented from supported sources.
- Allocation can be computed.
- Concentration can be analyzed.
- Company research can preserve source evidence.
- Watchlists can be represented.
- Earnings context can be surfaced.
- Investment notes or journal state can be preserved.
- Recommendations distinguish analysis from guaranteed outcomes.
- PCOS can explain portfolio observations using the user's actual connected state where available.

---

## Issue: Build Vehicle Maintenance Intelligence

**Status:** Backlog

**Priority:** Low

**Description:**

Create a vehicle-maintenance model so PCOS can remember service state and upcoming maintenance.

The initial discussed maintenance schedule includes:

- oil approximately every 5,000 miles;
- tire rotation approximately every 5,000 miles;
- engine air filter approximately every 20,000–30,000 miles;
- cabin filter yearly;
- transmission drain/fill approximately every 50,000–60,000 miles;
- brake fluid approximately every three years;
- coolant around 100,000 miles;
- spark plugs around 120,000 miles.

These intervals should be treated as configurable maintenance rules rather than immutable universal facts.

**Dependencies / blockers:**

Asset domain design.

Attention engine.

Mileage source can initially be manual.

**Acceptance criteria:**

- Vehicle identity can be stored.
- Current mileage can be stored.
- Service history can be stored.
- Mileage-based maintenance rules can be represented.
- Time-based maintenance rules can be represented.
- Next service threshold can be computed.
- Upcoming maintenance can create attention.
- Maintenance intervals can be edited.
- Completed service updates future thresholds.

---

## Issue: Investigate Automatic Vehicle Mileage Ingestion

**Status:** Backlog

**Priority:** Low

**Description:**

Investigate automatic mileage ingestion for Vehicle Maintenance Intelligence.

An OBD-II-based source was discussed as technically plausible.

The purpose is to remove manual mileage remembering.

This issue is an investigation and architecture decision before hardware implementation.

**Dependencies / blockers:**

Vehicle Maintenance Intelligence.

Hardware and vehicle compatibility research.

**Acceptance criteria:**

- OBD-II mileage-access feasibility is documented for the user's vehicle context.
- Candidate hardware approaches are identified.
- Data transport options are compared.
- Power and always-connected behavior are considered.
- Privacy and security implications are documented.
- Cost is estimated.
- A recommended approach or explicit no-build decision is recorded.
- No custom hardware is built solely to satisfy this investigation issue.

---

## Issue: Build Health Data Integration

**Status:** Backlog

**Priority:** Low

**Description:**

Connect automatic health and activity context to the Health and Daily Review experience.

Apple Health and Apple Watch were discussed as likely future sources.

The purpose is to reduce manual tracking and improve planned-versus-actual understanding.

**Dependencies / blockers:**

Native Apple client.

Health and Daily Review redesign.

Health data permissions and privacy architecture.

**Acceptance criteria:**

- Health data use cases are explicitly defined.
- Required HealthKit data types are identified.
- User permission boundaries are preserved.
- Relevant observed activity can contribute to Daily Review.
- PCOS distinguishes observed health data from inferred behavior.
- Health data is not used to generate unsupported conclusions.

---

## Issue: Build Smart Mirror PCOS Surface

**Status:** Backlog

**Priority:** Low

**Description:**

Create an ambient PCOS surface for a smart mirror.

The mirror should display glanceable current state such as:

- walk time to class;
- drive time to class;
- upcoming events;
- travel time home;
- other immediately relevant daily context.

The mirror is a presentation surface.

It should not implement independent PCOS reasoning.

**Dependencies / blockers:**

Hosted backend.

Reliable Today intelligence.

Travel-time data source.

Ambient-display hardware decision.

**Acceptance criteria:**

- Mirror consumes shared PCOS backend state.
- Upcoming commitments can be displayed.
- Relevant travel time can be displayed.
- Display state is glanceable.
- Stale state is identifiable or removed.
- No recommendation logic is implemented only in the mirror client.

---

## Issue: Explore Vision Pro PCOS Surface

**Status:** Backlog

**Priority:** Low

**Description:**

Explore a Vision Pro PCOS experience after shared native and hosted architecture exists.

The product should take advantage of spatial presentation only where it improves the PCOS experience.

Vision Pro should consume the same Project Brain and Today intelligence as every other client.

**Dependencies / blockers:**

Hosted backend.

Shared native architecture.

Stable PCOS intelligence APIs.

**Acceptance criteria:**

- Spatial PCOS use cases are documented.
- Use cases are evaluated against ordinary Mac or iPad presentation.
- A visionOS surface consumes shared backend intelligence.
- Project Brain is not reimplemented for visionOS.
- The feature proceeds only where spatial presentation creates meaningful value.

---

# 40. Recommended Active Linear Milestones

If this roadmap is imported into Linear now, the recommended active milestone order is:

1. Canonical Project Intelligence
2. Calendar Trust and Provider Reliability
3. Linear Project Management Integration
4. Project Awareness and Change Intelligence
5. Email Intelligence
6. Proactive PCOS Foundation
7. Daily and Weekly Intelligence
8. Memory Intelligence
9. Hosted and Multi-Device PCOS
10. Native Apple Surfaces
11. Future Life-System Modules

Milestones 0 and the completed issues within it should be treated as historical completed work.

The numbered milestones are capability lanes, not a requirement that every issue in an earlier milestone close before later design begins. Issue-level dependencies are authoritative. In particular, repository ingestion can begin in Milestone 4 while scheduled catch-ups wait for Milestone 6 background execution, and production/runtime architecture is co-designed before full Milestone 9 deployment.

The practical immediate sequence is narrower than the complete roadmap.

The first active issues should be:

1. Extract Project Brain Into a Dedicated Backend Service.
2. Create a Durable Canonical Project Registry.
3. Define the Normalized Work Model alongside the registry contract.
4. Build Shared Recommendation Service.
5. In parallel, Harden Calendar Time and Free-Block Correctness.
6. In parallel, Fix Connected-State Grounding in Calendar Conversations.
7. Make Today a Projection of Shared Intelligence.
8. Move Tasks Recommendation Logic to the Backend.
9. Ground Chat Project Questions in Project Brain.
10. Implement Linear Provider Connection and Read Adapter.
11. Link Linear Projects to Canonical PCOS Projects.
12. Feed Linear Work Into Project Brain.
13. Compute Trustworthy Project Blockers From Linear State.

This sequence intentionally delays broad feature expansion.

PCOS already has enough product surface to demonstrate the vision.

The current constraint is that its intelligence is distributed across overlapping implementations.

The highest-leverage work is to create one trustworthy project and recommendation model, then prove that architecture by adding Linear as the second work provider.

Once PCOS can combine Todoist, Linear, Calendar, Memory, and Activity into a coherent answer to:

> What's blocking Nebulo, and what should I do next?

That capability will move the architecture substantially closer to the Personal Chief of Staff product described in this handoff.

# 41. Engineering Runbook and Continuation Guide

This section exists so a new engineer, ChatGPT Work conversation, or Codex session can continue PCOS without reconstructing the development environment or repeating completed investigation.

It should be read after the product and architecture sections of this handoff.

The current repository is an active local-development application.

Do not assume the product vision described earlier is already implemented.

Use the implementation-status language in this handoff and verify repository state before making architectural changes.

---

# 42. Repository and Product Identity

The current repository is `ai-todoist-agent`.

The repository name reflects the project's original scope.

The product is now Personal Chief of Staff, or PCOS.

Do not interpret the repository name as the current product boundary.

PCOS is no longer intended to be only a Todoist agent.

The current accepted product model is:

```text
connected providers
        ↓
PCOS intelligence
        ↓
shared project and life context
        ↓
recommendations and attention
        ↓
approved provider actions
        ↓
multiple application surfaces
```

The immediate engineering direction is to consolidate Project Brain and recommendation intelligence, then integrate Linear as the deeper project-management provider.

---

# 43. Local Repository Location

The repository has been developed locally at:

`/Users/siddanthraja/Desktop/ai-todoist-agent`

Important paths are relative to that repository root unless otherwise stated.

Backend:

`backend/`

Frontend:

`frontend/`

Canonical handoff:

`docs/PCOS-handoff.md`

Current product specifications:

```text
docs/product-spec.md
docs/product-spec-v2.md
```

The canonical handoff should be treated as the latest cross-project reference when older product specifications conflict with a later decision explicitly documented here.

Do not delete older specifications merely because they contain superseded direction.

They remain useful development history.

---

# 44. Local Startup

The preferred current startup path is from the repository root:

```bash
cd /Users/siddanthraja/Desktop/ai-todoist-agent
./start.sh
```

The local application should then be available at:

`http://localhost:3010`

The backend should be available at:

`http://127.0.0.1:8000`

The backend health route is:

`http://127.0.0.1:8000/health`

The frontend intentionally uses port `3010` rather than port 3000.

This change was made because other projects frequently use port 3000 and caused local-development conflicts.

Do not casually move PCOS back to port 3000 without a specific reason.

---

# 45. Local Shutdown

From the repository root:

```bash
./stop.sh
```

The startup and shutdown scripts use runtime state under:

`.run/`

The `.run` directory is local runtime infrastructure.

It should not be treated as product state.

If the application behaves unexpectedly after build or development-server changes, verify that an old process is not still serving the application.

A previous `/projects` styling failure was caused by a stale Next.js development server remaining bound to port 3010 while `.next` had been regenerated by a separate build.

The symptom was:

- `/projects` appeared without expected application styling;
- the route appeared broken despite the source importing the correct CSS and using the correct layout.

The root cause was not missing Tailwind configuration or a missing CSS import.

The stale development server had to be stopped and the application cleanly restarted.

Before rewriting frontend layout or Tailwind configuration for a similar symptom:

1. Inspect running frontend processes.
2. Stop the current PCOS stack.
3. Cleanly restart the development server.
4. Verify the route response and loaded CSS asset.

Do not repeat the earlier investigation from zero unless the clean restart fails.

---

# 46. Backend Environment

Backend configuration is loaded through:

`backend/.env`

The repository contains configuration support for:

```text
TODOIST_API_TOKEN
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
GOOGLE_REFRESH_TOKEN
GOOGLE_CALENDAR_ID
USER_TIMEZONE
TIMEZONE
OPENAI_API_KEY
OPENAI_MODEL
AGENT_API_KEY
APP_DB_PATH
APP_DATABASE_PATH
```

Exact environment variable naming should always be verified against `backend/app/config.py` before adding new configuration.

Do not copy secrets into:

- this handoff;
- Linear issues;
- GitHub issues;
- commit messages;
- frontend source;
- screenshots;
- ChatGPT prompts intended as durable documentation.

No API key or OAuth token value is intentionally recorded in this document.

The configured OpenAI API key was previously replaced with a key associated with the intended paid OpenAI account.

The new chat or engineer does not need to repeat that migration unless provider health indicates OpenAI is failing.

---

# 47. Frontend Connection Configuration

The current frontend stores local connection settings in browser `localStorage`.

The keys are:

```text
pcos.backendUrl
pcos.apiKey
```

The default backend URL is:

`http://127.0.0.1:8000`

The frontend API wrapper is:

`frontend/src/lib/api.ts`

Frontend settings persistence is implemented in:

`frontend/src/lib/settings.ts`

The Settings UI is implemented through:

```text
frontend/src/app/settings/page.tsx
frontend/src/components/settings-panel.tsx
```

If protected API requests fail while `/health` succeeds:

1. Inspect Settings.
2. Verify the frontend backend URL.
3. Verify that a PCOS API key is saved.
4. Check `/settings/health`.
5. Distinguish an application authentication failure from a provider failure.

Do not immediately regenerate Todoist, Google, or OpenAI credentials merely because the frontend cannot call a protected PCOS endpoint.

---

# 48. Google Calendar OAuth Recovery

Google Calendar has historically been the most operationally fragile provider.

The confirmed failure pattern has included `RefreshError: invalid_grant` and `Token has been expired or revoked.`

The repository contains:

```text
backend/scripts/debug_google_auth.py
backend/scripts/google_oauth_setup.py
```

The diagnostic script should be used to distinguish:

- missing configuration;
- refresh-token failure;
- Calendar read failure;
- missing write scope;
- Calendar permission problems.

The current developer recovery workflow uses:

```bash
cd /Users/siddanthraja/Desktop/ai-todoist-agent
backend/.venv/bin/python backend/scripts/debug_google_auth.py
```

If the configured refresh token is invalid, the current local OAuth setup utility is:

```bash
backend/.venv/bin/python backend/scripts/google_oauth_setup.py
```

Follow the script's OAuth flow and update the local backend environment with the resulting credential state as required by the current script.

Then restart PCOS and verify provider health.

Do not place the generated refresh token in this document.

This workflow is current developer plumbing.

It is not the accepted final product experience.

The roadmap explicitly includes an in-app Google Calendar reconnect flow.

Do not spend time polishing Terminal instructions as though they are the final Calendar UX.

---

# 49. Backend Verification

The current backend test suite lives under:

`backend/tests/`

Important test modules include:

```text
backend/tests/test_agent_examples.py
backend/tests/test_app_surfaces.py
backend/tests/test_calendar_intelligence.py
```

The standard backend verification command is:

```bash
backend/.venv/bin/python -m unittest discover backend/tests
```

The latest recorded development checkpoint in this handoff reached:

`86 tests passing`

That number is a historical checkpoint.

It is not a permanent expected test count.

A future engineer should use the current repository's actual test count as the source of truth.

The important requirement is:

`all current backend tests pass`

Do not delete tests merely to restore the historical count of 86.

When changing Project Brain, recommendation logic, Calendar behavior, classification, provider actions, or conversation state, add regression tests for the intended behavior.

---

# 50. Frontend Verification

The standard frontend production-build verification is:

```bash
cd frontend
npm run build
```

The build should complete successfully.

The current frontend uses:

```text
Next.js App Router
React 19
TypeScript
Tailwind CSS 3
```

When changing frontend API contracts, verify both:

```bash
backend/.venv/bin/python -m unittest discover backend/tests
cd frontend
npm run build
```

Do not assume TypeScript build success proves backend compatibility.

Do not assume backend tests prove frontend API typing remains correct.

Both should be verified for cross-surface changes.

---

# 51. Diff Verification

The project has also used `git diff --check` as a final repository hygiene check.

The expected result is a clean command with no whitespace errors.

A normal engineering verification pass should therefore include:

```bash
backend/.venv/bin/python -m unittest discover backend/tests
cd frontend && npm run build
cd ..
git diff --check
```

If the local application behavior itself changed, also run `./start.sh` and verify `GET /health` plus the affected frontend route.

Do not report a feature as verified solely because code was written.

The development history consistently records test and build verification.

Continue that practice.

---

# 52. Current Important Backend Files

Before modifying PCOS architecture, inspect the following files.

## 52.1 Application and Project Brain

`backend/app/main.py`

Current responsibilities include:

- FastAPI application setup;
- API schemas;
- provider health;
- Today;
- Project Brain response schemas and HTTP route adapters;
- memory routes;
- habits routes;
- tasks routes;
- calendar routes;
- activity routes.

`backend/app/project_brain.py`

Current responsibilities include:

- consuming canonical project registry snapshots;
- Todoist, Calendar, Memory, and Activity aggregation;
- project classification and Needs Classification diagnostics;
- parent-child hierarchy and container handling;
- project blockers and status;
- project next recommendations.

`backend/app/project_registry.py`

Current responsibilities include:

- materializing enabled SQLite project records for Project Brain;
- resolving stable keys and aliases;
- translating stored classification hints into Project Brain definitions;
- synthesizing Needs Classification as a system state;
- exposing durable project IDs and provider mappings without changing API contracts.

`backend/app/work_domain.py`

Current responsibilities include:

- typed normalized work, dependency, status, and priority models;
- provider-neutral hierarchy, container, executable, and blocked fields;
- execution-state invariants;
- narrow legacy projection for existing Project Brain consumers.

`backend/app/todoist_work_adapter.py`

Current responsibilities include:

- converting normalized Todoist provider records into typed work;
- applying the documented higher-is-more-important priority scale;
- preserving original Todoist priority and provider metadata;
- resolving canonical project IDs through registry provider mappings;
- computing parent/container/executable state across the Todoist batch;
- leaving explicit dependencies and blocked state empty when Todoist supplies none.

`backend/app/recommendation_service.py`

Current responsibilities include:

- typed recommendation purpose, action, identity, context, evidence, alternative, and result models;
- canonical project-next-move and context-aware current-action computation;
- deterministic normalized priority, due urgency, task age, foundation, momentum, free-block, energy, and commitment scoring;
- executable/container/completed/canceled/blocked filtering;
- explicit blocker-resolution recommendations;
- stable provider-neutral tie-breaking.

`main.py` remains an architecture-consolidation target for responsibilities outside Project Brain.

Do not continue adding major intelligence subsystems directly to `main.py` without considering the Project Brain service roadmap.

## 52.2 Agent and Action Orchestration

`backend/app/agent.py`

Current responsibilities include:

- chat;
- deterministic capture;
- OpenAI structured interpretation;
- conversation state;
- project and entity resolution;
- memory context;
- Todoist actions;
- Calendar actions;
- confirmation;
- bulk actions;
- action execution;
- response formatting.

This module is approximately 3,500 lines at the audited checkpoint.

It is a technical-debt hotspot.

Do not add Linear, Email Intelligence, GitHub catch-ups, finance, and every future provider directly into this file as another collection of conditional branches.

Preserve existing behavior while extracting clear service and provider boundaries.

## 52.3 Planner

`backend/app/planner.py`

Contains current backend task enrichment and ranking behavior.

Audit this file before implementing the Shared Recommendation Service.

Do not rewrite recommendation ranking without identifying which current signals and tests depend on it.

## 52.4 Todoist Provider

`backend/app/todoist_tools.py`

Contains current Todoist reads, writes, sections, aliases, life-area resolution, parent lookup, and bulk subtask behavior.

This is the primary reference for building a provider-adapter pattern.

Do not make the normalized work model a renamed Todoist task model.

Linear semantics will differ.

## 52.5 Google Calendar Provider

`backend/app/calendar_tools.py`

Contains Google OAuth construction, Calendar API access, event normalization, event creation, event updates, and Calendar category behavior.

Time normalization and blocking behavior should remain centralized.

## 52.6 Calendar Intelligence

`backend/app/calendar_intelligence.py`

Contains deterministic conflict and buffer analysis.

Do not duplicate Calendar Intelligence logic inside Chat prompts or frontend components.

## 52.7 Storage

`backend/app/storage.py`

Contains current direct SQLite persistence.

Current tables include:

```text
memory_entries
habit_definitions
habit_checkins
activity_logs
canonical_projects
canonical_project_aliases
canonical_project_classification_hints
canonical_project_provider_mappings
```

Future actions, conversation state, job state, normalized work, and change intelligence will require additional persistence work.

Do not silently add unrelated columns to Memory as a substitute for designing the correct domain model.

---

# 53. Current Important Frontend Files

## 53.1 Shared Application Shell

`frontend/src/components/app-shell.tsx`

Owns current navigation and viewport behavior.

Chat intentionally uses different overflow behavior from normal pages.

## 53.2 Chat

`frontend/src/components/chat-panel.tsx`

Contains significant action-specific rendering and confirmation behavior.

This file is already large.

Future Linear and Email action cards should preferably move toward reusable action-card components rather than continuing to expand one monolithic Chat component.

## 53.3 Today

`frontend/src/app/today/page.tsx`

Current Today surface.

The roadmap intends to make this a projection of shared backend intelligence.

Do not add another independent recommendation algorithm here.

## 53.4 Projects

```text
frontend/src/app/projects/page.tsx
frontend/src/app/projects/[projectKey]/page.tsx
```

Current Project Brain application surfaces.

These are the primary frontend consumers of project intelligence.

## 53.5 Tasks

`frontend/src/app/tasks/page.tsx`

Contains current frontend-side explainable recommendation ranking.

This behavior is completed history but is now an architecture migration target.

Before removing the ranking implementation:

1. Understand its ranking signals.
2. Preserve the useful explanation experience.
3. Implement equivalent or explicitly superseding backend behavior.
4. Switch the frontend to the shared backend contract.
5. Remove the duplicated frontend scoring path.

Do not simply delete the current recommendation UI because the architecture is being centralized.

## 53.6 Calendar

`frontend/src/app/calendar/page.tsx`

Current Calendar V1.

Consumes real normalized Google Calendar data.

## 53.7 Memory

`frontend/src/app/memory/page.tsx`

Current Memory Center.

## 53.8 Habits

`frontend/src/app/habits/page.tsx`

Current manual Yes/Partial/No tracker.

The product direction is superseded.

Do not invest significant design work into polishing the existing tracker before the Health and Daily Review redesign.

## 53.9 API Wrapper

`frontend/src/lib/api.ts`

Inspect this file whenever backend response contracts change.

---

# 54. Current Known Product and Engineering Risks

The following risks should remain visible during implementation.

## 54.1 Calendar Correctness

Calendar errors have directly damaged trust.

Any feature using current time, free blocks, next events, preparation windows, or scheduling should receive explicit regression coverage.

## 54.2 Recommendation Fragmentation

Today, Project Brain, backend planner logic, and Tasks frontend logic currently overlap.

Adding another recommendation path is a regression in architecture even if the isolated feature appears intelligent.

## 54.3 Provider Coupling

Todoist assumptions remain deeply represented in current code.

Linear integration should validate the normalized work architecture rather than adding `if provider == "linear"` throughout unrelated application logic.

## 54.4 Agent Growth

`agent.py` is already too large.

Future provider actions should move toward typed action schemas, provider executors, and shared orchestration.

## 54.5 Process-local State

Conversation and pending-action behavior currently includes process-local state.

This will not support a continuously available multi-device PCOS.

## 54.6 Local-only Runtime

PCOS currently depends on the user's Mac development stack.

Proactive email monitoring, scheduled repository catch-ups, native iPhone use, and Live Activities require a hosted execution model.

## 54.7 Overbuilding the Future

Finance, investing, OBD-II hardware, smart mirror, Vision Pro, and native Apple surfaces are exciting product directions.

They are not the current architecture bottleneck.

The current highest-value problem is one trustworthy intelligence model, followed by Linear as the second work provider.

Do not use future-product excitement to avoid the harder consolidation work.

---

# 55. Decisions That Must Not Be Accidentally Reversed

The following decisions represent the latest accepted direction.

A future engineer or ChatGPT conversation should not silently return to an older model.

## 55.1 Deep Project Management Belongs in Linear

Superseded direction:

```text
large Todoist parent tasks
        ↓
many detailed project subtasks
```

Latest direction:

```text
Linear
    deeper project planning
    issues
    blockers
    milestones
    implementation detail

Todoist
    lightweight execution
    reminders
    personal tasks

PCOS
    understands and coordinates both
```

The existing bulk Todoist roadmap feature remains implemented history.

It is not the target architecture for detailed software-project planning.

## 55.2 Project Brain Should Become Canonical Project Intelligence

Do not create separate project-state logic for Today, Chat, native iPhone, email, or future surfaces.

They should consume shared project state.

## 55.3 Chat Is an Interface, Not the Product

Do not hide every new feature behind natural-language commands.

Important state needs durable visual surfaces.

## 55.4 Confirmation Should Execute Actions Directly

Do not return to:

```text
button
    ↓
synthetic "yes" chat message
    ↓
LLM reinterprets conversation
```

Use:

```text
button
    ↓
typed pending action
    ↓
direct confirmation endpoint
    ↓
provider execution
```

## 55.5 Recommendations Must Be Explainable

Do not replace deterministic and structured ranking evidence with:

`the model thought this task seemed best`

The model may assist interpretation.

The application should preserve evidence.

## 55.6 Unknown Classifications Should Remain Unknown

DDN established this principle.

If PCOS cannot confidently map work to a project, use Needs Classification or request clarification.

Do not confidently route ambiguous work to the wrong project merely to avoid an unresolved state.

## 55.7 Habits Is Being Redesigned

Do not assume the current Yes/Partial/No tracker is the desired long-term product.

The accepted direction is Health and Daily Review.

## 55.8 Finance Is Not the Immediate Next Feature

Finance and investing are accepted future modules.

They should be architected as connected PCOS life systems when the foundation is ready.

They are not the current implementation priority.

## 55.9 Native Clients Should Not Own Intelligence

iPhone, iPad, Mac, Vision Pro, smart mirror, widgets, and Live Activities should consume PCOS intelligence.

Do not port recommendation algorithms into every client.

---

# 56. Recommended First Work Session for a New Chat or Engineer

The next development conversation should not begin by brainstorming PCOS from zero.

The product direction is already documented.

The first session should inspect current repository state and begin Milestone 1.

Recommended workflow:

1. Read this handoff.
2. Inspect current git status.
3. Inspect recent commits.
4. Run the backend test suite.
5. Run the frontend build.
6. Inspect `backend/app/main.py`.
7. Locate current Project Brain aggregation.
8. Inspect `backend/app/planner.py`.
9. Inspect recommendation logic in `frontend/src/app/tasks/page.tsx`.
10. Identify current API contracts used by Today, Projects, and Tasks.
11. Propose the smallest safe extraction plan for Project Brain.
12. Implement `Extract Project Brain Into a Dedicated Backend Service`.
13. Preserve current behavior.
14. Add service-level tests.
15. Run full verification.
16. Record the completed work in Linear.

The first implementation should be a refactor with behavior preservation.

Do not combine the initial Project Brain extraction with:

- Linear integration;
- a database migration;
- a new recommendation algorithm;
- frontend redesign;
- agent decomposition;
- Calendar rewrites.

Those changes may all become relevant.

Combining them in one first implementation would make regressions difficult to isolate.

---

# 57. Suggested First Codex Instruction

A useful initial Codex instruction is:

```text
Read docs/PCOS-handoff.md as the canonical product and engineering reference.

We are beginning Milestone 1: Canonical Project Intelligence.

First inspect the current repository and establish the exact implementation state. Run the backend tests, frontend build, and git diff check before editing.

Then inspect backend/app/main.py and identify all code that currently defines project identities, classifies work into projects, aggregates Project Brain state, computes project blockers, builds task hierarchy, and selects project next recommendations.

Implement the Linear issue "Extract Project Brain Into a Dedicated Backend Service."

This is a behavior-preserving refactor. Do not add Linear yet. Do not redesign the frontend. Do not change the current project API contract unless a change is strictly required and explained first. Preserve Needs Classification, classification diagnostics, Todoist parent-child hierarchy, parent-container behavior, blockers, people, memories, upcoming events, recent activity, and current next-recommendation behavior.

Create a dedicated backend Project Brain module or service with a clear responsibility boundary. main.py should call the service rather than own the aggregation implementation.

Add focused service-level tests for Project Brain behavior.

After implementation run:
backend/.venv/bin/python -m unittest discover backend/tests
cd frontend && npm run build
cd ..
git diff --check

Report:
1. what moved,
2. what behavior was preserved,
3. files changed,
4. tests added,
5. exact verification results,
6. any architecture concerns discovered but intentionally not changed.
```

This instruction is intentionally narrow.

The first task is to establish a clean Project Brain boundary.

Do not ask Codex to “implement the whole roadmap.”

---

# 58. Suggested New ChatGPT Work Continuation Prompt

The following prompt can be used when continuing PCOS in a new ChatGPT Work conversation:

```text
We are continuing development of my Personal Chief of Staff project, PCOS.

The repository contains docs/PCOS-handoff.md.

Treat that file as the canonical engineering, product, architecture, integration-status, and roadmap reference for this project.

Read the entire handoff before recommending implementation work.

Important:
- Do not reconstruct the product vision from scratch.
- Do not assume planned or future features are implemented.
- Preserve the status language in the handoff.
- Preserve latest decisions when earlier directions were superseded.
- Deep project management is moving to Linear.
- Todoist remains a lighter task/execution provider.
- Project Brain is the accepted canonical project-intelligence direction.
- Today, Tasks, Chat, and future clients should consume shared backend intelligence.
- Recommendation logic is currently fragmented and must be consolidated.
- Calendar correctness is a trust-critical concern.
- DDN must remain unresolved unless explicit evidence classifies it.
- The current Habits product direction is superseded by Health and Daily Review.
- Finance, investing, vehicle intelligence, smart mirror, and native Apple surfaces are real future directions but are not the immediate architecture priority.

Before editing code:
1. Inspect the repository.
2. Inspect git status and recent work.
3. Run current verification.
4. Compare actual repository state against the handoff.
5. Explicitly call out any stale handoff detail.

We are beginning with the active Linear roadmap in the handoff.

Help me continue from the highest-priority unfinished issue rather than repeating completed work.
```

---

# 59. How to Update This Handoff

This document is intended to remain canonical.

It should evolve with the project.

After a meaningful milestone or architecture decision:

1. Update the implementation status.
2. Move completed work into completed history where appropriate.
3. Update integration status.
4. Update current architecture if code boundaries changed.
5. Update known bugs and technical debt.
6. Mark superseded decisions explicitly.
7. Update the Linear roadmap issue status.
8. Record verification results where meaningful.

Do not rewrite the entire handoff after every commit.

The document should track meaningful product and engineering state.

Examples of changes that should update the handoff:

- Project Brain is extracted into a dedicated service.
- The normalized work model becomes real.
- Linear is connected.
- Today begins consuming shared intelligence.
- Frontend recommendation scoring is removed.
- Google Calendar reconnect becomes in-app.
- Background execution is introduced.
- Email Intelligence becomes implemented.
- The backend is hosted.
- A native iPhone client begins development.

Examples of changes that usually do not require handoff updates:

- a small CSS adjustment;
- a typo fix;
- renaming a local variable;
- adding one isolated unit test;
- minor copy changes.

The handoff should describe the state another engineer needs to continue the project.

---

# 60. Definition of a Completed PCOS Issue

A Linear issue should not be marked Done merely because code was generated.

For engineering issues, Done should generally mean:

- intended behavior is implemented;
- acceptance criteria are satisfied;
- relevant tests exist;
- current backend tests pass;
- frontend build passes when frontend or API contracts are affected;
- `git diff --check` passes;
- affected runtime behavior is smoke-tested when appropriate;
- known limitations discovered during implementation are recorded;
- the handoff is updated if project state materially changed.

For provider integrations, Done should additionally mean:

- provider health can be diagnosed;
- provider failure does not silently produce fake or stale intelligence;
- source identity is preserved;
- PCOS can distinguish unavailable data from empty data.

For intelligence features, Done should additionally mean:

- output is grounded in available state;
- evidence or reasoning can be explained;
- uncertainty is preserved;
- the feature does not create a second competing intelligence path.

For action features, Done should additionally mean:

- action schema is structured;
- action is validated;
- confirmation policy is explicit;
- provider execution is observable;
- success and failure are surfaced;
- duplicate execution is considered;
- meaningful execution is recorded in Activity where appropriate.

---

# 61. Final Current-State Summary

At the canonical handoff point, PCOS is a functioning local web application with a real backend and real provider integrations.

Implemented systems include:

- FastAPI backend;
- Next.js frontend;
- Todoist read and write integration;
- Google Calendar read and write integration;
- OpenAI-assisted natural-language interpretation;
- deterministic action and routing logic;
- durable SQLite Memory;
- Activity foundation;
- current habit infrastructure;
- task enrichment and ranking;
- explainable task recommendations;
- Calendar Intelligence;
- direct confirmation execution;
- bulk Todoist roadmap actions;
- Today;
- Projects;
- Project Brain V1;
- dedicated Project Brain service;
- durable canonical project registry;
- typed normalized work model and Todoist adapter;
- Chat;
- Calendar V1;
- Tasks V1;
- Habits;
- Memory Center;
- Settings and provider health diagnostics;
- Linear read provider and normalized adapter;
- durable Linear project-to-canonical-project mappings;
- mapped Linear Project Brain ingestion and Project Work Packages;
- local startup and shutdown scripts.

“Implemented” in this inventory means the subsystem exists; it does not erase the audit limitations documented earlier. In particular, confirmation still has a legacy process-global path, Calendar Intelligence coordination is incomplete, Today provider state does not auto-refresh after mount, Tasks' age signal is disconnected, priority semantics are inconsistent, DDN capture can still be misclassified, Activity coverage is selective, cross-origin Memory/Habits mutations can fail CORS preflight, and deleted seeded defaults reappear after restart.

The mapped Linear Project Brain checkpoint reached 149 backend tests and 3 frontend presentation tests passing, with Python compilation, the Next.js 15.5.19 production build, `git diff --check`, ignored-secret checks, exact-project live reads, and grounded package construction passing. The durable Linear mapping checkpoint reached 134 backend tests, the Linear read-provider checkpoint reached 129 tests, the shared recommendation checkpoint reached 113 tests, and the normalized work checkpoint reached 100 tests. Earlier 8-, 56-, 75-, 85-, 86-, 90-, and 95-test checkpoints remain recorded as implementation history rather than current feature claims.

The current product is not yet the full Personal Operating System described in the vision.

The largest current architecture problem is that intelligence is distributed across overlapping implementations.

Project Brain exists.

Today exists.

Recommendation logic exists.

Tasks ranking exists.

Chat reasoning exists.

But they do not yet consistently consume one canonical intelligence model.

The immediate product and engineering priority is therefore:

`Canonical Project Intelligence`

The immediate work has a canonical-intelligence track and a parallel Calendar-trust track:

```text
Canonical intelligence                     Calendar trust
extract Project Brain                      harden time/free-block correctness
        ↓                                           ↓
create canonical project registry          fix connected-state grounding
        ↓                                           │
define normalized work model                        │
        ↓                                           │
build shared recommendation service                 │
        └───────────────────┬───────────────────────┘
                            ↓
                Today / Tasks / Chat consume
                   shared trustworthy state
```

Mapped Linear ingestion and Project Work Packages now provide the first proof of the multi-provider model. Today, Tasks, and Chat still need to converge on the shared intelligence path in later roadmap work.

The active deep project-management provider is:

`Linear`

Linear is now the deeper read-only project-management source for:

```text
PCOS
XO
Nebulo
Freelance
```

Todoist should remain useful for lighter execution and personal tasks.

The first major proof of the new architecture should be PCOS answering:

> What's blocking Nebulo, and what should I do next?

It should use:

- real Linear work;
- explicit blocker and dependency state;
- relevant Todoist execution state;
- upcoming Calendar commitments;
- durable Memory;
- recent Activity;
- one shared recommendation model.

After that foundation is trustworthy, PCOS can expand into:

- repository and Codex catch-ups;
- Email Intelligence for personal and A&M email;
- proactive background monitoring;
- Daily and Weekly Review;
- Memory Inbox;
- hosted multi-device infrastructure;
- native iPhone, iPad, and Mac experiences;
- widgets and Live Activities;
- Finance;
- Investing;
- Vehicle Maintenance and mileage;
- Health;
- smart mirror;
- Vision Pro.

Those systems are not separate products.

They are future connected domains and surfaces of the same Personal Chief of Staff.

The enduring product principle is:

> **PCOS should remember and coordinate the operational details so the user can spend more attention living, building, and creating.**

The enduring engineering principle is:

> **One trustworthy intelligence model should power every PCOS surface.**

The next step is not to brainstorm PCOS again.

The next step is to build that model.
