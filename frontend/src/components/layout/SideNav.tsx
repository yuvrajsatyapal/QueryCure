import Link from "next/link";

interface NavItem {
  label: string;
  href: string;
  available: boolean;
}

// Only routes that exist are links; planned sections render disabled so there are no dead links.
const NAV: NavItem[] = [
  { label: "Dashboard", href: "/app", available: true },
  { label: "New investigation", href: "/app/investigations/new", available: false },
  { label: "History", href: "/app/history", available: false },
  { label: "Connections", href: "/app/connections", available: false },
  { label: "Settings", href: "/app/settings", available: false },
];

export function SideNav() {
  return (
    <nav aria-label="Main" className="flex w-56 shrink-0 flex-col gap-1 border-r border-border bg-surface p-3">
      {NAV.map((item) =>
        item.available ? (
          <Link
            key={item.href}
            href={item.href}
            className="rounded-md px-3 py-2 text-sm font-medium text-ink hover:bg-surface-2"
          >
            {item.label}
          </Link>
        ) : (
          <span
            key={item.href}
            aria-disabled="true"
            className="flex items-center justify-between rounded-md px-3 py-2 text-sm text-muted"
          >
            <span>{item.label}</span>
            <span className="font-mono text-[11px] uppercase tracking-wider">soon</span>
          </span>
        ),
      )}
    </nav>
  );
}
