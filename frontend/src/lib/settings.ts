export const STORAGE_KEYS = {
  backendUrl: "pcos.backendUrl",
  apiKey: "pcos.apiKey",
} as const;

export type AgentSettings = {
  backendUrl: string;
  apiKey: string;
};

export const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";

export function normalizeBackendUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

export function readAgentSettings(): AgentSettings {
  if (typeof window === "undefined") {
    return { backendUrl: DEFAULT_BACKEND_URL, apiKey: "" };
  }

  return {
    backendUrl:
      normalizeBackendUrl(localStorage.getItem(STORAGE_KEYS.backendUrl) || "") ||
      DEFAULT_BACKEND_URL,
    apiKey: localStorage.getItem(STORAGE_KEYS.apiKey) || "",
  };
}

export function saveAgentSettings(settings: AgentSettings): AgentSettings {
  const normalized = {
    backendUrl: normalizeBackendUrl(settings.backendUrl) || DEFAULT_BACKEND_URL,
    apiKey: settings.apiKey.trim(),
  };

  localStorage.setItem(STORAGE_KEYS.backendUrl, normalized.backendUrl);
  localStorage.setItem(STORAGE_KEYS.apiKey, normalized.apiKey);

  return normalized;
}
