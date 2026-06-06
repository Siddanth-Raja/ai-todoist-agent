import { readAgentSettings } from "@/lib/settings";

export type MemoryEntry = {
  id: string;
  type: string;
  title: string;
  content: string;
  confidence: number;
  enabled: boolean;
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
  project_name?: string | null;
  section_name?: string | null;
  due?: Record<string, unknown> | null;
  due_date?: string | null;
  due_status?: string | null;
  priority?: number | null;
  todoist_priority?: number | null;
  completed: boolean;
  labels: string[];
  url?: string | null;
};

export type TaskSection = {
  name: string;
  tasks: TaskItem[];
};

export type TasksResponse = {
  sections: TaskSection[];
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

export type ActivityEntry = {
  id: string;
  action_type: string;
  title: string;
  detail: string | null;
  payload: Record<string, unknown> | null;
  created_at: string;
};

export type LifeArea = {
  name: string;
  description: string;
  status: string;
  task_count: number;
  overdue_count: number;
  today_count: number;
  high_priority_count: number;
};

export type TodayResponse = {
  life_areas: LifeArea[];
  errors: string[];
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
