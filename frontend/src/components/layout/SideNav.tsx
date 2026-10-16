import Link from "next/link";

interface NavItem {
  label: string;
  href: string;
  available: boolean;
}

// Only routes that exist are links; planned sections render disabled so there are no dead links.
const NAV: NavItem[] = [
  { label: "Dashboard", href: "/app", available: true },
  { label: "New investigation", href: "/app/investigations/new", available: true },
  { label: "History", href: "/app/history", available: true },
  { label: "Connections", href: "/app/connections", available: true },
  { label: "Settings", href: "/app/settings", available: true },
];

export function SideNav() {
  return (
    <nav aria-label="Main" className="flex shrink-0 gap-1 overflow-x-auto border-b border-border bg-surface p-2 md:w-56 md:flex-col md:overflow-visible md:border-r md:border-b-0 md:p-3">
      {NAV.map((item) =>
        item.available ? (
          <Link
            key={item.href}
            href={item.href}
            className="whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium text-ink hover:bg-surface-2"
          >
            {item.label}
          </Link>
        ) : (
          <span
            key={item.href}
            aria-disabled="true"
            className="flex items-center justify-between gap-2 whitespace-nowrap rounded-md px-3 py-2 text-sm text-muted"
          >
            <span>{item.label}</span>
            <span className="font-mono text-[11px] uppercase tracking-wider">soon</span>
          </span>
        ),
      )}
    </nav>
  );
}
