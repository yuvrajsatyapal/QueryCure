import { toCamel, toSnake } from "./case";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const API_PREFIX = "/api/v1";

export interface ApiErrorDetail {
  field?: string;
  message: string;
}

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: ApiErrorDetail[];
  readonly requestId: string | null;

  constructor(code: string, message: string, status: number, details: ApiErrorDetail[], requestId: string | null) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
    this.requestId = requestId;
  }
}

interface ErrorEnvelope {
  error?: { code?: unknown; message?: unknown; details?: unknown; request_id?: unknown };
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.split("; ").find((part) => part.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

async function toApiError(response: Response): Promise<ApiError> {
  let envelope: ErrorEnvelope | null = null;
  if (response.headers.get("content-type")?.includes("application/json")) {
    envelope = (await response.json().catch(() => null)) as ErrorEnvelope | null;
  }
  const e = envelope?.error;
  if (e && typeof e.code === "string" && typeof e.message === "string") {
    const details = Array.isArray(e.details) ? (e.details as ApiErrorDetail[]) : [];
    const requestId = typeof e.request_id === "string" ? e.request_id : null;
    return new ApiError(e.code, e.message, response.status, details, requestId);
  }
  return new ApiError(
    `HTTP_${response.status}`,
    "The server could not complete the request. Please try again.",
    response.status,
    [],
    null,
  );
}

export interface ApiRequest {
  method?: "GET" | "POST" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

export async function apiFetch<T>(path: string, request: ApiRequest = {}): Promise<T> {
  const method = request.method ?? "GET";
  const headers = new Headers({ Accept: "application/json" });
  if (request.body !== undefined) headers.set("Content-Type", "application/json");
  if (method !== "GET") {
    const csrf = readCookie("qd_csrf");
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${API_PREFIX}${path}`, {
      method,
      headers,
      credentials: "include",
      body: request.body === undefined ? undefined : JSON.stringify(toSnake(request.body)),
      signal: request.signal,
    });
  } catch {
    throw new ApiError("NETWORK_ERROR", "Could not reach the QueryDoctor API.", 0, [], null);
  }
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return toCamel(await response.json()) as T;
}
