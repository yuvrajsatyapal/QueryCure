import { afterEach, describe, expect, test, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConnectionForm } from "../ConnectionForm";
import { ApiError } from "@/lib/api/client";

afterEach(cleanup);

async function fillValid(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Name"), "local orders");
  await user.type(screen.getByLabelText("Host"), "127.0.0.1");
  await user.type(screen.getByLabelText("Database"), "app");
  await user.type(screen.getByLabelText("Username"), "inspector");
  await user.type(screen.getByLabelText("Password"), "s3cret");
}

describe("ConnectionForm", () => {
  test("refuses to submit with required fields missing", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<ConnectionForm onSubmit={onSubmit} />);

    await user.click(screen.getByRole("button", { name: "Save connection" }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("Name is required.")).toBeDefined();
  });

  test("submits typed values with defaults", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<ConnectionForm onSubmit={onSubmit} />);

    await fillValid(user);
    await user.click(screen.getByRole("button", { name: "Save connection" }));

    expect(onSubmit).toHaveBeenCalledWith({
      name: "local orders",
      host: "127.0.0.1",
      port: 5432,
      dbname: "app",
      username: "inspector",
      password: "s3cret",
      sslmode: "verify-full",
      environment: "development",
    });
  });

  test("shows the backend's message and detail, not a generic HTTP error", async () => {
    const onSubmit = vi
      .fn()
      .mockRejectedValue(
        new ApiError(
          "CONNECTION_TARGET_BLOCKED",
          "Target address is not allowed on this deployment.",
          422,
          [{ field: "host", message: "link-local address" }],
          "req_1",
        ),
      );
    const user = userEvent.setup();
    render(<ConnectionForm onSubmit={onSubmit} />);

    await fillValid(user);
    await user.click(screen.getByRole("button", { name: "Save connection" }));

    expect(await screen.findByText("Target address is not allowed on this deployment.")).toBeDefined();
    expect(screen.getByText("host: link-local address")).toBeDefined();
  });

  test("the password field never renders the value as text", async () => {
    render(<ConnectionForm onSubmit={vi.fn()} />);

    expect(screen.getByLabelText("Password").getAttribute("type")).toBe("password");
  });
});
