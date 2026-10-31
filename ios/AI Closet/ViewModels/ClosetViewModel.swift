import Foundation
import Combine
import PhotosUI
import SwiftUI
import UIKit

@MainActor
final class ClosetViewModel: ObservableObject {
    enum UploadConfig {
        static let batchSize = 5
        static let automaticRetryCount = 2
        static let retryDelayNanoseconds: UInt64 = 1_000_000_000
    }

    struct UploadFailure: Identifiable {
        let id = UUID()
        let photoLabel: String
        let reason: String
    }

    struct PreparedUpload: Codable {
        let photoLabel: String
        let payload: UploadImagePayload
    }

    @Published var items: [ClothingItemDTO] = []
    @Published var summary: ClosetSummaryDTO?
    @Published var taxonomy = TaxonomyDTO(categories: [], colors: [], styles: [], occasions: [], seasons: [], subtypes: [:],lengths:[],sleeveLengths:[])
    @Published var selectedCategories: Set<String> = []
    @Published var selectedColors: Set<String> = []
    @Published var viewMode: ClosetViewMode = .grid
    @Published var isUploading = false
    @Published var hasPendingUploads = false
    @Published var isLoading = false
    @Published var errorMessage: String?
    @Published var uploadFailures: [UploadFailure] = []

    let apiClient = APIClient.shared
    private var pollingTask: Task<Void, Never>?
    private var pollingEnabled = false
    private var pollingTokenProvider: (() async -> String?)?

    var visibleItems: [ClothingItemDTO] {
        items.filter { item in
            let categoryMatches = selectedCategories.isEmpty || selectedCategories.contains(item.category)
            let colorMatches = selectedColors.isEmpty || !selectedColors.isDisjoint(with: ColorSelectionSupport.decode(item.color))
            return categoryMatches && colorMatches
        }
    }

    var categoryOptions: [String] {
        taxonomy.categories.uniqueStrings()
    }

    var colorOptions: [String] {
        taxonomy.colors.uniqueStrings()
    }

    var totalItemCount: Int {
        max(summary?.totalItems ?? 0, items.count)
    }

    var categoryFilterLabel: String {
        filterLabel(for: selectedCategories, emptyLabel: "All categories")
    }

    var colorFilterLabel: String {
        filterLabel(for: selectedColors, emptyLabel: "All colors")
    }

    var hasActiveFilters: Bool {
        !selectedCategories.isEmpty || !selectedColors.isEmpty
    }

    func load(token: String?) async {
        isLoading = true
        hasPendingUploads = ((try? readPendingUploads(token: token).count) ?? 0) > 0
        errorMessage = nil
        defer { isLoading = false }
        do {
            let itemsResponse: [ClothingItemDTO] = try await apiClient.get("/api/v1/items", token: token)
            let summaryResponse: ClosetSummaryDTO = try await apiClient.get("/api/v1/summary", token: token)
            let taxonomyResponse: TaxonomyDTO = try await apiClient.get("/api/v1/taxonomy", token: token)
            ClothingTaxonomySupport.install(taxonomyResponse)
            items = itemsResponse
            summary = Self.reconciledSummary(summaryResponse, using: itemsResponse)
            taxonomy = taxonomyResponse
            startPollingIfNeeded(token: token)
        } catch {
            errorMessage = Self.userFacingError(error)
        }
    }

    func upload(_ pickerItems: [PhotosPickerItem], token: String?) async {
        guard !pickerItems.isEmpty, !isUploading else { return }
        isUploading = true
        errorMessage = nil
        uploadFailures = []
        defer { isUploading = false }

        var preparedImages: [PreparedUpload] = []
        var failures: [UploadFailure] = []

        for (index, pickerItem) in pickerItems.enumerated() {
            let photoLabel = "Photo \(index + 1)"
            do {
                if let data = try await pickerItem.loadTransferable(type: Data.self) {
                    preparedImages.append(
                        PreparedUpload(
                            photoLabel: photoLabel,
                            payload: UploadImagePayload(
                                data: Self.normalizedJPEGData(from: data),
                                filename: "\(UUID().uuidString).jpg"
                            )
                        )
                    )
                } else {
                    failures.append(UploadFailure(photoLabel: photoLabel, reason: "This photo could not be loaded from your library."))
                }
            } catch {
                failures.append(UploadFailure(photoLabel: photoLabel, reason: Self.userFacingError(error)))
            }
        }

        guard !preparedImages.isEmpty else {
            uploadFailures = failures
            errorMessage = "None of the selected photos could be loaded. Please try again."
            return
        }

        do {
            let existing = try readPendingUploads(token: token)
            try writePendingUploads(existing + preparedImages, token: token)
        } catch {
            errorMessage = "Could not save the upload queue. No new photos were sent. \(error.localizedDescription)"
            return
        }
        var uploadedItems: [ClothingItemDTO] = []

        for batch in preparedImages.chunked(into: UploadConfig.batchSize) {
            let result = await uploadBatchWithRetries(batch, token: token)
            uploadedItems.append(contentsOf: result.items)
            failures.append(contentsOf: result.failures)
        }

        uploadFailures = failures

        if uploadedItems.isEmpty {
            let failedCount = failures.count
            if failedCount > 0 {
                errorMessage = "Upload failed for \(failedCount) photo\(failedCount == 1 ? "" : "s"). Please try again."
            } else {
                errorMessage = "Upload failed. Please try again."
            }
            return
        }

        items = (uploadedItems + items).uniqueById()
        summary = Self.reconciledSummary(summary, using: items)
        startPollingIfNeeded(token: token)

        let failedCount = failures.count
        if failedCount > 0 {
            errorMessage = "Uploaded \(uploadedItems.count) of \(pickerItems.count) photos. \(failedCount) failed."
        } else {
            errorMessage = nil
        }
    }

    func update(_ item: ClothingItemDTO, token: String?, editSource: String = "ios", occasionBefore: String? = nil, occasionThresholdAtEdit: Double? = nil, occasionThresholdsAtEdit: [String: Double]? = nil) async -> Bool {
        errorMessage = nil
        do {
            let request = ClothingItemUpdateRequestDTO(
                category: item.category,
                subtype: item.subtype,
                color: item.color,
                season: item.season,
                style: item.style,
                occasion: item.occasion,
                recognitionSummary: item.recognitionSummary,
                editSource: editSource,
                material: item.material ?? "",
                length: item.length ?? "",
                sleeveLength: item.sleeveLength ?? "",
                occasionBefore: occasionBefore,
                occasionThresholdAtEdit: occasionThresholdAtEdit,
                occasionThresholdsAtEdit: occasionThresholdsAtEdit
            )
            let updated: ClothingItemDTO = try await apiClient.patch(Self.itemPath(item.id), token: token, body: request)
            replace(updated)
            return true
        } catch {
            errorMessage = Self.userFacingError(error)
            return false
        }
    }

    func replaceImage(
        _ imageData: Data,
        itemID: UUID,
        editMetadata: ImageEditMetadataDTO?,
        token: String?
    ) async -> ItemImageReplaceResult {
        errorMessage = nil
        let existingItem = items.first(where: { $0.id == itemID })
        let ownedInputData = Self.ownedDataCopy(imageData)
        guard !ownedInputData.isEmpty else {
            let message = "The edited photo is empty. Please try again."
            print(
                "[ClosetViewModel] replaceImage blocked",
                "item_id=\(itemID.uuidString)",
                "reason=empty_input_data",
                "incoming_bytes=\(imageData.count)"
            )
            errorMessage = message
            return .failure(message)
        }
        do {
            print(
                "[ClosetViewModel] replaceImage received",
                "item_id=\(itemID.uuidString)",
                "incoming_bytes=\(imageData.count)",
                "owned_input_bytes=\(ownedInputData.count)"
            )
            print(
                "[ClosetViewModel] replaceImage start",
                "item_id=\(itemID.uuidString)",
                "item_user_id=\(existingItem?.userId ?? "nil")",
                "image_path=\(existingItem?.imagePath ?? "nil")",
                "input_bytes=\(ownedInputData.count)",
                "normalized_bytes=\(ownedInputData.count)",
                "token_present=\(token != nil)"
            )
            let updated = try await apiClient.replaceItemImage(
                ownedInputData,
                itemID: itemID,
                editMetadata: editMetadata,
                token: token
            )
            print(
                "[ClosetViewModel] replaceImage success",
                "requested_item_id=\(itemID.uuidString)",
                "returned_item_id=\(updated.id.uuidString)",
                "returned_user_id=\(updated.userId ?? "nil")",
                "returned_image_path=\(updated.imagePath ?? "nil")"
            )
            replace(updated)
            startPollingIfNeeded(token: token)
            return .success(updated)
        } catch {
            let message = Self.userFacingError(error)
            print(
                "[ClosetViewModel] replaceImage failure",
                "item_id=\(itemID.uuidString)",
                "item_user_id=\(existingItem?.userId ?? "nil")",
                "message=\(message)"
            )
            errorMessage = message
            return .failure(message)
        }
    }

    func delete(_ item: ClothingItemDTO, token: String?) async -> Bool {
        errorMessage = nil
        do {
            print(
                "[ClosetViewModel] delete start",
                "item_id=\(item.id.uuidString)",
                "item_user_id=\(item.userId ?? "nil")",
                "image_path=\(item.imagePath ?? "nil")",
                "token_present=\(token != nil)"
            )
            try await apiClient.delete(Self.itemPath(item.id), token: token)
            print("[ClosetViewModel] delete success", "item_id=\(item.id.uuidString)")
            removeItem(item)
            return true
        } catch {
            let message = Self.userFacingError(error)
            print(
                "[ClosetViewModel] delete failure",
                "item_id=\(item.id.uuidString)",
                "item_user_id=\(item.userId ?? "nil")",
                "message=\(message)"
            )
            if Self.isAlreadyDeleted(error) || Self.isAlreadyDeletedMessage(message) {
                removeItem(item)
                errorMessage = nil
                return true
            }
            errorMessage = message
            return false
        }
    }

    func removeItem(_ item: ClothingItemDTO) {
        let deletedID = item.id
        items.removeAll { $0.id == deletedID }
        if let summary {
            let remainingRecentItems = summary.recentItems.filter { $0.id != deletedID }
            let categoryCounts = Dictionary(grouping: items, by: \.category).mapValues(\.count)
            self.summary = ClosetSummaryDTO(
                totalItems: items.count,
                categoryCounts: categoryCounts,
                recentItems: remainingRecentItems
            )
        }
    }

    private func replace(_ item: ClothingItemDTO) {
        if let index = items.firstIndex(where: { $0.id == item.id }) {
            items[index] = item
        }
        if let summary {
            let refreshedRecentItems = summary.recentItems.map { candidate in
                candidate.id == item.id ? item : candidate
            }
            let categoryCounts = Dictionary(grouping: items, by: \.category).mapValues(\.count)
            self.summary = ClosetSummaryDTO(
                totalItems: items.count,
                categoryCounts: categoryCounts,
                recentItems: refreshedRecentItems
            )
        }
    }

    private static func itemPath(_ itemID: UUID) -> String {
        "/api/v1/items/" + itemID.uuidString
    }

    func pausePolling() {
        pollingEnabled = false
        pollingTokenProvider = nil
        pollingTask?.cancel()
        pollingTask = nil
    }

    func resumePollingIfNeeded(token: String?, tokenProvider: @escaping () async -> String?) {
        pollingTokenProvider = tokenProvider
        pollingEnabled = true
        startPollingIfNeeded(token: token)
    }

    func startPollingIfNeeded(token: String?) {
        guard pollingEnabled else { return }
        guard pollingTask == nil else { return }
        pollingTask = Task { [weak self] in
            while !Task.isCancelled {
                let pending = self?.items.contains(where: \.isRecognitionPending) ?? false
                do {
                    try await Task.sleep(nanoseconds: pending ? 2_500_000_000 : 15_000_000_000)
                } catch { return }
                guard !Task.isCancelled else { return }
                // A poll can outlive the access token captured when this view opened.
                // Resolve/refresh the session on every iteration before sending.
                guard let provider = self?.pollingTokenProvider,
                      let freshToken = await provider() else {
                    self?.errorMessage = "Session expired. Please sign in again."
                    self?.pausePolling()
                    return
                }
                guard !Task.isCancelled else { return }
                await self?.refreshItemsDuringPolling(token: freshToken)
            }
        }
    }

    private func refreshItemsDuringPolling(token: String?) async {
        do {
            let refreshed: [ClothingItemDTO] = try await apiClient.get("/api/v1/items", token: token)
            guard !Task.isCancelled, pollingEnabled else { return }
            items = refreshed
            summary = Self.reconciledSummary(summary, using: refreshed)
        } catch {
            errorMessage = Self.userFacingError(error)
        }
    }

    static func userFacingError(_ error: Error) -> String {
        let message = error.localizedDescription
        if message.contains("schema cache") || message.contains("PGRST204") {
            return "Upload failed because the database schema is not up to date. Run the latest SQL migrations."
        }
        if message.contains("No files were uploaded") {
            return "Upload failed. Please choose a valid clothing image."
        }
        return message
    }

    private static func isAlreadyDeleted(_ error: Error) -> Bool {
        if case APIError.server(let message) = error {
            return isAlreadyDeletedMessage(message)
        }
        let message = String(describing: error).lowercased() + " " + error.localizedDescription.lowercased()
        return isAlreadyDeletedMessage(message)
    }

    private static func isAlreadyDeletedMessage(_ message: String) -> Bool {
        message.localizedCaseInsensitiveContains("not found")
    }

    static func reconciledSummary(_ summary: ClosetSummaryDTO?, using items: [ClothingItemDTO]) -> ClosetSummaryDTO? {
        guard summary != nil else { return nil }
        let categoryCounts = Dictionary(grouping: items, by: \.category).mapValues(\.count)
        return ClosetSummaryDTO(
            totalItems: items.count,
            categoryCounts: categoryCounts,
            recentItems: Array(items.prefix(5))
        )
    }

    func toggleCategory(_ category: String) {
        toggle(category, in: &selectedCategories)
    }

    func toggleColor(_ color: String) {
        toggle(color, in: &selectedColors)
    }

    func clearFilters() {
        selectedCategories.removeAll()
        selectedColors.removeAll()
    }

    private func toggle(_ value: String, in selection: inout Set<String>) {
        if selection.contains(value) {
            selection.remove(value)
        } else {
            selection.insert(value)
        }
    }

    private func filterLabel(for selection: Set<String>, emptyLabel: String) -> String {
        let sortedSelection = Array(selection).sorted()
        guard !sortedSelection.isEmpty else { return emptyLabel }
        if sortedSelection.count == 1 {
            return sortedSelection[0]
        }
        return "\(sortedSelection.count) selected"
    }
}

enum ClosetViewMode {
    case list
    case grid
}

extension Array where Element == ClothingItemDTO {
    func uniqueById() -> [ClothingItemDTO] {
        var seen = Set<UUID>()
        return filter { seen.insert($0.id).inserted }
    }
}

extension Array where Element == String {
    func uniqueStrings() -> [String] {
        var seen = Set<String>()
        return filter { seen.insert($0).inserted }
    }
}

extension Array {
    func chunked(into size: Int) -> [[Element]] {
        guard size > 0 else { return [self] }
        var chunks: [[Element]] = []
        chunks.reserveCapacity((count + size - 1) / size)
        var index = startIndex
        while index < endIndex {
            let nextIndex = self.index(index, offsetBy: size, limitedBy: endIndex) ?? endIndex
            chunks.append(Array(self[index..<nextIndex]))
            index = nextIndex
        }
        return chunks
    }
}
