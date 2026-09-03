import SwiftUI
import SwiftData
import PhotosUI

struct CategoryClosetView: View {
    let category: String

    @Environment(\.modelContext) private var modelContext
    @Query private var items: [ClothingItem]

    @State private var selectedItem: PhotosPickerItem?
    @State private var draft: PendingClothingDraft?
    @State private var cropEditorItem: ClothingItem?
    @State private var detailItem: ClothingItem?
    @State private var isEditMode = false
    @State private var selectedForDeletion = Set<UUID>()
    private let recognitionPipeline = ClothingRecognitionPipeline()

    private let columns = [
        GridItem(.flexible(), spacing: 12),
        GridItem(.flexible(), spacing: 12)
    ]
    init(category: String) {
        self.category = category
        _items = Query(
            filter: #Predicate<ClothingItem> { $0.category == category },
            sort: [SortDescriptor(\ClothingItem.createdAt, order: .reverse)]
        )
    }

    var body: some View {
        ScrollView {
            LazyVGrid(columns: columns, spacing: 12) {
                ForEach(items) { item in
                    ZStack {
                        Button {
                            handleCardTap(for: item)
                        } label: {
                            Group {
                                if let uiImage = loadCardImage(for: item) {
                                    Image(uiImage: uiImage)
                                        .resizable()
                                        .scaledToFill()
                                } else {
                                    RoundedRectangle(cornerRadius: 16)
                                        .foregroundStyle(.secondary.opacity(0.2))
                                }
                            }
                            .frame(maxWidth: .infinity)
                            .aspectRatio(1, contentMode: .fit)
                            .overlay {
                                RoundedRectangle(cornerRadius: 16)
                                    .stroke(
                                        selectedForDeletion.contains(item.id) ? Color.red : Color.clear,
                                        lineWidth: 3
                                    )
                            }
                            .clipShape(RoundedRectangle(cornerRadius: 16))
                            .contentShape(RoundedRectangle(cornerRadius: 16))
                        }
                        .buttonStyle(.plain)
                        .disabled(false)

                        if isEditMode {
                            Button {
                                cropEditorItem = item
                            } label: {
                                Image(systemName: "pencil")
                                    .font(.system(size: 13, weight: .semibold))
                                    .foregroundStyle(.primary)
                                    .frame(width: 30, height: 30)
                                    .background(.thinMaterial, in: Circle())
                            }
                            .buttonStyle(.plain)
                            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
                            .padding(8)

                            Image(systemName: selectedForDeletion.contains(item.id) ? "checkmark.circle.fill" : "circle")
                                .font(.system(size: 22, weight: .semibold))
                                .foregroundStyle(selectedForDeletion.contains(item.id) ? .red : .white)
                                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                                .padding(8)
                        }
                    }
                    .contextMenu {
                        Button(role: .destructive) {
                            deleteItem(item)
                        } label: {
                            Label("Delete", systemImage: "trash")
                        }
                    }
                }
            }
            .padding(16)
        }
        .navigationTitle(category)
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                Button {
                    toggleEditMode()
                } label: {
                    Image(systemName: isEditMode ? "xmark" : "pencil")
                }
            }
            ToolbarItem(placement: .navigationBarTrailing) {
                PhotosPicker(selection: $selectedItem, matching: .images) {
                    Image(systemName: "plus")
                }
                .disabled(isEditMode)
            }
            if isEditMode {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Delete (\(selectedForDeletion.count))", role: .destructive) {
                        deleteSelectedItems()
                    }
                    .disabled(selectedForDeletion.isEmpty)
                }
            }
        }
        .onChange(of: selectedItem) {
            print("ON CHANGE TRIGGERED")
            Task {
                guard let picked = selectedItem,
                      let data = try? await picked.loadTransferable(type: Data.self) else {
                    return
                }

                let analysis = await recognitionPipeline.analyze(imageData: data, fallbackCategory: category)
                draft = PendingClothingDraft(imageData: data, analysis: analysis)

                selectedItem = nil
            }
        }
        .sheet(item: $draft) { draft in
            AddClothingSheet(imageData: draft.imageData, analysis: draft.analysis)
        }
        .sheet(item: $cropEditorItem) { item in
            CoverCropEditorSheet(item: item)
        }
        .navigationDestination(item: $detailItem) { item in
            LegacyClothingDetailView(item: item)
        }
    }

    private func deleteItem(_ item: ClothingItem) {
        withAnimation {
            deleteImageFiles(for: item)
            ClothingItemPersistenceSupport.deleteItem(item, in: modelContext)
        }
    }

    private func loadCardImage(for item: ClothingItem) -> UIImage? {
        if let coverFilename = item.coverImageFilename,
           let coverImage = loadImage(filename: coverFilename) {
            return coverImage
        }

        guard let image = loadImage(filename: item.imageFilename) else { return nil }
        return centeredSquareImage(from: image)
    }

    private func loadImage(filename: String) -> UIImage? {
        let url = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(filename)
        return UIImage(contentsOfFile: url.path)
    }

    private func handleCardTap(for item: ClothingItem) {
        if isEditMode {
            if selectedForDeletion.contains(item.id) {
                selectedForDeletion.remove(item.id)
            } else {
                selectedForDeletion.insert(item.id)
            }
            return
        }

        detailItem = item
    }

    private func toggleEditMode() {
        isEditMode.toggle()
        if !isEditMode {
            selectedForDeletion.removeAll()
        }
    }

    private func deleteSelectedItems() {
        let itemsToDelete = items.filter { selectedForDeletion.contains($0.id) }
        withAnimation {
            for item in itemsToDelete {
                deleteImageFiles(for: item)
                ClothingItemPersistenceSupport.deleteItem(item, in: modelContext)
            }
        }
        selectedForDeletion.removeAll()
        isEditMode = false
    }

    private func deleteImageFiles(for item: ClothingItem) {
        let documentsURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let imageURLs = [item.imageFilename, item.coverImageFilename].compactMap { filename in
            filename.map { documentsURL.appendingPathComponent($0) }
        }

        for url in imageURLs where FileManager.default.fileExists(atPath: url.path) {
            try? FileManager.default.removeItem(at: url)
        }
    }

    private func centeredSquareImage(from image: UIImage) -> UIImage? {
        guard let cgImage = image.cgImage else { return image }

        let width = CGFloat(cgImage.width)
        let height = CGFloat(cgImage.height)
        let side = min(width, height)
        let origin = CGPoint(x: (width - side) / 2, y: (height - side) / 2)
        let rect = CGRect(origin: origin, size: CGSize(width: side, height: side)).integral

        guard let cropped = cgImage.cropping(to: rect) else { return image }
        return UIImage(cgImage: cropped)
    }
}

private struct LegacyClothingDetailView: View {
    let item: ClothingItem

    var body: some View {
        Form {
            Section("Item") {
                Text(item.category)
                Text(item.style)
                Text(item.occasion)
            }
        }
        .navigationTitle("Item")
    }
}

private struct CoverCropEditorSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var modelContext

    let item: ClothingItem

    @State private var uiImage: UIImage?
    @State private var dragOffset: CGSize = .zero
    @State private var committedOffset: CGSize = .zero
    @State private var zoomScale: CGFloat = 1
    @State private var committedZoomScale: CGFloat = 1
    @State private var editorSide: CGFloat = 0

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 20) {
                Text("Move and zoom the image to choose the cover.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 20)

                if let uiImage {
                    GeometryReader { proxy in
                        let side = min(proxy.size.width, proxy.size.height)

                        ZStack {
                            RoundedRectangle(cornerRadius: 24)
                                .fill(Color(.secondarySystemBackground))

                            CoverCropCanvas(
                                image: uiImage,
                                cropSide: side,
                                dragOffset: $dragOffset,
                                committedOffset: $committedOffset,
                                zoomScale: $zoomScale,
                                committedZoomScale: $committedZoomScale
                            )
                        }
                        .frame(width: side, height: side)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                        .onAppear {
                            editorSide = side
                        }
                        .onChange(of: side) { _, newValue in
                            editorSide = newValue
                        }
                    }
                    .frame(height: 420)
                    .padding(.horizontal, 20)
                } else {
                    ProgressView()
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }

                Spacer(minLength: 0)
            }
            .padding(.top, 20)
            .navigationTitle("Edit Cover")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Cancel") {
                        dismiss()
                    }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Save") {
                        saveCover()
                    }
                    .disabled(uiImage == nil)
                }
            }
        }
        .task {
            loadImage()
        }
    }

    private func loadImage() {
        let url = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(item.imageFilename)

        uiImage = UIImage(contentsOfFile: url.path)
        dragOffset = .zero
        committedOffset = .zero
        zoomScale = 1
        committedZoomScale = 1
    }

    private func saveCover() {
        guard let uiImage,
              let cgImage = uiImage.cgImage else {
            return
        }

        let imageSize = CGSize(width: cgImage.width, height: cgImage.height)
        let squareSide = editorSide > 0 ? editorSide : min(imageSize.width, imageSize.height)
        let baseScale = max(squareSide / imageSize.width, squareSide / imageSize.height)
        let totalScale = baseScale * zoomScale
        let scaledSize = CGSize(width: imageSize.width * totalScale, height: imageSize.height * totalScale)
        let maxHorizontalShift = max((scaledSize.width - squareSide) / 2, 0)
        let maxVerticalShift = max((scaledSize.height - squareSide) / 2, 0)

        let clampedX = min(max(dragOffset.width, -maxHorizontalShift), maxHorizontalShift)
        let clampedY = min(max(dragOffset.height, -maxVerticalShift), maxVerticalShift)

        let originX = ((scaledSize.width - squareSide) / 2 - clampedX) / totalScale
        let originY = ((scaledSize.height - squareSide) / 2 - clampedY) / totalScale
        let cropSide = squareSide / totalScale
        let cropRect = CGRect(x: originX, y: originY, width: cropSide, height: cropSide)
            .intersection(CGRect(origin: .zero, size: imageSize))
            .integral

        guard let cropped = cgImage.cropping(to: cropRect) else {
            return
        }

        let coverFilename = item.coverImageFilename ?? (UUID().uuidString + "_cover.jpg")
        let coverURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(coverFilename)

        let coverImage = UIImage(cgImage: cropped)
        guard let data = coverImage.jpegData(compressionQuality: 0.9) else {
            return
        }

        do {
            try data.write(to: coverURL, options: .atomic)
            item.coverImageFilename = coverFilename
            try? modelContext.save()
            dismiss()
        } catch {
            print("Failed to save cover image:", error)
        }
    }
}

private struct CoverCropCanvas: View {
    let image: UIImage
    let cropSide: CGFloat

    @Binding var dragOffset: CGSize
    @Binding var committedOffset: CGSize
    @Binding var zoomScale: CGFloat
    @Binding var committedZoomScale: CGFloat

    var body: some View {
        let imageSize = image.size
        let baseScale = max(cropSide / imageSize.width, cropSide / imageSize.height)
        let scaledSize = CGSize(width: imageSize.width * baseScale * zoomScale, height: imageSize.height * baseScale * zoomScale)
        let maxHorizontalShift = max((scaledSize.width - cropSide) / 2, 0)
        let maxVerticalShift = max((scaledSize.height - cropSide) / 2, 0)

        ZStack {
            Image(uiImage: image)
                .resizable()
                .frame(width: scaledSize.width, height: scaledSize.height)
                .offset(dragOffset)

            RoundedRectangle(cornerRadius: 24)
                .stroke(Color.white.opacity(0.95), lineWidth: 2)
        }
        .frame(width: cropSide, height: cropSide)
        .clipped()
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .contentShape(RoundedRectangle(cornerRadius: 24))
        .gesture(
            SimultaneousGesture(
                DragGesture()
                    .onChanged { value in
                        dragOffset = clampedOffset(
                            CGSize(
                                width: committedOffset.width + value.translation.width,
                                height: committedOffset.height + value.translation.height
                            ),
                            maxHorizontalShift: maxHorizontalShift,
                            maxVerticalShift: maxVerticalShift
                        )
                    }
                    .onEnded { _ in
                        committedOffset = dragOffset
                    },
                MagnificationGesture()
                    .onChanged { value in
                        zoomScale = clampedZoomScale(committedZoomScale * value)
                        let currentScaledSize = CGSize(
                            width: imageSize.width * baseScale * zoomScale,
                            height: imageSize.height * baseScale * zoomScale
                        )
                        dragOffset = clampedOffset(
                            dragOffset,
                            maxHorizontalShift: max((currentScaledSize.width - cropSide) / 2, 0),
                            maxVerticalShift: max((currentScaledSize.height - cropSide) / 2, 0)
                        )
                    }
                    .onEnded { value in
                        zoomScale = clampedZoomScale(committedZoomScale * value)
                        committedZoomScale = zoomScale
                        let currentScaledSize = CGSize(
                            width: imageSize.width * baseScale * zoomScale,
                            height: imageSize.height * baseScale * zoomScale
                        )
                        let clamped = clampedOffset(
                            dragOffset,
                            maxHorizontalShift: max((currentScaledSize.width - cropSide) / 2, 0),
                            maxVerticalShift: max((currentScaledSize.height - cropSide) / 2, 0)
                        )
                        dragOffset = clamped
                        committedOffset = clamped
                    }
            )
        )
    }

    private func clampedOffset(
        _ offset: CGSize,
        maxHorizontalShift: CGFloat,
        maxVerticalShift: CGFloat
    ) -> CGSize {
        CGSize(
            width: min(max(offset.width, -maxHorizontalShift), maxHorizontalShift),
            height: min(max(offset.height, -maxVerticalShift), maxVerticalShift)
        )
    }

    private func clampedZoomScale(_ value: CGFloat) -> CGFloat {
        min(max(value, 1), 4)
    }
}
