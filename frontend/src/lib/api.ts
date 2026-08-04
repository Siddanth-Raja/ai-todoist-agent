import { readAgentSettings } from "@/lib/settings";

export type MemoryEntry = {
  id: string;
  type: string;
  title: string;
  content: string;
  confidence: number;
  enabled: boolean;
  source?: string | null;
  created_at: string;
  updated_at: string;
};

export type HabitDefinition = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type HabitStatus = "yes" | "no" | "partial";

export type HabitCheckIn = {
  id: string;
  habit_id: string | null;
  habit: string;
  status: HabitStatus;
  note: string | null;
  timestamp: string;
  created_at: string;
};

export type TaskItem = {
  id: string | null;
  content: string;
  description?: string | null;
  section: string;
  parent_id?: string | null;
  project_name?: string | null;
  section_name?: string | null;
  category?: string | null;
  todoist_section_name?: string | null;
  todoist_section_id?: string | null;
  classification_source?: string | null;
  due?: Record<string, unknown> | null;
  due_date?: string | null;
  due_status?: string | null;
  priority?: number | null;
  todoist_priority?: number | null;
  created_at?: string | null;
  completed: boolean;
  labels: string[];
  url?: string | null;
};

export type TaskSection = {
  name: string;
  tasks: TaskItem[];
};

export type TasksLifeArea = "A&M" | "XO" | "Nebulo" | "Freelance" | "Personal" | "Misc";

export type TaskRecommendationEvidence = {
  signal: string;
  value: unknown;
  score_delta: number;
  explanation: string;
};

export type TaskRecommendationAlternative = {
  provider: string;
  provider_record_id: string;
  title: string;
  task: TaskItem;
  score: number;
  action: string;
};

export type TaskRecommendation = {
  provider: string;
  provider_record_id: string;
  title: string;
  task: TaskItem;
  action: string;
  score: number;
  explanation: string;
  evidence: TaskRecommendationEvidence[];
  alternatives: TaskRecommendationAlternative[];
  computed_at: string;
  context: {
    current_time: string | null;
    usable_free_block_minutes: number | null;
    energy: string | null;
    upcoming_commitment_title: string | null;
    minutes_until_upcoming_commitment: number | null;
    project_momentum_provider_record_ids: string[];
  };
};

export type TaskAreaRecommendation = {
  area: TasksLifeArea;
  section_name: string;
  task_count: number;
  state: "recommended" | "empty" | "unavailable";
  recommendation: TaskRecommendation | null;
};

export type TasksResponse = {
  sections: TaskSection[];
  recommendations: TaskAreaRecommendation[];
  computed_at: string;
  provider: {
    name: "todoist";
    status: "available" | "degraded" | "unavailable";
    message: string | null;
  };
  errors: string[];
};

export type CalendarEvent = {
  id: string | null;
  title: string;
  start: string;
  end: string;
  duration_minutes: number;
  all_day: boolean;
  busy: boolean;
  event_type: string;
  event_category?: string | null;
  status?: string | null;
  transparency?: string | null;
  attendees_count?: number | null;
  location?: string | null;
  html_link?: string | null;
};

export type CalendarConflict = {
  first_event_id: string | null;
  first_event_title: string;
  second_event_id: string | null;
  second_event_title: string;
  start: string;
  end: string;
};

export type CalendarResponse = {
  events: CalendarEvent[];
  conflicts: CalendarConflict[];
  errors: string[];
};

export type TodayEvent = {
  id: string | null;
  title: string;
  start: string;
  end: string;
  start_display: string;
  end_display: string;
  time_range_display: string;
  duration_minutes: number;
  event_category: string;
  location?: string | null;
  html_link?: string | null;
};

export type TodayFreeBlock = {
  start: string;
  end: string;
  start_display: string;
  end_display: string;
  time_range_display: string;
  duration_minutes: number;
  low_usefulness: boolean;
};

export type TodayWorkProviderState = {
  provider: string;
  provider_reference?: string | null;
  available: boolean;
  error?: string | null;
};

export type TodayObligation = {
  provider: string;
  provider_record_id: string;
  canonical_project_id?: string | null;
  title: string;
  due_date: string;
  due_at?: string | null;
  urgency: "overdue" | "due_today";
  days_overdue: number;
  priority: number;
  provider_url?: string | null;
};

export type TodayMustDo = {
  state: "available" | "degraded" | "unavailable";
  items: TodayObligation[];
  errors: string[];
  providers: TodayWorkProviderState[];
};

export type TodayRecommendation = {
  type: string;
  source: "calendar" | "shared_recommendation" | "fallback";
  title: string;
  detail: string;
  reason?: string | null;
  task?: TaskItem | Record<string, unknown> | null;
  event?: TodayEvent | null;
  evidence: Array<{
    signal: string;
    value: unknown;
    score_delta: number;
    explanation: string;
  }>;
  alternatives: Array<{
    work: { provider: string; provider_record_id: string; title: string };
    score: number;
    action: string;
  }>;
  provider?: string | null;
  provider_record_id?: string | null;
  canonical_project_id?: string | null;
  canonical_project_key?: string | null;
  canonical_project_next_move?: string | null;
  contextual_override: boolean;
};

export type ActivityEntry = {
  id: string;
  type: string;
  action_type: string;
  title: string;
  description: string | null;
  detail: string | null;
  source: string;
  metadata: Record<string, unknown> | null;
  payload: Record<string, unknown> | null;
  created_at: string;
  meaningful_event: MeaningfulActivityEvent | null;
  activity_schema_version: number | null;
  legacy_unstructured: boolean;
};

export type MeaningfulActivityCategory =
  | "approved_action"
  | "work_created"
  | "work_started"
  | "work_updated"
  | "work_completed"
  | "milestone_progress"
  | "milestone_completed"
  | "blocker_added"
  | "blocker_changed"
  | "blocker_removed"
  | "waiting_external"
  | "project_state_reviewed"
  | "focus_decision_reviewed"
  | "project_paused"
  | "project_resumed"
  | "repository_catch_up"
  | "communication_linked"
  | "communication_outcome"
  | "memory_context_reviewed";

export type MeaningfulActivityEvent = {
  schema_version: number;
  category: MeaningfulActivityCategory;
  canonical_project_id: string | null;
  source_provider: string;
  provider_record_type: string | null;
  provider_record_id: string | null;
  source_timestamp: string;
  observed_at: string;
  freshness: "fresh" | "stale" | "unavailable" | "unknown";
  evidence_key: string;
  summary: string;
  attributable_payload: Record<string, unknown>;
};

export type LifeArea = {
  name: string;
  description: string;
  project_key?: string | null;
  canonical_project_id?: string | null;
  status: string;
  next_recommendation?: string | null;
  task_count: number;
  overdue_count: number;
  today_count: number;
  high_priority_count: number;
  provider_status?: string | null;
  provider_message?: string | null;
  degraded: boolean;
};

export type TodayResponse = {
  now: string;
  now_display: string;
  next_event?: TodayEvent | null;
  minutes_until_next_event?: number | null;
  current_free_block?: TodayFreeBlock | null;
  today_remaining_events: TodayEvent[];
  must_do: TodayMustDo;
  recommendation: TodayRecommendation;
  life_areas: LifeArea[];
  errors: string[];
};

export type ProjectBlocker = {
  type: string;
  title: string;
  detail: string | null;
  severity: "warning" | "critical";
  source_id: string | null;
};

export type ProjectTaskDiagnostic = {
  task_title: string;
  parent_title: string | null;
  todoist_section: string | null;
  resolved_project: string;
  priority: number | null;
  included: boolean;
  reason: string;
};

export type ProjectTaskGroup = {
  parent_task: TaskItem;
  subtasks: TaskItem[];
  is_container: boolean;
};

export type LinearProjectDiagnostic = {
  provider: "linear";
  status:
    | "connected"
    | "not_mapped"
    | "not_configured"
    | "authentication_failure"
    | "provider_failure"
    | "malformed_response";
  provider_ref: string | null;
  issue_count: number;
  message: string;
};

export type ProjectWorkPackageItem = {
  provider: "linear";
  provider_record_id: string;
  provider_identifier: string | null;
  title: string;
  status: string;
  provider_status: string | null;
  priority: number;
  provider_priority: number | string | null;
  is_executable: boolean;
  is_container: boolean;
  is_blocked: boolean;
  dependency_evaluation_states: Array<"active" | "resolved" | "needs_review">;
  explicit_dependencies: Array<{
    provider: string;
    provider_record_id: string;
    dependency_type: string;
  }>;
  parent_provider_record_id: string | null;
  provider_url: string | null;
};

export type ProjectWorkPackageAction = {
  provider: "linear";
  provider_record_id: string;
  provider_identifier: string | null;
  title: string;
  provider_url: string | null;
  explanation: string;
};

export type ProjectWorkPackage = {
  package_id: string;
  canonical_project_id: string;
  canonical_project_key: string;
  title: string;
  context: string;
  provider: "linear";
  provider_reference_id: string;
  provider_url: string | null;
  open_action_count: number;
  executable_action_count: number;
  explicitly_blocked_action_count: number;
  needs_review_action_count: number;
  availability_state:
    | "available"
    | "needs_review"
    | "explicitly_blocked"
    | "no_executable_action";
  work_items: ProjectWorkPackageItem[];
  next_action: ProjectWorkPackageAction | null;
  considered_alternatives: Array<{
    provider: "linear";
    provider_record_id: string;
    title: string;
  }>;
};

export type DependencyWorkEvidence = {
  provider: string;
  provider_record_id: string;
  provider_identifier: string | null;
  title: string | null;
  status: "open" | "completed" | "canceled" | null;
  provider_status: string | null;
  provider_url: string | null;
  canonical_project_id: string | null;
  provider_project_id: string | null;
};

export type EvaluatedDependencyEvidence = {
  relationship_provider: string;
  relationship_id: string | null;
  dependency_type: "blocked_by";
  canonical_project_id: string | null;
  blocked_work: DependencyWorkEvidence;
  blocking_work: DependencyWorkEvidence;
  evaluation_state: "active" | "resolved" | "needs_review";
  explanation: string;
};

export type DependencySummary = {
  active_dependency_count: number;
  active_blocked_work_count: number;
  needs_review_dependency_count: number;
  needs_review_blocked_work_count: number;
  resolved_dependency_count: number;
};

export type ProjectFocusState =
  | "active_momentum"
  | "waiting_external"
  | "intentionally_paused"
  | "dedicated_session_needed"
  | "quiet_possible_drift"
  | "recently_completed"
  | "insufficient_evidence";

export type ProjectActivityFocus = {
  canonical_project_id: string;
  canonical_project_key: string;
  evaluated_at: string;
  primary_state: ProjectFocusState;
  supporting_states: ProjectFocusState[];
  conflicting_states: ProjectFocusState[];
  evidence: Array<{
    evidence_key: string;
    category: string;
    canonical_project_id: string;
    source_kind: string;
    provider: string;
    provider_record_type: string | null;
    provider_record_id: string | null;
    source_timestamp: string | null;
    observed_at: string;
    freshness: "fresh" | "stale" | "unavailable" | "unknown";
    summary: string;
    metadata: Record<string, unknown>;
  }>;
  evidence_total_count: number;
  evidence_returned_count: number;
  evidence_limit: number;
  evaluated_windows: Array<{
    days: 7 | 14 | 30;
    starts_at: string;
    ends_at: string;
    evidence_count: number;
    categories: string[];
  }>;
  confidence: "low" | "medium" | "high";
  freshness: "fresh" | "stale" | "unavailable" | "unknown";
  provider_coverage: Array<{
    provider: string;
    provider_reference: string | null;
    state:
      | "fresh"
      | "stale"
      | "unavailable"
      | "not_configured"
      | "not_applicable"
      | "missing_history"
      | "unknown";
    observed_at: string;
    historical_coverage_start: string | null;
    detail: string | null;
  }>;
  explicit_intent: {
    id: string;
    canonical_project_id: string;
    confirmed_state: ProjectFocusState;
    reason: string | null;
    confirmed_at: string;
    expires_at: string | null;
    review_after: string | null;
    review_trigger: string | null;
  } | null;
  explicitly_confirmed: boolean;
  inferred: boolean;
  user_confirmation_recommended: boolean;
  confirmation_question: string | null;
  confirmation_reason: string | null;
};

export type ProjectBrain = {
  key: string;
  name: string;
  description: string;
  status: string;
  task_count: number;
  next_recommendation: string;
  blockers: ProjectBlocker[];
  attention_signals: ProjectBlocker[];
  dependency_summary: DependencySummary;
  dependency_evidence: EvaluatedDependencyEvidence[];
  tasks: TaskItem[];
  task_groups: ProjectTaskGroup[];
  classification_diagnostics: ProjectTaskDiagnostic[];
  upcoming_events: CalendarEvent[];
  people: string[];
  memories: MemoryEntry[];
  recent_activity: ActivityEntry[];
  work_packages: ProjectWorkPackage[];
  linear_diagnostic: LinearProjectDiagnostic | null;
  activity_focus: ProjectActivityFocus;
};

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const settings = readAgentSettings();
  if (!settings.apiKey) {
    throw new Error("Add your AGENT_API_KEY in Settings first.");
  }

  const hasBody = typeof options.body !== "undefined";
  const response = await fetch(`${settings.backendUrl}${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${settings.apiKey}`,
      ...(hasBody ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });

  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const detail = payload?.detail;
    throw new Error(typeof detail === "string" ? detail : `HTTP ${response.status}`);
  }

  return payload as T;
}

export function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

export function formatTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}
