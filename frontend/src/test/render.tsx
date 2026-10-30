import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";

export function testQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

/** `client` lets a test seed the cache first (for example a report this session already loaded). */
export function renderWithQuery(ui: ReactElement, client = testQueryClient()) {
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}
