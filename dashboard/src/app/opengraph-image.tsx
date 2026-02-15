import { ImageResponse } from "next/og";

export const runtime = "edge";

export const alt = "Polymarket Arb Bot - Automated Complete-Set Arbitrage";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image() {
  const candles = [
    { open: 280, close: 320, high: 340, low: 260 },
    { open: 320, close: 290, high: 350, low: 270 },
    { open: 290, close: 360, high: 380, low: 280 },
    { open: 360, close: 340, high: 390, low: 320 },
    { open: 340, close: 400, high: 420, low: 330 },
    { open: 400, close: 370, high: 430, low: 350 },
    { open: 370, close: 420, high: 440, low: 360 },
    { open: 420, close: 450, high: 470, low: 400 },
    { open: 450, close: 410, high: 460, low: 390 },
    { open: 410, close: 460, high: 480, low: 400 },
  ];

  const chartLeft = 600;
  const chartWidth = 500;
  const chartTop = 120;
  const chartHeight = 400;
  const candleSpacing = chartWidth / candles.length;
  const priceMin = 240;
  const priceMax = 500;
  const priceRange = priceMax - priceMin;

  function yPos(price: number) {
    return chartTop + chartHeight - ((price - priceMin) / priceRange) * chartHeight;
  }

  return new ImageResponse(
    (
      <div
        style={{
          width: "1200px",
          height: "630px",
          display: "flex",
          backgroundColor: "#0e1117",
          position: "relative",
          fontFamily: "sans-serif",
        }}
      >
        {/* Left side - Text content */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            paddingLeft: "60px",
            width: "550px",
          }}
        >
          {/* Logo accent */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              marginBottom: "24px",
            }}
          >
            <div
              style={{
                width: "48px",
                height: "48px",
                borderRadius: "12px",
                background: "linear-gradient(135deg, #3b82f6, #8b5cf6)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                marginRight: "16px",
              }}
            >
              <span style={{ fontSize: "24px", color: "white", fontWeight: 700 }}>P</span>
            </div>
            <span style={{ fontSize: "16px", color: "#6b7280", letterSpacing: "2px" }}>
              POLYMARKET
            </span>
          </div>

          {/* Title */}
          <h1
            style={{
              fontSize: "48px",
              fontWeight: 700,
              color: "#f9fafb",
              lineHeight: 1.1,
              margin: 0,
            }}
          >
            Arb Bot
          </h1>

          {/* Subtitle */}
          <p
            style={{
              fontSize: "22px",
              color: "#9ca3af",
              marginTop: "16px",
              lineHeight: 1.4,
            }}
          >
            Automated Complete-Set Arbitrage
          </p>

          {/* Stats row */}
          <div
            style={{
              display: "flex",
              gap: "32px",
              marginTop: "40px",
            }}
          >
            <div style={{ display: "flex", flexDirection: "column" }}>
              <span style={{ fontSize: "14px", color: "#6b7280" }}>Strategy</span>
              <span style={{ fontSize: "18px", color: "#3b82f6", fontWeight: 600 }}>
                Complete-Set
              </span>
            </div>
            <div style={{ display: "flex", flexDirection: "column" }}>
              <span style={{ fontSize: "14px", color: "#6b7280" }}>Markets</span>
              <span style={{ fontSize: "18px", color: "#10b981", fontWeight: 600 }}>
                BTC 15m Up/Down
              </span>
            </div>
          </div>
        </div>

        {/* Right side - Candlestick chart */}
        <div
          style={{
            position: "absolute",
            top: "0",
            right: "0",
            width: "600px",
            height: "630px",
            display: "flex",
          }}
        >
          {/* Grid lines */}
          {[0.25, 0.5, 0.75].map((pct, i) => (
            <div
              key={i}
              style={{
                position: "absolute",
                left: `${chartLeft - 600 + 20}px`,
                top: `${chartTop + chartHeight * pct}px`,
                width: `${chartWidth - 20}px`,
                height: "1px",
                backgroundColor: "rgba(75, 85, 99, 0.3)",
              }}
            />
          ))}

          {/* Candles */}
          {candles.map((candle, i) => {
            const isGreen = candle.close >= candle.open;
            const color = isGreen ? "#10b981" : "#ef4444";
            const bodyTop = yPos(Math.max(candle.open, candle.close));
            const bodyBottom = yPos(Math.min(candle.open, candle.close));
            const bodyHeight = Math.max(bodyBottom - bodyTop, 2);
            const wickTop = yPos(candle.high);
            const wickBottom = yPos(candle.low);
            const x = chartLeft - 600 + 30 + i * candleSpacing + candleSpacing / 2;

            return (
              <div key={i} style={{ display: "flex" }}>
                {/* Wick */}
                <div
                  style={{
                    position: "absolute",
                    left: `${x - 1}px`,
                    top: `${wickTop}px`,
                    width: "2px",
                    height: `${wickBottom - wickTop}px`,
                    backgroundColor: color,
                  }}
                />
                {/* Body */}
                <div
                  style={{
                    position: "absolute",
                    left: `${x - 10}px`,
                    top: `${bodyTop}px`,
                    width: "20px",
                    height: `${bodyHeight}px`,
                    backgroundColor: color,
                    borderRadius: "2px",
                  }}
                />
              </div>
            );
          })}
        </div>

        {/* Bottom gradient overlay */}
        <div
          style={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            height: "80px",
            background: "linear-gradient(transparent, #0e1117)",
            display: "flex",
          }}
        />
      </div>
    ),
    {
      ...size,
    },
  );
}
