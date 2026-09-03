"use client";

import { useAuth } from "../lib/auth";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const { configured, loading, session } = useAuth();

  if (!configured) {
    return <>{children}</>;
  }

  if (loading) {
    return (
      <section className="auth-required-panel">
        <p className="section-label">Account</p>
        <h1>Checking your session</h1>
        <p className="lead compact">Loading your closet workspace.</p>
      </section>
    );
  }

  if (!session) {
    return (
      <section className="auth-required-panel">
        <p className="section-label">Private closet</p>
        <h1>Sign in to view your wardrobe</h1>
        <p className="lead compact">
          Your clothing items, images, weather preferences, recommendations, and agent context are scoped to your
          Supabase account.
        </p>
      </section>
    );
  }

  return <>{children}</>;
}
