"use client";

import { useMemo, useRef, useState } from "react";
import useSWR from "swr";
import AuthGate from "../../components/AuthGate";
import ItemCard from "../../components/ItemCard";
import { apiClient } from "../../lib/api-client";
import { useAuth } from "../../lib/auth";
import {
  CATEGORY_OPTIONS,
  CLOSET_RECOGNITION_POLL_INTERVAL_MS,
  COLOR_OPTIONS,
  FILTER_ALL_VALUE,
  RECOGNITION_SOURCE,
  STYLE_OPTIONS,
} from "../../lib/constants";
import { ClothingItem, ClothingItemUpdateRequest } from "../../types";

export default function ClosetPage() {
  const { configured, loading: authLoading, session } = useAuth();
  const canUsePrivateApi = !configured || (!authLoading && Boolean(session));
  const { data: items, error, mutate: mutateItems } = useSWR(
    canUsePrivateApi ? "items" : null,
    apiClient.items.list,
    {
    refreshInterval: (latestItems) =>
      latestItems?.some((item) => item.recognition_source === RECOGNITION_SOURCE.ANALYZING) ? CLOSET_RECOGNITION_POLL_INTERVAL_MS : 0,
    },
  );
  const { data: summary, mutate: mutateSummary } = useSWR(canUsePrivateApi ? "summary" : null, apiClient.items.summary, {
    refreshInterval: items?.some((item) => item.recognition_source === RECOGNITION_SOURCE.ANALYZING) ? CLOSET_RECOGNITION_POLL_INTERVAL_MS : 0,
  });
  const { data: taxonomy } = useSWR(canUsePrivateApi ? "taxonomy" : null, apiClient.taxonomy.get);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState<string>(FILTER_ALL_VALUE);
  const [activeStyle, setActiveStyle] = useState<string>(FILTER_ALL_VALUE);
  const [activeColor, setActiveColor] = useState<string>(FILTER_ALL_VALUE);
  const [viewMode, setViewMode] = useState<"list" | "grid">("list");
  const [editingItem, setEditingItem] = useState<ClothingItem | null>(null);
  const [editForm, setEditForm] = useState({
    category: "",
    subtype: "",
    color: "",
    season: "",
    style: "",
    occasion: "",
    recognition_summary: "",
  });
  const [savingEdit, setSavingEdit] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const filteredItems = useMemo(() => {
    if (!items) return [];
    return items.filter((item) => {
      if (item.recognition_source === RECOGNITION_SOURCE.ANALYZING) {
        return activeCategory === FILTER_ALL_VALUE && activeStyle === FILTER_ALL_VALUE && activeColor === FILTER_ALL_VALUE;
      }
      const categoryMatch = activeCategory === FILTER_ALL_VALUE || item.category === activeCategory;
      const styleMatch = activeStyle === FILTER_ALL_VALUE || item.style === activeStyle;
      const colorMatch = activeColor === FILTER_ALL_VALUE || item.color === activeColor;
      return categoryMatch && styleMatch && colorMatch;
    });
  }, [activeCategory, activeColor, activeStyle, items]);

  const recognizedItems = useMemo(
    () => items?.filter((item) => item.recognition_source !== RECOGNITION_SOURCE.ANALYZING) ?? [],
    [items],
  );

  const visibleCategories = useMemo(() => {
    const usedCategories = new Set(recognizedItems.map((item) => item.category));
    return CATEGORY_OPTIONS.filter((category) => usedCategories.has(category));
  }, [recognizedItems]);

  const visibleStyles = useMemo(() => {
    const usedStyles = new Set(recognizedItems.map((item) => item.style));
    return STYLE_OPTIONS.filter((style) => usedStyles.has(style));
  }, [recognizedItems]);

  const visibleColors = useMemo(() => {
    const usedColors = new Set(recognizedItems.map((item) => item.color));
    return COLOR_OPTIONS.filter((color) => usedColors.has(color));
  }, [recognizedItems]);

  const hasActiveFilters = activeCategory !== FILTER_ALL_VALUE || activeStyle !== FILTER_ALL_VALUE || activeColor !== FILTER_ALL_VALUE;

  function clearFilters() {
    setActiveCategory(FILTER_ALL_VALUE);
    setActiveStyle(FILTER_ALL_VALUE);
    setActiveColor(FILTER_ALL_VALUE);
  }

  function openEditor(item: ClothingItem) {
    setEditingItem(item);
    setEditError(null);
    setEditForm({
      category: item.category,
      subtype: item.subtype ?? "",
      color: item.color,
      season: item.season,
      style: item.style,
      occasion: item.occasion,
      recognition_summary: item.recognition_summary ?? "",
    });
  }

  function updateEditField(field: keyof typeof editForm, value: string) {
    setEditForm((current) => ({
      ...current,
      [field]: value,
      ...(field === "category" ? { subtype: "" } : {}),
    }));
  }

  async function handleSaveEdit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingItem) return;

    setSavingEdit(true);
    setEditError(null);
    try {
      const payload: ClothingItemUpdateRequest = {
        ...editForm,
        subtype: editForm.subtype || null,
        recognition_summary: editForm.recognition_summary || null,
      };
      await apiClient.items.update(editingItem.id, payload);
      setEditingItem(null);
      await Promise.all([mutateItems(), mutateSummary()]);
    } catch (error) {
      setEditError(error instanceof Error ? error.message : "Failed to save item.");
    } finally {
      setSavingEdit(false);
    }
  }

  async function handleUpload(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedFiles.length) return;

    setUploading(true);
    setUploadStatus(null);
    try {
      const formData = new FormData();
      selectedFiles.forEach((file) => {
        formData.append("files", file);
      });
      const result = await apiClient.items.uploadBatch(formData);
      setSelectedFiles([]);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      await Promise.all([mutateItems(), mutateSummary()]);
      const uploadedCount = result.items.length;
      const failedCount = (result.errors ?? []).length;
      setUploadStatus(
        failedCount
          ? `Uploaded ${uploadedCount} item${uploadedCount === 1 ? "" : "s"}. ${failedCount} file${failedCount === 1 ? "" : "s"} failed.`
          : `Uploaded ${uploadedCount} item${uploadedCount === 1 ? "" : "s"}. Cards will update when recognition finishes.`,
      );
    } catch (error) {
      setUploadStatus(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <AuthGate>
      <section className="page-shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">Closet</p>
          <h1>Structured wardrobe inventory</h1>
          <p className="lead compact">
            Upload a piece, let the backend assign wardrobe metadata, and keep the resulting state available to both
            recommendation and chat skills.
          </p>
        </div>
      </header>

      <div className="dashboard-grid">
        <section className="panel">
          <div className="section-heading">
            <div>
              <p className="section-label">Summary</p>
              <h2>Closet coverage</h2>
            </div>
            <span className="metric-badge">{summary?.total_items ?? 0} items</span>
          </div>
          <div className="stats-grid">
            <div className="stat-tile">
              <span>Total indexed</span>
              <strong>{summary?.total_items ?? 0}</strong>
            </div>
            {CATEGORY_OPTIONS.slice(0, 8).map((category) => (
              <div key={category} className="stat-tile">
                <span>{category}</span>
                <strong>{summary?.category_counts?.[category] ?? 0}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="section-heading">
            <div>
              <p className="section-label">Upload</p>
              <h2>Add a clothing image</h2>
            </div>
          </div>
          <form className="upload-form" onSubmit={handleUpload}>
            <label htmlFor="imageUpload">Select garment photos</label>
            <input
              ref={fileInputRef}
              id="imageUpload"
              type="file"
              accept="image/*"
              multiple
              onChange={(event) => setSelectedFiles(Array.from(event.target.files ?? []))}
            />
            <button className="button primary" type="submit" disabled={!selectedFiles.length || uploading}>
              {uploading
                ? "Uploading..."
                : selectedFiles.length > 1
                  ? `Upload ${selectedFiles.length} Items`
                  : "Upload and Analyze"}
            </button>
          </form>
          {uploadStatus && <p className="panel-note">{uploadStatus}</p>}
          <p className="panel-note">
            Recognition runs once at upload time. OpenAI Vision is used when an API key is configured; otherwise the
            backend falls back to local metadata rules.
          </p>
        </section>
      </div>

      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="section-label">Inventory</p>
            <h2>Wardrobe items</h2>
          </div>
          <div className="inventory-actions">
            <div className="view-toggle" aria-label="Inventory view">
              <button
                className={viewMode === "list" ? "active" : ""}
                type="button"
                onClick={() => setViewMode("list")}
              >
                List
              </button>
              <button
                className={viewMode === "grid" ? "active" : ""}
                type="button"
                onClick={() => setViewMode("grid")}
              >
                Grid
              </button>
            </div>
            <span className="metric-badge">{filteredItems.length} shown</span>
          </div>
        </div>

        <div className="closet-filter-bar dropdown-filter-bar" aria-label="Wardrobe filters">
          <label className="dropdown-filter">
            <span>Catalog</span>
            <select value={activeCategory} onChange={(event) => setActiveCategory(event.target.value)}>
              <option value={FILTER_ALL_VALUE}>All categories</option>
              {visibleCategories.map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </select>
          </label>

          <label className="dropdown-filter">
            <span>Style</span>
            <select value={activeStyle} onChange={(event) => setActiveStyle(event.target.value)}>
              <option value={FILTER_ALL_VALUE}>All styles</option>
              {visibleStyles.map((style) => (
                <option key={style} value={style}>
                  {style}
                </option>
              ))}
            </select>
          </label>

          <label className="dropdown-filter color-dropdown-filter">
            <span>Color</span>
            <select value={activeColor} onChange={(event) => setActiveColor(event.target.value)}>
              <option value={FILTER_ALL_VALUE}>All colors</option>
              {visibleColors.map((color) => (
                <option key={color} value={color}>
                  {color}
                </option>
              ))}
            </select>
          </label>

          <button className="button secondary filter-clear-button" type="button" onClick={clearFilters} disabled={!hasActiveFilters}>
            Clear
          </button>
        </div>

        {error && <p className="status-error">Failed to load items.</p>}
        {!items && !error && <p className="status-muted">Loading closet items...</p>}
        {items?.length === 0 && <p className="status-muted">No clothing items found yet.</p>}
        <div className={`inventory-list ${viewMode === "grid" ? "grid-view" : "list-view"}`}>
          {filteredItems.map((item) => (
            <ItemCard key={item.id} item={item} variant={viewMode} onEdit={openEditor} />
          ))}
        </div>
      </section>

      {editingItem && (
        <div className="modal-backdrop" role="presentation">
          <div className="edit-modal" role="dialog" aria-modal="true" aria-labelledby="editItemTitle">
            <div className="modal-heading">
              <div>
                <p className="section-label">Manual edit</p>
                <h2 id="editItemTitle">Update wardrobe item</h2>
              </div>
              <button className="text-button" type="button" onClick={() => setEditingItem(null)}>
                Close
              </button>
            </div>
            <form className="edit-form" onSubmit={handleSaveEdit}>
              <label>
                <span>Catalog</span>
                <select value={editForm.category} onChange={(event) => updateEditField("category", event.target.value)}>
                  {(taxonomy?.categories ?? CATEGORY_OPTIONS).map((category) => (
                    <option key={category} value={category}>
                      {category}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Subtype</span>
                <select value={editForm.subtype} onChange={(event) => updateEditField("subtype", event.target.value)}>
                  <option value="">No subtype</option>
                  {(taxonomy?.subtypes?.[editForm.category] ?? []).filter((subtype) => subtype !== "Unknown").map((subtype) => (
                    <option key={subtype} value={subtype}>
                      {subtype}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Color</span>
                <select value={editForm.color} onChange={(event) => updateEditField("color", event.target.value)}>
                  {(taxonomy?.colors ?? COLOR_OPTIONS).map((color) => (
                    <option key={color} value={color}>
                      {color}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Season</span>
                <input value={editForm.season} onChange={(event) => updateEditField("season", event.target.value)} />
              </label>
              <label>
                <span>Style</span>
                <select value={editForm.style} onChange={(event) => updateEditField("style", event.target.value)}>
                  {(taxonomy?.styles ?? STYLE_OPTIONS).map((style) => (
                    <option key={style} value={style}>
                      {style}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Occasion</span>
                <select value={editForm.occasion} onChange={(event) => updateEditField("occasion", event.target.value)}>
                  {(taxonomy?.occasions ?? []).map((occasion) => (
                    <option key={occasion} value={occasion}>
                      {occasion}
                    </option>
                  ))}
                </select>
              </label>
              <label className="full-width-field">
                <span>Summary</span>
                <textarea
                  value={editForm.recognition_summary}
                  onChange={(event) => updateEditField("recognition_summary", event.target.value)}
                  rows={3}
                />
              </label>
              {editError && <p className="status-error full-width-field">{editError}</p>}
              <div className="modal-actions full-width-field">
                <button className="button secondary" type="button" onClick={() => setEditingItem(null)}>
                  Cancel
                </button>
                <button className="button primary" type="submit" disabled={savingEdit}>
                  {savingEdit ? "Saving..." : "Save changes"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
      </section>
    </AuthGate>
  );
}
