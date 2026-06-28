"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

type ThemeCtx = {
  dark: boolean;
  cb: boolean;
  toggleDark: () => void;
  toggleCb: () => void;
};

const ThemeContext = createContext<ThemeCtx | null>(null);

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within AppShell");
  return ctx;
}

const LINKS = [
  { href: "/", label: "Triage Queue", icon: "queue" },
  { href: "/pipeline", label: "Pipeline", icon: "pipeline" },
  { href: "/extraction", label: "Extraction", icon: "extract" },
  { href: "/eligibility", label: "Eligibility table", icon: "table" },
  { href: "/presentation", label: "Presentation", icon: "pres" },
];

function NavIcon({ name }: { name: string }) {
  if (name === "queue")
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M3 6h18M3 12h18M3 18h18" />
      </svg>
    );
  if (name === "pipeline")
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
      </svg>
    );
  if (name === "extract")
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M14 3v5h5M7 3h8l5 5v13H7zM4 7v14h11" />
      </svg>
    );
  if (name === "table")
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="3" y="4" width="18" height="16" rx="2" />
        <path d="M3 10h18M9 4v16" />
      </svg>
    );
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v4l3 2" />
    </svg>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [dark, setDark] = useState(false);
  const [cb, setCb] = useState(false);

  useEffect(() => {
    const d = localStorage.getItem("ouchless-dark");
    const c = localStorage.getItem("ouchless-cb");
    if (d === "1") setDark(true);
    if (c === "1") setCb(true);
  }, []);

  useEffect(() => {
    localStorage.setItem("ouchless-dark", dark ? "1" : "0");
  }, [dark]);
  useEffect(() => {
    localStorage.setItem("ouchless-cb", cb ? "1" : "0");
  }, [cb]);

  const rootMods = ["app", dark ? "dark" : "", cb ? "cb" : ""].filter(Boolean).join(" ");

  return (
    <ThemeContext.Provider
      value={{
        dark,
        cb,
        toggleDark: () => setDark((v) => !v),
        toggleCb: () => setCb((v) => !v),
      }}
    >
      <div className={rootMods}>
        <aside className="side">
          <div className="brand">
            <div className="logo">O</div>
            <div>
              <div className="brandname">OuchLess</div>
              <div className="brandsub">Wound Care Billing Triage</div>
            </div>
          </div>
          <div className="navlbl">Workflow</div>
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} className={`nav${path === l.href ? " on" : ""}`}>
              <NavIcon name={l.icon} />
              {l.label}
            </Link>
          ))}
          <div className="navlbl">Account</div>
          <div className="nav" style={{ opacity: 0.55, cursor: "default" }}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 6.8 19l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 3 13.6H3a2 2 0 1 1 0-4h.1" />
            </svg>
            Settings
          </div>
          <div className="side-foot">
            <div className="userc">
              <div className="ava">RS</div>
              <div>
                <div className="uname">R. Shiny</div>
                <div className="urole">Medical Biller</div>
              </div>
            </div>
          </div>
        </aside>
        <div className="main">{children}</div>
      </div>
    </ThemeContext.Provider>
  );
}
