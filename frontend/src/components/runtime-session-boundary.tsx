"use client";
import { useEffect, useState } from "react";
import { acceptRuntimeSession, clearRuntimeSession, onRuntimeSessionChange, resumeRuntimeSession, runtimeAuthenticated, runtimeFetch, syntheticRuntime, type RuntimeBinding } from "@/lib/runtime-session";

export function RuntimeSessionBoundary({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!syntheticRuntime) return;
    let active = true;
    const unsubscribe = onRuntimeSessionChange(() => { if (active) setSignedIn(runtimeAuthenticated()); });
    void resumeRuntimeSession().then((valid) => { if (active) setSignedIn(valid); }).catch(() => {
      clearRuntimeSession(); if (active) setError("Owner session could not be recovered. Sign in again.");
    }).finally(() => { if (active) setReady(true); });
    return () => { active = false; unsubscribe(); };
  }, []);
  if (!syntheticRuntime) return children;
  if (!ready) return <p role="status">Checking synthetic owner session…</p>;
  if (signedIn) return <><div className="px-4 py-3 text-sm">Synthetic local environment · providers disabled <button type="button" disabled={busy} onClick={async () => {
    setBusy(true); setError("");
    try { const response = await runtimeFetch("/runtime/logout", { method:"POST" }); if (!response.ok) throw new Error("Logout was not confirmed. Retry before leaving this browser."); clearRuntimeSession(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Logout failed."); }
    finally { setBusy(false); }
  }}>Log out</button>{error && <p role="alert">{error}</p>}</div>{children}</>;
  return <main className="mx-auto max-w-md space-y-4 p-8"><h1 className="text-2xl">Synthetic owner login</h1><p>Local test credentials only. Providers are disabled.</p><form className="space-y-4" onSubmit={async (event) => {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const response = await fetch("/runtime-api/runtime/login", { method:"POST", credentials:"same-origin", cache:"no-store", headers:{"Content-Type":"application/json"}, body:JSON.stringify({password}) });
      setPassword("");
      if (!response.ok) throw new Error(response.status === 429 ? "Login is temporarily rate limited." : "Owner login was rejected.");
      const {csrf, ...binding} = await response.json();
      acceptRuntimeSession(binding as RuntimeBinding,csrf); setSignedIn(true);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Login unavailable."); }
    finally { setBusy(false); }
  }}><label className="block">Synthetic password<input className="block w-full rounded border bg-black p-3" type="password" autoComplete="off" required value={password} onChange={(event) => setPassword(event.target.value)} /></label><button type="submit" disabled={busy}>Sign in</button>{error && <p role="alert">{error}</p>}</form></main>;
}
