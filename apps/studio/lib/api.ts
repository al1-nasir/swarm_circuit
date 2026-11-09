export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch("/api/backend/" + path, {
    ...options,
    cache: "no-store",
  });
  const body = await response.json();
  if (!response.ok)
    throw new ApiError(
      response.status,
      body.code || "request_failed",
      body.message || "Request failed. Refresh to reconcile.",
    );
  return body as T;
}

export async function apiWindow<T>(path: string, count: number, limit: number) {
  const items: T[] = [];
  let cursor: string | null = null;
  const seen = new Set<string>();
  do {
    const page: { items: T[]; next_cursor?: string | null } = await api(
      `${path}?limit=${limit}${cursor ? "&cursor=" + encodeURIComponent(cursor) : ""}`,
    );
    items.push(...page.items);
    cursor = page.next_cursor || null;
    if (cursor && seen.has(cursor))
      throw new ApiError(
        502,
        "cursor_repeated",
        "History cursor did not advance.",
      );
    if (cursor) seen.add(cursor);
  } while (cursor && items.length < count);
  return { items, next_cursor: cursor };
}
