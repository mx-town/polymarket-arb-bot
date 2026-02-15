import Link from "next/link";

/**
 * Pricing cards section. Reusable on both the landing page
 * and the dedicated /pricing route.
 */

const tiers = [
  {
    name: "Free",
    price: "$0",
    period: "forever",
    description: "Get started with the essentials. Perfect for exploration.",
    features: [
      "1 bot instance",
      "7-day trade history",
      "Basic charts & analytics",
      "Community support",
      "Manual merge/redeem",
    ],
    cta: "Get Started Free",
    href: "/overview",
    highlighted: false,
  },
  {
    name: "Pro",
    price: "$29",
    period: "/mo",
    description: "For serious traders who want full automation and insights.",
    features: [
      "Unlimited bot instances",
      "30-day trade history",
      "Live Slack/Telegram alerts",
      "Priority support",
      "Auto merge & redeem",
      "Advanced risk analytics",
      "Custom strategy parameters",
    ],
    cta: "Start Pro Trial",
    href: "/overview",
    highlighted: true,
  },
];

export function Pricing() {
  return (
    <section className="bg-bg-secondary/50 px-4 py-24 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-5xl">
        {/* Section heading */}
        <div className="text-center">
          <p className="text-sm font-semibold uppercase tracking-wider text-accent-blue">
            Pricing
          </p>
          <h2 className="mt-3 text-3xl font-bold tracking-tight text-text-primary sm:text-4xl">
            Simple, transparent pricing
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-base text-text-secondary">
            Start free and scale when you are ready. No hidden fees.
          </p>
        </div>

        {/* Cards */}
        <div className="mt-16 grid gap-8 lg:grid-cols-2">
          {tiers.map((tier) => (
            <div
              key={tier.name}
              className={`relative rounded-xl border p-8 transition-all ${
                tier.highlighted
                  ? "border-accent-blue/50 bg-bg-secondary shadow-xl shadow-accent-blue/5"
                  : "border-border-primary bg-bg-secondary"
              }`}
            >
              {/* Recommended badge */}
              {tier.highlighted && (
                <span className="absolute -top-3 right-6 rounded-full bg-accent-blue px-3 py-1 text-xs font-semibold text-white">
                  Recommended
                </span>
              )}

              {/* Tier header */}
              <h3 className="text-lg font-semibold text-text-primary">
                {tier.name}
              </h3>
              <p className="mt-1 text-sm text-text-secondary">
                {tier.description}
              </p>

              {/* Price */}
              <div className="mt-6 flex items-baseline gap-1">
                <span className="font-mono text-4xl font-bold text-text-primary">
                  {tier.price}
                </span>
                <span className="text-sm text-text-muted">{tier.period}</span>
              </div>

              {/* Feature list */}
              <ul className="mt-8 space-y-3">
                {tier.features.map((feature) => (
                  <li
                    key={feature}
                    className="flex items-center gap-3 text-sm text-text-secondary"
                  >
                    <svg
                      width="16"
                      height="16"
                      viewBox="0 0 16 16"
                      fill="none"
                      className={
                        tier.highlighted
                          ? "shrink-0 text-accent-blue"
                          : "shrink-0 text-accent-green"
                      }
                    >
                      <path
                        d="M13.5 4.5l-7 7L3 8"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                    {feature}
                  </li>
                ))}
              </ul>

              {/* CTA button */}
              <Link
                href={tier.href}
                className={`mt-8 block w-full rounded-lg py-3 text-center text-sm font-semibold transition-all ${
                  tier.highlighted
                    ? "bg-accent-blue text-white hover:bg-accent-blue/85 hover:shadow-lg hover:shadow-accent-blue/20"
                    : "border border-border-primary bg-bg-tertiary text-text-primary hover:border-text-muted hover:bg-bg-hover"
                }`}
              >
                {tier.cta}
              </Link>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
