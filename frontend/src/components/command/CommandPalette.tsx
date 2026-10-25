"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import { runStatusMeta } from "@/components/ui/StatusPill";
import { ApiError } from "@/lib/api/client";
import { investigationKeys, listInvestigations } from "@/lib/api/investigations";
import { groupRunScopeItems } from "@/lib/command/runScope";
import { disambiguateTitles } from "@/lib/command/titles";
import { filterCommands } from "@/lib/keyboard/keyboard";
import type { Command, CommandGroup, PickSource, RunScope } from "./CommandProvider";
import { KeyHint } from "./KeyHint";
import { useModal } from "./useModal";

const GROUPS: CommandGroup[] = ["Actions", "Navigate", "This investigation"];
// In a run scope the run's own commands lead; the general ones follow so they never crowd the results.
const SCOPED_GROUPS: CommandGroup[] = ["This investigation", "Actions", "Navigate"];
const SEARCH_DEBOUNCE_MS = 200;
const SEARCH_LIMIT = 8;
const RECENT_LIMIT = 5;
// Per run-scope group: a short list until the user types, then more of what matches.
const SCOPE_CAP_IDLE = 5;
const SCOPE_CAP_SEARCH = 10;
// Handled inside the palette (it changes the scope and keeps the palette open).
const ENTER_SCOPE = "scope-run";
// Offered when the run has nothing matching: leaves the scope and keeps the query.
const LEAVE_SCOPE = "scope-everywhere";
const LEAVE_GROUP = "Outside this run";

interface Option {
  id: string;
  label: string;
  group: string;
  detail?: string;
  /** What tells same-titled investigations apart; never truncated, unlike the detail before it. */
  stamp?: string;
  keys?: readonly string[];
  run: (via: PickSource) => void;
}

/** Linear-style command palette (UI_UX §3.15): a modal combobox over commands and investigations.
 * Opened from an investigation it searches the selected run first (`scope`); the scope chip,
 * or Backspace in an empty field, widens it to everything. */
export function CommandPalette({ commands, scope, mac, onClose }: { commands: Command[]; scope: RunScope | null; mac: boolean; onClose: () => void }) {
  const router = useRouter();
  const dialog = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const listId = useId();
  const [text, setText] = useState("");
  const [search, setSearch] = useState("");
  const [active, setActive] = useState(0);
  const [scoped, setScoped] = useState(scope !== null);
  const [announcement, setAnnouncement] = useState("");
  // Browsers replay a mousemove at the same point after the list scrolls; only real moves select.
  const pointer = useRef<{ x: number; y: number } | null>(null);
  const region = useRef<HTMLDivElement>(null);
  useModal(dialog, onClose);
  const inScope = scoped && scope !== null;

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
    enabled: !inScope,
  });
  const searching = !inScope && (text.trim() !== search || investigations.isPending);
  const invGroup = search ? "Investigations" : "Recent investigations";

  function changeScope(next: boolean, keepQuery = false) {
    if (!scope) return;
    setScoped(next);
    const kept = keepQuery ? text : "";
    setText(kept);
    setSearch(kept.trim());
    setActive(0);
    setAnnouncement(next ? `Searching ${scope.label}` : "Searching everywhere");
    input.current?.focus();
  }

  // Only the current run's items: a scope is replaced when the selected run changes, and an item
  // stamped with another run is never shown.
  const sections = useMemo(() => {
    if (!inScope || scope.loading) return [];
    const own = scope.items.filter((i) => i.runId === scope.runId);
    return groupRunScopeItems(filterCommands(own, text), text.trim() ? SCOPE_CAP_SEARCH : SCOPE_CAP_IDLE);
  }, [inScope, scope, text]);
  const hiddenIn = new Map(sections.map((s) => [s.group as string, s.hidden]));
  const scopeEmpty = inScope && !scope.loading && sections.length === 0;
  const sameTitle = useMemo(() => disambiguateTitles(investigations.data?.items ?? []), [investigations.data]);

  const options = useMemo<Option[]>(() => {
    const fromScope: Option[] = sections.flatMap((s) => s.items.map((i) => ({ id: `run-${i.id}`, label: i.label, group: s.group, detail: i.detail, run: i.run })));
    const query = text.trim();
    const leave: Option[] = scopeEmpty
      ? [{ id: LEAVE_SCOPE, label: query ? `Search all investigations for “${query}”` : "Search all investigations", group: LEAVE_GROUP, run: () => {} }]
      : [];
    const rescope: Command[] =
      scope && !inScope
        ? [{ id: ENTER_SCOPE, label: `Search ${scope.label} only`, group: "Actions", keywords: ["scope", "this run", "narrow"], run: () => {} }]
        : [];
    const matched = filterCommands([...rescope, ...commands], text);
    const fromCommands = (inScope ? SCOPED_GROUPS : GROUPS).flatMap((g) =>
      matched
        .filter((c) => c.group === g)
        .map((c) => ({ id: c.id, label: c.label, group: g, keys: c.keys, run: c.run })),
    );
    const fromSearch =
      inScope || searching
        ? []
        : (investigations.data?.items ?? []).map((inv) => ({
            id: `inv-${inv.id}`,
            label: inv.title,
            group: invGroup,
            detail: runStatusMeta(inv.latestRun?.status).label,
            stamp: sameTitle.get(inv.id),
            run: () => router.push(`/app/investigations/${inv.id}`),
          }));
    return [...fromScope, ...leave, ...fromCommands, ...fromSearch];
  }, [sections, scopeEmpty, scope, inScope, commands, text, searching, investigations.data, sameTitle, invGroup, router]);

  const current = Math.min(active, Math.max(options.length - 1, 0));
  const optionId = (i: number) => `${listId}-opt-${i}`;
  useEffect(() => {
    // The first option also brings back its group heading and any notice above the list.
    if (current === 0 && region.current) region.current.scrollTop = 0;
    document.getElementById(optionId(current))?.scrollIntoView?.({ block: "nearest" });
    // optionId is derived from the stable listId.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current]);

  function choose(option: Option | undefined, via: PickSource) {
    if (!option) return;
    if (option.id === ENTER_SCOPE) return changeScope(true);
    if (option.id === LEAVE_SCOPE) return changeScope(false, true);
    onClose();
    option.run(via);
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
      choose(options[current], "keyboard");
    } else if (event.key === "Backspace" && inScope && text === "" && event.target === input.current) {
      event.preventDefault();
      changeScope(false);
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
          <Icon name="search" size={16} className="shrink-0 text-muted" />
          {inScope ? (
            <button
              type="button"
              onClick={() => changeScope(false)}
              aria-label={`Leave ${scope.label} scope and search everywhere`}
              title="Search everywhere (Backspace)"
              className="inline-flex h-6 max-w-[45%] shrink-0 items-center gap-1 rounded-md border border-accent/30 bg-accent-tint pr-1 pl-2 text-xs font-medium text-ink hover:border-accent/60"
            >
              <span className="truncate">{scope.label}</span>
              <Icon name="close" size={12} className="shrink-0 text-muted" />
            </button>
          ) : null}
          <input
            ref={input}
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={options.length > 0 ? optionId(current) : undefined}
            aria-label={inScope ? `Search ${scope.label} and commands` : "Search commands and investigations"}
            placeholder={inScope ? "Search this run…" : "Type a command or search investigations…"}
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
        <p role="status" aria-live="polite" className="sr-only">
          {announcement}
        </p>
        {/* A tab stop so the overflowing results can be scrolled by keyboard (axe scrollable-region-focusable);
            the same keys move the active option here as in the combobox. */}
        <div ref={region} tabIndex={0} role="region" aria-label="Results" onKeyDown={onKeyDown} className="min-h-0 overflow-y-auto p-1.5">
          {inScope && scope.loading ? <Skeleton label={`Loading ${scope.label}`} lines={2} className="px-2 py-1" /> : null}
          {inScope && scope.notice ? <p className="px-2 py-1.5 text-xs text-rejected">{scope.notice}</p> : null}
          {scopeEmpty && !scope.notice ? (
            <p className="px-2 py-1.5 text-xs text-muted">{text.trim() ? `Nothing in ${scope.label} matches.` : `Nothing recorded for ${scope.label} yet.`}</p>
          ) : null}
          <div id={listId} role="listbox" aria-label={inScope ? `${scope.label} results and commands` : "Commands and investigations"}>
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
                      onMouseMove={(e) => {
                        const last = pointer.current;
                        pointer.current = { x: e.clientX, y: e.clientY };
                        if (last && last.x === e.clientX && last.y === e.clientY) return;
                        setActive(i);
                      }}
                      onClick={() => choose(o, "pointer")}
                      // A detail stacks under its label on phones, so neither is cut to a few characters.
                      className={`flex cursor-pointer items-center justify-between gap-3 rounded-md px-2 py-1.5 text-sm ${
                        o.detail ? "max-sm:flex-col max-sm:items-stretch max-sm:gap-0" : ""
                      } ${i === current ? "bg-hover text-ink" : "text-ink"}`}
                    >
                      <span className="min-w-0 truncate">{o.label}</span>
                      {o.detail && o.stamp ? (
                        <span className="flex min-w-0 gap-1 text-xs text-muted sm:max-w-[60%] sm:shrink-0">
                          <span className="min-w-0 truncate">{o.detail}</span>
                          <span className="shrink-0 whitespace-nowrap tabular-nums">· {o.stamp}</span>
                        </span>
                      ) : o.detail ? (
                        <span className="min-w-0 truncate text-xs text-muted sm:max-w-[45%] sm:shrink-0">{o.detail}</span>
                      ) : null}
                      {o.keys ? <KeyHint keys={o.keys} mac={mac} /> : null}
                    </div>
                  ) : null,
                )}
                {hiddenIn.get(group) ? (
                  <p className="px-2 py-1 text-xs text-muted">
                    {hiddenIn.get(group)} more · {text.trim() ? "refine the search" : "type to narrow"}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
          {inScope ? null : searching ? (
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
