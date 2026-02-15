/**
 * Bottom call-to-action section with email signup.
 * Non-functional form (UI only for now).
 */
export function CTA() {
  return (
    <section className="bg-bg-primary px-4 py-24 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-4xl">
        <div className="relative overflow-hidden rounded-2xl border border-border-primary bg-bg-secondary p-8 sm:p-12">
          {/* Background gradient accent */}
          <div className="pointer-events-none absolute -right-20 -top-20 h-64 w-64 rounded-full bg-accent-blue/5 blur-3xl" />
          <div className="pointer-events-none absolute -bottom-20 -left-20 h-64 w-64 rounded-full bg-accent-green/5 blur-3xl" />

          <div className="relative text-center">
            <h2 className="text-3xl font-bold tracking-tight text-text-primary sm:text-4xl">
              Start Trading Smarter
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-base text-text-secondary">
              Get real-time arbitrage signals, automated position management, and
              on-chain settlement. Set up in under 5 minutes.
            </p>

            {/* Email form */}
            <div className="mx-auto mt-8 flex max-w-md flex-col gap-3 sm:flex-row">
              <input
                type="email"
                placeholder="you@example.com"
                className="flex-1 rounded-lg border border-border-primary bg-bg-primary px-4 py-3 text-sm text-text-primary placeholder-text-muted outline-none transition-colors focus:border-accent-blue"
                aria-label="Email address"
              />
              <button
                type="button"
                className="whitespace-nowrap rounded-lg bg-accent-blue px-6 py-3 text-sm font-semibold text-white transition-all hover:bg-accent-blue/85 hover:shadow-lg hover:shadow-accent-blue/20"
              >
                Get Started
              </button>
            </div>

            <p className="mt-4 text-xs text-text-muted">
              Free tier available. No credit card required.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
