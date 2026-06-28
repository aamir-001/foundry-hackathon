"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Worklist" },
  { href: "/eligibility", label: "Eligibility table" },
  { href: "/extraction", label: "Extraction" },
  { href: "/pipeline", label: "Pipeline" },
  { href: "/presentation", label: "Presentation" },
];

export default function Nav() {
  const path = usePathname();
  return (
    <nav className="topnav">
      <span className="brand">Wound-Care Triage</span>
      {LINKS.map((l) => (
        <Link key={l.href} href={l.href} className={path === l.href ? "active" : ""}>
          {l.label}
        </Link>
      ))}
    </nav>
  );
}
