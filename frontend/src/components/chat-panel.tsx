"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CalendarPlus,
  Check,
  CheckCircle2,
  ExternalLink,
  ListTodo,
  Loader2,
  Pencil,
  Send,
  ShieldQuestion,
  X,
} from "lucide-react";
import { readAgentSettings } from "@/lib/settings";

type JsonRecord = Record<string, unknown>;
type ChatAction = JsonRecord;

type ChatResponse = {
  answer: string;
  intent?: string;
  actions_taken?: ChatAction[];
  needs_confirmation?: boolean;
  confirmation_prompt?: string | null;
  pending_action?: ChatAction | null;
  free_block?: ChatAction | null;
  recommended_tasks?: ChatAction[];
  calendar_events?: ChatAction[];
  mode?: string;
  errors?: Array<string | ChatAction>;
};

type ConversationItem = {
  id: string;
  prompt: string;
  response?: ChatResponse;
  error?: string;
  createdAt?: string;
  confirmationStatus?: "cancelled";
};

const CHAT_HISTORY_KEY = "pcos.chatHistory";
const MAX_CHAT_HISTORY_ITEMS = 80;

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function getRecord(value: unknown, key: string): JsonRecord | null {
  if (!isRecord(value)) {
    return null;
  }

  const nested = value[key];
  return isRecord(nested) ? nested : null;
}

function getString(value: unknown, key: string): string | null {
  if (!isRecord(value)) {
    return null;
  }

  const nested = value[key];
  return typeof nested === "string" && nested.trim() ? nested.trim() : null;
}

function getNumber(value: unknown, key: string): number | null {
  if (!isRecord(value)) {
    return null;
  }

  const nested = value[key];
  return typeof nested === "number" && Number.isFinite(nested) ? nested : null;
}

function formatObject(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }

  return JSON.stringify(value, null, 2);
}

function formatDateTime(value: string | null): string | null {
  if (!value) {
    return null;
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function formatDateTimeRange(start: string | null, end: string | null): string | null {
  const formattedStart = formatDateTime(start);
  const formattedEnd = formatDateTime(end);
  if (formattedStart && formattedEnd) {
    return `${formattedStart} - ${formattedEnd}`;
  }
  return formattedStart || formattedEnd;
}

function formatDuration(minutes: number | null): string | null {
  if (minutes === null) {
    return null;
  }

  if (minutes < 60) {
    return `${minutes} min`;
  }

  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours} hr ${remainder} min` : `${hours} hr`;
}

function projectFromTitle(title: string | null): string | null {
  if (!title) {
    return null;
  }

  const match = title.match(/^(.+?)\s+[—-]\s+/);
  return match?.[1]?.trim() || null;
}

function projectFromAction(action: ChatAction): string | null {
  return (
    getString(action, "resolved_project") ||
    getString(action, "project_context") ||
    getString(getRecord(action, "task"), "resolved_project") ||
    getString(getRecord(action, "task"), "project_category") ||
    projectFromTitle(getString(getRecord(action, "event"), "title"))
  );
}

function FieldRow({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value === null || typeof value === "undefined" || value === "") {
    return null;
  }

  return (
    <div className="grid grid-cols-[6.5rem_1fr] gap-3 text-xs leading-5">
      <dt className="text-stone-500">{label}</dt>
      <dd className="min-w-0 break-words text-stone-200">{value}</dd>
    </div>
  );
}

function CardLink({ href, children }: { href: string | null; children: string }) {
  if (!href) {
    return null;
  }

  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="mt-3 inline-flex h-9 items-center gap-2 rounded-md border border-white/10 bg-white/[0.04] px-3 text-xs font-medium text-stone-100 transition hover:border-moss/40 hover:text-moss"
    >
      {children}
      <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
    </a>
  );
}

function CalendarActionCard({ action }: { action: ChatAction }) {
  const event = getRecord(action, "event") ?? action;
  const title = getString(event, "title");
  const start = getString(event, "start");
  const end = getString(event, "end");
  const duration = formatDuration(getNumber(event, "duration_minutes"));
  const category = getString(event, "event_category") || getString(event, "event_type");
  const project = projectFromAction(action);
  const link = getString(event, "html_link") || getString(event, "url");

  return (
    <div className="rounded-lg border border-moss/30 bg-moss/10 p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium text-moss">
        <CalendarPlus className="h-4 w-4" aria-hidden="true" />
        Calendar event added
      </div>
      <dl className="space-y-2">
        <FieldRow label="Title" value={title} />
        <FieldRow label="Date/time" value={formatDateTimeRange(start, end)} />
        <FieldRow label="Duration" value={duration} />
        <FieldRow label="Category" value={category} />
        <FieldRow label="Project" value={project} />
      </dl>
      <CardLink href={link}>Open in Google Calendar</CardLink>
    </div>
  );
}

function CalendarUpdateActionCard({ action }: { action: ChatAction }) {
  const event = getRecord(action, "event") ?? action;
  const previousEvent = getRecord(action, "previous_event");
  const title = getString(event, "title") || getString(previousEvent, "title");
  const start = getString(event, "start");
  const end = getString(event, "end");
  const previousStart = getString(previousEvent, "start");
  const previousEnd = getString(previousEvent, "end");
  const link = getString(event, "html_link") || getString(event, "url");

  return (
    <div className="rounded-lg border border-moss/30 bg-moss/10 p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium text-moss">
        <CalendarPlus className="h-4 w-4" aria-hidden="true" />
        Calendar event updated
      </div>
      <dl className="space-y-2">
        <FieldRow label="Title" value={title} />
        <FieldRow label="Old time" value={formatDateTimeRange(previousStart, previousEnd)} />
        <FieldRow label="New time" value={formatDateTimeRange(start, end)} />
      </dl>
      <CardLink href={link}>Open in Google Calendar</CardLink>
    </div>
  );
}

function TodoistActionCard({ action }: { action: ChatAction }) {
  const task = getRecord(action, "task") ?? action;
  const title = getString(task, "content");
  const section =
    getString(task, "section_name") ||
    getString(task, "project_category") ||
    getString(task, "section");
  const priority = getNumber(task, "priority");
  const dueDate = getString(task, "due_date") || getString(task, "due_string");
  const link = getString(task, "url");

  return (
    <div className="rounded-lg border border-moss/30 bg-moss/10 p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium text-moss">
        <ListTodo className="h-4 w-4" aria-hidden="true" />
        Todoist task added
      </div>
      <dl className="space-y-2">
        <FieldRow label="Task" value={title} />
        <FieldRow label="Section" value={section} />
        <FieldRow label="Priority" value={priority ? `P${priority}` : null} />
        <FieldRow label="Due" value={dueDate} />
      </dl>
      <CardLink href={link}>Open in Todoist</CardLink>
    </div>
  );
}

function ActionCards({ actions }: { actions: ChatAction[] }) {
  if (!actions.length) {
    return null;
  }

  return (
    <div className="space-y-2">
      {actions.map((action, index) => {
        const type = getString(action, "type");
        if (type === "create_calendar_event") {
          return <CalendarActionCard key={index} action={action} />;
        }
        if (type === "update_calendar_event") {
          return <CalendarUpdateActionCard key={index} action={action} />;
        }
        if (type === "create_todoist_task") {
          return <TodoistActionCard key={index} action={action} />;
        }

        return (
          <div key={index} className="rounded-lg border border-moss/30 bg-moss/10 p-4">
            <div className="flex items-center gap-2 text-sm font-medium text-moss">
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
              Action completed
            </div>
          </div>
        );
      })}
    </div>
  );
}

function readableError(error: string | ChatAction): string {
  if (typeof error === "string") {
    return error;
  }

  return getString(error, "message") || getString(error, "type") || "Something needs attention.";
}

function ResponseErrorCards({ errors }: { errors: Array<string | ChatAction> }) {
  if (!errors.length) {
    return null;
  }

  return (
    <div className="space-y-2">
      {errors.map((error, index) => (
        <div key={index} className="rounded-lg border border-coral/30 bg-coral/10 p-4 text-sm leading-6 text-coral">
          <div className="mb-1 flex items-center gap-2 font-medium">
            <AlertTriangle className="h-4 w-4" aria-hidden="true" />
            Attention needed
          </div>
          <p className="text-xs leading-5 text-stone-200">{readableError(error)}</p>
        </div>
      ))}
    </div>
  );
}

function confirmationEvent(response: ChatResponse): JsonRecord | null {
  const pendingAction = response.pending_action;
  return getRecord(pendingAction, "calendar_event");
}

function confirmationUpdateDetails(response: ChatResponse): JsonRecord | null {
  const pendingAction = response.pending_action;
  return getRecord(pendingAction, "details");
}

function confirmationProject(response: ChatResponse): string | null {
  const pendingAction = response.pending_action;
  const event = confirmationEvent(response);
  return (
    getString(pendingAction, "resolved_project") ||
    getString(event, "resolved_project") ||
    projectFromTitle(getString(event, "title"))
  );
}

function ConfirmationCard({
  response,
  status,
  onConfirm,
  onCancel,
  onModify,
  disabled,
  confirming,
}: {
  response: ChatResponse;
  status?: "cancelled";
  onConfirm: () => void;
  onCancel: () => void;
  onModify: () => void;
  disabled: boolean;
  confirming: boolean;
}) {
  if (status === "cancelled") {
    return (
      <div className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
        <div className="flex items-center gap-2 text-sm font-medium text-stone-300">
          <X className="h-4 w-4" aria-hidden="true" />
          Confirmation cancelled
        </div>
      </div>
    );
  }

  if (!response.needs_confirmation) {
    return null;
  }

  const pendingType =
    getString(response.pending_action, "action_type") || getString(response.pending_action, "type");
  const event = confirmationEvent(response);
  const updateDetails = confirmationUpdateDetails(response);
  const project = confirmationProject(response);
  const isExecutable = pendingType
    ? ["create_calendar_event", "create_todoist_task", "update_calendar_event"].includes(pendingType)
    : false;

  return (
    <div className="rounded-lg border border-gold/35 bg-gold/10 p-4">
      <div className="mb-2 flex items-center gap-2 text-sm font-medium text-gold">
        <ShieldQuestion className="h-4 w-4" aria-hidden="true" />
        Confirmation needed
      </div>
      <p className="text-sm leading-6 text-stone-200">
        {response.confirmation_prompt || "Review this pending action before it runs."}
      </p>

      {pendingType === "create_calendar_event" && event ? (
        <dl className="mt-3 space-y-2 rounded-lg border border-white/10 bg-black/20 p-3">
          <FieldRow label="Event" value={getString(event, "title")} />
          <FieldRow label="Start" value={formatDateTime(getString(event, "start"))} />
          <FieldRow label="End" value={formatDateTime(getString(event, "end"))} />
          <FieldRow label="Project" value={project} />
        </dl>
      ) : null}

      {pendingType === "update_calendar_event" && updateDetails ? (
        <dl className="mt-3 space-y-2 rounded-lg border border-white/10 bg-black/20 p-3">
          <FieldRow label="Event" value={getString(updateDetails, "title")} />
          <FieldRow
            label="Old time"
            value={formatDateTimeRange(
              getString(updateDetails, "old_start"),
              getString(updateDetails, "old_end"),
            )}
          />
          <FieldRow
            label="New time"
            value={formatDateTimeRange(
              getString(updateDetails, "new_start"),
              getString(updateDetails, "new_end"),
            )}
          />
        </dl>
      ) : null}

      {!isExecutable ? (
        <p className="mt-3 rounded-lg border border-white/10 bg-black/20 p-3 text-xs leading-5 text-stone-300">
          I can suggest this, but calendar editing for this action is not implemented yet.
        </p>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-2">
        {isExecutable ? (
          <button
            type="button"
            disabled={disabled || confirming}
            onClick={onConfirm}
            className="inline-flex h-9 items-center gap-2 rounded-md bg-gold px-3 text-xs font-semibold text-ink transition hover:bg-[#ffe29a] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {confirming ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <Check className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            {confirming ? "Confirming" : "Confirm"}
          </button>
        ) : null}
        <button
          type="button"
          disabled={disabled || confirming}
          onClick={onCancel}
          className="inline-flex h-9 items-center gap-2 rounded-md border border-white/10 bg-white/[0.04] px-3 text-xs font-medium text-stone-200 transition hover:border-coral/40 hover:text-coral disabled:cursor-not-allowed disabled:opacity-60"
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
          Cancel
        </button>
        <button
          type="button"
          disabled={disabled || confirming}
          onClick={onModify}
          className="inline-flex h-9 items-center gap-2 rounded-md border border-white/10 bg-white/[0.04] px-3 text-xs font-medium text-stone-200 transition hover:border-gold/40 hover:text-gold disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
          Modify
        </button>
      </div>
    </div>
  );
}

function DevDebugPanel({ item }: { item: ConversationItem }) {
  const isDevelopment = process.env.NODE_ENV === "development";

  if (!isDevelopment) {
    return null;
  }

  return (
    <details className="rounded-lg border border-white/10 bg-white/[0.035] p-3 text-xs text-stone-400">
      <summary className="cursor-pointer font-medium text-stone-300">Debug</summary>
      <pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-words leading-5 text-stone-300">
        {formatObject({ error: item.error, response: item.response })}
      </pre>
    </details>
  );
}

export function ChatPanel() {
  const [input, setInput] = useState("");
  const [items, setItems] = useState<ConversationItem[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [confirmingItemId, setConfirmingItemId] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const sessionIdRef = useRef<string>(
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random()}`,
  );

  const hasConversation = items.length > 0;
  const canSend = useMemo(() => input.trim().length > 0 && !isSending, [input, isSending]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(CHAT_HISTORY_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          setItems(
            parsed.filter(
              (item): item is ConversationItem =>
                typeof item?.id === "string" && typeof item?.prompt === "string",
            ),
          );
        }
      }
    } finally {
      setHistoryLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (!historyLoaded) {
      return;
    }

    localStorage.setItem(
      CHAT_HISTORY_KEY,
      JSON.stringify(items.slice(-MAX_CHAT_HISTORY_ITEMS)),
    );
  }, [historyLoaded, items]);

  async function sendChatMessage(message: string) {
    if (!message || isSending) {
      return;
    }

    const settings = readAgentSettings();
    const itemId =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random()}`;
    const nextItem: ConversationItem = {
      id: itemId,
      prompt: message,
      createdAt: new Date().toISOString(),
    };

    setItems((current) => [...current, nextItem]);
    setInput("");
    setIsSending(true);

    try {
      if (!settings.apiKey) {
        throw new Error("Add your AGENT_API_KEY in Settings first.");
      }

      const response = await fetch(`${settings.backendUrl}/chat`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${settings.apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message,
          session_id: sessionIdRef.current,
          current_time: new Date().toISOString(),
        }),
      });

      const payload = await response.json().catch(() => null);

      if (!response.ok) {
        const detail = payload?.detail ? formatObject(payload.detail) : `HTTP ${response.status}`;
        throw new Error(detail);
      }

      setItems((current) =>
        current.map((item) =>
          item.id === itemId ? { ...item, response: payload as ChatResponse } : item,
        ),
      );
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Unable to reach the backend.";
      setItems((current) =>
        current.map((item) => (item.id === itemId ? { ...item, error: errorMessage } : item)),
      );
    } finally {
      setIsSending(false);
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await sendChatMessage(input.trim());
  }

  async function handleConfirm(itemId: string, response: ChatResponse) {
    const pendingAction = response.pending_action;
    if (!pendingAction || confirmingItemId) {
      return;
    }

    const settings = readAgentSettings();
    setConfirmingItemId(itemId);

    try {
      if (!settings.apiKey) {
        throw new Error("Add your AGENT_API_KEY in Settings first.");
      }

      const confirmResponse = await fetch(`${settings.backendUrl}/confirm`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${settings.apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          session_id: sessionIdRef.current,
          pending_action: pendingAction,
          current_time: new Date().toISOString(),
        }),
      });

      const payload = await confirmResponse.json().catch(() => null);
      if (!confirmResponse.ok) {
        const detail = payload?.detail ? formatObject(payload.detail) : `HTTP ${confirmResponse.status}`;
        throw new Error(detail);
      }

      setItems((current) =>
        current.map((item) =>
          item.id === itemId
            ? {
                ...item,
                response: {
                  ...(payload as ChatResponse),
                  answer: item.response?.answer ?? (payload as ChatResponse).answer,
                },
                error: undefined,
                confirmationStatus: undefined,
              }
            : item,
        ),
      );
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Unable to confirm this action.";
      setItems((current) =>
        current.map((item) =>
          item.id === itemId
            ? {
                ...item,
                response: item.response
                  ? {
                      ...item.response,
                      errors: [...(item.response.errors ?? []), errorMessage],
                    }
                  : item.response,
              }
            : item,
        ),
      );
    } finally {
      setConfirmingItemId(null);
    }
  }

  async function handleCancel(itemId: string, response: ChatResponse) {
    setItems((current) =>
      current.map((item) =>
        item.id === itemId ? { ...item, confirmationStatus: "cancelled" } : item,
      ),
    );

    const settings = readAgentSettings();
    if (!settings.apiKey || !response.pending_action) {
      return;
    }

    await fetch(`${settings.backendUrl}/confirm-cancel`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${settings.apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        session_id: sessionIdRef.current,
        pending_action: response.pending_action,
      }),
    }).catch(() => null);
  }

  function handleModify(response: ChatResponse) {
    const event = confirmationEvent(response);
    const title = getString(event, "title");
    const draft = title ? `Modify ${title}: ` : "Modify: ";
    setInput(draft);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }

  return (
    <section className="mx-auto flex h-full min-h-0 max-w-3xl flex-col overflow-hidden">
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain pb-5 pr-1">
        {!hasConversation ? (
          <div className="flex min-h-[42dvh] items-center">
            <div>
              <p className="text-sm font-medium uppercase tracking-[0.24em] text-moss">Ready</p>
              <h3 className="mt-3 max-w-xl text-3xl font-semibold tracking-normal text-stone-50 md:text-5xl">
                What needs your attention?
              </h3>
            </div>
          </div>
        ) : null}

        {items.map((item) => (
          <article key={item.id} className="space-y-3">
            <div className="ml-auto max-w-[88%] rounded-lg bg-white px-4 py-3 text-sm leading-6 text-ink shadow-glow">
              {item.prompt}
            </div>

            {item.response ? (
              <div className="max-w-[92%] space-y-3">
                <div className="glass-panel rounded-lg px-4 py-3 text-sm leading-6 text-stone-100">
                  {item.response.answer}
                </div>
                <ActionCards actions={item.response.actions_taken ?? []} />
                <ConfirmationCard
                  response={item.response}
                  status={item.confirmationStatus}
                  disabled={isSending}
                  confirming={confirmingItemId === item.id}
                  onConfirm={() => void handleConfirm(item.id, item.response as ChatResponse)}
                  onCancel={() => void handleCancel(item.id, item.response as ChatResponse)}
                  onModify={() => handleModify(item.response as ChatResponse)}
                />
                <ResponseErrorCards errors={item.response.errors ?? []} />
                <DevDebugPanel item={item} />
              </div>
            ) : item.error ? (
              <div className="max-w-[92%] space-y-3">
                <div className="rounded-lg border border-coral/30 bg-coral/10 px-4 py-3 text-sm leading-6 text-coral">
                  <div className="flex items-center gap-2 font-medium">
                    <AlertTriangle className="h-4 w-4" aria-hidden="true" />
                    Request failed
                  </div>
                </div>
                <DevDebugPanel item={item} />
              </div>
            ) : (
              <div className="flex max-w-[92%] items-center gap-2 rounded-lg border border-line bg-white/[0.04] px-4 py-3 text-sm text-stone-400">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Thinking
              </div>
            )}
          </article>
        ))}
      </div>

      <form
        onSubmit={handleSubmit}
        className="z-10 shrink-0 rounded-lg border border-line bg-panel/95 p-2 shadow-glow backdrop-blur-xl"
      >
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            rows={1}
            placeholder="Ask your chief of staff..."
            className="max-h-36 min-h-12 flex-1 resize-none rounded-lg border border-transparent bg-white/[0.04] px-4 py-3 text-base leading-6 text-stone-50 outline-none placeholder:text-stone-600 focus:border-moss/50"
          />
          <button
            type="submit"
            disabled={!canSend}
            aria-label="Send"
            className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-moss text-ink transition hover:bg-[#b7e5c9] active:scale-[0.98] disabled:cursor-not-allowed disabled:bg-stone-700 disabled:text-stone-500"
          >
            {isSending ? (
              <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" />
            ) : (
              <Send className="h-5 w-5" aria-hidden="true" />
            )}
          </button>
        </div>
      </form>
    </section>
  );
}
