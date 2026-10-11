import { afterEach, describe, expect, test, vi } from "vitest";
import { ApiError, apiFetch } from "../client";

function mockFetch(status: number, body: unknown, contentType = "application/json") {
  const fn = vi.fn().mockResolvedValue(
    new Response(typeof body === "string" ? body : JSON.stringify(body), {
      status,
      headers: { "content-type": contentType },
    }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "qc_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

describe("apiFetch", () => {
  test("prefixes the API path, sends cookies and converts the response to camelCase", async () => {
    const fetchMock = mockFetch(200, { run_id: "r1", last_event_seq: 2 });

    const data = await apiFetch<{ runId: string; lastEventSeq: number }>("/runs/r1");

    expect(data).toEqual({ runId: "r1", lastEventSeq: 2 });
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toMatch(/\/api\/v1\/runs\/r1$/);
    expect(init.credentials).toBe("include");
  });

  test("sends snake_case bodies and the CSRF header on mutations", async () => {
    document.cookie = "qc_csrf=tok123";
    const fetchMock = mockFetch(202, { ok: true });

    await apiFetch("/investigations", { method: "POST", body: { paramSets: [], workloadId: "w" } });

    const init = fetchMock.mock.calls[0]![1];
    expect(JSON.parse(init.body)).toEqual({ param_sets: [], workload_id: "w" });
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("tok123");
  });

  test("does not send the CSRF header on GET", async () => {
    document.cookie = "qc_csrf=tok123";
    const fetchMock = mockFetch(200, {});

    await apiFetch("/me");

    expect(new Headers(fetchMock.mock.calls[0]![1].headers).has("X-CSRF-Token")).toBe(false);
  });

  test("surfaces the backend error envelope, not the generic HTTP message", async () => {
    mockFetch(422, {
      error: {
        code: "SQL_NOT_ALLOWED",
        message: "Only a single SELECT statement can be inspected.",
        status: 422,
        details: [{ field: "query", message: "statement DELETE" }],
        request_id: "req_9",
      },
    });

    const error = await apiFetch("/inspect/sql", { method: "POST", body: {} }).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      code: "SQL_NOT_ALLOWED",
      status: 422,
      message: "Only a single SELECT statement can be inspected.",
      requestId: "req_9",
      details: [{ field: "query", message: "statement DELETE" }],
    });
  });

  test("falls back to a friendly message when the error body is not an envelope", async () => {
    mockFetch(502, "<html>Bad gateway</html>", "text/html");

    const error = await apiFetch("/healthz").catch((e: unknown) => e);

    expect(error).toMatchObject({ code: "HTTP_502", status: 502 });
    expect((error as ApiError).message).not.toMatch(/Request failed/);
  });

  test("network failures become ApiError with status 0", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const error = await apiFetch("/healthz").catch((e: unknown) => e);

    expect(error).toMatchObject({ code: "NETWORK_ERROR", status: 0 });
  });
});
