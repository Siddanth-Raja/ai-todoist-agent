"use client";

import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, RefreshCw, Save } from "lucide-react";
import { DEFAULT_BACKEND_URL, normalizeBackendUrl, readAgentSettings, saveAgentSettings } from "@/lib/settings";

type HealthStatus = "idle" | "checking" | "ok" | "warning" | "error";

type ProviderHealth = {
  status: "ok" | "warning" | "error";
  message: string;
  details?: Record<string, unknown>;
};

type SettingsHealthResponse = {
  checks: {
    todoist: ProviderHealth;
    google_calendar: ProviderHealth;
    openai: ProviderHealth;
  };
};

type HealthCheck = {
  id: "backend" | "todoist" | "google_calendar" | "openai";
  label: string;
  status: HealthStatus;
  message: string;
};

const INITIAL_CHECKS: HealthCheck[] = [
  { id: "backend", label: "Backend", status: "idle", message: "Not checked yet." },
  { id: "todoist", label: "Todoist", status: "idle", message: "Not checked yet." },
  { id: "google_calendar", label: "Google Calendar", status: "idle", message: "Not checked yet." },
  { id: "openai", label: "OpenAI", status: "idle", message: "Not checked yet." },
];

export function SettingsPanel() {
  const [backendUrl, setBackendUrl] = useState(DEFAULT_BACKEND_URL);
  const [apiKey, setApiKey] = useState("");
  const [saved, setSaved] = useState(false);
  const [healthChecks, setHealthChecks] = useState<HealthCheck[]>(INITIAL_CHECKS);
  const [isCheckingHealth, setIsCheckingHealth] = useState(false);

  useEffect(() => {
    const settings = readAgentSettings();
    setBackendUrl(settings.backendUrl);
    setApiKey(settings.apiKey);
  }, []);

  function handleSave() {
    const settings = saveAgentSettings({ backendUrl, apiKey });
    setBackendUrl(settings.backendUrl);
    setApiKey(settings.apiKey);
    setSaved(true);
    window.setTimeout(() => setSaved(false), 1800);
  }

  async function handleCheckHealth() {
    const normalizedBackendUrl = normalizeBackendUrl(backendUrl) || DEFAULT_BACKEND_URL;
    const trimmedApiKey = apiKey.trim();
    setIsCheckingHealth(true);
    setHealthChecks((checks) =>
      checks.map((check) => ({
        ...check,
        status: "checking",
        message: "Checking...",
      })),
    );

    let backendOk = false;
    try {
      const response = await fetch(`${normalizedBackendUrl}/health`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      backendOk = true;
      updateHealthCheck("backend", {
        status: "ok",
        message: `Reachable at ${normalizedBackendUrl}.`,
      });
    } catch (error) {
      updateHealthCheck("backend", {
        status: "error",
        message: `Could not reach the backend at ${normalizedBackendUrl}: ${errorMessage(error)}.`,
      });
    }

    if (!backendOk) {
      setHealthChecks((checks) =>
        checks.map((check) =>
          check.id === "backend"
            ? check
            : {
                ...check,
                status: "error",
                message: "Backend must be reachable before provider checks can run.",
              },
        ),
      );
      setIsCheckingHealth(false);
      return;
    }

    if (!trimmedApiKey) {
      setHealthChecks((checks) =>
        checks.map((check) =>
          check.id === "backend"
            ? check
            : {
                ...check,
                status: "error",
                message: "Add the AGENT_API_KEY from backend/.env, then run checks again.",
              },
        ),
      );
      setIsCheckingHealth(false);
      return;
    }

    try {
      const response = await fetch(`${normalizedBackendUrl}/settings/health`, {
        cache: "no-store",
        headers: {
          Authorization: `Bearer ${trimmedApiKey}`,
        },
      });
      const payload = (await response.json()) as SettingsHealthResponse | { detail?: string };
      if (!response.ok) {
        const detail = "detail" in payload && typeof payload.detail === "string" ? payload.detail : `HTTP ${response.status}`;
        throw new Error(detail);
      }

      const checks = (payload as SettingsHealthResponse).checks;
      setHealthChecks((currentChecks) =>
        currentChecks.map((check) => {
          if (check.id === "backend") {
            return check;
          }
          const providerCheck = checks[check.id];
          return {
            ...check,
            status: providerCheck.status,
            message: providerCheck.message,
          };
        }),
      );
    } catch (error) {
      setHealthChecks((checks) =>
        checks.map((check) =>
          check.id === "backend"
            ? check
            : {
                ...check,
                status: "error",
                message: `Could not run provider checks: ${errorMessage(error)}.`,
              },
        ),
      );
    } finally {
      setIsCheckingHealth(false);
    }
  }

  function updateHealthCheck(id: HealthCheck["id"], update: Pick<HealthCheck, "status" | "message">) {
    setHealthChecks((checks) => checks.map((check) => (check.id === id ? { ...check, ...update } : check)));
  }

  return (
    <section className="mx-auto max-w-3xl">
      <div className="glass-panel rounded-lg p-5 md:p-8">
        <div className="space-y-5">
          <label className="block">
            <span className="text-sm font-medium text-stone-200">Backend URL</span>
            <input
              value={backendUrl}
              onChange={(event) => setBackendUrl(event.target.value)}
              placeholder={DEFAULT_BACKEND_URL}
              className="mt-2 min-h-14 w-full rounded-lg border border-line bg-white/[0.04] px-4 text-base text-stone-50 outline-none transition placeholder:text-stone-600 focus:border-moss/70 focus:bg-white/[0.06]"
              inputMode="url"
            />
          </label>

          <label className="block">
            <span className="text-sm font-medium text-stone-200">API key</span>
            <input
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="AGENT_API_KEY"
              className="mt-2 min-h-14 w-full rounded-lg border border-line bg-white/[0.04] px-4 text-base text-stone-50 outline-none transition placeholder:text-stone-600 focus:border-moss/70 focus:bg-white/[0.06]"
              type="password"
              autoComplete="off"
            />
          </label>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleSave}
              className="inline-flex min-h-12 items-center justify-center gap-2 rounded-lg bg-moss px-5 text-sm font-semibold text-ink transition hover:bg-[#b7e5c9] active:scale-[0.99]"
            >
              <Save className="h-4 w-4" aria-hidden="true" />
              Save
            </button>
            <p className="text-sm text-stone-500">{saved ? "Saved locally." : "Stored in this browser."}</p>
          </div>
        </div>
      </div>

      <div className="mt-4 glass-panel rounded-lg p-5 md:p-8">
        <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-stone-50">Health checks</h2>
            <p className="mt-1 text-sm text-stone-500">Backend, Todoist, Google Calendar, and OpenAI.</p>
          </div>
          <button
            type="button"
            onClick={handleCheckHealth}
            disabled={isCheckingHealth}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-line px-4 text-sm font-semibold text-stone-100 transition hover:border-moss/60 hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isCheckingHealth ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
            )}
            Run checks
          </button>
        </div>

        <div className="grid gap-3">
          {healthChecks.map((check) => (
            <article key={check.id} className="rounded-lg border border-line bg-white/[0.03] p-4">
              <div className="flex items-start gap-3">
                <HealthIcon status={check.status} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-sm font-semibold text-stone-100">{check.label}</h3>
                    <span className={statusPillClass(check.status)}>{statusLabel(check.status)}</span>
                  </div>
                  <p className="mt-1 text-sm text-stone-400">{check.message}</p>
                  {check.id === "google_calendar" && check.status === "error" ? (
                    <p className="mt-3 rounded-lg border border-coral/30 bg-coral/10 p-3 text-sm text-stone-200">
                      Reconnect Google Calendar: run{" "}
                      <code className="rounded bg-black/30 px-1 py-0.5 text-xs text-stone-100">
                        cd backend && .venv/bin/python scripts/google_oauth_setup.py
                      </code>
                      , then restart with <code className="rounded bg-black/30 px-1 py-0.5 text-xs text-stone-100">./start.sh</code>.
                    </p>
                  ) : null}
                </div>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function HealthIcon({ status }: { status: HealthStatus }) {
  if (status === "checking") {
    return <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-stone-400" aria-hidden="true" />;
  }
  if (status === "ok") {
    return <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-moss" aria-hidden="true" />;
  }
  if (status === "warning") {
    return <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-gold" aria-hidden="true" />;
  }
  if (status === "error") {
    return <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-coral" aria-hidden="true" />;
  }
  return <RefreshCw className="mt-0.5 h-5 w-5 shrink-0 text-stone-500" aria-hidden="true" />;
}

function statusLabel(status: HealthStatus): string {
  if (status === "ok") {
    return "OK";
  }
  if (status === "warning") {
    return "Warning";
  }
  if (status === "error") {
    return "Issue";
  }
  if (status === "checking") {
    return "Checking";
  }
  return "Idle";
}

function statusPillClass(status: HealthStatus): string {
  const base = "rounded-full border px-2 py-0.5 text-[0.7rem] font-semibold uppercase";
  if (status === "ok") {
    return `${base} border-moss/30 bg-moss/10 text-moss`;
  }
  if (status === "warning") {
    return `${base} border-gold/30 bg-gold/10 text-gold`;
  }
  if (status === "error") {
    return `${base} border-coral/30 bg-coral/10 text-coral`;
  }
  if (status === "checking") {
    return `${base} border-stone-400/30 bg-white/[0.04] text-stone-300`;
  }
  return `${base} border-line bg-white/[0.03] text-stone-500`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown error";
}
