"use client";

import { useEffect, useState } from "react";
import { Save } from "lucide-react";
import { DEFAULT_BACKEND_URL, readAgentSettings, saveAgentSettings } from "@/lib/settings";

export function SettingsPanel() {
  const [backendUrl, setBackendUrl] = useState(DEFAULT_BACKEND_URL);
  const [apiKey, setApiKey] = useState("");
  const [saved, setSaved] = useState(false);

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
    </section>
  );
}
