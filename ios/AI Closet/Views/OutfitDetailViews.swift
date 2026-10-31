import SwiftUI

struct OutfitLibraryPreview: View {
    let items: [ClothingItemDTO]
    var body: some View {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 4) {
            ForEach(items) { item in
                ClosetAsyncImage(url: item.imageUrl, itemID: item.id)
                    .frame(height: 100).clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
    }
}

struct OutfitLibraryDetail: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var authStore: AuthStore
    let outfit: LibraryOutfitDTO
    @ObservedObject var closet: ClosetViewModel
    let onDisliked: () -> Void
    @State private var selectedItem: ClothingItemDTO?
    @State private var editedItems: [ClothingItemDTO]?
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text("Base outfit").font(.headline)
                    OutfitActions(surface: .library, outfitID: outfit.id, items: editedItems ?? outfit.items,
                                  onSaved: { editedItems = $0 }, onDisliked: onDisliked,
                                  initiallyLiked: outfit.liked,showFeedbackActions:false)
                    ForEach(editedItems ?? outfit.items) { item in
                        Button { selectedItem = item } label: {
                            HStack {
                                ClosetAsyncImage(url: item.imageUrl, itemID: item.id)
                                    .frame(width: 96, height: 120).clipShape(RoundedRectangle(cornerRadius: 12))
                                VStack(alignment: .leading) {
                                    Text(item.displayTitle).font(.headline)
                                    Text(item.color).foregroundStyle(.secondary)
                                }
                                Spacer()
                                Image(systemName: "chevron.right")
                            }
                        }.buttonStyle(.plain)
                    }
                    OutfitActions(surface: .library,outfitID:outfit.id,items:editedItems ?? outfit.items,
                                  onDisliked:onDisliked,initiallyLiked:outfit.liked,
                                  showPrimaryActions:false)
                    if editedItems == nil, let additions = outfit.optionalAdditions, !additions.isEmpty {
                        Divider()
                        Text("Optional layers & accessories").font(.headline)
                        Text("Each option goes with the base outfit. Choose for the weather and occasion.")
                            .font(.subheadline).foregroundStyle(.secondary)
                        ForEach(Array(additions.enumerated()), id: \.element.id) { index, addition in
                            VStack(alignment: .leading, spacing: 12) {
                                Text("Option \(index + 1)").font(.subheadline.weight(.semibold))
                                OutfitActions(surface: .library, outfitID: outfit.id,
                                              items: Array(Dictionary((outfit.items + addition.items).map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first }).values),
                                              onSaved: { editedItems = $0 }, onDisliked: onDisliked,
                                              initiallyLiked: addition.liked,showFeedbackActions:false)
                                if addition.visualReviewStatus == "pending" {
                                    Text("Awaiting photo review").font(.caption).foregroundStyle(.secondary)
                                }
                                ForEach(addition.items) { item in
                                    Button { selectedItem = item } label: {
                                        HStack {
                                            ClosetAsyncImage(url: item.imageUrl, itemID: item.id)
                                                .frame(width: 80, height: 100)
                                                .clipShape(RoundedRectangle(cornerRadius: 12))
                                            Text(item.displayTitle)
                                            Spacer()
                                            Image(systemName: "chevron.right")
                                        }
                                    }.buttonStyle(.plain)
                                }
                                OutfitActions(surface:.library,outfitID:outfit.id,
                                              items:Array(Dictionary((outfit.items + addition.items).map { ($0.id,$0) },uniquingKeysWith:{ first,_ in first }).values),
                                              onDisliked:onDisliked,initiallyLiked:addition.liked,
                                              showPrimaryActions:false)
                            }
                            .padding()
                            .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 12))
                        }
                    }
                }.padding()
            }
            .navigationTitle("Outfit")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .sheet(item: $selectedItem) { item in
                ClothingDetailView(item: item, viewModel: closet, taxonomy: closet.taxonomy,
                    tokenProvider: { await authStore.validAccessToken() },
                    onDeleteComplete: { selectedItem = nil; dismiss() })
            }
        }
    }
}

extension Notification.Name {
    static let outfitLibraryChanged = Notification.Name("outfitLibraryChanged")
    static let outfitWearChanged = Notification.Name("outfitWearChanged")
}

struct PersonalOutfitBody: Encodable {
    let itemIds: [UUID]
    let title: String
}
struct WearBody: Encodable {
    let id: UUID
    let itemIds: [UUID]
    let wornAt: String
    let wearDate: String
}
struct OutfitFeedbackBody: Encodable {
    let id: UUID
    let outfitId: UUID?
    let itemIds: [UUID]
    let action: String
    let reasonCodes: [String]
    let note: String?
    let surface: String
}
struct OutfitFeedbackResult: Decodable { let id: UUID }

enum OutfitActionSurface: String {
    case today, library, recommendations, chat
}

// Shared by Today, Recommendations and library detail/optional combinations.
struct OutfitActions: View {
    @EnvironmentObject private var authStore: AuthStore
    var surface: OutfitActionSurface = .recommendations
    var outfitID: UUID? = nil
    let items: [ClothingItemDTO]
    var onSaved: ([ClothingItemDTO]) -> Void = { _ in }
    var onDisliked: () -> Void = {}
    var onWorn: () -> Void = {}
    var onWearUndone: () -> Void = {}
    var initiallyLiked = false
    var showPrimaryActions = true
    var showFeedbackActions = true
    @State private var editing = false
    @State private var pendingWear: WearBody?
    @State private var selectedToday: OutfitWearEventDTO?
    @State private var latestWornAt: String?
    @State private var busy = false
    @State private var message: String?
    @State private var choosingDislikeReason = false
    @State private var liked = false
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if showPrimaryActions {
                HStack {
                    Button("Replace items", systemImage: "arrow.triangle.2.circlepath") { editing = true }
                    Spacer()
                    Button(selectedTodayMatches ? "Cancel selection" : "Wear it today",
                           systemImage: selectedTodayMatches ? "xmark.circle" : "checkmark.circle") {
                        Task {
                            if selectedTodayMatches { await cancelToday() }
                            else { await wearToday() }
                        }
                    }
                }
                .buttonStyle(.bordered)
            }
            if showFeedbackActions && surface != .chat {
                HStack {
                    Button("Not for me", systemImage: "hand.thumbsdown") { choosingDislikeReason = true }
                        .tint(.red)
                    Spacer()
                    Button(liked ? "Liked" : "Like", systemImage: liked ? "heart.fill" : "heart") {
                        Task { await like() }
                    }
                    .disabled(liked || busy)
                }
                .buttonStyle(.borderedProminent)
            }
            if showPrimaryActions, let latestWornAt, let text = Self.lastWornText(latestWornAt) {
                Text(text).font(.footnote).foregroundStyle(.secondary)
            }
            if let message { Text(message).font(.footnote).foregroundStyle(.secondary) }
        }
        .sheet(isPresented: $editing) {
            OutfitComposerView(initialItems: items) { result in
                onSaved(result.items); message = "Saved as a new outfit."
                if surface == .today { Task { await wearToday(result.items) } }
            }
        }
        .confirmationDialog("Why isn't this for you?", isPresented: $choosingDislikeReason, titleVisibility: .visible) {
            Button("Color or pattern") { Task { await dislike("color_pattern") } }
            Button("Style") { Task { await dislike("style") } }
            Button("Too formal") { Task { await dislike("too_formal") } }
            Button("Too casual") { Task { await dislike("too_casual") } }
            Button("Not right for the weather") { Task { await dislike("weather_mismatch") } }
            Button("Not right for the occasion") { Task { await dislike("occasion_mismatch") } }
            Button("Pieces don't match") { Task { await dislike("pieces_do_not_match") } }
            Button("Layering") { Task { await dislike("layering") } }
            Button("Shoes or accessories") { Task { await dislike("shoes_accessories") } }
            Button("Too repetitive") { Task { await dislike("too_repetitive") } }
            Button("No reason") { Task { await dislike(nil) } }
            Button("Cancel", role: .cancel) {}
        }
        .onAppear { liked = initiallyLiked }
        .task(id: items.map(\.id).map(\.uuidString).sorted().joined(separator: ",")) { await loadWearStatus() }
        .onReceive(NotificationCenter.default.publisher(for: .outfitWearChanged)) { _ in
            Task { await loadWearStatus() }
        }
    }
    private var selectedTodayMatches: Bool {
        Set(selectedToday?.itemIds ?? []) == Set(items.map(\.id))
    }
    @MainActor private func wearToday(_ chosenItems:[ClothingItemDTO]?=nil) async {
        busy = true
        defer { busy = false }
        let members=chosenItems ?? items
        let timestamp = ISO8601DateFormatter().string(from: Date())
        if pendingWear?.wornAt != timestamp || pendingWear?.itemIds != members.map(\.id) {
            pendingWear = WearBody(id: UUID(), itemIds: members.map(\.id), wornAt: timestamp,
                                   wearDate: Self.localDateString())
        }
        guard let body = pendingWear else { return }
        do {
            let result: OutfitWearEventDTO = try await APIClient.shared.post("/api/v1/outfits/wear", token: await authStore.validAccessToken(), body: body)
            selectedToday = result; latestWornAt = result.wornAt; pendingWear = nil
            message = "Selected for today."
            onWorn()
            NotificationCenter.default.post(name: .outfitWearChanged, object: nil)
        } catch { message = error.localizedDescription }
    }

    @MainActor private func cancelToday() async {
        guard let eventID=selectedToday?.id else { return }
        busy=true;defer { busy=false }
        do {
            try await APIClient.shared.delete("/api/v1/outfits/wear/\(eventID.uuidString)", token: await authStore.validAccessToken())
            selectedToday=nil;message="Today's outfit selection was canceled."
            await loadWearStatus()
            onWearUndone()
            NotificationCenter.default.post(name: .outfitWearChanged, object: nil)
        } catch { message=error.localizedDescription }
    }

    @MainActor private func loadWearStatus() async {
        var query=[URLQueryItem(name:"wear_date",value:Self.localDateString())]
        query.append(contentsOf:items.map { URLQueryItem(name:"item_ids",value:$0.id.uuidString) })
        do {
            let status:OutfitWearStatusDTO=try await APIClient.shared.get(
                "/api/v1/outfits/wear/status",token:await authStore.validAccessToken(),queryItems:query)
            selectedToday=status.selectedToday;latestWornAt=status.latestWornAt;liked=status.liked
        } catch { if message == nil { message=error.localizedDescription } }
    }

    static func localDateString(_ date:Date=Date())->String {
        let formatter = DateFormatter()
        formatter.calendar = .current
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: date)
    }

    private static func lastWornText(_ value:String)->String? {
        let fractional=ISO8601DateFormatter();fractional.formatOptions=[.withInternetDateTime,.withFractionalSeconds]
        let plain=ISO8601DateFormatter()
        guard let date=fractional.date(from:value) ?? plain.date(from:value) else { return nil }
        if Calendar.current.isDateInToday(date) {
            return "Last worn: Today at \(date.formatted(date:.omitted,time:.shortened))"
        }
        return "Last worn: \(date.formatted(date:.abbreviated,time:.shortened))"
    }

    @MainActor private func like() async {
        busy = true
        defer { busy = false }
        do {
            try await sendFeedback("liked", reason: nil)
            liked = true
            message = "Added to your liked outfits."
            NotificationCenter.default.post(name: .outfitLibraryChanged, object: nil)
        } catch { message = error.localizedDescription }
    }

    @MainActor private func dislike(_ reason: String?) async {
        busy = true
        defer { busy = false }
        do {
            try await sendFeedback("disliked", reason: reason)
            message = "We'll use this to improve your recommendations."
            if surface == .today && selectedTodayMatches { await cancelToday() }
            onDisliked()
        } catch { message = error.localizedDescription }
    }

    private func sendFeedback(_ action: String, reason: String?) async throws {
        let _: OutfitFeedbackResult = try await APIClient.shared.post(
            "/api/v1/outfits/feedback", token: await authStore.validAccessToken(),
            body: OutfitFeedbackBody(id: UUID(), outfitId: outfitID, itemIds: items.map(\.id),
                                     action: action, reasonCodes: reason.map { [$0] } ?? [],
                                     note: nil, surface: surface.rawValue)
        )
    }
}

struct OutfitComposerView: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var authStore: AuthStore
    @StateObject private var closet = ClosetViewModel()
    @State private var selected: [ClothingItemDTO]
    @State private var title = "My outfit"
    @State private var category = "All categories"
    @State private var replacing: UUID?
    @State private var saving = false
    @State private var error: String?
    let onSaved: (LibraryOutfitDTO) -> Void
    init(initialItems: [ClothingItemDTO] = [], onSaved: @escaping (LibraryOutfitDTO) -> Void = { _ in }) {
        _selected = State(initialValue: initialItems)
        self.onSaved = onSaved
    }
    private var candidates: [ClothingItemDTO] {
        closet.items.filter { item in (category == "All categories" || item.category == category) && !selected.contains(where: { s in s.id == item.id }) }
    }
    var body: some View {
        NavigationStack {
            List {
                Section("Outfit") {
                    TextField("Name", text: $title)
                    ForEach(selected) { item in
                        HStack {
                            ClosetAsyncImage(url: item.imageUrl, itemID: item.id).frame(width: 56, height: 70).clipped()
                            VStack(alignment: .leading) { Text(item.displayTitle); Text(item.category).font(.caption).foregroundStyle(.secondary) }
                            Spacer()
                            Button(replacing == item.id ? "Choosing…" : "Replace") { replacing = item.id; category = item.category }.buttonStyle(.borderless)
                            Button { selected.removeAll { $0.id == item.id }; if replacing == item.id { replacing = nil } } label: { Image(systemName: "minus.circle") }.buttonStyle(.borderless)
                        }
                    }
                    if replacing != nil { Button("Cancel replacement") { replacing = nil } }
                }
                Section(replacing == nil ? "Add from your closet" : "Choose a replacement") {
                    Picker("Category", selection: $category) {
                        Text("All categories").tag("All categories")
                        ForEach(Array(Set(closet.items.map(\.category))).sorted(), id: \.self) { Text($0).tag($0) }
                    }
                    if closet.isLoading { ProgressView() }
                    ForEach(candidates) { item in
                        Button {
                            if let id = replacing, let index = selected.firstIndex(where: { $0.id == id }) { selected[index] = item }
                            else if selected.count < 12 { selected.append(item) }
                            replacing = nil
                        } label: {
                            HStack {
                                ClosetAsyncImage(url: item.imageUrl, itemID: item.id).frame(width: 56, height: 70).clipped()
                                VStack(alignment: .leading) { Text(item.displayTitle); Text(item.color).font(.caption) }
                                Spacer(); Image(systemName: "plus.circle")
                            }
                        }.disabled(selected.count >= 12 && replacing == nil)
                    }
                }
                if let error = error ?? closet.errorMessage { Text(error).foregroundStyle(.red) }
            }
            .navigationTitle("Create outfit")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() }.disabled(saving) }
                ToolbarItem(placement: .confirmationAction) { Button("Save") { Task { await save() } }.disabled(saving || selected.isEmpty || title.trimmingCharacters(in: .whitespaces).isEmpty) }
            }
            .task { await closet.load(token: await authStore.validAccessToken()) }
        }
    }
    @MainActor private func save() async {
        saving = true
        defer { saving = false }
        do {
            let result: LibraryOutfitDTO = try await APIClient.shared.post("/api/v1/outfits/personal", token: await authStore.validAccessToken(), body: PersonalOutfitBody(itemIds: selected.map(\.id), title: title))
            onSaved(result)
            NotificationCenter.default.post(name: .outfitLibraryChanged, object: nil)
            dismiss()
        } catch { self.error = error.localizedDescription }
    }
}
