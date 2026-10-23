import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { useRunEvents } from "../useRunEvents";

class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static instances: FakeEventSource[] = [];
  readyState = FakeEventSource.CONNECTING;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, (m: MessageEvent<string>) => void>();
  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: (m: MessageEvent<string>) => void) {
    this.listeners.set(type, fn);
  }
  close() {
    this.readyState = FakeEventSource.CLOSED;
  }
  emit(type: string, seq: number, payload: Record<string, unknown> = {}) {
    const data = JSON.stringify({ run_id: "r1", seq, ts: "t", type, payload });
    this.listeners.get(type)?.({ data } as MessageEvent<string>);
  }
  fail() {
    this.readyState = FakeEventSource.CLOSED; // an HTTP error: the browser gives up
    this.onerror?.();
  }
}

function nth(i: number): FakeEventSource {
  const source = FakeEventSource.instances.at(i);
  if (!source) throw new Error(`no EventSource #${i}`);
  return source;
}

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
);

beforeEach(() => {
  vi.useFakeTimers();
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("after an HTTP error the stream reconnects with after_seq and keeps the events", () => {
  const { result } = renderHook(() => useRunEvents("r1"), { wrapper });
  const first = nth(0);
  expect(first.url).toMatch(/\/api\/v1\/runs\/r1\/events$/);
  act(() => first.emit("node.started", 1));
  act(() => first.emit("node.started", 2));
  act(() => first.fail());
  expect(FakeEventSource.instances).toHaveLength(1);
  act(() => vi.advanceTimersByTime(1000));
  expect(FakeEventSource.instances).toHaveLength(2);
  expect(nth(1).url).toMatch(/\/events\?after_seq=2$/);
  expect(result.current.events.map((e) => e.seq)).toEqual([1, 2]);
});

test("reconnects stop after the limit and after a terminal event", () => {
  renderHook(() => useRunEvents("r1"), { wrapper });
  for (let i = 0; i < 10; i += 1) {
    act(() => nth(-1).fail());
    act(() => vi.advanceTimersByTime(30_000));
  }
  expect(FakeEventSource.instances).toHaveLength(7); // the first connection plus 6 retries

  FakeEventSource.instances = [];
  renderHook(() => useRunEvents("r2"), { wrapper });
  const source = nth(0);
  act(() => source.emit("run.status_changed", 1, { from: "running", to: "completed" }));
  act(() => source.fail());
  act(() => vi.advanceTimersByTime(30_000));
  expect(FakeEventSource.instances).toHaveLength(1);
});

test("unmounting cancels a pending reconnect", () => {
  const { unmount } = renderHook(() => useRunEvents("r1"), { wrapper });
  act(() => nth(0).fail());
  unmount();
  act(() => vi.advanceTimersByTime(30_000));
  expect(FakeEventSource.instances).toHaveLength(1);
});
