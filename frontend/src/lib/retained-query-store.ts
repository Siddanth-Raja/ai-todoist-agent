export type RetainedQuerySnapshot<T> = {
  data: T | null;
  initialError: string | null;
  refreshError: string | null;
  isInitialLoading: boolean;
  isRefreshing: boolean;
  lastSuccessAt: number | null;
};

type QueryEntry<T> = RetainedQuerySnapshot<T> & {
  sequence: number;
  inFlight: Promise<T> | null;
  listeners: Set<() => void>;
};

function emptySnapshot<T>(): RetainedQuerySnapshot<T> {
  return {
    data: null,
    initialError: null,
    refreshError: null,
    isInitialLoading: true,
    isRefreshing: false,
    lastSuccessAt: null,
  };
}

function messageFor(error: unknown): string {
  return error instanceof Error ? error.message : "Unable to refresh this page.";
}

export class RetainedQueryStore {
  private scopes = new WeakMap<object, Map<string, QueryEntry<unknown>>>();

  private entry<T>(scope: object, key: string): QueryEntry<T> {
    let queries = this.scopes.get(scope);
    if (!queries) {
      queries = new Map();
      this.scopes.set(scope, queries);
    }

    let entry = queries.get(key) as QueryEntry<T> | undefined;
    if (!entry) {
      entry = {
        ...emptySnapshot<T>(),
        sequence: 0,
        inFlight: null,
        listeners: new Set(),
      };
      queries.set(key, entry as QueryEntry<unknown>);
    }
    return entry;
  }

  snapshot<T>(scope: object, key: string): RetainedQuerySnapshot<T> {
    const entry = this.entry<T>(scope, key);
    return {
      data: entry.data,
      initialError: entry.initialError,
      refreshError: entry.refreshError,
      isInitialLoading: entry.isInitialLoading,
      isRefreshing: entry.isRefreshing,
      lastSuccessAt: entry.lastSuccessAt,
    };
  }

  subscribe(scope: object, key: string, listener: () => void): () => void {
    const entry = this.entry(scope, key);
    entry.listeners.add(listener);
    return () => entry.listeners.delete(listener);
  }

  private emit(entry: QueryEntry<unknown>): void {
    entry.listeners.forEach((listener) => listener());
  }

  refresh<T>(
    scope: object,
    key: string,
    load: () => Promise<T>,
    options: { force?: boolean } = {},
  ): Promise<T> {
    const entry = this.entry<T>(scope, key);
    if (entry.inFlight && !options.force) {
      return entry.inFlight;
    }

    const sequence = entry.sequence + 1;
    entry.sequence = sequence;
    if (entry.data === null) {
      entry.isInitialLoading = true;
      entry.initialError = null;
    } else {
      entry.isRefreshing = true;
    }
    this.emit(entry as QueryEntry<unknown>);

    const request = load()
      .then((data) => {
        if (entry.sequence === sequence) {
          entry.data = data;
          entry.initialError = null;
          entry.refreshError = null;
          entry.isInitialLoading = false;
          entry.isRefreshing = false;
          entry.lastSuccessAt = Date.now();
          this.emit(entry as QueryEntry<unknown>);
        }
        return data;
      })
      .catch((error: unknown) => {
        if (entry.sequence === sequence) {
          if (entry.data === null) {
            entry.initialError = messageFor(error);
          } else {
            entry.refreshError = messageFor(error);
          }
          entry.isInitialLoading = false;
          entry.isRefreshing = false;
          this.emit(entry as QueryEntry<unknown>);
        }
        throw error;
      })
      .finally(() => {
        if (entry.inFlight === request) {
          entry.inFlight = null;
        }
      });

    entry.inFlight = request;
    return request;
  }
}

export const retainedQueryStore = new RetainedQueryStore();
