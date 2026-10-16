import { apiFetch } from "./client";
import type { DemoDetail, DemoGallery, DemoVerification } from "./types";

/** Public, read-only gallery: no session needed, nothing runs. */
export const demoKeys = {
  gallery: ["demo", "gallery"] as const,
  detail: (slug: string) => ["demo", "gallery", slug] as const,
  verification: (slug: string) => ["demo", "gallery", slug, "verification"] as const,
};

export const getDemoGallery = (signal?: AbortSignal) => apiFetch<DemoGallery>("/demo/gallery", { signal });
export const getDemo = (slug: string, signal?: AbortSignal) =>
  apiFetch<DemoDetail>(`/demo/gallery/${encodeURIComponent(slug)}`, { signal });
export const verifyDemo = (slug: string, signal?: AbortSignal) =>
  apiFetch<DemoVerification>(`/demo/gallery/${encodeURIComponent(slug)}/verification`, { signal });
