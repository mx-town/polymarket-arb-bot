"use client";

import Link from "next/link";

function GitHubIcon() {
  return (
    <svg
      className="h-5 w-5"
      fill="currentColor"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path
        fillRule="evenodd"
        d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
        clipRule="evenodd"
      />
    </svg>
  );
}

export default function LoginPage() {
  return (
    <div className="rounded-lg border border-border-primary bg-bg-secondary p-8">
      <h1 className="mb-1 text-xl font-semibold text-text-primary">
        Sign In
      </h1>
      <p className="mb-6 text-sm text-text-secondary">
        Enter your credentials to access the dashboard
      </p>

      <form
        onSubmit={(e) => e.preventDefault()}
        className="space-y-4"
      >
        {/* Email */}
        <div>
          <label
            htmlFor="email"
            className="mb-1.5 block text-sm font-medium text-text-secondary"
          >
            Email
          </label>
          <input
            id="email"
            type="email"
            placeholder="you@example.com"
            autoComplete="email"
            className="w-full rounded-md border border-border-primary bg-bg-primary px-3 py-2 text-sm text-text-primary placeholder:text-text-muted outline-none transition-colors focus:border-accent-blue focus:ring-1 focus:ring-accent-blue"
          />
        </div>

        {/* Password */}
        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <label
              htmlFor="password"
              className="text-sm font-medium text-text-secondary"
            >
              Password
            </label>
            <Link
              href="#"
              className="text-xs text-accent-blue hover:underline"
            >
              Forgot password?
            </Link>
          </div>
          <input
            id="password"
            type="password"
            placeholder="••••••••"
            autoComplete="current-password"
            className="w-full rounded-md border border-border-primary bg-bg-primary px-3 py-2 text-sm text-text-primary placeholder:text-text-muted outline-none transition-colors focus:border-accent-blue focus:ring-1 focus:ring-accent-blue"
          />
        </div>

        {/* Sign In button */}
        <button
          type="submit"
          className="w-full rounded-md bg-accent-blue px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
        >
          Sign In
        </button>
      </form>

      {/* Divider */}
      <div className="my-6 flex items-center gap-3">
        <div className="h-px flex-1 bg-border-primary" />
        <span className="text-xs text-text-muted">or</span>
        <div className="h-px flex-1 bg-border-primary" />
      </div>

      {/* GitHub OAuth */}
      <button
        type="button"
        className="flex w-full items-center justify-center gap-2 rounded-md border border-border-primary bg-bg-tertiary px-4 py-2 text-sm font-medium text-text-primary transition-colors hover:bg-bg-hover"
      >
        <GitHubIcon />
        Continue with GitHub
      </button>

      {/* Register link */}
      <p className="mt-6 text-center text-sm text-text-secondary">
        Don&apos;t have an account?{" "}
        <Link
          href="/register"
          className="font-medium text-accent-blue hover:underline"
        >
          Sign Up
        </Link>
      </p>
    </div>
  );
}
