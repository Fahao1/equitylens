import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, retryTransient } from "./api";
afterEach(() => vi.unstubAllGlobals());
describe("structured API failures and cancellation", () => {
  it("preserves provider error identity, retryability and retry-after", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            ticker: "ORCL",
            status: "error",
            error_code: "RATE_LIMITED",
            message: "Yahoo is rate limited.",
            retryable: true,
          }),
          { status: 429, headers: { "Retry-After": "60" } },
        ),
      ),
    );
    expect(
      retryTransient(0, new ApiError("Wait", "RATE_LIMITED", true, 429)),
    ).toBe(false);
    await expect(api("/stocks/ORCL/research")).rejects.toMatchObject({
      name: "ApiError",
      code: "RATE_LIMITED",
      retryable: true,
      status: 429,
      retryAfter: "60",
    });
  });
  it("explains an unavailable local backend as a retryable proxy502", async () => {
    const detail = {
      code: "RESEARCH_SERVICE_UNAVAILABLE",
      message:
        "The EquityLens research service is not running or cannot be reached. Start the backend, then retry.",
      retryable: true,
    };
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ detail }), { status: 502 }),
        ),
    );
    await expect(api("/stocks/QQQ/research")).rejects.toMatchObject({
      code: "RESEARCH_SERVICE_UNAVAILABLE",
      status: 502,
      retryable: true,
      message: detail.message,
    });
  });
  it("preserves a real backend500 and its original analysis error", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({
              detail: {
                code: "INTERNAL_ERROR",
                message: "Analysis failed.",
                retryable: false,
              },
            }),
            { status: 500 },
          ),
        ),
    );
    await expect(api("/stocks/QQQ/research")).rejects.toMatchObject({
      code: "INTERNAL_ERROR",
      status: 500,
      retryable: false,
      message: "Analysis failed.",
    });
  });
  it("keeps a permanent invalid-symbol error non-retryable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              code: "INVALID_TICKER_FORMAT",
              message: "Invalid ticker format.",
              retryable: false,
            },
          }),
          { status: 422 },
        ),
      ),
    );
    let failure: Error | undefined;
    try {
      await api("/stocks/INVALID/research");
    } catch (error) {
      failure = error as Error;
    }
    expect(failure).toBeInstanceOf(ApiError);
    expect(retryTransient(0, failure!)).toBe(false);
  });
  it("forwards external cancellation and does not mislabel it as a provider timeout", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url, options: RequestInit) =>
          new Promise((_resolve, reject) =>
            options.signal?.addEventListener("abort", () =>
              reject(new DOMException("Aborted", "AbortError")),
            ),
          ),
      ),
    );
    const controller = new AbortController();
    const request = api("/search?q=Oracle", { signal: controller.signal });
    controller.abort();
    await expect(request).rejects.toMatchObject({
      name: "AbortError",
      message: "Request canceled",
    });
  });
  it("classifies the bounded timeout separately from an explicit cancellation", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url, options: RequestInit) =>
          new Promise((_resolve, reject) =>
            options.signal?.addEventListener("abort", () =>
              reject(new DOMException("Aborted", "AbortError")),
            ),
          ),
      ),
    );
    const request = api("/stocks/ORCL/history");
    const assertion = expect(request).rejects.toMatchObject({
      code: "REQUEST_TIMEOUT",
      retryable: true,
    });
    await vi.advanceTimersByTimeAsync(120000);
    await assertion;
  });
});
