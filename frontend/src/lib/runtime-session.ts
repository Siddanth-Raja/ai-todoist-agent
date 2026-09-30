/** Same-origin synthetic owner sessions. Never read provider credentials. */
export const syntheticRuntime = process.env.NEXT_PUBLIC_PCOS_SYNTHETIC_RUNTIME === "1";
export type RuntimeBinding = { environment_id: string; actor_id: string; workspace_id: string; auth_generation: string };
const SESSION_KEY = "pcos.runtime.session.v1";
let current: { binding: RuntimeBinding; csrf: string } | null = null;
let epoch = 0;
const listeners = new Set<() => void>();
export function onRuntimeSessionChange(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; }
function bindingScope(binding: RuntimeBinding) { return JSON.stringify([binding.environment_id,binding.actor_id,binding.workspace_id,binding.auth_generation]); }
export function runtimeScope() { return current ? bindingScope(current.binding) : "unauthenticated"; }
export function runtimeAuthenticated() { return Boolean(current); }
export function clearRuntimeSession() {
  current = null; epoch += 1;
  try {
    sessionStorage.removeItem(SESSION_KEY);
    for (const key of Object.keys(sessionStorage)) if (key.startsWith("pcos.college.delivery.")) sessionStorage.removeItem(key);
  } finally {
    // Even blocked browser storage must immediately unmount authenticated views.
    listeners.forEach((listener) => listener());
  }
}
export function acceptRuntimeSession(binding: RuntimeBinding, csrf: string) {
  if (![binding.environment_id,binding.actor_id,binding.workspace_id,binding.auth_generation].every((value) => typeof value === "string" && value.length > 0) || typeof csrf !== "string" || !csrf) throw new Error("Invalid owner session.");
  const scope = bindingScope(binding);
  const retained = sessionStorage.getItem(SESSION_KEY);
  if (retained && bindingScope(JSON.parse(retained).binding) !== scope) clearRuntimeSession();
  sessionStorage.setItem(SESSION_KEY,JSON.stringify({binding,csrf}));
  current = { binding, csrf }; epoch += 1;
  listeners.forEach((listener) => listener());
}
export async function resumeRuntimeSession() {
  const retained = sessionStorage.getItem(SESSION_KEY);
  const response = await fetch("/runtime-api/runtime/session", { credentials:"same-origin", cache:"no-store" });
  if (!response.ok || !retained) { clearRuntimeSession(); return false; }
  const binding: RuntimeBinding = await response.json();
  const saved = JSON.parse(retained);
  if (bindingScope(saved.binding) !== bindingScope(binding)) { clearRuntimeSession(); return false; }
  acceptRuntimeSession(binding,saved.csrf);
  return true;
}
export async function runtimeFetch(path: string, options: RequestInit = {}) {
  if (!current) throw new Error("Sign in to the synthetic owner environment first.");
  const began = epoch;
  const headers = new Headers(options.headers);
  headers.delete("Authorization");
  if (options.body !== undefined) headers.set("Content-Type","application/json");
  if (options.method && options.method !== "GET") headers.set("X-CSRF-Token",current.csrf);
  const response = await fetch(`/runtime-api${path}`, { ...options, headers, credentials:"same-origin", cache:"no-store" });
  const content = await response.text();
  if (began !== epoch) throw new Error("Owner session changed; the previous result was discarded.");
  if (response.status === 401) clearRuntimeSession();
  return new Response(content, {status:response.status, headers:response.headers});
}
