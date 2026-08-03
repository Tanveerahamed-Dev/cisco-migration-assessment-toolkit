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
    url: "https://enhancements-master-reference.tanveerahamed81.chatgpt.site",
  },
  robots: {
    index: true,
    follow: true,
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
