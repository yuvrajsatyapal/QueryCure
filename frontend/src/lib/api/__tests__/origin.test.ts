import { expect, test } from "vitest";
import { DEV_API_ORIGIN, resolveApiOrigin } from "../origin";

test("development falls back to the local API", () => {
  expect(resolveApiOrigin(undefined, { production: false })).toBe(DEV_API_ORIGIN);
  expect(resolveApiOrigin("", { production: false })).toBe(DEV_API_ORIGIN);
});

test("a production build without the API origin fails instead of shipping localhost", () => {
  expect(() => resolveApiOrigin(undefined, { production: true })).toThrow(/NEXT_PUBLIC_API_BASE_URL/);
  expect(() => resolveApiOrigin("  ", { production: true })).toThrow(/NEXT_PUBLIC_API_BASE_URL/);
});

test("production requires an https origin unless it is loopback", () => {
  expect(resolveApiOrigin("https://api.example.dev", { production: true })).toBe("https://api.example.dev");
  expect(resolveApiOrigin("http://localhost:8100", { production: true })).toBe("http://localhost:8100");
  expect(resolveApiOrigin("http://127.0.0.1:8000", { production: true })).toBe("http://127.0.0.1:8000");
  expect(() => resolveApiOrigin("http://api.example.dev", { production: true })).toThrow(/https/);
});

test("the value must be a bare origin", () => {
  expect(resolveApiOrigin("https://api.example.dev/", { production: true })).toBe("https://api.example.dev");
  for (const bad of ["api.example.dev", "https://api.example.dev/v1", "https://api.example.dev?x=1", "ftp://x.dev", "https://u:p@api.example.dev"]) {
    expect(() => resolveApiOrigin(bad, { production: true }), bad).toThrow(/NEXT_PUBLIC_API_BASE_URL/);
  }
  // Development validates too: a typo should not silently point the app somewhere else.
  expect(() => resolveApiOrigin("localhost:8000", { production: false })).toThrow();
});
