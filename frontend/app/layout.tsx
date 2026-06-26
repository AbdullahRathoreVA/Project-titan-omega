import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Titan Omega — Empire Command Center",
  description:
    "Autonomous Founder Empire Operating System. Command center for the Executive Intelligence Core and the Digital Employee Network.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
