"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import AuthGate from "../../components/AuthGate";
import ProfilePreferencesForm from "../../components/ProfilePreferencesForm";
import { apiClient } from "../../lib/api-client";
import { useAuth } from "../../lib/auth";

export default function ProfilePage() {
  return (
    <Suspense fallback={<p className="status-muted">Loading profile...</p>}>
      <ProfilePageContent />
    </Suspense>
  );
}

function ProfilePageContent() {
  const searchParams = useSearchParams();
  const onboardingMode = searchParams.get("onboarding") === "1";
  const activeSection = searchParams.get("section");
  const { configured, loading: authLoading, session, signOut } = useAuth();
  const canUsePrivateApi = !configured || (!authLoading && Boolean(session));
  const { data: preferences, error, mutate } = useSWR(canUsePrivateApi ? "preferences" : null, apiClient.preferences.get);
  return (
    <AuthGate>
      <section className="profile-dashboard">
        <div className="profile-workspace">
          <header className="profile-title-row">
            <div>
              <p className="eyebrow">{onboardingMode ? "Setup" : "Profile"}</p>
              <h1>
                {activeSection === "memory"
                  ? "Style Preference"
                  : activeSection === "taxonomy"
                    ? "Catalog Tags"
                    : onboardingMode
                      ? "Set up your closet profile"
                      : "My Profile"}
              </h1>
            </div>
          </header>

          {error ? <p className="status-error">Failed to load profile preferences.</p> : null}
          {!preferences && !error ? <p className="status-muted">Loading profile preferences...</p> : null}
          {preferences ? (
            <ProfilePreferencesForm
              email={session?.user.email ?? null}
              initialPreferences={preferences}
              onboardingMode={onboardingMode}
              activeSection={activeSection === "memory" || activeSection === "taxonomy" ? activeSection : null}
              onSignOut={signOut}
              onSaved={(nextPreferences) => mutate(nextPreferences, false)}
            />
          ) : null}
        </div>
      </section>
    </AuthGate>
  );
}
