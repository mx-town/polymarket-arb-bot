/**
 * Feature grid for the landing page.
 * 2x3 on desktop, single column on mobile. Each card has an icon,
 * title, and short description with hover effects.
 */

const features = [
  {
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
      </svg>
    ),
    title: "Real-Time Charts",
    description:
      "Live BTC candlestick and probability charts powered by lightweight, high-performance rendering. Watch markets evolve tick by tick.",
    color: "text-accent-blue",
    glow: "group-hover:shadow-accent-blue/10",
  },
  {
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <path d="M16 8l-4 4-4-4" />
        <path d="M8 16l4-4 4 4" />
      </svg>
    ),
    title: "Complete Set Arbitrage",
    description:
      "Automated entry, hedge, and merge workflow. Buy both sides when the combined cost is below $1, then redeem on-chain for guaranteed profit.",
    color: "text-accent-green",
    glow: "group-hover:shadow-accent-green/10",
  },
  {
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      </svg>
    ),
    title: "Risk Management",
    description:
      "Position limits, bankroll tracking, and hedge ratio monitoring. Configurable guards for entry price bounds and BTC momentum filters.",
    color: "text-accent-yellow",
    glow: "group-hover:shadow-accent-yellow/10",
  },
  {
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
      </svg>
    ),
    title: "Event-Driven",
    description:
      "WebSocket-powered sub-second market updates. React instantly to price movements and order book changes across all active markets.",
    color: "text-accent-purple",
    glow: "group-hover:shadow-accent-purple/10",
  },
  {
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
        <path d="M16 21V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v16" />
      </svg>
    ),
    title: "On-Chain Settlement",
    description:
      "Direct merge and redeem via Gnosis Safe on Polygon. Complete-set redemption happens trustlessly on-chain with gas-optimized transactions.",
    color: "text-accent-orange",
    glow: "group-hover:shadow-accent-orange/10",
  },
  {
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
        <polyline points="15 3 21 3 21 9" />
        <line x1="10" y1="14" x2="21" y2="3" />
      </svg>
    ),
    title: "Open Source",
    description:
      "Full transparency with self-hostable infrastructure. MIT licensed, auditable code, and community-driven development.",
    color: "text-accent-blue",
    glow: "group-hover:shadow-accent-blue/10",
  },
];

export function Features() {
  return (
    <section className="bg-bg-primary px-4 py-24 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-6xl">
        {/* Section heading */}
        <div className="text-center">
          <p className="text-sm font-semibold uppercase tracking-wider text-accent-blue">
            Features
          </p>
          <h2 className="mt-3 text-3xl font-bold tracking-tight text-text-primary sm:text-4xl">
            Everything you need to trade smarter
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-base text-text-secondary">
            Purpose-built tools for Polymarket complete-set arbitrage, from
            market discovery to on-chain settlement.
          </p>
        </div>

        {/* Feature grid */}
        <div className="mt-16 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {features.map((feature) => (
            <div
              key={feature.title}
              className={`group relative rounded-xl border border-border-primary bg-bg-secondary p-6 transition-all duration-300 hover:-translate-y-0.5 hover:border-text-muted/30 hover:shadow-xl ${feature.glow}`}
            >
              {/* Icon */}
              <div
                className={`inline-flex rounded-lg bg-bg-tertiary p-2.5 ${feature.color}`}
              >
                {feature.icon}
              </div>

              {/* Content */}
              <h3 className="mt-4 text-lg font-semibold text-text-primary">
                {feature.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-text-secondary">
                {feature.description}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
