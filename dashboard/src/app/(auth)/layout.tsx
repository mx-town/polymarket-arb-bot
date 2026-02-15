export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-bg-primary px-4">
      {/* Subtle branding */}
      <div className="mb-8 flex items-center gap-2">
        <div className="h-3 w-3 rounded-full bg-accent-blue" />
        <span className="text-lg font-semibold text-text-primary">
          Polymarket Bot
        </span>
      </div>

      {/* Centered card container */}
      <div className="w-full max-w-md">{children}</div>

      {/* Footer */}
      <p className="mt-8 text-xs text-text-muted">
        &copy; 2026 Polymarket Arb Bot. All rights reserved.
      </p>
    </div>
  );
}
