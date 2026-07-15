const isoDatePrefix = /^(\d{4})-(\d{2})-(\d{2})(?=$|T)/;

type TaskDateFields = {
  due_date?: unknown;
  due?: unknown;
};

export function parseTaskDate(value: unknown): Date | null {
  if (typeof value !== "string") {
    return null;
  }

  const normalized = value.trim();
  if (!normalized) {
    return null;
  }

  const dateParts = normalized.match(isoDatePrefix);
  if (!dateParts || !isValidCalendarDate(dateParts)) {
    return null;
  }

  const parsed = new Date(
    normalized.length === 10 ? `${normalized}T12:00:00` : normalized,
  );
  return Number.isFinite(parsed.getTime()) ? parsed : null;
}

export function taskDateTime(value: unknown): number | null {
  const parsed = parseTaskDate(value);
  if (!parsed) {
    return null;
  }

  const timestamp = parsed.getTime();
  return Number.isFinite(timestamp) ? timestamp : null;
}

export function taskDueDateValue(task: TaskDateFields): string | null {
  const nestedDue =
    typeof task.due === "object" && task.due !== null
      ? (task.due as { date?: unknown }).date
      : null;

  for (const candidate of [task.due_date, nestedDue]) {
    if (typeof candidate === "string" && parseTaskDate(candidate)) {
      return candidate.trim();
    }
  }
  return null;
}

export function formatTaskDate(
  value: unknown,
  options: Intl.DateTimeFormatOptions,
  fallback: string,
): string {
  const parsed = parseTaskDate(value);
  if (!parsed || !Number.isFinite(parsed.getTime())) {
    return fallback;
  }

  return new Intl.DateTimeFormat(undefined, options).format(parsed);
}

function isValidCalendarDate(parts: RegExpMatchArray): boolean {
  const year = Number(parts[1]);
  const month = Number(parts[2]);
  const day = Number(parts[3]);
  const candidate = new Date(Date.UTC(year, month - 1, day));

  return (
    Number.isFinite(candidate.getTime())
    && candidate.getUTCFullYear() === year
    && candidate.getUTCMonth() === month - 1
    && candidate.getUTCDate() === day
  );
}
