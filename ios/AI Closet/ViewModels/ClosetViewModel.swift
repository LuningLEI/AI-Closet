import Foundation
import Combine
import PhotosUI
import SwiftUI
import UIKit

@MainActor
final class ClosetViewModel: ObservableObject {
    private enum UploadConfig {
        static let batchSize = 5
    }

    @Published var items: [ClothingItemDTO] = []
    @Published var summary: ClosetSummaryDTO?
    @Published var taxonomy = TaxonomyDTO(categories: [], colors: [], styles: [], occasions: [], seasons: [], subtypes: [:])
    @Published var selectedCategories: Set<String> = []
    @Published var selectedColors: Set<String> = []
    @Published var viewMode: ClosetViewMode = .grid
    @Published var isUploading = false
    @Published var isLoading = false
    @Published var errorMessage: String?

    private let apiClient = APIClient.shared
    private var pollingTask: Task<Void, Never>?

    var visibleItems: [ClothingItemDTO] {
        items.filter { item in
            let categoryMatches = selectedCategories.isEmpty || selectedCategories.contains(item.category)
            let colorMatches = selectedColors.isEmpty || selectedColors.contains(item.color)
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
        errorMessage = nil
        defer { isLoading = false }
        do {
            let itemsResponse: [ClothingItemDTO] = try await apiClient.get("/api/v1/items", token: token)
            let summaryResponse: ClosetSummaryDTO = try await apiClient.get("/api/v1/summary", token: token)
            let taxonomyResponse: TaxonomyDTO = try await apiClient.get("/api/v1/taxonomy", token: token)
            items = itemsResponse
            summary = Self.reconciledSummary(summaryResponse, using: itemsResponse)
            taxonomy = taxonomyResponse
            startPollingIfNeeded(token: token)
        } catch {
            errorMessage = Self.userFacingError(error)
        }
    }

    func upload(_ pickerItems: [PhotosPickerItem], token: String?) async {
        guard !pickerItems.isEmpty else { return }
        isUploading = true
        errorMessage = nil
        defer { isUploading = false }

        var preparedImages: [Data] = []
        var skippedCount = 0

        for pickerItem in pickerItems {
            do {
                if let data = try await pickerItem.loadTransferable(type: Data.self) {
                    preparedImages.append(Self.normalizedJPEGData(from: data))
                } else {
                    skippedCount += 1
                }
            } catch {
                skippedCount += 1
            }
        }

        guard !preparedImages.isEmpty else {
            errorMessage = "None of the selected photos could be loaded. Please try again."
            return
        }

        var uploadedItems: [ClothingItemDTO] = []
        var backendFailures: [BatchUploadFailureDTO] = []
        var failedChunkCount = 0

        for batch in preparedImages.chunked(into: UploadConfig.batchSize) {
            do {
                let response = try await apiClient.uploadImages(batch, token: token)
                uploadedItems.append(contentsOf: response.items)
                backendFailures.append(contentsOf: response.errors)
            } catch {
                failedChunkCount += batch.count
                print(
                    "[ClosetViewModel] upload batch failed",
                    "batch_size=\(batch.count)",
                    "message=\(error.localizedDescription)"
                )
            }
        }

        if uploadedItems.isEmpty {
            let failedCount = backendFailures.count + skippedCount + failedChunkCount
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

        let failedCount = backendFailures.count + skippedCount + failedChunkCount
        if failedCount > 0 {
            errorMessage = "Uploaded \(uploadedItems.count) of \(pickerItems.count) photos. \(failedCount) failed."
        } else {
            errorMessage = nil
        }
    }

    func update(_ item: ClothingItemDTO, token: String?) async {
        errorMessage = nil
        do {
            let request = ClothingItemUpdateRequestDTO(
                category: item.category,
                subtype: item.subtype,
                color: item.color,
                season: item.season,
                style: item.style,
                occasion: item.occasion,
                recognitionSummary: item.recognitionSummary
            )
            let updated: ClothingItemDTO = try await apiClient.patch(Self.itemPath(item.id), token: token, body: request)
            replace(updated)
        } catch {
            errorMessage = Self.userFacingError(error)
        }
    }

    func replaceImage(_ imageData: Data, itemID: UUID, token: String?) async -> ItemImageReplaceResult {
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
            let updated = try await apiClient.replaceItemImage(ownedInputData, itemID: itemID, token: token)
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
        stopPollingIfNoPendingItems()
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
        pollingTask?.cancel()
        pollingTask = nil
    }

    func resumePollingIfNeeded(token: String?) {
        startPollingIfNeeded(token: token)
    }

    private func startPollingIfNeeded(token: String?) {
        guard items.contains(where: \.isRecognitionPending) else {
            pollingTask?.cancel()
            pollingTask = nil
            return
        }
        guard pollingTask == nil else { return }
        pollingTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 2_500_000_000)
                await self?.refreshItemsDuringPolling(token: token)
            }
        }
    }

    private func refreshItemsDuringPolling(token: String?) async {
        do {
            let refreshed: [ClothingItemDTO] = try await apiClient.get("/api/v1/items", token: token)
            items = refreshed
            summary = Self.reconciledSummary(summary, using: refreshed)
            if !refreshed.contains(where: \.isRecognitionPending) {
                pollingTask?.cancel()
                pollingTask = nil
            }
        } catch {
            errorMessage = Self.userFacingError(error)
        }
    }

    private func stopPollingIfNoPendingItems() {
        guard !items.contains(where: \.isRecognitionPending) else { return }
        pollingTask?.cancel()
        pollingTask = nil
    }

    private static func normalizedJPEGData(from data: Data) -> Data {
        guard let image = UIImage(data: data),
              let jpeg = image.jpegData(compressionQuality: 0.86) else {
            return data
        }
        return jpeg
    }

    private static func ownedDataCopy(_ data: Data) -> Data {
        data.withUnsafeBytes { Data($0) }
    }

    private static func userFacingError(_ error: Error) -> String {
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

    private static func reconciledSummary(_ summary: ClosetSummaryDTO?, using items: [ClothingItemDTO]) -> ClosetSummaryDTO? {
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

private extension Array where Element == ClothingItemDTO {
    func uniqueById() -> [ClothingItemDTO] {
        var seen = Set<UUID>()
        return filter { seen.insert($0.id).inserted }
    }
}

private extension Array where Element == String {
    func uniqueStrings() -> [String] {
        var seen = Set<String>()
        return filter { seen.insert($0).inserted }
    }
}

private extension Array {
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
