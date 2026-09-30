import { runtimeScope, syntheticRuntime } from "./runtime-session";
export const STORAGE_KEYS = {
  backendUrl: "pcos.backendUrl",
  collegeUrl: "pcos.collegeUrl",
  apiKey: "pcos.apiKey",
} as const;

export type AgentSettings = {
  backendUrl: string;
  collegeUrl: string;
  apiKey: string;
};

export const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";
export const DEFAULT_COLLEGE_URL = "http://127.0.0.1:8003";

export function normalizeBackendUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

export function readAgentSettings(): AgentSettings {
  if (syntheticRuntime) return { backendUrl:"/runtime-api", collegeUrl:"/runtime-api", apiKey:runtimeScope() };
  if (typeof window === "undefined") {
    return { backendUrl: DEFAULT_BACKEND_URL, collegeUrl: DEFAULT_COLLEGE_URL, apiKey: "" };
  }

  return {
    backendUrl:
      normalizeBackendUrl(localStorage.getItem(STORAGE_KEYS.backendUrl) || "") ||
      DEFAULT_BACKEND_URL,
    collegeUrl:
      normalizeBackendUrl(localStorage.getItem(STORAGE_KEYS.collegeUrl) || "") ||
      DEFAULT_COLLEGE_URL,
    apiKey: localStorage.getItem(STORAGE_KEYS.apiKey) || "",
  };
}

export function saveAgentSettings(settings: AgentSettings): AgentSettings {
  const normalized = {
    backendUrl: normalizeBackendUrl(settings.backendUrl) || DEFAULT_BACKEND_URL,
    collegeUrl: normalizeBackendUrl(settings.collegeUrl) || DEFAULT_COLLEGE_URL,
    apiKey: settings.apiKey.trim(),
  };

  localStorage.setItem(STORAGE_KEYS.backendUrl, normalized.backendUrl);
  localStorage.setItem(STORAGE_KEYS.collegeUrl, normalized.collegeUrl);
  localStorage.setItem(STORAGE_KEYS.apiKey, normalized.apiKey);

  return normalized;
}
