"use client";

import { FormEvent, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, Send, ShieldQuestion } from "lucide-react";
import { readAgentSettings } from "@/lib/settings";

type ChatAction = Record<string, unknown>;

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
};

function formatObject(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }

  return JSON.stringify(value, null, 2);
}

function ActionCards({ actions }: { actions: ChatAction[] }) {
  if (!actions.length) {
    return null;
  }

  return (
    <div className="space-y-2">
      {actions.map((action, index) => (
        <div key={index} className="rounded-lg border border-moss/25 bg-moss/10 p-3">
          <div className="mb-2 flex items-center gap-2 text-sm font-medium text-moss">
            <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
            Action taken
          </div>
          <pre className="overflow-x-auto whitespace-pre-wrap break-words text-xs leading-5 text-stone-300">
            {formatObject(action)}
          </pre>
        </div>
      ))}
    </div>
  );
}

function ConfirmationCard({ response }: { response: ChatResponse }) {
  if (!response.needs_confirmation) {
    return null;
  }

  return (
    <div className="rounded-lg border border-gold/30 bg-gold/10 p-4">
      <div className="mb-2 flex items-center gap-2 text-sm font-medium text-gold">
        <ShieldQuestion className="h-4 w-4" aria-hidden="true" />
        Confirmation needed
      </div>
      <p className="text-sm leading-6 text-stone-200">
        {response.confirmation_prompt || "Review this pending action before it runs."}
      </p>
      {response.pending_action ? (
        <pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-words rounded-lg border border-line bg-black/30 p-3 text-xs leading-5 text-stone-300">
          {formatObject(response.pending_action)}
        </pre>
      ) : null}
    </div>
  );
}

function DevDebugPanel({ item }: { item: ConversationItem }) {
  const isDevelopment = process.env.NODE_ENV === "development";
  const errors = item.response?.errors ?? [];

  if (!isDevelopment || (!item.error && errors.length === 0)) {
    return null;
  }

  return (
    <details className="rounded-lg border border-coral/25 bg-coral/10 p-3 text-xs text-coral">
      <summary className="cursor-pointer font-medium">Debug</summary>
      <pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-words leading-5 text-stone-300">
        {item.error || formatObject(errors)}
      </pre>
    </details>
  );
}

export function ChatPanel() {
  const [input, setInput] = useState("");
  const [items, setItems] = useState<ConversationItem[]>([]);
  const [isSending, setIsSending] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const hasConversation = items.length > 0;
  const canSend = useMemo(() => input.trim().length > 0 && !isSending, [input, isSending]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = input.trim();

    if (!message || isSending) {
      return;
    }

    const settings = readAgentSettings();
    const itemId = crypto.randomUUID();
    const nextItem: ConversationItem = { id: itemId, prompt: message };

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

  return (
    <section className="mx-auto flex min-h-[calc(100dvh-11rem)] max-w-3xl flex-col md:min-h-[calc(100dvh-9rem)]">
      <div className="flex-1 space-y-5 pb-5">
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
                <ConfirmationCard response={item.response} />
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
        className="sticky bottom-[5.5rem] z-10 rounded-lg border border-line bg-panel/95 p-2 shadow-glow backdrop-blur-xl md:bottom-4"
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
