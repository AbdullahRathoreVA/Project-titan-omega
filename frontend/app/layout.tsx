import type { Metadata, Viewport } from "next";
import "./globals.css";
import { RegisterSW } from "@/components/RegisterSW";

const SITE = "https://titanomega-ai.com";

export const metadata: Metadata = {
  metadataBase: new URL(SITE),
  title: "Titan Omega — Empire Command Center",
  description:
    "Autonomous SEO, compliance and social platform. Audit any business in any jurisdiction — technical, local and legal, scored separately.",
  applicationName: "Titan Omega",
  manifest: "/manifest.webmanifest",
  // Titan sells legal compliance; a missing canonical splits its own ranking
  // between the custom domain and the *.hf.space origin behind it.
  alternates: { canonical: SITE },
  icons: {
    icon: "/favicon.png",
    apple: "/icons/apple-touch-icon.png",
  },
  appleWebApp: {
    capable: true,
    title: "Titan Omega",
    statusBarStyle: "black-translucent",
  },
  openGraph: {
    type: "website",
    url: SITE,
    siteName: "Titan Omega",
    title: "Titan Omega — Empire Command Center",
    description:
      "Audit any business in any jurisdiction. Technical SEO, local ranking factors and legal exposure — reported separately, never averaged.",
  },
};

export const viewport: Viewport = {
  themeColor: "#05070d",
  // The command centre is edge-to-edge; without this the 3D canvas stops at the
  // notch on a phone.
  viewportFit: "cover",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        {children}
        <RegisterSW />
      </body>
    </html>
  );
}
