# Known Issues and Major Debug Notes

This document records major issues we hit during development, along with root cause and resolution notes. It is intended to preserve debugging context for future contributors across web, backend, and iOS surfaces.

## 2026-08-27 - iOS closet item deletion failed inside detail card

### Symptoms

- Deleting a clothing item from the closet grid/list context menu worked.
- Deleting the same clothing item from inside the item detail sheet failed.
- The detail-sheet delete path sometimes showed `Clothing item not found`.
- In earlier iterations, the simulator could freeze or crash with Swift runtime errors such as:
  - `UnsafeBufferPointer has a nil start and nonzero count`
  - `EXC_BAD_ACCESS`
- In some cases, the sheet dismissed but the item still remained visible in the closet UI.

### Root cause

This issue was caused by two overlapping problems.

1. The detail sheet was not deleting through a stable reference to the current closet item.
   The outer closet view deleted directly from the live list item, but the detail sheet held its own state copy. That meant the inside-card delete flow could send a stale item identity to the backend, which then correctly returned `Clothing item not found`.

2. The iOS local state cleanup logic after deletion was too fragile.
   It attempted to reconcile deleted items using a mix of `id`, `imagePath`, and `imageUrl`. That introduced unstable string comparisons and state reconciliation issues, which triggered Swift runtime crashes and UI inconsistency after delete operations.

### Resolution

- Changed iOS delete handling to use a stable item identity for the sheet delete flow.
- Simplified local item removal logic to match only on `id`.
- Forced the detail sheet to rebuild per item with `.id(item.id)`.
- After successful delete, dismissed the detail sheet and reloaded closet state.
- Tightened the backend delete contract so a delete that does not actually remove a row returns `404` instead of silently behaving like success.

### Why outside delete worked while inside delete failed

The outside delete path operated on the current item instance from the closet list, so it avoided the stale sheet-state problem. The inside delete path passed through a separate detail-state layer, which made stale identity and local reconciliation bugs visible.

### Files involved

- [ClosetHomeView.swift](/Users/luning/Documents/Extracurricular/AI Closet project/ios/AI Closet/ClosetHomeView.swift)
- [ClothingDetailView.swift](/Users/luning/Documents/Extracurricular/AI Closet project/ios/AI Closet/ClothingDetailView.swift)
- [ClosetViewModel.swift](/Users/luning/Documents/Extracurricular/AI Closet project/ios/AI Closet/ViewModels/ClosetViewModel.swift)
- [item_service.py](/Users/luning/Documents/Extracurricular/AI Closet project/backend/app/services/item_service.py)
- [routes.py](/Users/luning/Documents/Extracurricular/AI Closet project/backend/app/api/routes.py)

### Preventive lesson

For iOS sheet- or modal-based editing flows, destructive actions should operate on a stable primary key and not rely on duplicated view-local object state. On the backend side, mutation endpoints should fail explicitly when the target record is not found, so UI bugs do not get masked by weak API behavior.
