const BASE = (import.meta as any).env.VITE_API_URL || "";

export class ApiError extends Error {
  readonly code: string;
  readonly retryable: boolean;
  readonly status: number;
  readonly retryAfter: string | null;
  constructor(
    message: string,
    code: string,
    retryable: boolean,
    status = 0,
    retryAfter: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.retryable = retryable;
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const cancel = () => controller.abort(options.signal?.reason);
  if (options.signal?.aborted) cancel();
  else options.signal?.addEventListener("abort", cancel, { once: true });
  const timeout = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, 120_000);
  try {
    const response = await fetch(`${BASE}/api${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...options.headers },
      signal: controller.signal,
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = body?.detail ?? body?.error ?? body;
      const message =
        typeof detail === "string"
          ? detail
          : detail?.message ||
            (Array.isArray(detail)
              ? detail.map((x: any) => x.msg).join("; ")
              : `Request failed (${response.status})`);
      const retryable =
        detail?.retryable ??
        body?.retryable ??
        [408, 429, 502, 503, 504].includes(response.status);
      throw new ApiError(
        message,
        detail?.code ??
          detail?.error_code ??
          body?.error_code ??
          `HTTP_${response.status}`,
        retryable,
        response.status,
        response.headers.get("Retry-After"),
      );
    }
    return body as T;
  } catch (error) {
    if (options.signal?.aborted)
      throw new DOMException("Request canceled", "AbortError");
    if (timedOut)
      throw new ApiError(
        "The data provider took too long to respond. Please retry.",
        "REQUEST_TIMEOUT",
        true,
      );
    if (error instanceof ApiError) throw error;
    if (error instanceof TypeError)
      throw new ApiError(
        "The research service could not be reached. Check its connection and retry.",
        "NETWORK_ERROR",
        true,
      );
    throw error;
  } finally {
    window.clearTimeout(timeout);
    options.signal?.removeEventListener("abort", cancel);
  }
}
export const post = <T>(
  path: string,
  body: unknown,
  options: RequestInit = {},
) => api<T>(path, { ...options, method: "POST", body: JSON.stringify(body) });
export const retryTransient = (attempt: number, error: Error) =>
  attempt < 1 &&
  (!(error instanceof ApiError) || (error.retryable && error.status !== 429)) &&
  !(error instanceof DOMException && error.name === "AbortError");
export function safeUrl(value: unknown): string | undefined {
  try {
    const url = new URL(String(value));
    return ["http:", "https:"].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}
