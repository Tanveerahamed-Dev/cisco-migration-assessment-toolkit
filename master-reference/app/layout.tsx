import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(
    "https://enhancements-master-reference.tanveerahamed81.chatgpt.site",
  ),
  title: "Enhancements · Master Reference",
  description:
    "A self-explanatory map of the Enhancements repository and the reasoning behind every major engineering decision.",
  applicationName: "Enhancements Master Reference",
  authors: [{ name: "Enhancements" }],
  creator: "Enhancements",
  openGraph: {
    title: "Atlas · Whole-Repository Master Reference",
    description:
      "A private, exact-source map from repository lines and symbols to evidence, decisions, interfaces, outputs, gaps, and uncertainty.",
    type: "website",
    url: "https://enhancements-master-reference.tanveerahamed81.chatgpt.site",
    images: [
      {
        url: "/atlas-social-card.png",
        width: 1731,
        height: 909,
        alt: "Abstract Atlas digital thread connecting source records to evidence, interfaces, decisions, and a horizon.",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Atlas · Whole-Repository Master Reference",
    description: "Private, exact-source project intelligence with visible uncertainty.",
    images: ["/atlas-social-card.png"],
  },
  robots: {
    index: false,
    follow: false,
    nocache: true,
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
