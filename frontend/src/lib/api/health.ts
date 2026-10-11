import type { CamelCasedPropertiesDeep } from "type-fest";
import { apiFetch } from "./client";
import type { components } from "./generated/schema";

export type Health = CamelCasedPropertiesDeep<components["schemas"]["HealthResponse"]>;

export function getHealth(signal?: AbortSignal): Promise<Health> {
  return apiFetch<Health>("/healthz", { signal });
}
