"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon, type IconName } from "@/components/ui/Icon";

interface NavItem {
  label: string;
  href: string;
  icon: IconName;
}

// Linear-style groups. Every entry is a real route: no placeholders, no dead links.
const GROUPS: { title: string | null; items: NavItem[] }[] = [
  {
    title: null,
    items: [
      { label: "Dashboard", href: "/app", icon: "dashboard" },
      { label: "History", href: "/app/history", icon: "history" },
    ],
  },
  {
    title: "Workspace",
    items: [
      { label: "Connections", href: "/app/connections", icon: "plug" },
      { label: "Demo gallery", href: "/demo", icon: "play" },
    ],
  },
];

const SETTINGS: NavItem = { label: "Settings", href: "/app/settings", icon: "settings" };

function isActive(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  if (href === "/app") return pathname === "/app";
  // An open investigation belongs to History, where it was picked from.
  if (href === "/app/history") return pathname.startsWith("/app/history") || /^\/app\/(investigations\/(?!new)|reports|replay)/.test(pathname);
  return pathname.startsWith(href);
}

function NavLink({ item, pathname, onNavigate }: { item: NavItem; pathname: string | null; onNavigate?: () => void }) {
  const active = isActive(pathname, item.href);
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={`flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] font-medium ${
        active ? "bg-hover text-ink" : "text-muted hover:bg-hover hover:text-ink"
      }`}
    >
      <Icon name={item.icon} size={15} className={active ? "text-ink" : "text-faint"} />
      {item.label}
    </Link>
  );
}

export function SideNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="flex flex-1 flex-col gap-5">
      <Link href="/app/investigations/new" onClick={onNavigate} className="qc-btn-secondary w-full justify-start shadow-sm">
        <Icon name="plus" size={15} className="text-muted" />
        New investigation
      </Link>
      {GROUPS.map((group) => (
        <div key={group.title ?? "main"} className="flex flex-col gap-0.5">
          {group.title ? <p className="px-2 pb-1 text-[11px] font-medium text-muted">{group.title}</p> : null}
          {group.items.map((item) => (
            <NavLink key={item.href} item={item} pathname={pathname} onNavigate={onNavigate} />
          ))}
        </div>
      ))}
      <div className="mt-auto flex flex-col gap-0.5">
        <NavLink item={SETTINGS} pathname={pathname} onNavigate={onNavigate} />
      </div>
    </nav>
  );
}
