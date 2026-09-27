"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ShieldCheck, Gauge, ScanSearch, FileBarChart2, GraduationCap } from "lucide-react";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Overview", icon: Gauge, match: (p: string) => p === "/dashboard" },
  { href: "/", label: "New scan", icon: ScanSearch, match: (p: string) => p === "/" },
  { href: "/reports", label: "Reports", icon: FileBarChart2, match: (p: string) => p.startsWith("/reports") },
  { href: "/training", label: "Training", icon: GraduationCap, match: (p: string) => p.startsWith("/training") },
];

export default function Navbar() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-10 bg-paper/95 backdrop-blur border-b border-line">
      <div className="max-w-6xl mx-auto px-6 sm:px-10 h-16 flex items-center justify-between gap-6">
        <Link href="/dashboard" className="flex items-center gap-2.5 shrink-0">
          <span className="w-8 h-8 rounded-lg bg-ink flex items-center justify-center">
            <ShieldCheck className="w-[18px] h-[18px] text-paper" strokeWidth={2} />
          </span>
          <span className="font-display font-semibold text-[15px] tracking-tight hidden sm:inline">
            Network Compliance Auditor
          </span>
        </Link>

        <nav className="flex items-center gap-1">
          {NAV_ITEMS.map((item) => {
            const active = item.match(pathname);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2 rounded-full px-3.5 py-2 text-[13px] font-medium transition-colors
                  ${active ? "bg-ink text-paper" : "text-ink-soft hover:bg-paper-dim hover:text-ink"}`}
              >
                <Icon className="w-[16px] h-[16px] shrink-0" strokeWidth={2} />
                <span className="hidden md:inline">{item.label}</span>
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
