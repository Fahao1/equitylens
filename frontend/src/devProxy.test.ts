import { describe, expect, it, vi } from "vitest";
import type { IncomingMessage, ServerResponse } from "node:http";
import { handleProxyConnectionError } from "../devProxy";

function responseFixture() {
  const response = {
    headersSent: false,
    writableEnded: false,
    writeHead: vi.fn(),
    end: vi.fn(),
  };
  return response;
}
describe("development proxy connection failures", () => {
  it.each(["ECONNREFUSED", "ECONNRESET", "ENOTFOUND", "ETIMEDOUT"])(
    "returns a retryable JSON502 for %s",
    (code) => {
      const response = responseFixture();
      handleProxyConnectionError(
        Object.assign(new Error("connection failed"), { code }),
        {} as IncomingMessage,
        response as unknown as ServerResponse,
      );
      expect(response.writeHead).toHaveBeenCalledWith(502, {
        "Content-Type": "application/json",
      });
      expect(JSON.parse(response.end.mock.calls[0][0])).toMatchObject({
        error_code: "RESEARCH_SERVICE_UNAVAILABLE",
        retryable: true,
        detail: {
          code: "RESEARCH_SERVICE_UNAVAILABLE",
          message: expect.stringContaining("Start the backend"),
          retryable: true,
        },
      });
    },
  );
  it("does not reclassify an internal proxy failure as a stopped backend", () => {
    const response = responseFixture();
    handleProxyConnectionError(
      new Error("unrelated failure"),
      {} as IncomingMessage,
      response as unknown as ServerResponse,
    );
    expect(response.writeHead).not.toHaveBeenCalled();
  });
  it.each(["headersSent", "writableEnded"] as const)(
    "does not write over an existing response when %s",
    (flag) => {
      const response = responseFixture();
      response[flag] = true;
      handleProxyConnectionError(
        Object.assign(new Error("connection failed"), { code: "ECONNREFUSED" }),
        {} as IncomingMessage,
        response as unknown as ServerResponse,
      );
      expect(response.writeHead).not.toHaveBeenCalled();
    },
  );
});
