# Personal Chief of Staff Product Spec

Status: Draft  
Last updated: 2026-06-04  
Repository: `ai-todoist-agent`

## 1. Product Summary

Personal Chief of Staff is a personal AI assistant for coordinating tasks, calendar events, reminders, and schedule changes across the user's real life.

This is not just a Todoist bot. Todoist is one important source of tasks, but the product should reason across multiple personal systems:

- Google Calendar for time-blocked tasks, meetings, hard commitments, gym, work blocks, and scheduled events.
- Todoist for tasks the user needs to do.
- Notion for notes and reference material only, not active task management.
- Apple Reminders as an optional notification layer for simple one-off reminders.
- Siri Shortcuts as the preferred mobile interface in a later version.
- A chat endpoint as the first backend interface.

The assistant should help the user answer questions like:

- "What should I work on right now?"
- "What are the urgent things I should start with during this work block?"
- "I had gym planned at 1 but I ate lunch instead. It's 2 now. What should I do?"
- "I feel like watching my show all day. What's a small piece of work I can do to feel accomplished?"

The product should behave like a calm, practical chief of staff: it should understand commitments, recommend the next useful action, protect hard calendar events, avoid risky automatic changes, and help the user recover from normal schedule drift without shame.

## 2. Core User

The primary user is one person managing several ongoing areas of life and work:

- A&M
- XO
- Nebulo
- Freelance
- Personal
- Misc

The user has an existing system:

- Calendar represents time and commitments.
- Todoist represents tasks.
- Notion represents reference.
- Some reminders may live in Apple Reminders.
- Mobile capture should eventually happen through Siri Shortcuts.

The assistant should fit this system instead of replacing it.

## 3. Product Goals

### 3.1 Primary Goals

1. Recommend what the user should work on right now based on current time, today's calendar, Todoist tasks, urgency, due dates, project, estimated duration, and energy level.
2. Preserve the distinction between tasks, events, reminders, notes, planning questions, and replanning questions.
3. Reduce decision fatigue during work blocks, low-energy moments, and schedule disruptions.
4. Keep Todoist as the source of truth for tasks unless a task is intentionally time-blocked.
5. Keep Google Calendar as the source of truth for scheduled time.
6. Ask for confirmation before changing important schedule commitments.
7. Avoid destructive or socially risky actions unless explicitly confirmed.

### 3.2 Secondary Goals

1. Capture new tasks quickly from natural language.
2. Create calendar events from natural language.
3. Add reminders or notifications to relevant events.
4. Categorize tasks into the user's main projects.
5. Support Siri Shortcut voice capture.
6. Support adaptive replanning when the user's day changes.
7. Provide "small win" recommendations on low-motivation days.

### 3.3 Non-Goals

The system should not:

- Replace Todoist as the task manager.
- Replace Google Calendar as the calendar source of truth.
- Use Notion as a task-management system.
- Automatically delete tasks or events.
- Automatically cancel meetings.
- Automatically email, message, or notify other people.
- Move important calendar events without confirmation.
- Pretend to know information that was not retrieved or inferred with reasonable confidence.
- Optimize the user's life according to a rigid productivity philosophy.

## 4. Source-of-Truth Rules

Each external system has a clear role.

### 4.1 Google Calendar

Google Calendar is the source of truth for time.

Use it for:

- Meetings.
- Classes.
- Appointments.
- Hard commitments.
- Gym blocks.
- Work blocks.
- Errands.
- Scheduled rest or chill time.
- Time-blocked tasks.

Calendar events can be classified as:

- Hard events: classes, meetings, appointments, important commitments.
- Flexible blocks: gym, work blocks, errands, personal blocks that can move.
- Soft blocks: rest, watching shows, chill time, buffer, optional routines.

### 4.2 Todoist

Todoist is the source of truth for tasks.

Use it for:

- Things the user needs to do.
- Shopping items.
- Errands.
- Project tasks.
- Personal tasks.
- Follow-ups.
- Action items captured from chat.

Tasks should remain in Todoist unless the user intentionally asks to schedule or time-block them.

### 4.3 Notion

Notion is for notes and reference only.

Use it for:

- Reference notes.
- Project docs.
- Long-form planning docs.
- Stored context.

Do not create active tasks in Notion. If a Notion note contains actionable tasks, future versions may migrate or copy those tasks into Todoist with confirmation.

### 4.4 Apple Reminders

Apple Reminders is optional and should be treated as a lightweight notification layer.

Use it for:

- Quick one-off reminders if integration is practical.
- Mobile-friendly reminder capture.
- Notifications that do not need rich task metadata.

Apple Reminders should not become the main task source unless the user explicitly changes the system design.

### 4.5 Siri Shortcuts

Siri Shortcuts is the preferred future mobile interface.

Use it for:

- Dictating a message to the assistant.
- Sending dictated text to `POST /chat`.
- Returning a short spoken or displayed response.

Siri Shortcuts should be a thin client. The backend should own classification, planning, and tool execution.

### 4.6 Chat Endpoint

The first backend interface is a chat endpoint.

Use it for:

- Natural language requests.
- Planning questions.
- Read-only recommendations in the MVP.
- Later write actions after confirmation.

The initial endpoint should be:

- `POST /chat`

Expected request shape for early versions:

```json
{
  "message": "What should I work on right now?",
  "context": {
    "energy_level": "medium",
    "current_time": "optional ISO timestamp override"
  }
}
```

Expected response shape for early versions:

```json
{
  "reply": "You have 45 minutes before your next meeting. I would start with...",
  "recommendations": [],
  "proposed_actions": [],
  "needs_confirmation": false
}
```

The exact schema can evolve during implementation, but the endpoint should preserve these concepts.

## 5. Intent Categories

The agent must distinguish between at least six input types.

### 5.1 Calendar Events

A calendar event is something that happens at a specific time or over a specific time range.

Examples:

- "Meeting with Brandon tomorrow at 6 for an hour"
- "Gym at 1"
- "Class from 10 to 11:30"
- "Work block from 2 to 4"

Expected behavior:

- MVP: explain that write actions are not available yet if the user asks to create the event.
- V1: create a Google Calendar event after parsing date, time, duration, title, and event type.
- If time details are missing, ask a focused follow-up question.
- If the event sounds important or involves another person, treat it as hard by default unless the user says otherwise.

### 5.2 Todoist Tasks

A Todoist task is an action the user needs to complete, but it is not necessarily scheduled at a specific time.

Examples:

- "I need Nike socks"
- "Add finish XO proposal"
- "Remind me to buy protein powder" if no specific alert time is provided and it sounds like a task.

Expected behavior:

- MVP: no task creation yet.
- V1: create a Todoist task.
- Infer project/category when possible.
- Default uncertain or shopping-style tasks to Misc unless the content strongly suggests another project.
- Preserve tasks in Todoist unless the user asks to time-block them.

Example:

Input: "I need Nike socks"  
Expected V1 action: create Todoist task "Buy Nike socks" in Misc.

### 5.3 Reminders

A reminder is a notification or alert, usually connected to an event or task.

Examples:

- "Remind me 30 minutes before my Brandon meeting"
- "Remind me tomorrow morning to submit the invoice"
- "Ping me before gym"

Expected behavior:

- If the reminder references a calendar event, find the matching event and add or propose adding a calendar reminder.
- If the reminder is a quick one-off and Apple Reminders integration exists, consider Apple Reminders.
- If the reminder has no time, ask for the missing time.
- Do not duplicate reminders if a matching reminder already exists.

Example:

Input: "Remind me 30 minutes before my Brandon meeting"  
Expected V1 action: find the Brandon meeting and add a 30-minute calendar notification after resolving ambiguity.

### 5.4 Notes and Reference

Notes and reference requests are for capturing or retrieving context, not managing tasks.

Examples:

- "Save this idea for Nebulo pricing"
- "What did I write about XO onboarding?"
- "Add this to my notes about A&M"

Expected behavior:

- MVP: likely unsupported unless implementation includes read-only local context.
- V1: probably still not a primary feature.
- V2: Notion may be used for reference capture or lookup.
- If the user says something actionable, ask whether it should become a Todoist task instead of a note.

### 5.5 Planning Questions

Planning questions ask what to do, how to prioritize, or how to use available time.

Examples:

- "What should I work on right now?"
- "What are urgent things I should start with during this work block?"
- "I have 30 minutes. What should I do?"
- "What should I do before my 4pm meeting?"

Expected behavior:

- Read today's calendar.
- Read Todoist tasks.
- Identify the current time, current block, and next hard commitment.
- Estimate available time.
- Recommend 1 to 3 tasks.
- Explain the reason briefly.
- Favor tasks that fit the available time and energy level.
- Avoid recommending a task that will collide with a hard event.

### 5.6 Replanning and Check-In Questions

Replanning questions happen when the user's actual day diverges from the calendar or plan.

Examples:

- "I had gym planned at 1 but I ate lunch instead. It's 2 now. What should I do?"
- "I missed my work block. How should I recover?"
- "I am behind. What should I move?"
- "I feel like watching my show all day. What's a small piece of work I can do to feel accomplished?"

Expected behavior:

- Acknowledge the new current state without judgment.
- Recompute from the current time.
- Identify hard events that must remain fixed.
- Identify flexible and soft blocks that could move.
- Recommend a practical next step.
- If moving calendar blocks is needed, propose the change and ask for confirmation before editing.
- For low motivation, prioritize a small, useful, bounded task.

## 6. Scheduling Rules

### 6.1 Event Types

Hard events:

- Classes.
- Meetings.
- Appointments.
- Calls with other people.
- Deadlines with a fixed time.
- Travel or logistics that cannot easily move.

Behavior:

- Never move automatically.
- Never cancel automatically.
- Ask before making any change.
- Prefer planning around these events.

Flexible blocks:

- Gym.
- Work blocks.
- Errands.
- Solo deep work.
- Admin blocks.
- Some personal routines.

Behavior:

- Can suggest moving.
- Ask before changing existing calendar events.
- If the block is moved, preserve its purpose and realistic duration when possible.

Soft blocks:

- Rest.
- Watching shows.
- Chill time.
- Buffer.
- Optional personal time.

Behavior:

- Can be moved more freely.
- Still avoid editing the calendar without confirmation in early versions.
- Can be shortened or replaced in recommendations if the user asks for productivity help.

Tasks:

- Stay in Todoist unless intentionally time-blocked.
- Can be recommended during available calendar space.
- Can be converted into calendar blocks only when the user asks or confirms.

### 6.2 Global Safety Rules

The assistant must never:

- Delete tasks automatically.
- Delete calendar events automatically.
- Cancel meetings automatically.
- Email people automatically.
- Message people automatically.
- RSVP to events automatically.
- Move important events without confirmation.
- Make irreversible changes without confirmation.

The assistant may:

- Read tasks and events during the MVP.
- Recommend a plan.
- Draft proposed changes.
- Ask the user to confirm changes.
- Execute confirmed write actions in V1 and later.

### 6.3 Confirmation Rules

Ask for confirmation when:

- Creating a calendar event with another person.
- Moving a hard event.
- Moving a flexible event that already exists on the calendar.
- Adding or changing notifications on important events.
- Creating multiple tasks or events from one message.
- Any interpretation has meaningful ambiguity.

Do not require confirmation when:

- Answering read-only planning questions.
- Recommending tasks.
- Explaining priorities.
- Creating a simple Todoist task in V1, if the user's intent is explicit and low-risk.

## 7. Main Projects and Categorization

The assistant should classify tasks into one of:

- A&M
- XO
- Nebulo
- Freelance
- Personal
- Misc

### 7.1 Default Categorization

Use Misc when:

- The task is a shopping item.
- The task does not clearly map to a known project.
- The task is a general errand.
- The task has too little context.

Use Personal when:

- The task relates to health, home, relationships, routines, personal admin, or self-care.

Use Freelance when:

- The task relates to client work, invoices, proposals, deliverables, calls, or independent work that is not clearly A&M, XO, or Nebulo.

Use A&M, XO, or Nebulo when:

- The user names the project.
- The task contains project-specific names, context, or known keywords.
- The surrounding conversation indicates the project.

### 7.2 Ambiguity Handling

If the category is uncertain but low-risk:

- Create the task in Misc in V1.
- Include the inferred category in the response.

If the category matters for prioritization:

- Ask a short follow-up question.

Example:

Input: "I need Nike socks"  
Category: Misc  
Reason: shopping item with no project-specific context.

## 8. Inferred Metadata

Each task, event, reminder, or planning item should have inferred metadata where possible.

### 8.1 Shared Metadata

- `id`: provider-specific ID when available.
- `title`: human-readable name.
- `source_app`: `todoist`, `google_calendar`, `notion`, `apple_reminders`, or `assistant`.
- `project`: A&M, XO, Nebulo, Freelance, Personal, or Misc.
- `status`: open, completed, scheduled, cancelled, unknown.
- `created_at`: timestamp if available.
- `updated_at`: timestamp if available.

### 8.2 Task Metadata

- `priority`: explicit provider priority or inferred priority.
- `due_date`: Todoist due date if available.
- `estimated_duration`: inferred or user-provided duration.
- `energy_level`: low, medium, high, or unknown.
- `deadline_type`: hard, soft, or unknown.
- `requires_calendar_block`: true, false, or unknown.
- `requires_focus`: low, medium, high, or unknown.
- `tags`: provider labels or inferred labels.

### 8.3 Calendar Event Metadata

- `start`: event start time.
- `end`: event end time.
- `duration_minutes`: computed duration.
- `event_type`: hard, flexible, soft, or unknown.
- `attendees`: available attendee metadata.
- `location`: if available.
- `reminders`: current reminder settings.
- `is_recurring`: true or false.
- `movability`: hard, flexible, soft, or unknown.

### 8.4 Reminder Metadata

- `target_type`: task, event, or standalone.
- `target_id`: provider-specific target ID when available.
- `offset_minutes`: if relative to an event.
- `remind_at`: if absolute.
- `channel`: calendar notification, Apple Reminder, or unknown.

### 8.5 Planning Context Metadata

- `current_time`: actual or provided current time.
- `available_minutes`: time until next hard commitment or block boundary.
- `current_block`: current calendar event if any.
- `next_hard_event`: next hard calendar event.
- `energy_level`: user-provided or inferred.
- `mode`: normal, urgent, low_motivation, recovery, planning.

## 9. Recommendation and Ranking Logic

The planner should recommend 1 to 3 tasks for planning questions.

### 9.1 Ranking Inputs

Use:

- Todoist due dates.
- Todoist priority.
- Project/category.
- Current calendar context.
- Time until next hard event.
- Estimated task duration.
- Energy level.
- Whether the task is overdue.
- Whether the task is small enough to complete now.
- Whether the task belongs to the current work block's project, if known.
- User's stated mood or intent.

### 9.2 Ranking Principles

The best recommendation is not always the most important task. It is the best fit for the current moment.

Prefer tasks that:

- Are urgent or overdue.
- Fit inside the available time.
- Match the user's current energy.
- Match the current calendar block.
- Create momentum.
- Reduce future stress.
- Are clearly actionable.

Avoid tasks that:

- Cannot fit before the next hard event.
- Require high energy when the user says energy is low.
- Depend on context not currently available.
- Are vague and need clarification.
- Conflict with a hard calendar event.

### 9.3 Energy-Aware Behavior

Energy levels:

- Low: recommend small, concrete, low-friction tasks.
- Medium: recommend useful tasks that can fit the current block.
- High: recommend harder, more important, focus-heavy tasks.

Low motivation example:

Input: "I feel like watching my show all day. What's a small piece of work I can do to feel accomplished?"

Expected response:

- Pick one small useful task.
- Keep it bounded.
- Avoid moralizing.
- Suggest a short duration.
- Optionally suggest returning to rest afterward.

Example response style:

"Do the smallest useful thing: spend 15 minutes drafting the first three bullets for the XO proposal. It is contained, it moves a real project forward, and you can stop after the timer."

### 9.4 Time Fit Rules

If available time is less than 15 minutes:

- Recommend quick admin, capture, review, or tiny cleanup tasks.
- Avoid deep work.

If available time is 15 to 45 minutes:

- Recommend one small task or the first step of a larger task.

If available time is 45 to 120 minutes:

- Recommend one focused task or two smaller tasks.

If available time is more than 120 minutes:

- Recommend a primary focus task plus optional secondary tasks.

### 9.5 Urgency Rules

Urgency should consider:

- Due today.
- Overdue.
- Due soon.
- High Todoist priority.
- User-stated importance.
- Calendar-related timing.
- Project relevance.

Due-date urgency should not blindly override context. A high-priority task that cannot realistically fit before a hard event may be recommended for a later block instead.

## 10. MVP Scope

The first working version should be read-only planning.

### 10.1 MVP Capabilities

The MVP should:

- Expose `POST /chat`.
- Read Todoist tasks.
- Read today's Google Calendar events.
- Answer: "What should I work on right now?"
- Recommend 1 to 3 tasks.
- Use urgency, due date, project, estimated duration, and energy level when available.
- Identify available time until the next hard commitment.
- Explain recommendations briefly.

### 10.2 MVP Inputs

The MVP should accept:

- A natural language message.
- Optional energy level.
- Optional current time override for testing.

Example:

```json
{
  "message": "What should I work on right now?",
  "context": {
    "energy_level": "low"
  }
}
```

### 10.3 MVP Outputs

The MVP should return:

- A short natural language answer.
- 1 to 3 recommendations.
- Reasons for each recommendation.
- A note about upcoming calendar constraints.
- No write actions.

Example:

```json
{
  "reply": "You have about 50 minutes before your next hard event. Start with the invoice follow-up, then use any leftover time to buy Nike socks.",
  "recommendations": [
    {
      "title": "Send invoice follow-up",
      "project": "Freelance",
      "reason": "Due today, short enough for this block, and likely reduces future stress.",
      "estimated_duration": 20,
      "energy_level": "medium"
    }
  ],
  "proposed_actions": [],
  "needs_confirmation": false
}
```

### 10.4 MVP Constraints

The MVP should not:

- Create Todoist tasks.
- Create Google Calendar events.
- Move calendar events.
- Add reminders.
- Write to Notion.
- Write to Apple Reminders.
- Perform email or messaging actions.

If the user asks for a write action during MVP, the assistant should say that write actions are not available yet and, when useful, provide the parsed intent.

Example:

Input: "Meeting with Brandon tomorrow at 6 for an hour"

MVP response:

"I understand this as a calendar event: Meeting with Brandon, tomorrow at 6pm, lasting 1 hour. Calendar creation is not enabled in the MVP yet."

## 11. V1 Scope

V1 adds basic write actions and mobile capture.

### 11.1 V1 Capabilities

V1 should:

- Create Todoist tasks.
- Create Google Calendar events.
- Add calendar reminders.
- Categorize tasks into A&M, XO, Nebulo, Freelance, Personal, or Misc.
- Support a basic Siri Shortcut that sends dictated text to `POST /chat`.

### 11.2 V1 Todoist Creation

For explicit task capture:

- Parse task title.
- Infer project/category.
- Infer due date if stated.
- Infer priority if stated.
- Create the task in Todoist.
- Respond with what was created.

Example:

Input: "I need Nike socks"

Expected response:

"Added Todoist task: Buy Nike socks, categorized as Misc."

### 11.3 V1 Calendar Creation

For explicit event creation:

- Parse title.
- Parse date.
- Parse start time.
- Parse duration or end time.
- Infer event type.
- Ask for missing required fields.
- Create the event after confirmation when needed.

Example:

Input: "Meeting with Brandon tomorrow at 6 for an hour"

Expected response:

"I can add Meeting with Brandon for tomorrow from 6:00pm to 7:00pm. Should I create it?"

If the implementation chooses to create low-risk explicit events without confirmation, it must still ask when another person is involved, details are ambiguous, or the event is important.

### 11.4 V1 Calendar Reminders

For reminder requests tied to events:

- Search today's and nearby calendar events.
- Match by title, attendee, or semantic similarity.
- If exactly one likely event is found, add the reminder or ask for confirmation depending on risk.
- If multiple events match, ask the user to choose.

Example:

Input: "Remind me 30 minutes before my Brandon meeting"

Expected response:

"I found Meeting with Brandon tomorrow at 6:00pm. Should I add a 30-minute reminder?"

### 11.5 V1 Siri Shortcut

The basic Siri Shortcut should:

- Dictate text.
- Send the text to `POST /chat`.
- Display or speak the response.
- Include a configurable backend URL.
- Avoid storing secrets in the shortcut if possible.

The shortcut should not own business logic. It should act as a capture and response interface.

## 12. V2 Scope

V2 adds adaptive replanning and broader integrations.

### 12.1 V2 Capabilities

V2 should:

- Support adaptive replanning.
- Move flexible calendar blocks with confirmation.
- Integrate Apple Reminders if practical.
- Migrate Notion tasks into Todoist with confirmation.
- Produce a daily planning summary.
- Improve energy-aware recommendations.
- Add "small win" mode for low motivation days.

### 12.2 Adaptive Replanning

Adaptive replanning should:

- Compare the calendar plan against the user's actual current situation.
- Identify missed, current, and upcoming blocks.
- Protect hard events.
- Suggest changes to flexible and soft blocks.
- Ask before modifying existing calendar events.
- Offer a realistic next action.

Example:

Input: "I had gym planned at 1 but I ate lunch instead. It's 2 now. What should I do?"

Expected reasoning:

- Current time is 2pm.
- Gym block was missed or displaced.
- Check next hard event.
- Check whether gym can still fit.
- Check flexible work blocks and soft blocks.
- Recommend either going to gym now, shortening gym, moving gym, or doing a smaller task.

Expected response style:

"You still have enough room to go now if you keep it to 45 minutes and leave your 4pm meeting untouched. I would move the flexible work block back by an hour. Want me to make that calendar change?"

### 12.3 Apple Reminders

Apple Reminders integration should be considered only if practical from the backend environment.

Possible uses:

- One-off reminders.
- Mobile-native alerts.
- Simple personal nudges.

Risks:

- Apple ecosystem APIs may be less straightforward from a backend service.
- Calendar notifications may cover many reminder needs.

### 12.4 Notion Task Migration

Notion should remain reference-only, but V2 may detect action items in Notion notes and migrate them to Todoist.

Rules:

- Never silently convert a note into tasks.
- Show proposed tasks first.
- Ask for confirmation.
- Create tasks in Todoist, not Notion.
- Preserve a reference link back to the Notion page when possible.

### 12.5 Daily Planning Summary

A daily planning summary should:

- Read today's calendar.
- Read relevant Todoist tasks.
- Identify hard commitments.
- Identify flexible blocks.
- Recommend a primary focus.
- Highlight urgent tasks.
- Leave room for recovery and schedule drift.

Possible prompt:

"What's my plan for today?"

Expected response:

- Morning overview.
- Key commitments.
- Recommended focus.
- 1 to 3 task priorities.
- Risks or schedule pinch points.

## 13. Backend Architecture

The backend should be a FastAPI app organized around the existing repo structure.

### 13.1 Files

```text
backend/
  app/
    main.py
    agent.py
    todoist_tools.py
    calendar_tools.py
    planner.py
    config.py
  .env
  requirements.txt
shortcuts/
  README.md
docs/
  product-spec.md
```

### 13.2 Responsibilities

`main.py`

- Create the FastAPI app.
- Define `POST /chat`.
- Handle request and response schemas.
- Call the agent layer.
- Return structured responses.

`agent.py`

- Classify user intent.
- Decide which tools or planner functions are needed.
- Coordinate read-only planning, task creation, event creation, reminders, and replanning.
- Enforce confirmation and safety rules.
- Format user-facing responses.

`todoist_tools.py`

- Read Todoist tasks.
- Create Todoist tasks in V1.
- Map Todoist projects to the user's categories.
- Normalize Todoist task metadata.

`calendar_tools.py`

- Read Google Calendar events.
- Create calendar events in V1.
- Add reminders in V1.
- Identify event types and movability.
- Normalize calendar metadata.

`planner.py`

- Combine Todoist tasks and calendar events.
- Compute available time.
- Rank tasks.
- Generate recommendations.
- Support energy-aware planning.
- Support adaptive replanning in V2.

`config.py`

- Load environment variables.
- Validate required settings.
- Centralize provider credentials and API configuration.

`.env`

- Store secrets and local configuration.
- Should not be committed to source control.

### 13.3 Layering Rules

- API route code should stay thin.
- Provider-specific API calls should stay in tool modules.
- Planning logic should not directly call external APIs.
- Agent logic should orchestrate tools and planner functions.
- Safety and confirmation rules should be enforced before writes.
- Normalized task and event structures should be passed into planner functions.

### 13.4 Read and Write Separation

Read actions:

- Fetch Todoist tasks.
- Fetch calendar events.
- Fetch current event context.
- Retrieve metadata.

Write actions:

- Create Todoist task.
- Create calendar event.
- Add calendar reminder.
- Move calendar event.
- Create Apple Reminder.
- Migrate Notion tasks to Todoist.

The MVP should implement read actions only. Later versions should make write actions explicit and confirm risky changes.

## 14. Chat Behavior

### 14.1 Tone

The assistant should be:

- Practical.
- Calm.
- Concise.
- Non-judgmental.
- Action-oriented.
- Honest about uncertainty.

It should not:

- Scold the user.
- Over-explain simple choices.
- Pretend a low-energy day is a failure.
- Recommend unrealistic plans.

### 14.2 Response Shape

For planning answers:

1. Mention current time constraint if relevant.
2. Recommend the best next action.
3. Give 1 to 3 options if useful.
4. Explain why briefly.
5. Mention any required confirmation for changes.

Example:

"You have about 40 minutes before your next meeting. Start with the Freelance invoice follow-up because it is due today and should fit in this block. If you finish early, knock out the Nike socks task as a quick Misc errand."

### 14.3 Handling Ambiguity

Ask follow-up questions only when needed.

Good follow-up:

"What time tomorrow should I remind you?"

Too much follow-up:

"Can you clarify the project, priority, deadline, estimated duration, and preferred reminder type?"

The assistant should infer reasonable defaults for low-risk actions.

### 14.4 Handling Unsupported Requests

During MVP, write actions are unsupported. The assistant should still parse the request and explain what would happen in a later version.

Example:

"I understand this as a Todoist task: Buy Nike socks, category Misc. Task creation is not enabled in the MVP yet."

## 15. Example Inputs and Expected Behavior

### 15.1 "I need Nike socks"

Intent: Todoist task  
Category: Misc  
MVP behavior: parse but do not create.  
V1 behavior: create Todoist task.

Expected V1 response:

"Added Todoist task: Buy Nike socks, categorized as Misc."

### 15.2 "Meeting with Brandon tomorrow at 6 for an hour"

Intent: Calendar event  
Event type: hard by default because it involves another person  
MVP behavior: parse but do not create.  
V1 behavior: ask for confirmation, then create event.

Expected V1 response:

"I can add Meeting with Brandon tomorrow from 6:00pm to 7:00pm. Should I create it?"

### 15.3 "Remind me 30 minutes before my Brandon meeting"

Intent: Reminder attached to calendar event  
MVP behavior: unsupported write action.  
V1 behavior: find matching calendar event, ask if ambiguous, add calendar reminder.

Expected V1 response:

"I found Meeting with Brandon tomorrow at 6:00pm. Should I add a 30-minute reminder?"

### 15.4 "I feel like watching my show all day. What's a small piece of work I can do to feel accomplished?"

Intent: Planning question, low motivation  
MVP behavior: read tasks and calendar, recommend one small useful task.  
V2 behavior: use improved small win mode.

Expected response:

"Pick one small win: spend 15 minutes on the shortest useful task in Todoist. Based on your list, I would start with [task] because it is concrete, low-friction, and still moves [project] forward."

### 15.5 "I had gym planned at 1 but I ate lunch instead. It's 2 now. What should I do?"

Intent: Replanning/check-in  
MVP behavior: provide read-only recommendation from current time.  
V2 behavior: propose moving flexible blocks with confirmation.

Expected V2 response:

"Your hard events should stay where they are. Gym is flexible, so the cleanest recovery is to go now for a shorter session if it still fits before your next commitment. I can move the flexible work block later if you want."

### 15.6 "What are urgent things I should start with during this work block?"

Intent: Planning question  
MVP behavior: rank Todoist tasks against current calendar block.

Expected response:

"Start with these: 1. [task] because it is due today, 2. [task] because it fits this block, 3. [task] if you have extra time."

## 16. Data Normalization

The planner should receive normalized data instead of raw provider objects.

### 16.1 Normalized Task

```json
{
  "id": "todoist-task-id",
  "title": "Send invoice follow-up",
  "source_app": "todoist",
  "project": "Freelance",
  "priority": 3,
  "due_date": "2026-06-04",
  "estimated_duration": 20,
  "energy_level": "medium",
  "status": "open",
  "labels": ["invoice"],
  "url": "https://todoist.com/..."
}
```

### 16.2 Normalized Calendar Event

```json
{
  "id": "calendar-event-id",
  "title": "Meeting with Brandon",
  "source_app": "google_calendar",
  "start": "2026-06-05T18:00:00-05:00",
  "end": "2026-06-05T19:00:00-05:00",
  "duration_minutes": 60,
  "event_type": "hard",
  "movability": "hard",
  "attendees": [],
  "reminders": [
    {
      "method": "popup",
      "minutes": 30
    }
  ],
  "status": "scheduled"
}
```

### 16.3 Recommendation Object

```json
{
  "task_id": "todoist-task-id",
  "title": "Send invoice follow-up",
  "project": "Freelance",
  "rank": 1,
  "reason": "Due today and should fit before the next meeting.",
  "estimated_duration": 20,
  "energy_level": "medium",
  "score": 0.87
}
```

Scores are internal and should not be shown to the user unless needed for debugging.

## 17. Environment and Configuration

Expected configuration categories:

- Todoist API token.
- Google Calendar credentials.
- Calendar ID or primary calendar setting.
- Timezone.
- Optional LLM provider configuration.
- Optional Notion credentials.
- Optional Apple Reminders configuration.

Configuration should live in `backend/app/config.py` and be loaded from environment variables.

Secrets should live in `backend/.env` for local development and should not be committed.

## 18. Authentication and Privacy

This is a personal assistant with access to private calendar and task data.

Implementation should treat privacy as a core requirement:

- Do not log secrets.
- Avoid logging full task and calendar contents unless explicitly debugging locally.
- Keep provider tokens in environment variables.
- Prefer least-privilege API scopes.
- Make write actions auditable in responses.
- Avoid sending unnecessary private context to external models.

For local development, simple local configuration is acceptable. If deployed beyond local use, the system should add appropriate authentication for `POST /chat`.

## 19. Error Handling

The assistant should handle provider failures gracefully.

Examples:

- Todoist unavailable: explain that task data could not be fetched and answer from calendar only if useful.
- Google Calendar unavailable: explain that calendar context is missing and avoid time-specific recommendations.
- Missing credentials: return a setup-focused error.
- Ambiguous time phrase: ask a follow-up question.
- No tasks available: recommend reviewing or capturing tasks instead of fabricating work.
- No calendar events today: rank tasks without calendar constraints.

The assistant should never hide uncertainty in planning responses.

## 20. Testing and Acceptance Criteria

### 20.1 MVP Acceptance Criteria

The MVP is successful when:

- `POST /chat` accepts a planning question.
- The backend fetches Todoist tasks.
- The backend fetches today's Google Calendar events.
- The planner identifies available time until the next hard event.
- The assistant recommends 1 to 3 tasks.
- The recommendation includes a concise reason.
- The assistant does not perform write actions.

Test prompts:

- "What should I work on right now?"
- "What are urgent things I should start with during this work block?"
- "I have 20 minutes and low energy. What should I do?"

### 20.2 V1 Acceptance Criteria

V1 is successful when:

- The assistant can create a Todoist task from "I need Nike socks."
- The assistant categorizes that task as Misc.
- The assistant can parse a calendar event from "Meeting with Brandon tomorrow at 6 for an hour."
- The assistant asks for confirmation before creating important or people-involved calendar events.
- The assistant can add a reminder to a matching calendar event.
- A Siri Shortcut can send dictated text to `POST /chat` and display the response.

### 20.3 V2 Acceptance Criteria

V2 is successful when:

- The assistant can replan from the current time after a missed flexible block.
- The assistant can propose moving flexible blocks.
- The assistant asks for confirmation before moving existing events.
- The assistant can generate a useful daily planning summary.
- The assistant can recommend small, low-friction tasks for low motivation.
- Notion task migration only happens after confirmation.

## 21. Open Product Questions

These questions can be answered during implementation:

- How should estimated task duration be stored in Todoist: labels, comments, task description, or inferred only?
- Should energy level be user-provided each chat, inferred from wording, or persisted?
- Should project/category mapping use Todoist projects, labels, or both?
- Should the MVP use a deterministic planner first, an LLM-assisted planner, or a hybrid?
- What date range should reminder event matching search by default?
- Should the assistant create calendar events immediately for simple solo events, or always confirm event creation?
- What authentication should protect `POST /chat` if exposed outside localhost?

## 22. Implementation Order

Recommended implementation order:

1. Define request and response schemas for `POST /chat`.
2. Implement configuration loading.
3. Implement Todoist read tools.
4. Implement Google Calendar read tools.
5. Normalize tasks and calendar events.
6. Implement planner ranking for "What should I work on right now?"
7. Implement agent intent classification for MVP planning and unsupported write requests.
8. Add tests with mocked Todoist and calendar data.
9. Add V1 Todoist task creation.
10. Add V1 calendar event creation.
11. Add V1 calendar reminders.
12. Add Siri Shortcut documentation.
13. Add V2 replanning and flexible block movement.

The implementation should start with the MVP and avoid building the full system before the read-only planning loop works reliably.
