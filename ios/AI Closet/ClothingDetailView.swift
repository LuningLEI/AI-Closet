import SwiftUI

enum ItemImageReplaceResult {
    case success(ClothingItemDTO)
    case failure(String)
}

struct ClothingDetailView: View {
    typealias TokenProvider = @MainActor () async -> String?
    typealias DeleteCompletion = @MainActor () async -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var labelsConfirmed = false
    @State private var confirmationError = false
    private let openingItem: ClothingItemDTO
    @State private var editableItem: ClothingItemDTO
    @State private var selectedSeasons: Set<String>
    @State private var selectedColors: Set<String>
    @State private var selectedOccasions: Set<String>
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

    // Failed/pending cards have no valid labels to auto-confirm, but remain editable.
    private var isAwaitingLabelConfirmation: Bool {
        openingItem.canConfirmOpeningLabels && !labelsConfirmed
    }

    private var subtypeOptions: [String] {
        uniqueOptions(["Unknown"] + (taxonomy.subtypes[editableItem.category] ?? []) + [editableItem.subtype].compactMap{$0})
    }
    private var colorOptions:[String] { uniqueOptions(taxonomy.colors+Array(selectedColors)) }
    private var seasonOptions:[String] { uniqueOptions(taxonomy.seasons+Array(selectedSeasons)) }

    init(
        item: ClothingItemDTO,
        viewModel: ClosetViewModel,
        taxonomy: TaxonomyDTO,
        tokenProvider: @escaping TokenProvider,
        onDeleteComplete: @escaping DeleteCompletion
    ) {
        let savedSeasons=item.season.split(separator:",").map{$0.trimmingCharacters(in:.whitespacesAndNewlines)}
        let savedOccasions=item.occasion.split(separator:",").map{$0.trimmingCharacters(in:.whitespacesAndNewlines)}
        openingItem = item
        _editableItem = State(initialValue: item)
        _selectedSeasons = State(initialValue: SeasonSelectionSupport.decode(item.season,options:Array(Set(taxonomy.seasons+savedSeasons))))
        _selectedColors = State(initialValue: ColorSelectionSupport.decode(item.color))
        _selectedOccasions = State(initialValue: OccasionSelectionSupport.decode(item.occasion, options:Array(Set(taxonomy.occasions+savedOccasions))))
        self.viewModel = viewModel
        self.taxonomy = taxonomy
        self.tokenProvider = tokenProvider
        self.onDeleteComplete = onDeleteComplete
    }

    var body: some View {
        NavigationStack {
            Form {
                Group {
                    Section("Preview") {
                        ClosetAsyncImage(url: editableItem.imageUrl, itemID: editableItem.id) { refreshedURL in
                            editableItem.imageUrl = refreshedURL
                        }
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

                    Section("Outfits") {
                        NavigationLink("Outfits with this item") {
                            ScrollView {
                                OutfitLibraryView(closet: viewModel, initialItemID: editableItem.id)
                                    .padding()
                            }
                            .navigationTitle("Outfits")
                        }
                    }

                    Section("Details") {
                        Picker("Category", selection: $editableItem.category) {
                            ForEach(uniqueOptions(taxonomy.categories+[editableItem.category]), id: \.self) { Text($0).tag($0) }
                        }

                        Picker("Subtype", selection: Binding(
                            get: { editableItem.subtype ?? "Unknown" },
                            set: { editableItem.subtype = $0 == "Unknown" ? nil : $0 }
                        )) {
                            ForEach(subtypeOptions, id: \.self) {
                                Text($0).tag($0)
                            }
                        }

                        MultiSelectDisclosure(
                            title: "Color",
                            options: colorOptions,
                            selection: $selectedColors,
                            displayText: { ColorSelectionSupport.encode($0, options: colorOptions) },
                            toggle: ColorSelectionSupport.toggled
                        )

                        MultiSelectDisclosure(
                            title: "Season",
                            options: seasonOptions,
                            selection: $selectedSeasons,
                            displayText: { SeasonSelectionSupport.displayText(for:$0,options:seasonOptions) },
                            toggle: { SeasonSelectionSupport.toggled($0,in:$1,options:seasonOptions) }
                        )

                        Picker("Garment length", selection: Binding(
                            get: { editableItem.length ?? "" },
                            set: { editableItem.length = $0.isEmpty ? nil : $0 }
                        )) {
                            Text("Unknown").tag("")
                            ForEach(uniqueOptions(taxonomy.lengths + [editableItem.length].compactMap { $0 }), id: \.self) { Text($0).tag($0) }
                        }

                        Picker("Sleeve length", selection: Binding(
                            get: { editableItem.sleeveLength ?? "" },
                            set: { editableItem.sleeveLength = $0.isEmpty ? nil : $0 }
                        )) {
                            Text("Unknown").tag("")
                            ForEach(uniqueOptions(taxonomy.sleeveLengths + [editableItem.sleeveLength].compactMap { $0 }), id: \.self) { Text($0).tag($0) }
                        }

                        HStack {
                            Text("Material")
                            TextField("Unknown", text: Binding(
                                get: { editableItem.material ?? "" },
                                set: { editableItem.material = $0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : $0 }
                            ))
                            .multilineTextAlignment(.trailing)
                        }

                        Picker("Style", selection: $editableItem.style) {
                            ForEach(uniqueOptions(taxonomy.styles+[editableItem.style]), id: \.self) { Text($0).tag($0) }
                        }

                        MultiSelectDisclosure(
                            title: "Occasion",
                            options: occasionOptions,
                            selection: $selectedOccasions,
                            displayText: { $0.isEmpty ? "None selected" : OccasionSelectionSupport.encode($0, options: occasionOptions) },
                            toggle: { occasion, selection in
                                OccasionSelectionSupport.toggled(occasion, in: selection, options: taxonomy.occasions)
                            }
                        )
                    }

                    if let error = viewModel.errorMessage {
                        Text(error).foregroundStyle(.red)
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
                .disabled(isAwaitingLabelConfirmation)
            }
            .task { await confirmOpeningLabels() }
            .alert("Could not confirm item details", isPresented: $confirmationError) {
                Button("Retry") { Task { await confirmOpeningLabels() } }
                Button("Close", role: .cancel) { dismiss() }
            } message: {
                Text("Your displayed labels have not been saved yet. Please retry before editing the photo or details.")
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
                            var itemToSave = editableItem
                            itemToSave.season = SeasonSelectionSupport.encode(selectedSeasons,options:seasonOptions)
                            itemToSave.color = ColorSelectionSupport.encode(selectedColors, options: colorOptions)
                            itemToSave.occasion = OccasionSelectionSupport.encode(selectedOccasions, options: occasionOptions)
                            let saved = await viewModel.update(
                                itemToSave, token: await tokenProvider(),
                                occasionBefore: editableItem.occasion,
                                occasionThresholdAtEdit: editableItem.recognitionTags?.displayOccasionThreshold,
                                occasionThresholdsAtEdit: editableItem.recognitionTags?.displayOccasionThresholds
                            )
                            isSaving = false
                            if saved { dismiss() }
                        }
                    }
                    .disabled(isSaving || isDeleting || isReplacingImage || isAwaitingLabelConfirmation)
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
                    title: editableItem.displayTitle,
                    refreshImageURL: {
                        let fresh: ClothingItemDTO = try await APIClient.shared.get(
                            "/api/v1/items/\(editableItem.id.uuidString.lowercased())",
                            token: await tokenProvider()
                        )
                        try Task.checkCancellation()
                        editableItem.imageUrl = fresh.imageUrl
                        return fresh.imageUrl
                    }
                ) { imageData, editMetadata in
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
                        editMetadata: editMetadata,
                        token: await tokenProvider()
                    )
                    isReplacingImage = false
                    switch result {
                    case .success(let updatedItem):
                        var merged = updatedItem
                        merged.category = itemSnapshot.category
                        merged.subtype = itemSnapshot.subtype
                        merged.color = itemSnapshot.color
                        merged.season = itemSnapshot.season
                        merged.style = itemSnapshot.style
                        merged.occasion = itemSnapshot.occasion
                        merged.recognitionSummary = itemSnapshot.recognitionSummary
                        editableItem = merged
                        return .success
                    case .failure(let message):
                        return .failure(message)
                    }
                }
            }
        }
    }

    @MainActor
    private func confirmOpeningLabels() async {
        guard !labelsConfirmed, openingItem.canConfirmOpeningLabels else { return }
        let saved = await viewModel.update(openingItem, token: await tokenProvider(), editSource: "ios_card_open")
        labelsConfirmed = saved
        confirmationError = !saved
    }

    private var occasionOptions: [String] {
        uniqueOptions(taxonomy.occasions+Array(selectedOccasions))
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

private struct MultiSelectDisclosure: View {
    let title: String
    let options: [String]
    @Binding var selection: Set<String>
    let displayText: @MainActor @Sendable (Set<String>) -> String
    let toggle: @MainActor @Sendable (String, Set<String>) -> Set<String>

    var body: some View {
        NavigationLink {
            MultiSelectOptionsView(
                title: title,
                options: options,
                selection: $selection,
                toggle: { option, current in toggle(option, current) }
            )
        } label: {
            HStack {
                Text(title)
                Spacer()
                Text(displayText(selection))
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.trailing)
                    .lineLimit(2)
            }
        }
    }
}

private struct MultiSelectOptionsView: View {
    let title: String
    let options: [String]
    @Binding var selection: Set<String>
    let toggle: @MainActor @Sendable (String, Set<String>) -> Set<String>

    var body: some View {
        List {
            ForEach(options, id: \.self) { option in
                HStack {
                    Text(option)
                    Spacer()
                    if selection.contains(option) {
                        Image(systemName: "checkmark")
                            .foregroundStyle(.tint)
                    }
                }
                .contentShape(Rectangle())
                .onTapGesture {
                    selection = toggle(option, selection)
                }
                .accessibilityAddTraits(.isButton)
            }
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
    }
}
