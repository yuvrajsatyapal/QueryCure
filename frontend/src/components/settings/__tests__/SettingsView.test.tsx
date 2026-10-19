import { afterEach, expect, test, vi } from "vitest";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test/render";
import { SettingsView } from "../SettingsView";

const listCredentials = vi.fn();
const addCredential = vi.fn();
const deleteCredential = vi.fn();
vi.mock("@/lib/api/settings", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  listCredentials: (...a: unknown[]) => listCredentials(...a),
  addCredential: (...a: unknown[]) => addCredential(...a),
  deleteCredential: (...a: unknown[]) => deleteCredential(...a),
}));
vi.mock("@/lib/api/investigations", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  getModels: () => Promise.resolve({ provider: "openrouter", model: "nvidia/nemotron:free", fallbackModel: null, configured: false }),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const saved = { id: "c-1", provider: "openrouter", keyHint: "WXYZ", defaultModel: null, createdAt: "2026-10-16T10:00:00Z", lastUsedAt: null };

test("saving a key clears the field and the list shows only the hint", async () => {
  listCredentials.mockResolvedValueOnce({ items: [] }).mockResolvedValue({ items: [saved] });
  addCredential.mockResolvedValue(saved);
  renderWithQuery(<SettingsView />);
  expect(await screen.findByText(/No key saved/)).toBeTruthy();
  const field = screen.getByLabelText("OpenRouter API key") as HTMLInputElement;
  expect(field.type).toBe("password");
  await userEvent.type(field, "sk-or-v1-secret-WXYZ");
  await userEvent.click(screen.getByRole("button", { name: "Save key" }));
  await waitFor(() => expect(addCredential).toHaveBeenCalledWith({ apiKey: "sk-or-v1-secret-WXYZ", defaultModel: undefined }));
  await screen.findByText("…WXYZ");
  expect(field.value).toBe("");
  expect(document.body.textContent).not.toContain("sk-or-v1-secret");
});

test("a saved key can be deleted", async () => {
  listCredentials.mockResolvedValueOnce({ items: [saved] }).mockResolvedValue({ items: [] });
  deleteCredential.mockResolvedValue(undefined);
  renderWithQuery(<SettingsView />);
  await userEvent.click(await screen.findByRole("button", { name: "Delete key" }));
  await waitFor(() => expect(deleteCredential).toHaveBeenCalledWith("c-1"));
  expect(await screen.findByText(/No key saved/)).toBeTruthy();
});

test("appearance offers the themes as keyboard-operable radios", async () => {
  renderWithQuery(<SettingsView />);
  const group = await screen.findByRole("radiogroup", { name: "Theme" });
  const radios = within(group).getAllByRole("radio");
  expect(radios.map((r) => (r as HTMLInputElement).value)).toEqual(["dark", "light", "system"]);
  expect((within(group).getByRole("radio", { name: "Dark" }) as HTMLInputElement).checked).toBe(true);
});
