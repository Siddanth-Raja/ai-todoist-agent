export type PendingActionReference = {
  action_id: string;
  expected_version: number;
  fingerprint: string;
};

type StorageLike = Pick<Storage, "getItem" | "setItem">;

export const CHAT_SESSION_KEY = "pcos.chatSessionId";

export function getOrCreateChatSessionId(
  storage: StorageLike,
  createId: () => string,
): string {
  const existing = storage.getItem(CHAT_SESSION_KEY)?.trim();
  if (existing) {
    return existing;
  }
  const created = createId();
  storage.setItem(CHAT_SESSION_KEY, created);
  return created;
}

export function pendingActionReference(value: unknown): PendingActionReference | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  const actionId = typeof record.action_id === "string" ? record.action_id.trim() : "";
  const version = record.version;
  const fingerprint = typeof record.fingerprint === "string" ? record.fingerprint.trim() : "";
  if (!actionId || !Number.isInteger(version) || Number(version) < 1 || fingerprint.length !== 64) {
    return null;
  }
  return {
    action_id: actionId,
    expected_version: Number(version),
    fingerprint,
  };
}
