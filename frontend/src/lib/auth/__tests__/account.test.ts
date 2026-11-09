import { expect, test } from "vitest";
import { initials } from "../account";

test("initials are the first letters of the first and last word", () => {
  expect(initials("Ada Lovelace")).toBe("AL");
  expect(initials("Augusta Ada King Lovelace")).toBe("AL");
  expect(initials("  ada  ")).toBe("A");
});

test("there are no initials without a name", () => {
  expect(initials(null)).toBeNull();
  expect(initials("   ")).toBeNull();
});
