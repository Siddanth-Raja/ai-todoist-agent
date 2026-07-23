"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { apiRequest } from "@/lib/api";
import { readAgentSettings, type AgentSettings } from "@/lib/settings";
import {
  retainedQueryStore,
  type RetainedQuerySnapshot,
} from "@/lib/retained-query-store";

const connectionScopes = new Map<string, Map<string, object>>();
const FOCUS_REVALIDATE_AFTER_MS = 60_000;

function connectionScope(settings: AgentSettings): object {
  let keys = connectionScopes.get(settings.backendUrl);
  if (!keys) {
    keys = new Map();
    connectionScopes.set(settings.backendUrl, keys);
  }

  let scope = keys.get(settings.apiKey);
  if (!scope) {
    scope = {};
    keys.set(settings.apiKey, scope);
  }
  return scope;
}

export type RetainedApiQuery<T> = RetainedQuerySnapshot<T> & {
  refresh: () => Promise<T>;
};

export function useRetainedApiQuery<T>(
  key: string,
  load?: () => Promise<T>,
): RetainedApiQuery<T> {
  const settings = readAgentSettings();
  const scope = connectionScope(settings);
  const loader = useMemo(() => load ?? (() => apiRequest<T>(key)), [key, load]);
  const [snapshot, setSnapshot] = useState(() =>
    retainedQueryStore.snapshot<T>(scope, key),
  );

  const refresh = useCallback(
    () => retainedQueryStore.refresh(scope, key, loader, { force: true }),
    [key, loader, scope],
  );

  useEffect(() => {
    setSnapshot(retainedQueryStore.snapshot<T>(scope, key));
    const unsubscribe = retainedQueryStore.subscribe(scope, key, () => {
      setSnapshot(retainedQueryStore.snapshot<T>(scope, key));
    });

    void retainedQueryStore.refresh(scope, key, loader).catch(() => undefined);

    const revalidateOnFocus = () => {
      const current = retainedQueryStore.snapshot<T>(scope, key);
      if (
        document.visibilityState === "visible" &&
        current.lastSuccessAt !== null &&
        Date.now() - current.lastSuccessAt >= FOCUS_REVALIDATE_AFTER_MS
      ) {
        void retainedQueryStore.refresh(scope, key, loader).catch(() => undefined);
      }
    };
    window.addEventListener("focus", revalidateOnFocus);
    document.addEventListener("visibilitychange", revalidateOnFocus);

    return () => {
      unsubscribe();
      window.removeEventListener("focus", revalidateOnFocus);
      document.removeEventListener("visibilitychange", revalidateOnFocus);
    };
  }, [key, loader, scope]);

  return { ...snapshot, refresh };
}
