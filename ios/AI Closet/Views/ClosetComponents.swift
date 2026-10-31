import SwiftUI

struct UploadFailureDetailsView: View {
    let failures: [ClosetViewModel.UploadFailure]
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List(failures) { failure in
                VStack(alignment: .leading, spacing: 5) {
                    Text(failure.photoLabel)
                        .font(.headline)
                    Text(failure.reason)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
                .padding(.vertical, 3)
            }
            .navigationTitle("Upload failures")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        dismiss()
                    }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

struct ClosetGridCard: View {
    let item: ClothingItemDTO
    let cardWidth: CGFloat
    let onEdit: () -> Void
    let onDelete: () -> Void
    let onViewOutfits: () -> Void

    var body: some View {
        Button(action: onEdit) {
            VStack(alignment: .leading, spacing: 10) {
                ClosetAsyncImage(url: item.imageUrl, itemID: item.id)
                .frame(width: imageWidth, height: 168)
                .background(Color(.tertiarySystemBackground))
                .clipShape(RoundedRectangle(cornerRadius: 16))

                VStack(alignment: .leading, spacing: 4) {
                    Text(item.displayTitle)
                        .font(.headline)
                        .lineLimit(1)
                        .truncationMode(.tail)
                    if item.isRecognitionPending {
                        Label("Analyzing", systemImage: "sparkles")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.blue)
                            .lineLimit(1)
                    } else if item.isRecognitionFailed {
                        Label("Recognition failed", systemImage: "exclamationmark.triangle")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.orange)
                    } else {
                        Text([item.category, item.color, item.style].joined(separator: " · "))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                            .truncationMode(.tail)
                    }
                }
                .frame(width: imageWidth, alignment: .leading)
                .frame(height: 54, alignment: .topLeading)
            }
            .padding(12)
            .frame(width: cardWidth, height: 260, alignment: .topLeading)
            .background(Color(.systemBackground), in: RoundedRectangle(cornerRadius: 18))
            .overlay {
                RoundedRectangle(cornerRadius: 18).stroke(Color(.separator).opacity(0.35))
            }
            .contentShape(RoundedRectangle(cornerRadius: 18))
            .clipped()
        }
        .buttonStyle(.plain)
        .contextMenu {
            Button(action: onViewOutfits) {
                Label("Outfits with this item", systemImage: "square.stack")
            }
            Button(role: .destructive, action: onDelete) {
                Label("Delete", systemImage: "trash")
            }
        }
    }

    private var imageWidth: CGFloat {
        cardWidth - 24
    }
}

struct ClosetListCard: View {
    let item: ClothingItemDTO
    let onEdit: () -> Void
    let onDelete: () -> Void
    let onViewOutfits: () -> Void

    var body: some View {
        Button(action: onEdit) {
            HStack(spacing: 14) {
                ClosetAsyncImage(url: item.imageUrl, itemID: item.id)
                    .frame(width: 92, height: 92)
                    .clipShape(RoundedRectangle(cornerRadius: 14))

                VStack(alignment: .leading, spacing: 6) {
                    Text(item.displayTitle)
                        .font(.headline)
                    if item.isRecognitionPending {
                        Text("Recognition in progress")
                            .foregroundStyle(.secondary)
                    } else {
                        Text(item.recognitionSummary ?? "\(item.color) \(item.category.lowercased()) for \(item.occasion.lowercased()).")
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .foregroundStyle(.tertiary)
            }
            .padding(12)
            .background(Color(.systemBackground), in: RoundedRectangle(cornerRadius: 18))
            .overlay {
                RoundedRectangle(cornerRadius: 18).stroke(Color(.separator).opacity(0.35))
            }
        }
        .buttonStyle(.plain)
        .contextMenu {
            Button(action: onViewOutfits) {
                Label("Outfits with this item", systemImage: "square.stack")
            }
            Button(role: .destructive, action: onDelete) {
                Label("Delete", systemImage: "trash")
            }
        }
    }
}

struct ClosetAsyncImage: View {
    let url: String
    var itemID: UUID? = nil
    var onURLRefreshed: ((String) -> Void)? = nil
    @EnvironmentObject private var authStore: AuthStore
    @Environment(\.scenePhase) private var scenePhase
    @State private var isClosetVisible = false
    @State private var retryCount = 0
    @State private var phase: RemoteImagePhase = .loading

    var body: some View {
        let resolvedURL = ImageURLResolver.resolve(url)

        ZStack {
            Color(.tertiarySystemBackground)
            switch phase {
            case .success(let image):
                image
                    .resizable()
                    .scaledToFill()
            case .failure:
                Button {
                    retryCount += 1
                } label: {
                    Label("Retry photo", systemImage: "arrow.clockwise")
                        .font(.caption)
                }
                .buttonStyle(.borderless)
            case .loading:
                ProgressView()
            }
        }
        .task(id: "\(url)#\(retryCount)") {
            await loadImage(from: resolvedURL)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .contentShape(Rectangle())
        .clipped()
    }

    @MainActor
    private func loadImage(from resolvedURL: URL?) async {
        guard let resolvedURL else {
            phase = .failure
            return
        }
        if let cachedImage = RemoteImageCache.shared.image(for: resolvedURL) {
            phase = .success(Image(uiImage: cachedImage))
            return
        }
        phase = .loading
        do {
            let image: UIImage
            do {
                image = try await downloadImage(from: resolvedURL)
            } catch {
                // Scrolling away cancels loads; cancellation is not an image failure.
                try Task.checkCancellation()
                guard let itemID else { throw error }
                let token = await authStore.validAccessToken()
                let fresh: ClothingItemDTO = try await APIClient.shared.get(
                    "/api/v1/items/\(itemID.uuidString.lowercased())", token: token
                )
                try Task.checkCancellation()
                guard let freshURL = ImageURLResolver.resolve(fresh.imageUrl) else {
                    throw URLError(.badURL)
                }
                image = try await downloadImage(from: freshURL)
                try Task.checkCancellation()
                RemoteImageCache.shared.insert(image, for: freshURL)
                onURLRefreshed?(fresh.imageUrl)
            }
            try Task.checkCancellation()
            RemoteImageCache.shared.insert(image, for: resolvedURL)
            phase = .success(Image(uiImage: image))
        } catch {
            guard !Task.isCancelled else { return }
            // Do not log signed URLs: they contain temporary access tokens.
            print("[ClosetAsyncImage] load_failed", "message=\(error.localizedDescription)")
            phase = .failure
        }
    }

    private func downloadImage(from url: URL) async throws -> UIImage {
        var request = URLRequest(url: url)
        request.timeoutInterval = 30
        request.cachePolicy = .reloadIgnoringLocalCacheData
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
        guard let image = UIImage(data: data) else { throw URLError(.cannotDecodeContentData) }
        return image
    }

}

private enum RemoteImagePhase {
    case loading
    case success(Image)
    case failure
}

private final class RemoteImageCache {
    static let shared = RemoteImageCache()

    private let cache = NSCache<NSURL, UIImage>()

    private init() {}

    func image(for url: URL) -> UIImage? {
        cache.object(forKey: url as NSURL)
    }

    func insert(_ image: UIImage, for url: URL) {
        cache.setObject(image, forKey: url as NSURL)
    }
}
