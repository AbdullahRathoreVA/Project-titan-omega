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

/**
 * Product schema, rendered server-side into the static export.
 *
 * Titan's own audit reports "no structured data" as CRITICAL on client sites,
 * and its own homepage had none — the schema on /pricing is injected by the
 * FastAPI route, which never touches this Next-rendered page.
 *
 * Deliberately carries no prices. The priced Offers live on /pricing where the
 * server generates them from the live plan table; duplicating them here as
 * static strings is how a marked-up price silently drifts from the charged one.
 */
const PRODUCT_SCHEMA = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "SoftwareApplication",
      name: "Titan Omega",
      applicationCategory: "BusinessApplication",
      operatingSystem: "Web",
      url: SITE,
      description:
        "SEO, local ranking and legal compliance audits for any business in any jurisdiction. Technical, local and legal findings are scored separately, never averaged.",
      featureList: [
        "Technical SEO audit",
        "Local ranking factor scoring on published 2026 weights",
        "Legal compliance across 9 jurisdictions (Impressum / §5 DDG, GDPR consent)",
        "24/7 monitoring with regression alerts",
        "Client-ready PDF reports",
      ],
    },
    { "@type": "Organization", name: "Titan Omega", url: SITE, logo: `${SITE}/icons/icon-512.png` },
    { "@type": "WebSite", name: "Titan Omega", url: SITE },
  ],
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
        <script
          type="application/ld+json"
          // Next escapes this for us; the object is a literal, never user input.
          dangerouslySetInnerHTML={{ __html: JSON.stringify(PRODUCT_SCHEMA) }}
        />
      </body>
    </html>
  );
}
