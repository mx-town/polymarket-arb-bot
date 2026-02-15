import type { Metadata } from "next";
import Link from "next/link";
import { Pricing } from "@/components/landing/pricing";

export const metadata: Metadata = {
  title: "Pricing | Polymarket Dashboard",
  description:
    "Simple, transparent pricing for Polymarket trading automation. Free tier available.",
};

export default function PricingPage() {
  return (
    <main className="min-h-screen bg-bg-primary">
      {/* Navigation bar */}
      <nav className="border-b border-border-primary bg-bg-primary px-4 py-4 sm:px-6">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <Link
            href="/"
            className="text-sm font-semibold text-text-primary transition-colors hover:text-accent-blue"
          >
            Polymarket Dashboard
          </Link>
          <Link
            href="/overview"
            className="rounded-lg bg-accent-blue px-4 py-2 text-sm font-semibold text-white transition-all hover:bg-accent-blue/85"
          >
            Open Dashboard
          </Link>
        </div>
      </nav>

      {/* Pricing section */}
      <Pricing />

      {/* FAQ / Additional details */}
      <section className="bg-bg-primary px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl">
          <h3 className="text-center text-xl font-semibold text-text-primary">
            Frequently Asked Questions
          </h3>

          <div className="mt-10 space-y-6">
            {[
              {
                q: "Can I self-host the bot?",
                a: "Yes. The bot is fully open source and MIT licensed. The dashboard SaaS provides managed hosting, alerts, and analytics on top of the core trading engine.",
              },
              {
                q: "What happens to my positions if the service goes down?",
                a: "All positions are on-chain and fully under your control via your Gnosis Safe. The bot simply automates order placement; your funds are never custodied.",
              },
              {
                q: "Can I cancel anytime?",
                a: "Yes. Pro subscriptions can be cancelled at any time. Your existing positions and trade history remain accessible on the Free tier.",
              },
              {
                q: "Do you support markets beyond crypto Up/Down?",
                a: "Currently we focus on 15-minute crypto prediction markets on Polymarket. Support for additional market types is on the roadmap.",
              },
            ].map((faq) => (
              <div
                key={faq.q}
                className="rounded-lg border border-border-primary bg-bg-secondary p-6"
              >
                <h4 className="font-semibold text-text-primary">{faq.q}</h4>
                <p className="mt-2 text-sm leading-relaxed text-text-secondary">
                  {faq.a}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border-primary bg-bg-primary px-4 py-8">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 text-xs text-text-muted sm:flex-row">
          <p>Polymarket Dashboard. Built for traders, by traders.</p>
          <div className="flex gap-6">
            <Link
              href="/"
              className="transition-colors hover:text-text-secondary"
            >
              Home
            </Link>
            <a
              href="https://github.com"
              target="_blank"
              rel="noopener noreferrer"
              className="transition-colors hover:text-text-secondary"
            >
              GitHub
            </a>
          </div>
        </div>
      </footer>
    </main>
  );
}
