import Link from "next/link";

/**
 * Hero section for the landing page.
 * Features a gradient mesh background, animated SVG chart preview,
 * and two CTA buttons.
 */
export function Hero() {
  return (
    <section className="relative overflow-hidden bg-bg-primary px-4 pb-20 pt-24 sm:px-6 lg:px-8">
      {/* Background grid pattern */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            "linear-gradient(rgba(74, 158, 255, 0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(74, 158, 255, 0.03) 1px, transparent 1px)",
          backgroundSize: "64px 64px",
        }}
      />

      {/* Gradient orbs */}
      <div className="pointer-events-none absolute left-1/4 top-0 h-96 w-96 -translate-x-1/2 rounded-full bg-accent-blue/5 blur-3xl" />
      <div className="pointer-events-none absolute right-1/4 top-20 h-72 w-72 rounded-full bg-accent-purple/5 blur-3xl" />

      <div className="relative mx-auto max-w-6xl">
        {/* Badge */}
        <div className="flex justify-center">
          <span className="inline-flex items-center gap-2 rounded-full border border-border-primary bg-bg-secondary px-4 py-1.5 text-xs font-medium text-text-secondary">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent-green" />
            Live on Polygon
          </span>
        </div>

        {/* Heading */}
        <h1 className="mt-8 text-center text-4xl font-bold leading-tight tracking-tight text-text-primary sm:text-5xl lg:text-6xl">
          Automated Arbitrage
          <br />
          <span className="text-accent-blue">for Polymarket</span>
        </h1>

        {/* Subtitle */}
        <p className="mx-auto mt-6 max-w-2xl text-center text-lg leading-relaxed text-text-secondary">
          Monitor 15-minute crypto prediction markets in real time.
          Automatically identify complete-set arbitrage opportunities, enter
          positions, hedge, and merge for guaranteed profit.
        </p>

        {/* CTAs */}
        <div className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
          <Link
            href="/overview"
            className="inline-flex items-center gap-2 rounded-lg bg-accent-blue px-8 py-3.5 text-sm font-semibold text-white transition-all hover:bg-accent-blue/85 hover:shadow-lg hover:shadow-accent-blue/20"
          >
            Open Dashboard
            <svg
              width="16"
              height="16"
              viewBox="0 0 16 16"
              fill="none"
              className="transition-transform group-hover:translate-x-0.5"
            >
              <path
                d="M6 3l5 5-5 5"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </Link>
          <a
            href="https://github.com"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 rounded-lg border border-border-primary bg-bg-secondary px-8 py-3.5 text-sm font-semibold text-text-primary transition-all hover:border-text-muted hover:bg-bg-tertiary"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 16 16"
              fill="currentColor"
            >
              <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z" />
            </svg>
            View on GitHub
          </a>
        </div>

        {/* Animated chart preview */}
        <div className="mx-auto mt-16 max-w-4xl">
          <div className="rounded-xl border border-border-primary bg-bg-secondary p-1 shadow-2xl shadow-black/40">
            {/* Mock window chrome */}
            <div className="flex items-center gap-2 border-b border-border-primary px-4 py-3">
              <span className="h-3 w-3 rounded-full bg-accent-red/60" />
              <span className="h-3 w-3 rounded-full bg-accent-yellow/60" />
              <span className="h-3 w-3 rounded-full bg-accent-green/60" />
              <span className="ml-4 text-xs text-text-muted">
                polymarket-dashboard / overview
              </span>
            </div>

            {/* Chart area */}
            <div className="relative h-64 overflow-hidden rounded-b-lg bg-bg-primary p-6 sm:h-80">
              {/* Y-axis labels */}
              <div className="absolute left-2 top-6 flex h-[calc(100%-3rem)] flex-col justify-between text-xs text-text-muted">
                <span>$0.92</span>
                <span>$0.78</span>
                <span>$0.64</span>
                <span>$0.50</span>
              </div>

              {/* Animated chart SVG */}
              <svg
                viewBox="0 0 800 250"
                className="ml-8 h-full w-full"
                preserveAspectRatio="none"
              >
                {/* Grid lines */}
                <line x1="0" y1="62" x2="800" y2="62" stroke="#30363d" strokeWidth="0.5" strokeDasharray="4 4" />
                <line x1="0" y1="125" x2="800" y2="125" stroke="#30363d" strokeWidth="0.5" strokeDasharray="4 4" />
                <line x1="0" y1="188" x2="800" y2="188" stroke="#30363d" strokeWidth="0.5" strokeDasharray="4 4" />

                {/* Gradient fill under chart line */}
                <defs>
                  <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#4a9eff" stopOpacity="0.15" />
                    <stop offset="100%" stopColor="#4a9eff" stopOpacity="0" />
                  </linearGradient>
                  <linearGradient id="lineGradient" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="#4a9eff" />
                    <stop offset="100%" stopColor="#2dc96f" />
                  </linearGradient>
                </defs>

                {/* Fill area */}
                <polygon
                  points="0,200 0,180 50,175 100,160 150,170 200,145 250,150 300,130 350,120 400,125 450,105 500,95 550,100 600,80 650,70 700,55 750,45 800,30 800,250 0,250"
                  fill="url(#chartGradient)"
                  style={{
                    animation: "fadeIn 2s ease-out forwards",
                    opacity: 0,
                  }}
                />

                {/* Main chart line */}
                <polyline
                  points="0,180 50,175 100,160 150,170 200,145 250,150 300,130 350,120 400,125 450,105 500,95 550,100 600,80 650,70 700,55 750,45 800,30"
                  fill="none"
                  stroke="url(#lineGradient)"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  style={{
                    strokeDasharray: 1200,
                    strokeDashoffset: 1200,
                    animation: "drawLine 3s ease-out forwards",
                  }}
                />

                {/* Pulsing dot at end */}
                <circle
                  cx="800"
                  cy="30"
                  r="4"
                  fill="#2dc96f"
                  style={{
                    opacity: 0,
                    animation: "fadeIn 0.5s ease-out 2.5s forwards",
                  }}
                />
                <circle
                  cx="800"
                  cy="30"
                  r="4"
                  fill="#2dc96f"
                  style={{
                    opacity: 0,
                    animation: "fadeIn 0.5s ease-out 2.5s forwards, pulse 2s ease-in-out 3s infinite",
                  }}
                />

                {/* Second line (probability) */}
                <polyline
                  points="0,140 50,145 100,135 150,150 200,130 250,140 300,120 350,115 400,130 450,110 500,115 550,105 600,100 650,95 700,85 750,80 800,70"
                  fill="none"
                  stroke="#a78bfa"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeOpacity="0.5"
                  style={{
                    strokeDasharray: 1200,
                    strokeDashoffset: 1200,
                    animation: "drawLine 3.5s ease-out 0.3s forwards",
                  }}
                />
              </svg>

              {/* Legend */}
              <div className="absolute bottom-4 right-6 flex items-center gap-4 text-xs text-text-muted">
                <span className="flex items-center gap-1.5">
                  <span className="inline-block h-0.5 w-4 rounded bg-accent-blue" />
                  BTC Price
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="inline-block h-0.5 w-4 rounded bg-accent-purple/50" />
                  Up Probability
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Stats bar */}
        <div className="mx-auto mt-12 grid max-w-3xl grid-cols-2 gap-6 sm:grid-cols-4">
          {[
            { label: "Markets Tracked", value: "96+" },
            { label: "Avg Resolution", value: "15 min" },
            { label: "On-Chain", value: "Polygon" },
            { label: "Uptime", value: "99.7%" },
          ].map((stat) => (
            <div key={stat.label} className="text-center">
              <p className="font-mono text-2xl font-bold text-text-primary">
                {stat.value}
              </p>
              <p className="mt-1 text-xs text-text-muted">{stat.label}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Keyframe animations */}
      <style
        dangerouslySetInnerHTML={{
          __html: `
            @keyframes drawLine {
              to { stroke-dashoffset: 0; }
            }
            @keyframes fadeIn {
              to { opacity: 1; }
            }
            @keyframes pulse {
              0%, 100% { r: 4; opacity: 1; }
              50% { r: 8; opacity: 0.4; }
            }
          `,
        }}
      />
    </section>
  );
}
