"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import { runStatusMeta } from "@/components/ui/StatusPill";
import { ApiError } from "@/lib/api/client";
import { investigationKeys, listInvestigations } from "@/lib/api/investigations";
import { filterCommands } from "@/lib/keyboard/keyboard";
import type { Command, CommandGroup } from "./CommandProvider";
import { KeyHint } from "./KeyHint";
import { useModal } from "./useModal";

const GROUPS: CommandGroup[] = ["Actions", "Navigate", "This investigation"];
const SEARCH_DEBOUNCE_MS = 200;
const SEARCH_LIMIT = 8;
const RECENT_LIMIT = 5;

interface Option {
  id: string;
  label: string;
  group: string;
  detail?: string;
  keys?: readonly string[];
  run: () => void;
}

/** Linear-style command palette (UI_UX §3.15): a modal combobox over commands and investigations. */
export function CommandPalette({ commands, mac, onClose }: { commands: Command[]; mac: boolean; onClose: () => void }) {
  const router = useRouter();
  const dialog = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const listId = useId();
  const [text, setText] = useState("");
  const [search, setSearch] = useState("");
  const [active, setActive] = useState(0);
  useModal(dialog, onClose);

  useEffect(() => {
    input.current?.focus();
  }, []);
  useEffect(() => {
    const timer = setTimeout(() => setSearch(text.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [text]);

  const params = search ? { q: search, limit: SEARCH_LIMIT } : { limit: RECENT_LIMIT };
  const investigations = useQuery({
    queryKey: investigationKeys.list(params),
    queryFn: ({ signal }) => listInvestigations(params, signal),
  });
  const searching = text.trim() !== search || investigations.isPending;
  const invGroup = search ? "Investigations" : "Recent investigations";

  const options = useMemo<Option[]>(() => {
    const matched = filterCommands(commands, text);
    const fromCommands = GROUPS.flatMap((g) =>
      matched.filter((c) => c.group === g).map((c) => ({ id: c.id, label: c.label, group: g, keys: c.keys, run: c.run })),
    );
    const fromSearch = searching
      ? []
      : (investigations.data?.items ?? []).map((inv) => ({
          id: `inv-${inv.id}`,
          label: inv.title,
          group: invGroup,
          detail: runStatusMeta(inv.latestRun?.status).label,
          run: () => router.push(`/app/investigations/${inv.id}`),
        }));
    return [...fromCommands, ...fromSearch];
  }, [commands, text, searching, investigations.data, invGroup, router]);

  const current = Math.min(active, Math.max(options.length - 1, 0));
  const optionId = (i: number) => `${listId}-opt-${i}`;
  useEffect(() => {
    document.getElementById(optionId(current))?.scrollIntoView?.({ block: "nearest" });
    // optionId is derived from the stable listId.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current]);

  function choose(option: Option | undefined) {
    if (!option) return;
    onClose();
    option.run();
  }

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive(options.length === 0 ? 0 : (current + 1) % options.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive(options.length === 0 ? 0 : (current - 1 + options.length) % options.length);
    } else if (event.key === "Home") {
      event.preventDefault();
      setActive(0);
    } else if (event.key === "End") {
      event.preventDefault();
      setActive(Math.max(options.length - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(options[current]);
    }
  }

  const groups = [...new Set(options.map((o) => o.group))];
  const searchError = investigations.error instanceof ApiError ? investigations.error.message : investigations.error ? "Could not load investigations." : null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh]">
      <div aria-hidden="true" onClick={onClose} className="absolute inset-0 bg-black/40" />
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        data-command-palette=""
        className="relative flex max-h-[70vh] w-full max-w-xl flex-col overflow-hidden rounded-lg border border-border bg-surface shadow-pop"
      >
        <div className="flex items-center gap-2 border-b border-border px-3 has-[input:focus-visible]:shadow-[inset_0_-2px_0_var(--accent)]">
          <Icon name="search" size={16} className="text-muted" />
          <input
            ref={input}
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={options.length > 0 ? optionId(current) : undefined}
            aria-label="Search commands and investigations"
            placeholder="Type a command or search investigations…"
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setActive(0);
            }}
            onKeyDown={onKeyDown}
            // The global :focus-visible outline is clipped here; the search row's accent underline shows focus instead.
            style={{ outline: "none" }}
            className="h-11 min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-muted"
          />
          <KeyHint keys={["Esc"]} />
        </div>
        {/* A tab stop so the overflowing results can be scrolled by keyboard (axe scrollable-region-focusable);
            the same keys move the active option here as in the combobox. */}
        <div tabIndex={0} role="region" aria-label="Results" onKeyDown={onKeyDown} className="min-h-0 overflow-y-auto p-1.5">
          <div id={listId} role="listbox" aria-label="Commands and investigations">
            {groups.map((group, g) => (
              <div key={group} role="group" aria-labelledby={`${listId}-group-${g}`} className="pb-1">
                <p id={`${listId}-group-${g}`} className="px-2 pt-2 pb-1 text-[11px] font-medium text-muted">
                  {group}
                </p>
                {options.map((o, i) =>
                  o.group === group ? (
                    <div
                      key={o.id}
                      id={optionId(i)}
                      role="option"
                      aria-selected={i === current}
                      onMouseMove={() => setActive(i)}
                      onClick={() => choose(o)}
                      className={`flex cursor-pointer items-center justify-between gap-3 rounded-md px-2 py-1.5 text-sm ${
                        i === current ? "bg-hover text-ink" : "text-ink"
                      }`}
                    >
                      <span className="min-w-0 truncate">{o.label}</span>
                      {o.detail ? <span className="shrink-0 text-xs text-muted">{o.detail}</span> : null}
                      {o.keys ? <KeyHint keys={o.keys} mac={mac} /> : null}
                    </div>
                  ) : null,
                )}
              </div>
            ))}
          </div>
          {searching ? (
            <Skeleton label="Searching investigations" lines={2} className="px-2 py-1" />
          ) : searchError ? (
            <p className="px-2 py-1.5 text-xs text-rejected">{searchError}</p>
          ) : (investigations.data?.items.length ?? 0) === 0 ? (
            <p className="px-2 py-1.5 text-xs text-muted">{search ? "No matching investigations." : "No investigations yet."}</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
