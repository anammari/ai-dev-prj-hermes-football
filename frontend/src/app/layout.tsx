import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: "Hermes Football — dashboard",
  description: "Freshness, standings, fixtures, the agent's audit log and the golden-question scoreboard.",
};

const LINKS = [
  { href: "/", label: "Freshness" },
  { href: "/standings", label: "Standings" },
  { href: "/fixtures", label: "Fixtures" },
  { href: "/turns", label: "Agent turns" },
  { href: "/evals", label: "Evals" },
  { href: "/system", label: "System" },
] as const;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <header className="topbar">
            <div className="brand">
              Hermes Football <span>· dashboard</span>
            </div>
            <nav className="nav" aria-label="Sections">
              {LINKS.map((link) => (
                <Link key={link.href} href={link.href}>
                  {link.label}
                </Link>
              ))}
            </nav>
          </header>
          <main>{children}</main>
          <footer className="foot">
            Read-only view of the API in `openapi.yaml`. Data is the delayed free tier — never live.
            Simple answers stay local; complex answers and routing use the signed-off cloud paths.
          </footer>
        </div>
      </body>
    </html>
  );
}
