import { Hero } from "@/components/landing/hero";
import { Features } from "@/components/landing/features";
import { Pricing } from "@/components/landing/pricing";
import { CTA } from "@/components/landing/cta";

export default function HomePage() {
  return (
    <main className="min-h-screen bg-bg-primary">
      <Hero />
      <Features />
      <Pricing />
      <CTA />

      {/* Footer */}
      <footer className="border-t border-border-primary bg-bg-primary px-4 py-8">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 text-xs text-text-muted sm:flex-row">
          <p>Polymarket Dashboard. Built for traders, by traders.</p>
          <div className="flex gap-6">
            <a href="/pricing" className="transition-colors hover:text-text-secondary">
              Pricing
            </a>
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
