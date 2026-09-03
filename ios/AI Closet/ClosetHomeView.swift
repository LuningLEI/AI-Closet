import PhotosUI
import SwiftUI

struct ClosetHomeView: View {
    private enum ActiveFilterPanel {
        case category
        case color
    }

    private let contentHorizontalPadding: CGFloat = 16
    @EnvironmentObject private var authStore: AuthStore
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @StateObject private var viewModel = ClosetViewModel()
    @State private var selectedPhotos: [PhotosPickerItem] = []
    @State private var editingItem: ClothingItemDTO?
    @State private var itemPendingDelete: ClothingItemDTO?
    @State private var showingCardDeleteConfirmation = false
    @State private var activeFilterPanel: ActiveFilterPanel?
    @State private var showsFilters = false

    var body: some View {
        ZStack(alignment: .top) {
            NavigationStack {
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        header
                        if showsFilters {
                            filters
                        }
                        content
                    }
                    .padding(contentHorizontalPadding)
                }
                .navigationTitle("Closet")
                .toolbar {
                    ToolbarItem(placement: .navigationBarTrailing) {
                        Picker("View", selection: $viewModel.viewMode) {
                            Image(systemName: "square.grid.2x2").tag(ClosetViewMode.grid)
                            Image(systemName: "list.bullet").tag(ClosetViewMode.list)
                        }
                        .pickerStyle(.segmented)
                        .frame(width: 104)
                    }
                    ToolbarItem(placement: .navigationBarTrailing) {
                        let isUploading = viewModel.isUploading
                        PhotosPicker(selection: $selectedPhotos, maxSelectionCount: 20, matching: .images) {
                            if isUploading {
                                ProgressView()
                            } else {
                                Image(systemName: "plus")
                            }
                        }
                    }
                }
                .refreshable {
                    await viewModel.load(token: await authStore.validAccessToken())
                }
                .onAppear {
                    Task {
                        let token = await authStore.validAccessToken()
                        if viewModel.items.isEmpty && !viewModel.isLoading {
                            await viewModel.load(token: token)
                        } else {
                            viewModel.resumePollingIfNeeded(token: token)
                        }
                    }
                }
                .onDisappear {
                    viewModel.pausePolling()
                }
                .onChange(of: selectedPhotos) { _, newValue in
                    Task {
                        await viewModel.upload(newValue, token: await authStore.validAccessToken())
                        selectedPhotos = []
                    }
                }
                .sheet(item: $editingItem) { item in
                    ClothingDetailView(
                        item: item,
                        viewModel: viewModel,
                        taxonomy: viewModel.taxonomy,
                        tokenProvider: {
                            await authStore.validAccessToken()
                        },
                        onDeleteComplete: {
                            editingItem = nil
                            await viewModel.load(token: await authStore.validAccessToken())
                        }
                    )
                    .id(item.id)
                }
                .confirmationDialog(
                    "Delete this clothing item?",
                    isPresented: $showingCardDeleteConfirmation,
                    titleVisibility: .visible
                ) {
                    Button("Delete", role: .destructive) {
                        guard let item = itemPendingDelete else { return }
                        Task {
                            _ = await viewModel.delete(item, token: await authStore.validAccessToken())
                            itemPendingDelete = nil
                        }
                    }
                    Button("Cancel", role: .cancel) {
                        itemPendingDelete = nil
                    }
                } message: {
                    Text("This removes the clothing card and its recognition records.")
                }
            }

            if activeFilterPanel != nil {
                Color.black.opacity(0.001)
                    .ignoresSafeArea()
                    .onTapGesture {
                        activeFilterPanel = nil
                    }
                    .zIndex(1)
            }

            if let activeFilterPanel {
                VStack {
                    filterPanel(for: activeFilterPanel)
                        .padding(.top, 112)
                        .padding(.horizontal, contentHorizontalPadding + 12)
                    Spacer()
                }
                .zIndex(2)
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Text("\(viewModel.totalItemCount) items indexed")
                    .foregroundStyle(.secondary)

                Spacer(minLength: 0)

                Button {
                    let nextValue = !showsFilters
                    showsFilters = nextValue
                    if !nextValue {
                        activeFilterPanel = nil
                    }
                } label: {
                    Image(systemName: viewModel.hasActiveFilters ? "line.3.horizontal.decrease.circle.fill" : "line.3.horizontal.decrease.circle")
                        .font(.title3)
                        .foregroundStyle(viewModel.hasActiveFilters ? .blue : .secondary)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Toggle filters")
            }
            if let errorMessage = viewModel.errorMessage {
                Label(errorMessage, systemImage: "exclamationmark.triangle.fill")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(.red)
                    .lineLimit(3)
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.red.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
            }
        }
    }

    private var filters: some View {
        HStack(alignment: .center, spacing: 12) {
            filterChipButton(title: viewModel.categoryFilterLabel, panel: .category)
            filterChipButton(title: viewModel.colorFilterLabel, panel: .color)

            Spacer(minLength: 0)

            if viewModel.hasActiveFilters {
                Button("Clear") {
                    viewModel.clearFilters()
                    activeFilterPanel = nil
                }
                .font(.footnote.weight(.semibold))
            }
        }
        .padding(12)
        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 14))
        .zIndex(3)
    }

    @ViewBuilder
    private var content: some View {
        if viewModel.isLoading && viewModel.items.isEmpty {
            ProgressView("Loading closet")
                .frame(maxWidth: .infinity, minHeight: 240)
        } else if viewModel.visibleItems.isEmpty {
            ContentUnavailableView("No clothes yet", systemImage: "tshirt", description: Text("Upload clothing photos to build your private closet."))
        } else if viewModel.viewMode == .grid {
            GeometryReader { proxy in
                let spacing: CGFloat = 14
                let columnCount = CGFloat(gridColumnCount)
                let availableWidth = max(
                    proxy.size.width - (contentHorizontalPadding * 2),
                    0
                )
                let cardWidth = floor((availableWidth - spacing * (columnCount - 1)) / columnCount)

                LazyVGrid(columns: gridColumns(cardWidth: cardWidth), alignment: .leading, spacing: spacing) {
                    ForEach(viewModel.visibleItems) { item in
                        ClosetGridCard(item: item, cardWidth: cardWidth) {
                            editingItem = item
                        } onDelete: {
                            itemPendingDelete = item
                            showingCardDeleteConfirmation = true
                        }
                    }
                }
                .frame(width: availableWidth, alignment: .leading)
            }
            .frame(minHeight: gridContentHeight(itemCount: viewModel.visibleItems.count))
        } else {
            LazyVStack(spacing: 12) {
                ForEach(viewModel.visibleItems) { item in
                    ClosetListCard(item: item) {
                        editingItem = item
                    } onDelete: {
                        itemPendingDelete = item
                        showingCardDeleteConfirmation = true
                    }
                }
            }
        }
    }

    private var gridColumnCount: Int {
        horizontalSizeClass == .regular ? 3 : 2
    }

    private func gridColumns(cardWidth: CGFloat) -> [GridItem] {
        return Array(
            repeating: GridItem(.fixed(cardWidth), spacing: 14),
            count: gridColumnCount
        )
    }

    private func gridContentHeight(itemCount: Int) -> CGFloat {
        let rows = max(1, Int(ceil(Double(itemCount) / Double(gridColumnCount))))
        let cardHeight: CGFloat = 260
        let spacing: CGFloat = 14
        return CGFloat(rows) * cardHeight + CGFloat(max(0, rows - 1)) * spacing
    }

    private func filterChipButton(title: String, panel: ActiveFilterPanel) -> some View {
        Button {
            activeFilterPanel = activeFilterPanel == panel ? nil : panel
        } label: {
            HStack(spacing: 6) {
                Text(title)
                    .lineLimit(1)
                Image(systemName: activeFilterPanel == panel ? "chevron.up" : "chevron.down")
                    .font(.caption.weight(.semibold))
            }
            .font(.body)
            .foregroundStyle(.blue)
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .background(Color(.systemBackground), in: RoundedRectangle(cornerRadius: 12))
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private func filterPanel(for panel: ActiveFilterPanel) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(panel == .category ? "Category" : "Color")
                .font(.headline)

            ScrollView {
                LazyVStack(spacing: 0) {
                    ForEach(filterOptions(for: panel), id: \.self) { option in
                        Button {
                            toggleFilterOption(option, for: panel)
                        } label: {
                            HStack {
                                if panel == .color {
                                    ColorSwatchCircle(colorName: option)
                                }

                                Text(option)
                                    .foregroundStyle(.primary)
                                Spacer()
                                if isFilterSelected(option, for: panel) {
                                    Image(systemName: "checkmark")
                                        .foregroundStyle(.blue)
                                }
                            }
                            .padding(.vertical, 12)
                            .padding(.horizontal, 14)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)

                        if option != filterOptions(for: panel).last {
                            Divider()
                        }
                    }
                }
            }
            .frame(maxHeight: 280)

            if panel == .category ? !viewModel.selectedCategories.isEmpty : !viewModel.selectedColors.isEmpty {
                Button("Clear this filter") {
                    clearFilterPanel(panel)
                }
                .font(.footnote.weight(.semibold))
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.systemBackground), in: RoundedRectangle(cornerRadius: 18))
        .overlay {
            RoundedRectangle(cornerRadius: 18)
                .stroke(Color(.separator).opacity(0.28))
        }
        .shadow(color: .black.opacity(0.08), radius: 16, y: 8)
    }

    private func filterOptions(for panel: ActiveFilterPanel) -> [String] {
        switch panel {
        case .category:
            return viewModel.categoryOptions
        case .color:
            return viewModel.colorOptions
        }
    }

    private func isFilterSelected(_ option: String, for panel: ActiveFilterPanel) -> Bool {
        switch panel {
        case .category:
            return viewModel.selectedCategories.contains(option)
        case .color:
            return viewModel.selectedColors.contains(option)
        }
    }

    private func toggleFilterOption(_ option: String, for panel: ActiveFilterPanel) {
        switch panel {
        case .category:
            viewModel.toggleCategory(option)
        case .color:
            viewModel.toggleColor(option)
        }
    }

    private func clearFilterPanel(_ panel: ActiveFilterPanel) {
        switch panel {
        case .category:
            viewModel.selectedCategories.removeAll()
        case .color:
            viewModel.selectedColors.removeAll()
        }
    }
}

private struct ClosetGridCard: View {
    let item: ClothingItemDTO
    let cardWidth: CGFloat
    let onEdit: () -> Void
    let onDelete: () -> Void

    var body: some View {
        Button(action: onEdit) {
            VStack(alignment: .leading, spacing: 10) {
                ClosetAsyncImage(url: item.imageUrl)
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
            Button(role: .destructive, action: onDelete) {
                Label("Delete", systemImage: "trash")
            }
        }
    }

    private var imageWidth: CGFloat {
        cardWidth - 24
    }
}

private struct ClosetListCard: View {
    let item: ClothingItemDTO
    let onEdit: () -> Void
    let onDelete: () -> Void

    var body: some View {
        Button(action: onEdit) {
            HStack(spacing: 14) {
                ClosetAsyncImage(url: item.imageUrl)
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
            Button(role: .destructive, action: onDelete) {
                Label("Delete", systemImage: "trash")
            }
        }
    }
}

struct ClosetAsyncImage: View {
    let url: String
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
                Image(systemName: "photo")
                    .font(.largeTitle)
                    .foregroundStyle(.secondary)
            case .loading:
                ProgressView()
            }
        }
        .task(id: url) {
            await loadImage(from: resolvedURL)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .contentShape(Rectangle())
        .clipped()
    }

    private func loadImage(from resolvedURL: URL?) async {
        guard let resolvedURL else {
            print("[ClosetAsyncImage] invalid_image_url", "raw=\(url)")
            phase = .failure
            return
        }

        if let cachedImage = RemoteImageCache.shared.image(for: resolvedURL) {
            phase = .success(Image(uiImage: cachedImage))
            return
        }

        phase = .loading

        var request = URLRequest(url: resolvedURL)
        request.timeoutInterval = 20

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse,
                  (200..<300).contains(httpResponse.statusCode),
                  let uiImage = UIImage(data: data) else {
                phase = .failure
                return
            }
            RemoteImageCache.shared.insert(uiImage, for: resolvedURL)
            phase = .success(Image(uiImage: uiImage))
        } catch {
            print(
                "[ClosetAsyncImage] load_failed",
                "url=\(resolvedURL.absoluteString)",
                "message=\(error.localizedDescription)"
            )
            phase = .failure
        }
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
