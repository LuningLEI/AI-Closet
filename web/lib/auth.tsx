"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { isSupabaseAuthConfigured, supabase } from "./supabase";

type AuthContextValue = {
  configured: boolean;
  loading: boolean;
  session: Session | null;
  signIn: (email: string, password: string) => Promise<string | null>;
  signUp: (email: string, password: string) => Promise<string | null>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const configured = isSupabaseAuthConfigured();
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(configured);

  useEffect(() => {
    if (!supabase) {
      setLoading(false);
      return;
    }

    let mounted = true;
    supabase.auth.getSession().then(({ data }) => {
      if (!mounted) return;
      setSession(data.session);
      setLoading(false);
    });

    const { data } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      setLoading(false);
    });

    return () => {
      mounted = false;
      data.subscription.unsubscribe();
    };
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      configured,
      loading,
      session,
      async signIn(email: string, password: string) {
        if (!supabase) return "Supabase Auth is not configured.";
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        return error?.message ?? null;
      },
      async signUp(email: string, password: string) {
        if (!supabase) return "Supabase Auth is not configured.";
        const { error, data } = await supabase.auth.signUp({ email, password });
        if (error) return error.message;
        return data.session ? null : "Account created. Check your email if confirmation is enabled.";
      },
      async signOut() {
        if (!supabase) return;
        await supabase.auth.signOut();
      },
    }),
    [configured, loading, session],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used inside AuthProvider.");
  }
  return value;
}
