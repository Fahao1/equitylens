import type { IncomingMessage, ServerResponse } from "node:http";
import type { Socket } from "node:net";

const connectionErrors = new Set([
  "ECONNREFUSED",
  "ECONNRESET",
  "ENOTFOUND",
  "EAI_AGAIN",
  "EHOSTUNREACH",
  "ENETUNREACH",
  "ETIMEDOUT",
]);

export function handleProxyConnectionError(
  error: Error & { code?: string },
  _request: IncomingMessage,
  response: ServerResponse | Socket,
) {
  if (
    !connectionErrors.has(error.code || "") ||
    !("writeHead" in response) ||
    response.headersSent ||
    response.writableEnded
  )
    return;
  const failure = {
    code: "RESEARCH_SERVICE_UNAVAILABLE",
    message:
      "The EquityLens research service is not running or cannot be reached. Start the backend, then retry.",
    retryable: true,
  };
  response.writeHead(502, { "Content-Type": "application/json" });
  response.end(
    JSON.stringify({
      status: "error",
      error_code: failure.code,
      message: failure.message,
      retryable: true,
      detail: failure,
    }),
  );
}
