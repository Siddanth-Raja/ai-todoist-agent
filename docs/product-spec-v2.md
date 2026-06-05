# Personal Chief of Staff Product Spec v2

Status: Draft  
Last updated: 2026-06-05  
Repository: `ai-todoist-agent`  
Scope: Planning/specification only. Do not implement these features yet.

## 1. Product Name

Working product name:

**Personal Chief of Staff**

This name is provisional. It captures the desired role of the product: a calm, practical operating layer that helps Siddanth decide what to do, follow through, adapt when the day changes, and understand patterns in his behavior.

## 2. Core Vision

Personal Chief of Staff is a personal operating system for planning, follow-through, adaptation, and self-awareness.

It sits above:

- Google Calendar
- Todoist
- Memory
- Planned vs actual tracking

The product should not try to replace every app immediately. Instead, it should become the reasoning and accountability layer above the existing tools Siddanth already uses.

The product should help answer:

- What should I do right now?
- What did I plan to do?
- What actually happened?
- What needs to move because the day changed?
- What pattern am I repeating?
- What is the next realistic action?

The product should feel like:

- Motion-style schedule intelligence
- Personal memory
- Accountability coaching
- Conversational AI

## 3. Product Positioning

Personal Chief of Staff should coordinate across systems without becoming a monolithic replacement for them.

Google Calendar remains the source of truth for scheduled time. Todoist remains the source of truth for tasks. Memory stores durable context about Siddanth. Planned vs actual tracking records the gap between intentions and behavior.

The product's job is to reason across those sources, recommend action, ask for confirmation where needed, and help Siddanth recover from normal schedule drift without guilt.

## 4. Sources of Truth

### 4.1 Google Calendar

Google Calendar is used for:

- Fixed events
- Meetings
- Classes
- Gym blocks
- Work blocks
- Appointments
- Planned time

Calendar events should be classified into three types.

#### Hard Events

Hard events include:

- Meetings
- Appointments
- Classes
- Deadlines
- Commitments involving other people

Rules:

- Hard events never move automatically.
- Any change to a hard event requires explicit user confirmation.
- The app should be conservative when classifying an event as hard.

#### Flexible Events

Flexible events include:

- Gym
- Deep work
- Errands
- Work blocks
- Personal admin blocks

Rules:

- Flexible events can be moved with confirmation.
- The app may recommend new times for flexible events.
- The app should explain why a move is recommended.

#### Soft Events

Soft events include:

- Rest
- Entertainment
- Optional plans
- Recovery time
- Loose personal blocks

Rules:

- Soft events can be moved casually.
- The user should still have visibility into changes.
- The app should not silently erase rest or entertainment time as if it does not matter.

### 4.2 Todoist

Todoist is the source of truth for tasks.

Todoist structure:

- Project: `To-Do`
- Sections:
  - `A&M`
  - `XO`
  - `Freelance`
  - `Personal`
  - `Misc`

#### A&M

Use for:

- College
- Transcript
- Housing
- Registration
- Orientation
- TAMU
- Blinn
- Classes
- School admin

#### XO

Use for:

- VR project
- Prototype
- Headset
- Ashwin
- Charlie
- Environments
- Gamma deck
- Design
- XO Collective

#### Freelance

Use for:

- Clients
- Law firms
- Dentists
- Realtors
- Outreach
- Portfolio
- Websites
- Invoices
- Follow-ups

#### Personal

Use for:

- Gym
- Health
- Shopping
- Errands
- Car
- Family
- Life admin
- Personal purchases
- Water bottle
- Nike socks

#### Misc

Use only for tasks that do not confidently fit anywhere else.

Rules:

- Do not use `Misc` as a default dumping ground.
- If a task can confidently fit `A&M`, `XO`, `Freelance`, or `Personal`, put it there.
- If classification confidence is low, the app may ask the user or propose a section with a change option.

### 4.3 Memory Center

Memory Center is user-visible and editable. It stores things the assistant knows about Siddanth.

Memory categories:

- Projects
- Preferences
- Classification rules
- Routines
- Goals
- Patterns
- Sensitive/private habits

Memory entries should have:

```json
{
  "id": "memory_id",
  "type": "project | preference | classification_rule | routine | goal | pattern | sensitive_private_habit",
  "title": "Short memory title",
  "content": "What the assistant knows",
  "confidence": 0.0,
  "source": "user | inferred | imported | system",
  "created_at": "ISO timestamp",
  "updated_at": "ISO timestamp",
  "enabled": true,
  "user_editable": true
}
```

Example project memory:

> XO is Siddanth's VR/worldbuilding project involving Ashwin and Charlie.

Example preference memory:

> Siddanth prefers one clear next action instead of a long task list.

Example classification rule:

> Shopping tasks usually go to Todoist -> To-Do -> Personal.

Example routine:

> Gym is important but flexible.

Example pattern:

> Siddanth often skips gym when it is scheduled after 5 PM.

Example sensitive/private habit:

> Siddanth is trying to reduce weed/nicotine use.

Sensitive/private habit memories should be optional, private, editable, and deletable.

Memory rules:

- Important memories should not be silently saved.
- The app should ask: "Should I remember this?"
- The user can edit, delete, disable, or hide any memory.
- Sensitive habit memories must be opt-in.
- Memory should improve recommendations but never shame the user.
- Memory should support user agency, not create a hidden profile the user cannot inspect.

## 5. Planned vs Actual Tracking

The app should compare:

- What was planned
- What actually happened

Example:

- Planned: Gym 5:30 PM
- Actual: Skipped gym

The app should ask lightweight check-in questions after relevant planned blocks.

Example habit check:

> Gym ended. Did you go?

Buttons:

- Yes
- No
- Partially

This creates tracking data.

Tracking categories:

- Gym
- Running
- Nebulo work
- XO work
- Freelance outreach
- A&M admin
- Sensitive habits, optional/private

Rules:

- Check-ins should be quick and low-friction.
- The app should not over-question the user.
- The user should be able to correct tracking data.
- Tracking should power recommendations, weekly summaries, and pattern detection.
- Missed plans should be treated as information, not failure.

## 6. Accountability Layer

The app should help Siddanth follow through without guilt.

The accountability layer should combine:

- Calendar context
- Todoist tasks
- Planned vs actual history
- Habit patterns
- Preferences from Memory
- Current free blocks

Example recommendation:

> You skipped gym yesterday and you're free for 90 minutes. Want to go now?

Example recommendation:

> You haven't contacted freelance leads in 5 days. Want to do a 15-minute outreach sprint?

Example recommendation:

> You planned Nebulo work but skipped it twice this week. Should we schedule it earlier in the day?

Tone:

- Direct
- Supportive
- Not shame-based
- Realistic
- Action-oriented

Rules:

- Do not moralize missed plans.
- Do not use streak loss or guilt as the primary motivator.
- Prefer one clear next action over a long list.
- Make recommendations that fit the user's actual available time.
- When recommending a change, explain the reasoning briefly.

## 7. Habit Tracking

The app should track positive habits:

- Gym
- Running
- Deep work
- Freelance outreach

The app may also track sensitive habits if Siddanth explicitly opts in:

- Weed use
- Nicotine use
- Urges
- Relapses

Sensitive habit tracking rules:

- Opt-in only.
- Private by default.
- Easy to delete.
- Easy to export.
- Never moralizing.
- Never surfaced casually in public or shared contexts.
- Should suggest safer alternatives and real support when needed.

Habit tracking should help Siddanth understand patterns and take better next actions. It should not become a judgment system.

## 8. Primary Interfaces

### 8.1 Primary Interface

The primary interface should be a mobile-first web app / PWA.

This is where the user should be able to:

- Review today
- Chat with the assistant
- Approve action cards
- Inspect calendar recommendations
- Review tasks
- Track habits
- Edit Memory
- Adjust settings

### 8.2 Secondary Interfaces

Secondary interfaces may come later:

- Mac app
- Native iOS app
- Siri quick capture

### 8.3 Siri Role

Siri is good for quick capture.

Good Siri examples:

- "I need Nike socks"
- "Meeting tomorrow at 6"
- "I skipped gym"

Siri is not the right interface for:

- Long planning conversations
- Conflict resolution
- Memory editing
- Dashboard review

Siri should be treated as a thin capture layer, not the main planning surface.

## 9. App UI

The app should use these top-level tabs:

- Today
- Chat
- Calendar
- Tasks
- Habits
- Memory
- Settings

### 9.1 Today Tab

The Today tab should show:

- Current free block
- Next event
- Top recommended action
- Gym status
- Missed or at-risk plans
- Quick buttons

The Today tab should answer: "What should I do next?"

### 9.2 Chat Tab

The Chat tab should provide natural language conversation with action cards.

The assistant should respond with a mix of:

- Short text
- Proposed actions
- Confirmation cards
- Conflict cards
- Habit check cards

Chat should not be only a text transcript. It should be an action surface.

### 9.3 Calendar Tab

The Calendar tab should show:

- Hard events
- Flexible events
- Soft events
- Conflicts
- Recommendations

The user should be able to understand what is fixed, what can move, and what the assistant recommends.

### 9.4 Tasks Tab

The Tasks tab should show Todoist tasks grouped by:

- A&M
- XO
- Freelance
- Personal
- Misc

The app should preserve Todoist as the task source of truth while making tasks easier to reason about in context.

### 9.5 Habits Tab

The Habits tab should show:

- Gym completion
- Running
- Work sessions
- Weekly stats
- Planned vs actual

The Habits tab should focus on insight and recovery, not guilt.

### 9.6 Memory Tab

The Memory tab should show editable memory entries.

The user should be able to:

- View memories
- Edit memories
- Delete memories
- Disable memories
- Hide memories
- See why a memory exists

### 9.7 Settings

Settings should include:

- API connections
- Privacy
- Notification preferences
- Sensitive tracking controls

## 10. Action Cards

The app should not only respond with text. It should present action cards when a concrete decision or confirmation is needed.

### 10.1 Add Task Card

Example:

- Task: Buy water bottle from Target
- Section: Personal

Buttons:

- Add
- Change section
- Cancel

### 10.2 Conflict Card

Example:

- Conflict: Gym 5:30-6:30 conflicts with Nebulo 6:00-7:00
- Recommendation: Move gym to 7:15

Buttons:

- Approve
- Pick another time
- Ignore

### 10.3 Habit Check Card

Example:

> Gym ended. Did you go?

Buttons:

- Yes
- No
- Partially

### 10.4 Memory Card

Example:

> Should I remember this?

Memory:

- Type: Pattern
- Title: Gym after 5 PM is harder
- Content: Siddanth often skips gym when it is scheduled after 5 PM.

Buttons:

- Remember
- Edit
- Not now

Action card rules:

- Cards should make decisions visible.
- Cards should allow correction.
- Cards should avoid hiding important state changes in chat text.
- Cards should preserve confirmation for task creation, event moves, memory saves, and sensitive tracking.

## 11. Build Phases

### Phase 1: Backend Reliability

Focus:

- Auth
- Schema stability
- Capture reliability
- Confirmation state
- Calendar update support

Goal:

Create a trustworthy backend foundation before expanding the interface.

### Phase 2: Mobile-First Web App

Focus:

- Chat UI
- Action cards
- Today tab
- Basic tasks display
- Basic calendar display

Goal:

Give Siddanth a practical daily surface for capture, review, and decision-making.

### Phase 3: Memory Center

Focus:

- Editable memories
- Ask-to-remember flow
- Classification rules

Goal:

Make memory visible, controllable, and useful for recommendations.

### Phase 4: Planned vs Actual

Focus:

- Gym tracking
- Habit check-ins
- Weekly summary

Goal:

Start measuring the gap between planned behavior and actual behavior in a supportive way.

### Phase 5: Accountability Intelligence

Focus:

- Pattern detection
- Proactive recommendations
- Energy-aware planning

Goal:

Use history and context to recommend better timing, smaller actions, and realistic recovery plans.

### Phase 6: Native Apps

Focus:

- PWA polish
- Mac app
- iOS app
- Notifications
- Widgets
- App Intents/Siri

Goal:

Expand the assistant into the places Siddanth naturally captures and reviews plans.

## 12. Privacy and Trust Principles

The product must be trustworthy because it reasons about personal plans, behavior, and potentially sensitive habits.

Principles:

- The user should know what the app remembers.
- Important memories require confirmation.
- Sensitive memories and habit tracking are opt-in.
- The user can edit, disable, delete, hide, and export relevant personal data.
- The app should not shame the user.
- The app should not silently move hard commitments.
- The app should not perform socially risky actions without explicit confirmation.
- Recommendations should be explainable in plain language.

## 13. North Star

The product should help Siddanth close the gap between:

- What he planned
- What he actually did
- What he wants his life to become

Personal Chief of Staff should become the layer that notices the plan, notices reality, and helps Siddanth choose the next useful action.
