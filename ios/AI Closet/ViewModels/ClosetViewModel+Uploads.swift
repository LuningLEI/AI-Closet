import Foundation
import UIKit

@MainActor
extension ClosetViewModel {
    static func normalizedJPEGData(from data: Data) -> Data {
        guard let image = UIImage(data: data),
              let jpeg = image.jpegData(compressionQuality: 0.86) else {
            return data
        }
        return jpeg
    }

    // Queue contents are scoped to the authenticated account, never to a rotating token.
    // Photos stay in Application Support until acknowledged; no credentials are persisted.
    func uploadQueueURL(token: String?) throws -> URL {
        guard let token, token.split(separator: ".").count == 3 else { throw APIError.missingSession }
        var part = String(token.split(separator: ".")[1]).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        part += String(repeating: "=", count: (4 - part.count % 4) % 4)
        guard let data = Data(base64Encoded: part),
              let claims = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let subject = claims["sub"] as? String, let owner = UUID(uuidString: subject) else {
            throw APIError.missingSession
        }
        var directory = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                                     appropriateFor: nil, create: true).appendingPathComponent("PendingUploads", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try directory.setResourceValues(values)
        return directory.appendingPathComponent(owner.uuidString + ".json")
    }

    func readPendingUploads(token: String?) throws -> [PreparedUpload] {
        let url = try uploadQueueURL(token: token)
        guard FileManager.default.fileExists(atPath: url.path) else { return [] }
        return try JSONDecoder().decode([PreparedUpload].self, from: Data(contentsOf: url))
    }

    func writePendingUploads(_ pending: [PreparedUpload], token: String?) throws {
        let url = try uploadQueueURL(token: token)
        try JSONEncoder().encode(pending).write(to: url, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        hasPendingUploads = !pending.isEmpty
    }

    func retryPendingUploads(token: String?) async {
        guard !isUploading else { return }
        isUploading = true
        defer { isUploading = false }
        do {
            let pending = try readPendingUploads(token: token)
            var failures: [UploadFailure] = []
            for batch in pending.chunked(into: UploadConfig.batchSize) {
                let result = await uploadBatchWithRetries(batch, token: token)
                items = (result.items + items).uniqueById()
                failures.append(contentsOf: result.failures)
            }
            uploadFailures = failures
            summary = Self.reconciledSummary(summary, using: items)
            errorMessage = failures.isEmpty ? nil : "Some uploads are still pending. You can retry them when connected."
            startPollingIfNeeded(token: token)
        } catch {
            errorMessage = Self.userFacingError(error)
        }
    }

    func uploadBatchWithRetries(
        _ initialBatch: [PreparedUpload],
        token: String?
    ) async -> (items: [ClothingItemDTO], failures: [UploadFailure]) {
        var batch = initialBatch
        var uploadedItems: [ClothingItemDTO] = []

        for attempt in 0...UploadConfig.automaticRetryCount {
            guard !Task.isCancelled else {
                return (uploadedItems, batch.map { UploadFailure(photoLabel: $0.photoLabel, reason: "Upload paused; retry pending uploads to continue.") })
            }
            do {
                let response = try await apiClient.uploadImages(batch.map(\.payload), token: token)
                uploadedItems.append(contentsOf: response.items)
                let failedNames = Set(response.errors.map(\.filename))
                let confirmedNames = Set(batch.map { $0.payload.filename }).subtracting(failedNames)
                // Only acknowledge a complete, internally consistent per-file response.
                guard response.items.count + response.errors.count == batch.count,
                      failedNames.isSubset(of: Set(batch.map { $0.payload.filename })) else {
                    throw APIError.invalidResponse
                }
                let pending = try readPendingUploads(token: token)
                try writePendingUploads(pending.filter { !confirmedNames.contains($0.payload.filename) }, token: token)

                guard !response.errors.isEmpty else {
                    return (uploadedItems, [])
                }

                let itemsByFilename = Dictionary(uniqueKeysWithValues: batch.map { ($0.payload.filename, $0) })
                let retryableFailures = response.errors.filter { itemsByFilename[$0.filename] != nil }
                let unmatchedFailures = response.errors.filter { itemsByFilename[$0.filename] == nil }

                if retryableFailures.isEmpty || attempt == UploadConfig.automaticRetryCount {
                    return (
                        uploadedItems,
                        response.errors.map { failure in
                            UploadFailure(
                                photoLabel: itemsByFilename[failure.filename]?.photoLabel ?? failure.filename,
                                reason: failure.detail
                            )
                        }
                    )
                }

                print(
                    "[ClosetViewModel] retrying failed uploads",
                    "attempt=\(attempt + 1)",
                    "failed_count=\(retryableFailures.count)"
                )
                batch = retryableFailures.compactMap { itemsByFilename[$0.filename] }
                let delay = UploadConfig.retryDelayNanoseconds * UInt64(attempt + 1)
                try? await Task.sleep(nanoseconds: delay)

                if !unmatchedFailures.isEmpty {
                    return (
                        uploadedItems,
                        unmatchedFailures.map { UploadFailure(photoLabel: $0.filename, reason: $0.detail) }
                    )
                }
            } catch {
                if attempt < UploadConfig.automaticRetryCount && !Task.isCancelled {
                    try? await Task.sleep(nanoseconds: UploadConfig.retryDelayNanoseconds * UInt64(attempt + 1))
                    continue
                }
                let reason = Self.userFacingError(error)
                print(
                    "[ClosetViewModel] upload batch failed without a response",
                    "batch_size=\(batch.count)",
                    "message=\(reason)"
                )
                return (uploadedItems, batch.map { UploadFailure(photoLabel: $0.photoLabel, reason: reason) })
            }
        }

        return (uploadedItems, [])
    }

    static func ownedDataCopy(_ data: Data) -> Data {
        data.withUnsafeBytes { Data($0) }
    }

}
