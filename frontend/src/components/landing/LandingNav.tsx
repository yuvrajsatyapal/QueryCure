"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { Logo } from "@/components/ui/Logo";

const SECTIONS = [
  ["#screens", "Product"],
  ["#how", "How it works"],
  ["#safety", "Safety"],
  ["#verify", "Verification"],
  ["#report", "Reports"],
  ["#data", "Real data"],
] as const;

/** Sticky landing header; it condenses into a floating pill once the page scrolls. */
export function LandingNav() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return (
    <header className={`nav${scrolled ? " scrolled" : ""}`}>
      <div className="wrap">
        <Link href="/" className="brand">
          <Logo size={22} animated />
          QueryCure
        </Link>
        <nav className="nav-links" aria-label="Sections">
          {SECTIONS.map(([href, label]) => (
            <a key={href} href={href}>
              {label}
            </a>
          ))}
        </nav>
        <div className="nav-right">
          <ThemeToggle />
          <Link href="/app" className="btn btn-primary btn-sm">
            Open QueryCure
          </Link>
        </div>
      </div>
    </header>
  );
}
