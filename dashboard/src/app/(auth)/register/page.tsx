"use client";

import Link from "next/link";

export default function RegisterPage() {
  return (
    <div className="rounded-lg border border-border-primary bg-bg-secondary p-8">
      <h1 className="mb-1 text-xl font-semibold text-text-primary">
        Create Account
      </h1>
      <p className="mb-6 text-sm text-text-secondary">
        Set up your dashboard account to get started
      </p>

      <form
        onSubmit={(e) => e.preventDefault()}
        className="space-y-4"
      >
        {/* Name */}
        <div>
          <label
            htmlFor="name"
            className="mb-1.5 block text-sm font-medium text-text-secondary"
          >
            Name
          </label>
          <input
            id="name"
            type="text"
            placeholder="Your name"
            autoComplete="name"
            className="w-full rounded-md border border-border-primary bg-bg-primary px-3 py-2 text-sm text-text-primary placeholder:text-text-muted outline-none transition-colors focus:border-accent-blue focus:ring-1 focus:ring-accent-blue"
          />
        </div>

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
          <label
            htmlFor="password"
            className="mb-1.5 block text-sm font-medium text-text-secondary"
          >
            Password
          </label>
          <input
            id="password"
            type="password"
            placeholder="••••••••"
            autoComplete="new-password"
            className="w-full rounded-md border border-border-primary bg-bg-primary px-3 py-2 text-sm text-text-primary placeholder:text-text-muted outline-none transition-colors focus:border-accent-blue focus:ring-1 focus:ring-accent-blue"
          />
        </div>

        {/* Confirm Password */}
        <div>
          <label
            htmlFor="confirm-password"
            className="mb-1.5 block text-sm font-medium text-text-secondary"
          >
            Confirm Password
          </label>
          <input
            id="confirm-password"
            type="password"
            placeholder="••••••••"
            autoComplete="new-password"
            className="w-full rounded-md border border-border-primary bg-bg-primary px-3 py-2 text-sm text-text-primary placeholder:text-text-muted outline-none transition-colors focus:border-accent-blue focus:ring-1 focus:ring-accent-blue"
          />
        </div>

        {/* Terms checkbox */}
        <div className="flex items-start gap-2">
          <input
            id="terms"
            type="checkbox"
            className="mt-1 h-4 w-4 rounded border-border-primary bg-bg-primary accent-accent-blue"
          />
          <label
            htmlFor="terms"
            className="text-sm text-text-secondary"
          >
            I agree to the{" "}
            <Link href="#" className="text-accent-blue hover:underline">
              Terms of Service
            </Link>{" "}
            and{" "}
            <Link href="#" className="text-accent-blue hover:underline">
              Privacy Policy
            </Link>
          </label>
        </div>

        {/* Create Account button */}
        <button
          type="submit"
          className="w-full rounded-md bg-accent-blue px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
        >
          Create Account
        </button>
      </form>

      {/* Sign In link */}
      <p className="mt-6 text-center text-sm text-text-secondary">
        Already have an account?{" "}
        <Link
          href="/login"
          className="font-medium text-accent-blue hover:underline"
        >
          Sign In
        </Link>
      </p>
    </div>
  );
}
