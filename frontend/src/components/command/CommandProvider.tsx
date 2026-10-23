"use client";

import { useTheme } from "next-themes";
import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { createSequenceMatcher, isTypingTarget } from "@/lib/keyboard/keyboard";
import { CommandPalette } from "./CommandPalette";
import { ShortcutsDialog } from "./ShortcutsDialog";

export type CommandGroup = "Actions" | "Navigate" | "This investigation";

/** Every command is an existing route or action (UI_UX §3.15); nothing here is a placeholder. */
export interface Command {
  id: string;
  label: string;
  group: CommandGroup;
  keywords?: readonly string[];
  /** One key or a two-key sequence, e.g. ["g", "d"]. */
  keys?: readonly string[];
  run: () => void;
}

interface CommandContextValue {
  openPalette: () => void;
  register: (owner: string, commands: Command[]) => () => void;
  mac: boolean;
}

const CommandContext = createContext<CommandContextValue | null>(null);
const SEQUENCE_TIMEOUT_MS = 1000;

const subscribe = () => () => {};
const detectMac = () => /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

export function useCommands(): CommandContextValue {
  const value = useContext(CommandContext);
  if (!value) throw new Error("useCommands must be used inside CommandProvider");
  return value;
}

/** Page-level commands (shown in the palette and bound to their keys) while the page is mounted. */
export function useContextCommands(owner: string, commands: Command[]) {
  const value = useContext(CommandContext);
  const register = value?.register;
  useEffect(() => (register ? register(owner, commands) : undefined), [register, owner, commands]);
}

export function CommandProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { resolvedTheme, setTheme } = useTheme();
  const mac = useSyncExternalStore(subscribe, detectMac, () => false);
  const [palette, setPalette] = useState(false);
  const [help, setHelp] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const [contextual, setContextual] = useState<Record<string, Command[]>>({});

  const register = useCallback((owner: string, commands: Command[]) => {
    setContextual((current) => ({ ...current, [owner]: commands }));
    return () =>
      setContextual((current) => {
        const next = { ...current };
        delete next[owner];
        return next;
      });
  }, []);

  const base = useMemo<Command[]>(() => {
    const dark = resolvedTheme !== "light";
    return [
      { id: "new", label: "New investigation", group: "Actions", keywords: ["create", "start"], keys: ["c"], run: () => router.push("/app/investigations/new") },
      {
        id: "theme",
        label: dark ? "Switch to light theme" : "Switch to dark theme",
        group: "Actions",
        keywords: ["appearance", "mode", "theme"],
        run: () => {
          setTheme(dark ? "light" : "dark");
          setAnnouncement(dark ? "Light theme on" : "Dark theme on");
        },
      },
      { id: "shortcuts", label: "Keyboard shortcuts", group: "Actions", keywords: ["help", "keys"], keys: ["?"], run: () => setHelp(true) },
      { id: "go-dashboard", label: "Go to Dashboard", group: "Navigate", keywords: ["home"], keys: ["g", "d"], run: () => router.push("/app") },
      { id: "go-history", label: "Go to History", group: "Navigate", keywords: ["investigations", "runs"], keys: ["g", "h"], run: () => router.push("/app/history") },
      { id: "go-connections", label: "Go to Connections", group: "Navigate", keywords: ["database"], keys: ["g", "c"], run: () => router.push("/app/connections") },
      { id: "go-settings", label: "Go to Settings", group: "Navigate", keywords: ["preferences", "keys"], keys: ["g", "s"], run: () => router.push("/app/settings") },
      { id: "go-demo", label: "Go to Demo gallery", group: "Navigate", keywords: ["prerecorded", "examples"], run: () => router.push("/demo") },
    ];
  }, [resolvedTheme, router, setTheme]);

  const commands = useMemo(() => [...base, ...Object.values(contextual).flat()], [base, contextual]);
  const commandsRef = useRef(commands);
  useEffect(() => {
    commandsRef.current = commands;
  }, [commands]);

  useEffect(() => {
    const match = createSequenceMatcher(
      () => commandsRef.current.flatMap((c) => (c.keys ? [{ id: c.id, keys: c.keys }] : [])),
      SEQUENCE_TIMEOUT_MS,
    );
    function onKeyDown(event: KeyboardEvent) {
      const mod = detectMac() ? event.metaKey : event.ctrlKey;
      if (mod && !event.altKey && !event.shiftKey && event.key.toLowerCase() === "k") {
        // Works in inputs too, but never on top of another modal dialog.
        if (document.querySelector('[aria-modal="true"]:not([data-command-palette])')) return;
        event.preventDefault();
        setPalette((open) => !open);
        return;
      }
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
      if (isTypingTarget(event.target) || document.querySelector('[aria-modal="true"]')) return;
      const id = match(event.key);
      const command = id ? commandsRef.current.find((c) => c.id === id) : undefined;
      if (command) {
        event.preventDefault();
        command.run();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const value = useMemo(() => ({ openPalette: () => setPalette(true), register, mac }), [register, mac]);

  return (
    <CommandContext.Provider value={value}>
      {children}
      {palette ? <CommandPalette commands={commands} mac={mac} onClose={() => setPalette(false)} /> : null}
      {help ? <ShortcutsDialog commands={commands} mac={mac} onClose={() => setHelp(false)} /> : null}
      <p role="status" aria-live="polite" className="sr-only">
        {announcement}
      </p>
    </CommandContext.Provider>
  );
}
