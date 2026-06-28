import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Wound-Care Billing Triage",
  description: "Medicare Part B wound-care eligibility pipeline",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
