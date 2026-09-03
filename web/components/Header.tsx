"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { apiClient } from "../lib/api-client";
import { useAuth } from "../lib/auth";
import { PROFILE_ONBOARDING_PENDING_KEY, PROFILE_UPDATED_EVENT } from "../lib/constants";
import { UserPreferences } from "../types";

const navItems = [
  { href: "/", label: "Today" },
  { href: "/closet", label: "Closet" },
  { href: "/recommendations", label: "Recommendations" },
  { href: "/chat", label: "Agent Chat" },
];
const ONBOARDING_ALWAYS_SHOW_EMAILS = new Set(["luninglei.2027@gmail.com"]);

export default function Header() {
  const { configured, loading, session } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [authOpen, setAuthOpen] = useState(false);
  const [loadedPreferencesFor, setLoadedPreferencesFor] = useState<string | null>(null);
  const [nickname, setNickname] = useState("Closet user");
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);

  useEffect(() => {
    const userId = session?.user.id ?? null;
    const userEmail = session?.user.email?.toLowerCase() ?? "";
    if (!configured || loading || !userId || loadedPreferencesFor === userId) return;

    setLoadedPreferencesFor(userId);
    apiClient.preferences.get()
      .then((nextPreferences) => {
        const profile = nextPreferences.preferences?.profile as { avatar_url?: string | null; nickname?: string | null } | undefined;
        setNickname(profile?.nickname?.trim() || session?.user.email?.split("@")[0].replace(/[._-]+/g, " ") || "Closet user");
        setAvatarUrl(profile?.avatar_url ?? null);
        const shouldAlwaysShowOnboarding = ONBOARDING_ALWAYS_SHOW_EMAILS.has(userEmail);
        const onboardingPending =
          typeof window !== "undefined" && window.localStorage.getItem(PROFILE_ONBOARDING_PENDING_KEY) === "true";
        if (shouldAlwaysShowOnboarding || (onboardingPending && !Boolean(nextPreferences.preferences?.onboarding_completed))) {
          if (pathname !== "/profile") {
            router.replace("/profile?onboarding=1");
          }
        } else if (onboardingPending && Boolean(nextPreferences.preferences?.onboarding_completed)) {
          window.localStorage.removeItem(PROFILE_ONBOARDING_PENDING_KEY);
        }
      })
      .catch(() => {});
  }, [configured, loadedPreferencesFor, loading, pathname, router, session?.user.email, session?.user.id]);

  useEffect(() => {
    function updateNickname(event: Event) {
      const detail = (event as CustomEvent<{ avatarUrl?: string | null; nickname?: string }>).detail;
      if (detail?.nickname) {
        setNickname(detail.nickname);
      }
      if ("avatarUrl" in detail) {
        setAvatarUrl(detail.avatarUrl ?? null);
      }
    }

    window.addEventListener(PROFILE_UPDATED_EVENT, updateNickname);
    return () => window.removeEventListener(PROFILE_UPDATED_EVENT, updateNickname);
  }, []);

  return (
    <header className="site-header">
      <div className="brand-block">
        <Link className="brand-link" href="/">
          AI Closet
        </Link>
      </div>
      <nav className="site-nav" aria-label="Primary">
        {navItems.map((item) => (
          <Link key={item.href} href={item.href}>
            {item.label}
          </Link>
        ))}
      </nav>
      <section className="auth-panel" aria-label="Account">
        {!configured ? (
          <span className="auth-status demo">Demo mode</span>
        ) : loading ? (
          <span className="auth-status">Checking account...</span>
        ) : session ? (
          <Link className="account-menu" href="/profile" aria-label="Open profile">
            <span className="account-avatar" aria-hidden="true">
              {avatarUrl ? <img src={avatarUrl} alt="" /> : nickname.slice(0, 1).toUpperCase()}
            </span>
            <div className="account-copy">
              <strong>{nickname}</strong>
            </div>
          </Link>
        ) : (
          <button className="button primary compact-button" type="button" onClick={() => setAuthOpen(true)}>
            Sign in
          </button>
        )}
      </section>
      {authOpen ? <AuthModal onClose={() => setAuthOpen(false)} /> : null}
    </header>
  );
}

function AuthModal({ onClose }: { onClose: () => void }) {
  const { signIn, signUp } = useAuth();
  const [mode, setMode] = useState<"sign-in" | "sign-up">("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [messageTone, setMessageTone] = useState<"error" | "success">("error");

  async function submitAuth(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const result = mode === "sign-in" ? await signIn(email, password) : await signUp(email, password);
      if (result) {
        if (mode === "sign-up" && result.startsWith("Account created") && typeof window !== "undefined") {
          window.localStorage.setItem(PROFILE_ONBOARDING_PENDING_KEY, "true");
        }
        setMessage(result);
        setMessageTone(mode === "sign-up" && result.startsWith("Account created") ? "success" : "error");
        return;
      }
      if (mode === "sign-up" && typeof window !== "undefined") {
        window.localStorage.setItem(PROFILE_ONBOARDING_PENDING_KEY, "true");
      }
      onClose();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop auth-backdrop" role="presentation">
      <div className="auth-modal" role="dialog" aria-modal="true" aria-labelledby="authTitle">
        <div className="modal-heading">
          <div>
            <p className="section-label">Account</p>
            <h2 id="authTitle">{mode === "sign-in" ? "Sign in to your closet" : "Create your closet account"}</h2>
          </div>
          <button className="text-button" type="button" onClick={onClose}>
            Close
          </button>
        </div>

        <div className="auth-mode wide">
          <button className={mode === "sign-in" ? "active" : ""} type="button" onClick={() => setMode("sign-in")}>
            Sign in
          </button>
          <button className={mode === "sign-up" ? "active" : ""} type="button" onClick={() => setMode("sign-up")}>
            Register
          </button>
        </div>

        <form className="auth-form modal-auth-form" onSubmit={submitAuth}>
          <label>
            Email
            <input
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              type="email"
              placeholder="you@example.com"
            />
          </label>
          <label>
            Password
            <input
              autoComplete={mode === "sign-in" ? "current-password" : "new-password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              type="password"
              placeholder="At least 6 characters"
            />
          </label>
          <button className="button primary" type="submit" disabled={busy || !email || password.length < 6}>
            {busy ? "Working..." : mode === "sign-in" ? "Sign in" : "Create account"}
          </button>
          {message ? <p className={messageTone === "success" ? "status-success" : "status-error"}>{message}</p> : null}
        </form>
      </div>
    </div>
  );
}
