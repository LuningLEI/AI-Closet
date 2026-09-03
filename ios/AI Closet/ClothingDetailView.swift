import SwiftUI

enum ItemImageReplaceResult {
    case success(ClothingItemDTO)
    case failure(String)
}

struct ClothingDetailView: View {
    typealias TokenProvider = @MainActor () async -> String?
    typealias DeleteCompletion = @MainActor () async -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var editableItem: ClothingItemDTO
    @State private var showingDeleteConfirmation = false
    @State private var showingImageEditor = false
    @State private var isSaving = false
    @State private var isDeleting = false
    @State private var isReplacingImage = false
    @State private var deleteError: String?

    @ObservedObject var viewModel: ClosetViewModel
    let taxonomy: TaxonomyDTO
    let tokenProvider: TokenProvider
    let onDeleteComplete: DeleteCompletion

    private var subtypeOptions: [String] {
        uniqueOptions(["Unknown"] + (taxonomy.subtypes[editableItem.category] ?? []))
    }

    init(
        item: ClothingItemDTO,
        viewModel: ClosetViewModel,
        taxonomy: TaxonomyDTO,
        tokenProvider: @escaping TokenProvider,
        onDeleteComplete: @escaping DeleteCompletion
    ) {
        _editableItem = State(initialValue: item)
        self.viewModel = viewModel
        self.taxonomy = taxonomy
        self.tokenProvider = tokenProvider
        self.onDeleteComplete = onDeleteComplete
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Preview") {
                    ClosetAsyncImage(url: editableItem.imageUrl)
                        .frame(maxHeight: 320)
                        .clipShape(RoundedRectangle(cornerRadius: 16))

                    Button {
                        showingImageEditor = true
                    } label: {
                        if isReplacingImage {
                            Label("Saving photo...", systemImage: "arrow.triangle.2.circlepath")
                        } else {
                            Label("Crop or rotate photo", systemImage: "crop.rotate")
                        }
                    }
                    .disabled(isSaving || isDeleting || isReplacingImage)
                }

                Section("Details") {
                    Picker("Category", selection: $editableItem.category) {
                        ForEach(uniqueOptions(taxonomy.categories), id: \.self) { Text($0).tag($0) }
                    }

                    Picker("Subtype", selection: Binding(
                        get: { editableItem.subtype ?? "Unknown" },
                        set: { editableItem.subtype = $0 == "Unknown" ? nil : $0 }
                    )) {
                        ForEach(subtypeOptions, id: \.self) {
                            Text($0).tag($0)
                        }
                    }

                    Picker("Color", selection: $editableItem.color) {
                        ForEach(uniqueOptions(taxonomy.colors), id: \.self) { Text($0).tag($0) }
                    }

                    Picker("Season", selection: $editableItem.season) {
                        ForEach(uniqueOptions(taxonomy.seasons), id: \.self) { Text($0).tag($0) }
                    }

                    Picker("Style", selection: $editableItem.style) {
                        ForEach(uniqueOptions(taxonomy.styles), id: \.self) { Text($0).tag($0) }
                    }

                    Picker("Occasion", selection: $editableItem.occasion) {
                        ForEach(uniqueOptions(taxonomy.occasions), id: \.self) { Text($0).tag($0) }
                    }
                }

                if let summary = editableItem.recognitionSummary {
                    Section("Recognition") {
                        Text(summary)
                            .foregroundStyle(.secondary)
                    }
                }

                Section {
                    Button(role: .destructive) {
                        showingDeleteConfirmation = true
                    } label: {
                        if isDeleting {
                            ProgressView()
                        } else {
                            Label("Delete clothing item", systemImage: "trash")
                        }
                    }
                    .disabled(isDeleting)

                    if let deleteError {
                        Text(deleteError)
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("Edit item")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        Task {
                            isSaving = true
                            await viewModel.update(editableItem, token: await tokenProvider())
                            isSaving = false
                            dismiss()
                        }
                    }
                    .disabled(isSaving || isDeleting)
                }
            }
            .confirmationDialog(
                "Delete this clothing item?",
                isPresented: $showingDeleteConfirmation,
                titleVisibility: .visible
            ) {
                Button("Delete", role: .destructive) {
                    Task {
                        isDeleting = true
                        deleteError = nil
                        let didDelete = await viewModel.delete(editableItem, token: await tokenProvider())
                        isDeleting = false
                        if didDelete {
                            await onDeleteComplete()
                            dismiss()
                        } else {
                            let errorMessage = viewModel.errorMessage ?? "Delete failed. Please try again."
                            if !Self.isAlreadyDeletedMessage(errorMessage) {
                                deleteError = errorMessage
                            } else {
                                await onDeleteComplete()
                                dismiss()
                            }
                        }
                    }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("This removes the clothing card and its recognition records.")
            }
            .sheet(isPresented: $showingImageEditor) {
                ClothingImageEditorSheet(
                    imageURL: editableItem.imageUrl,
                    title: editableItem.displayTitle
                ) { imageData in
                    let itemSnapshot = editableItem
                    let ownedImageData = Self.ownedDataCopy(imageData)
                    print(
                        "[ClothingDetailView] onSave received",
                        "item_id=\(itemSnapshot.id.uuidString)",
                        "incoming_bytes=\(imageData.count)",
                        "owned_bytes=\(ownedImageData.count)"
                    )
                    isReplacingImage = true
                    let result = await viewModel.replaceImage(
                        ownedImageData,
                        itemID: itemSnapshot.id,
                        token: await tokenProvider()
                    )
                    isReplacingImage = false
                    switch result {
                    case .success(let updatedItem):
                        editableItem = updatedItem
                        return .success
                    case .failure(let message):
                        return .failure(message)
                    }
                }
            }
        }
    }

    private func uniqueOptions(_ options: [String]) -> [String] {
        var seen = Set<String>()
        return options.filter { seen.insert($0).inserted }
    }

    private static func isAlreadyDeletedMessage(_ message: String) -> Bool {
        message.localizedCaseInsensitiveContains("not found")
    }

    private static func ownedDataCopy(_ data: Data) -> Data {
        data.withUnsafeBytes { Data($0) }
    }
}
