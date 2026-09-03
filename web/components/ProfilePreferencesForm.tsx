"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { apiClient } from "../lib/api-client";
import {
  CATEGORY_OPTIONS,
  DEFAULT_DAILY_OCCASIONS,
  DEFAULT_STYLE_PREFERENCES,
  GENDER_OPTIONS,
  OCCASION_OPTIONS,
  PROFILE_ONBOARDING_PENDING_KEY,
  PROFILE_UPDATED_EVENT,
  STYLE_OPTIONS,
} from "../lib/constants";
import { UserPreferences } from "../types";

export const ONBOARDING_PENDING_KEY = PROFILE_ONBOARDING_PENDING_KEY;

const currentYear = new Date().getFullYear();
const birthYearOptions = ["Prefer not to say", ...Array.from({ length: 90 }, (_, index) => String(currentYear - 12 - index))];

type ProfilePreferences = {
  onboarding_completed?: boolean;
  profile?: {
    nickname?: string | null;
    avatar_path?: string | null;
    avatar_url?: string | null;
    birth_year?: number | string | null;
    gender_identity?: string | null;
    daily_occasions?: string[];
    style_preferences?: string[];
  };
  taxonomy?: {
    selected_categories?: string[];
    custom_categories?: string[];
  };
};

type EditableSection = "identity" | "occasions" | "styles" | "taxonomy";

export default function ProfilePreferencesForm({
  email,
  initialPreferences,
  onboardingMode = false,
  activeSection = null,
  onSignOut,
  onSaved,
}: {
  email?: string | null;
  initialPreferences: UserPreferences;
  onboardingMode?: boolean;
  activeSection?: "memory" | "taxonomy" | null;
  onSignOut?: () => Promise<void>;
  onSaved: (preferences: UserPreferences) => void;
}) {
  const stored = (initialPreferences.preferences ?? {}) as ProfilePreferences;
  const storedProfile = stored.profile ?? {};
  const storedTaxonomy = stored.taxonomy ?? {};
  const initialCustomCategories = storedTaxonomy.custom_categories ?? [];
  const initialBirthYear = storedProfile.birth_year ? String(storedProfile.birth_year) : "Prefer not to say";

  const [selectedCategories, setSelectedCategories] = useState<string[]>(
    storedTaxonomy.selected_categories?.length ? storedTaxonomy.selected_categories : CATEGORY_OPTIONS,
  );
  const [customCategories, setCustomCategories] = useState<string[]>(initialCustomCategories);
  const [customCategoryDraft, setCustomCategoryDraft] = useState("");
  const initialNickname = storedProfile.nickname?.trim() || email?.split("@")[0].replace(/[._-]+/g, " ") || "Closet user";
  const [savedNickname, setSavedNickname] = useState(initialNickname);
  const [nicknameDraft, setNicknameDraft] = useState(initialNickname);
  const [avatarUrl, setAvatarUrl] = useState(storedProfile.avatar_url ?? null);
  const [avatarPath, setAvatarPath] = useState(storedProfile.avatar_path ?? null);
  const [avatarBusy, setAvatarBusy] = useState(false);
  const [avatarPreviewOpen, setAvatarPreviewOpen] = useState(false);
  const [signOutConfirmOpen, setSignOutConfirmOpen] = useState(false);
  const [birthYear, setBirthYear] = useState(initialBirthYear);
  const [genderIdentity, setGenderIdentity] = useState(storedProfile.gender_identity ?? "Prefer not to say");
  const [dailyOccasions, setDailyOccasions] = useState<string[]>(storedProfile.daily_occasions ?? DEFAULT_DAILY_OCCASIONS);
  const [stylePreferences, setStylePreferences] = useState<string[]>(storedProfile.style_preferences ?? DEFAULT_STYLE_PREFERENCES);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editingSection, setEditingSection] = useState<EditableSection | null>(null);

  const categoryOptions = useMemo(
    () => [...CATEGORY_OPTIONS, ...customCategories.filter((category) => !CATEGORY_OPTIONS.includes(category))],
    [customCategories],
  );
  const displayName = useMemo(() => savedNickname.trim() || "Closet user", [savedNickname]);

  function toggleValue(value: string, selected: string[], setter: (values: string[]) => void) {
    setter(selected.includes(value) ? selected.filter((item) => item !== value) : [...selected, value]);
  }

  function addCustomCategory() {
    const nextCategory = customCategoryDraft.trim();
    if (!nextCategory) return;
    if (!categoryOptions.includes(nextCategory)) {
      setCustomCategories((current) => [...current, nextCategory]);
      setSelectedCategories((current) => [...current, nextCategory]);
    }
    setCustomCategoryDraft("");
  }

  async function savePreferences(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setStatus(null);
    setError(null);
    try {
      const parsedBirthYear = birthYear === "Prefer not to say" ? null : Number(birthYear);
      const preferences = await apiClient.preferences.update({
        preferences: {
          ...(initialPreferences.preferences ?? {}),
          onboarding_completed: true,
          profile: {
            nickname: nicknameDraft.trim() || "Closet user",
            avatar_path: avatarPath,
            birth_year: Number.isFinite(parsedBirthYear) ? parsedBirthYear : null,
            gender_identity: genderIdentity,
            daily_occasions: dailyOccasions,
            style_preferences: stylePreferences,
          },
          taxonomy: {
            selected_categories: selectedCategories.length ? selectedCategories : CATEGORY_OPTIONS,
            custom_categories: customCategories,
          },
        },
      });
      const nextProfile = preferences.preferences?.profile as { avatar_url?: string | null; nickname?: string | null } | undefined;
      const nextNickname = nextProfile?.nickname?.trim() || nicknameDraft.trim() || "Closet user";
      setSavedNickname(nextNickname);
      setNicknameDraft(nextNickname);
      setAvatarUrl(nextProfile?.avatar_url ?? avatarUrl);
      if (typeof window !== "undefined") {
        window.localStorage.removeItem(ONBOARDING_PENDING_KEY);
        window.dispatchEvent(
            new CustomEvent(PROFILE_UPDATED_EVENT, {
            detail: { nickname: nextNickname, avatarUrl: nextProfile?.avatar_url ?? avatarUrl },
          }),
        );
      }
      onSaved(preferences);
      setStatus(onboardingMode ? "Profile setup complete." : "Profile preferences saved.");
      setEditingSection(null);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to save profile.");
    } finally {
      setBusy(false);
    }
  }

  async function uploadAvatar(file: File | null) {
    if (!file) return;
    setAvatarBusy(true);
    setStatus(null);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const preferences = await apiClient.profile.uploadAvatar(formData);
      const nextProfile = preferences.preferences?.profile as { avatar_path?: string | null; avatar_url?: string | null } | undefined;
      setAvatarPath(nextProfile?.avatar_path ?? null);
      setAvatarUrl(nextProfile?.avatar_url ?? null);
      onSaved(preferences);
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent(PROFILE_UPDATED_EVENT, {
            detail: { nickname: savedNickname, avatarUrl: nextProfile?.avatar_url ?? null },
          }),
        );
      }
      setStatus("Profile photo updated.");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to upload profile photo.");
    } finally {
      setAvatarBusy(false);
    }
  }

  function isEditing(section: EditableSection) {
    return activeSection === "memory" || activeSection === "taxonomy" || editingSection === section;
  }

  function renderEditButton(section: EditableSection) {
    if (section === "occasions" || section === "styles") {
      return (
        <Link className="section-edit-button" href="/profile?section=memory">
          Edit
        </Link>
      );
    }
    if (section === "taxonomy") {
      return (
        <Link className="section-edit-button" href="/profile?section=taxonomy">
          Edit
        </Link>
      );
    }
    const active = editingSection === section;
    return (
      <button className="section-edit-button" type="button" onClick={() => setEditingSection(active ? null : section)}>
        {active ? "Done" : "Edit"}
      </button>
    );
  }

  function renderSubpageHeader(title: string, label: string) {
    return (
      <div className="profile-subpage-heading">
        <div>
          <p className="section-label">{label}</p>
          <h2>{title}</h2>
        </div>
        <Link className="button secondary" href="/profile">
          Back to profile
        </Link>
      </div>
    );
  }

  if (activeSection === "memory") {
    return (
      <form className="profile-settings-form" onSubmit={savePreferences}>
        <section className="profile-card profile-settings-section">
          {renderSubpageHeader("Style preference", "Preferences")}
          <div className="profile-subsection">
            <div>
              <p className="section-label">Daily occasions</p>
              <h3>What you usually dress for</h3>
            </div>
            <div className="checkbox-grid compact">
              {OCCASION_OPTIONS.map((occasion) => (
                <label key={occasion} className="checkbox-pill">
                  <input
                    type="checkbox"
                    checked={dailyOccasions.includes(occasion)}
                    onChange={() => toggleValue(occasion, dailyOccasions, setDailyOccasions)}
                  />
                  <span>{occasion}</span>
                </label>
              ))}
            </div>
          </div>
          <div className="profile-subsection">
            <div>
              <p className="section-label">Style Signal</p>
              <h3>Preferred style language</h3>
            </div>
            <div className="checkbox-grid compact">
              {STYLE_OPTIONS.map((style) => (
                <label key={style} className="checkbox-pill">
                  <input
                    type="checkbox"
                    checked={stylePreferences.includes(style)}
                    onChange={() => toggleValue(style, stylePreferences, setStylePreferences)}
                  />
                  <span>{style}</span>
                </label>
              ))}
            </div>
          </div>
        </section>
        <div className="profile-save-bar">
          <div>
            {status ? <p className="status-success">{status}</p> : null}
            {error ? <p className="status-error">{error}</p> : null}
          </div>
          <button className="button primary" type="submit" disabled={busy || dailyOccasions.length === 0 || stylePreferences.length === 0}>
            {busy ? "Saving..." : "Save style preference"}
          </button>
        </div>
      </form>
    );
  }

  if (activeSection === "taxonomy") {
    return (
      <form className="profile-settings-form" onSubmit={savePreferences}>
        <section className="profile-card profile-settings-section">
          {renderSubpageHeader("Catalog tags", "Catalog Taxonomy")}
          <div className="checkbox-grid">
            {categoryOptions.map((category) => (
              <label key={category} className="checkbox-pill">
                <input
                  type="checkbox"
                  checked={selectedCategories.includes(category)}
                  onChange={() => toggleValue(category, selectedCategories, setSelectedCategories)}
                />
                <span>{category}</span>
              </label>
            ))}
          </div>
          <div className="custom-tag-row">
            <input
              value={customCategoryDraft}
              onChange={(event) => setCustomCategoryDraft(event.target.value)}
              placeholder="Add a custom catalog tag"
            />
            <button className="button secondary" type="button" onClick={addCustomCategory}>
              Add
            </button>
          </div>
        </section>
        <div className="profile-save-bar">
          <div>
            {status ? <p className="status-success">{status}</p> : null}
            {error ? <p className="status-error">{error}</p> : null}
          </div>
          <button className="button primary" type="submit" disabled={busy || selectedCategories.length === 0}>
            {busy ? "Saving..." : "Save catalog tags"}
          </button>
        </div>
      </form>
    );
  }

  return (
    <form className="profile-settings-form" onSubmit={savePreferences}>
      <section className="profile-hero-card">
        <div className="profile-photo-wrap">
          <button
            className="profile-photo-button"
            type="button"
            onClick={() => {
              if (avatarUrl) setAvatarPreviewOpen(true);
            }}
            aria-label="View profile photo"
          >
            {avatarUrl ? (
              <img src={avatarUrl} alt="" />
            ) : (
              <span className="account-avatar profile-photo" aria-hidden="true">
                {displayName.slice(0, 1).toUpperCase()}
              </span>
            )}
          </button>
          <label className="profile-photo-edit" aria-label="Change profile photo">
            <input accept="image/*" type="file" onChange={(event) => uploadAvatar(event.target.files?.[0] ?? null)} />
            <span>{avatarBusy ? "..." : "✎"}</span>
          </label>
        </div>
        <div>
          <h2>{displayName}</h2>
        </div>
        {onSignOut ? (
          <button className="button secondary profile-hero-signout" type="button" onClick={() => setSignOutConfirmOpen(true)}>
            Sign out
          </button>
        ) : null}
      </section>

      <section className="profile-card profile-settings-card">
        <div id="personal" className="profile-settings-row">
          <div className="section-heading">
            <div>
              <h2>Basic profile</h2>
            </div>
            {renderEditButton("identity")}
          </div>
          {isEditing("identity") ? (
            <div className="two-column-fields">
              <label>
                Nickname
                <input value={nicknameDraft} onChange={(event) => setNicknameDraft(event.target.value)} placeholder="Your display name" />
              </label>
              <label>
                Birth year
                <select value={birthYear} onChange={(event) => setBirthYear(event.target.value)}>
                  {birthYearOptions.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Gender
                <select value={genderIdentity} onChange={(event) => setGenderIdentity(event.target.value)}>
                  {GENDER_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          ) : (
            <dl className="profile-detail-grid">
              <div>
                <dt>Nickname</dt>
                <dd>{displayName}</dd>
              </div>
              <div>
                <dt>Birth year</dt>
                <dd>{birthYear}</dd>
              </div>
              <div>
                <dt>Gender</dt>
                <dd>{genderIdentity}</dd>
              </div>
            </dl>
          )}
        </div>

        <div id="memory" className="profile-settings-row">
          <div className="section-heading">
            <div>
              <h2>Style preference</h2>
            </div>
            {renderEditButton("occasions")}
          </div>
        </div>

        <div id="taxonomy" className="profile-settings-row">
          <div className="section-heading">
            <div>
              <h2 className="inline-count-heading">
                Catalog tags <span>{selectedCategories.length}</span>
              </h2>
            </div>
            {renderEditButton("taxonomy")}
          </div>
        </div>
      </section>

      {onboardingMode || editingSection ? (
        <div className="profile-save-bar">
          <div>
            {status ? <p className="status-success">{status}</p> : null}
            {error ? <p className="status-error">{error}</p> : null}
          </div>
          <button
            className="button primary"
            type="submit"
            disabled={busy || selectedCategories.length === 0 || dailyOccasions.length === 0 || stylePreferences.length === 0}
          >
            {busy ? "Saving..." : onboardingMode ? "Finish setup" : "Save preferences"}
          </button>
        </div>
      ) : null}
      {!onboardingMode && !editingSection && (status || error) ? (
        <div className="profile-inline-status">
          {status ? <p className="status-success">{status}</p> : null}
          {error ? <p className="status-error">{error}</p> : null}
        </div>
      ) : null}
      {avatarPreviewOpen && avatarUrl ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setAvatarPreviewOpen(false)}>
          <div
            className="avatar-preview-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Profile photo preview"
            onClick={(event) => event.stopPropagation()}
          >
            <button className="text-button avatar-preview-close" type="button" onClick={() => setAvatarPreviewOpen(false)}>
              Close
            </button>
            <img src={avatarUrl} alt="" />
          </div>
        </div>
      ) : null}
      {signOutConfirmOpen && onSignOut ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setSignOutConfirmOpen(false)}>
          <div
            className="confirm-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="signOutConfirmTitle"
            onClick={(event) => event.stopPropagation()}
          >
            <div>
              <p className="section-label">Account</p>
              <h2 id="signOutConfirmTitle">Sign out?</h2>
            </div>
            <p className="confirm-copy">You will need to sign in again to access your closet and profile.</p>
            <div className="modal-actions">
              <button className="button secondary" type="button" onClick={() => setSignOutConfirmOpen(false)}>
                Cancel
              </button>
              <button className="button primary" type="button" onClick={onSignOut}>
                Sign out
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </form>
  );
}
