import SwiftUI

struct LibraryOutfitAddition: Decodable, Identifiable {
    let id: String
    let items: [ClothingItemDTO]
    let visualReviewStatus: String?
    let liked: Bool
}

struct LibraryOutfitDTO: Decodable, Identifiable {
    let source: String?
    let id: UUID
    let items: [ClothingItemDTO]
    let optionalAdditions: [LibraryOutfitAddition]?
    let aestheticScore: Double?
    let structuralReason: String
    let aestheticReason: String
    let visualReviewStatus: String?
    let liked: Bool
    let replacesOutfitId: UUID?
}

struct OutfitLibraryResponse: Decodable {
    let outfits: [LibraryOutfitDTO]
    let total: Int
    let jobs: [String: Int]
    let enrolled: Bool
    let nextOffset: Int?
}

private struct OutfitBuildRequest: Encodable {
    let anchorItemID: String?
    let retryFailed: Bool
    enum CodingKeys: String, CodingKey {
        case anchorItemID = "anchor_item_id"
        case retryFailed = "retry_failed"
    }
}

private struct OutfitBuildResponse: Decodable {
    let queued: Int
    let jobs: [String: Int]
}

struct OutfitLibraryView: View {
    @EnvironmentObject private var authStore: AuthStore
    @ObservedObject var closet: ClosetViewModel
    var initialItemID: UUID? = nil
    @State private var anchorID = ""
    @State private var outfits: [LibraryOutfitDTO] = []
    @State private var total = 0
    @State private var jobs: [String: Int] = [:]
    @State private var enrolled = false
    @State private var nextOffset: Int?
    @State private var loading = false
    @State private var building = false
    @State private var error: String?
    @State private var selectedOutfit: LibraryOutfitDTO?
    @State private var refreshID = UUID()
    @State private var requestID = UUID()
    @State private var initialLoadComplete = false
    @AppStorage("closet.outfits.likedOnly") private var likedOnly = false

    init(closet: ClosetViewModel, initialItemID: UUID? = nil) {
        _closet = ObservedObject(wrappedValue: closet)
        self.initialItemID = initialItemID
        _anchorID = State(initialValue: initialItemID?.uuidString.lowercased() ?? "")
    }

    private var pending: Int { jobs["queued", default: 0] + jobs["processing", default: 0] }
    private var failed: Int { jobs["failed", default: 0] }
    private var taskKey: String { anchorID + String(likedOnly) + refreshID.uuidString }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text(libraryStatusTitle)
                    .foregroundStyle(.secondary)
                Spacer()
                Button { refreshID = UUID() } label: { Image(systemName: "arrow.clockwise") }
                    .accessibilityLabel("Refresh outfits")
            }
            if initialItemID == nil {
                Picker("Filter", selection: $likedOnly) {
                    Text("All outfits").tag(false)
                    Text("Liked").tag(true)
                }
                .pickerStyle(.menu)
            }
            if pending > 0 {
                VStack(alignment: .leading, spacing: 4) {
                    Label("Current build · \(jobs["complete", default: 0]) items checked · \(pending) remaining", systemImage: "clock")
                    Text("Existing outfits and new results are shown together below.")
                }
                .font(.footnote).foregroundStyle(.secondary)
            }
            if failed > 0 {
                Text("\(failed) items could not be processed. You can retry them.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            if let error {
                Text(error).font(.footnote).foregroundStyle(.red)
            }
            Button {
                Task { await build() }
            } label: {
                Label(building ? "Queueing…" : failed > 0 ? "Retry failed items" : !anchorID.isEmpty ? "Find outfits with this item" : enrolled ? "Find new outfits" : "Build outfit library", systemImage: "sparkles")
            }
            .buttonStyle(.borderedProminent)
            .disabled(building || pending > 0)

            if (!initialLoadComplete || loading) && outfits.isEmpty {
                ProgressView("Loading outfits").frame(maxWidth: .infinity, minHeight: 120)
            } else if outfits.isEmpty {
                ContentUnavailableView(
                    pending > 0 ? "Your outfits are being prepared" : "No outfits yet",
                    systemImage: "square.stack.3d.up",
                    description: Text(pending > 0 ? "Completed outfits will appear here automatically." : "Build your library to find wearable, coordinated combinations from your clothes.")
                )
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 160), spacing: 12)], spacing: 12) {
                    ForEach(outfits) { outfit in
                        Button { selectedOutfit = outfit } label: {
                            VStack(alignment: .leading, spacing: 8) {
                                OutfitLibraryPreview(items: outfit.items)
                                Text("\(outfit.items.count) core pieces").font(.headline)
                                if outfit.source == "personal" {
                                    Text("Saved by you").font(.caption).foregroundStyle(.secondary)
                                } else if outfit.visualReviewStatus == "pending" {
                                    Text("Awaiting photo review").font(.caption).foregroundStyle(.secondary)
                                }
                                if !(outfit.optionalAdditions ?? []).isEmpty {
                                    Text("Optional layers available").font(.caption).foregroundStyle(.secondary)
                                }
                                Text(outfit.items.map(\.displayTitle).joined(separator: " + "))
                                    .font(.caption).foregroundStyle(.secondary).lineLimit(2)
                            }
                            .padding(10)
                            .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
                        }.buttonStyle(.plain)
                    }
                }
                if nextOffset != nil {
                    Button("Load more") { Task { await load(append: true) } }.disabled(loading)
                }
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .outfitLibraryChanged)) { _ in refreshID = UUID() }
        .onChange(of: anchorID) { _, _ in
            outfits = []; nextOffset = nil; total = 0; initialLoadComplete = false
        }
        .onChange(of: likedOnly) { _, _ in
            outfits = []; nextOffset = nil; total = 0; initialLoadComplete = false
        }
        .task(id: taskKey) {
            await load()
            while !Task.isCancelled {
                do { try await Task.sleep(nanoseconds: 5_000_000_000) }
                catch { return }
                // Keep watching even when idle: recognition may complete for a newly uploaded item.
                if enrolled || pending > 0 { await load() }
            }
        }
        .sheet(item: $selectedOutfit) { outfit in
            OutfitLibraryDetail(outfit: outfit, closet: closet) {
                outfits.removeAll { $0.id == outfit.id }
                total = max(0, total - 1)
                selectedOutfit = nil
            }
        }
    }

    private var libraryStatusTitle: String {
        if !initialLoadComplete || (loading && outfits.isEmpty) {
            return anchorID.isEmpty ? "Loading outfit library…" : "Loading outfits with this item…"
        }
        if !anchorID.isEmpty && outfits.isEmpty && pending > 0 {
            return "Checking the current build for this item…"
        }
        return anchorID.isEmpty ? "\(total) outfits in your library" : "\(total) outfits with this item"
    }

    @MainActor private func load(append: Bool = false) async {
        let thisRequest = UUID()
        requestID = thisRequest
        loading = true
        defer { if requestID == thisRequest { loading = false } }
        let requestedAnchor = anchorID
        let offset = append ? (nextOffset ?? 0) : 0
        // Preserve the loaded page count during background refreshes.
        let limit = append ? 30 : min(100, max(30, outfits.count))
        var query = [URLQueryItem(name: "offset", value: String(offset)), URLQueryItem(name: "limit", value: String(limit))]
        if !requestedAnchor.isEmpty { query.append(URLQueryItem(name: "anchor_item_id", value: requestedAnchor)) }
        if likedOnly { query.append(URLQueryItem(name: "liked_only", value: "true")) }
        do {
            var response: OutfitLibraryResponse = try await APIClient.shared.get(
                "/api/v1/outfits", token: await authStore.validAccessToken(), queryItems: query
            )
            guard !Task.isCancelled && anchorID == requestedAnchor && requestID == thisRequest else { return }
            var fetched = response.outfits
            let desiredCount = max(30, outfits.count)
            while !append, fetched.count < desiredCount, let next = response.nextOffset {
                var moreQuery = [URLQueryItem(name: "offset", value: String(next)),
                                 URLQueryItem(name: "limit", value: String(min(100, desiredCount - fetched.count)))]
                if !requestedAnchor.isEmpty { moreQuery.append(URLQueryItem(name: "anchor_item_id", value: requestedAnchor)) }
                if likedOnly { moreQuery.append(URLQueryItem(name: "liked_only", value: "true")) }
                response = try await APIClient.shared.get("/api/v1/outfits", token: await authStore.validAccessToken(), queryItems: moreQuery)
                guard !Task.isCancelled && anchorID == requestedAnchor && requestID == thisRequest else { return }
                if response.outfits.isEmpty { break }
                fetched += response.outfits
            }
            var known = append ? Set(outfits.map(\.id)) : Set<UUID>()
            let unique = fetched.filter { known.insert($0.id).inserted }
            if append { outfits += unique } else { outfits = unique }
            total = response.total; jobs = response.jobs; enrolled = response.enrolled
            nextOffset = response.nextOffset; error = nil
            initialLoadComplete = true
        } catch {
            guard !Task.isCancelled && requestID == thisRequest else { return }
            self.error = error.localizedDescription
            initialLoadComplete = true
        }
    }

    @MainActor private func build() async {
        building = true
        defer { building = false }
        do {
            let _: OutfitBuildResponse = try await APIClient.shared.post(
                "/api/v1/outfits/build", token: await authStore.validAccessToken(),
                body: OutfitBuildRequest(anchorItemID: anchorID.isEmpty ? nil : anchorID, retryFailed: failed > 0)
            )
            await load()
        } catch { self.error = error.localizedDescription }
    }
}
