import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Providers } from "@/app/providers";
import "@/styles/globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://arb.polymarket.tools"),
  title: {
    default: "Polymarket Arb Bot - Automated Arbitrage Dashboard",
    template: "%s | Polymarket Arb Bot",
  },
  description:
    "Real-time dashboard for automated complete-set arbitrage on Polymarket prediction markets. Live BTC charts, probability tracking, and P&L analytics.",
  keywords: [
    "polymarket",
    "arbitrage",
    "prediction markets",
    "trading bot",
    "crypto",
    "btc",
  ],
  authors: [{ name: "Polymarket Arb Bot" }],
  openGraph: {
    type: "website",
    locale: "en_US",
    siteName: "Polymarket Arb Bot",
    title: "Polymarket Arb Bot - Automated Arbitrage Dashboard",
    description:
      "Real-time dashboard for automated complete-set arbitrage on Polymarket prediction markets.",
  },
  twitter: {
    card: "summary_large_image",
    title: "Polymarket Arb Bot",
    description: "Automated arbitrage for Polymarket prediction markets",
  },
  robots: {
    index: true,
    follow: true,
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <body className="min-h-screen bg-bg-primary font-sans text-text-primary antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
