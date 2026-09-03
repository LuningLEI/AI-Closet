//
//  AddClothingSheet.swift
//  AI Closet
//
//  Created by Luning Lei on 2/18/26.
//


import SwiftUI
import SwiftData
import CoreImage
import CoreImage.CIFilterBuiltins

struct AddClothingSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var modelContext

    let imageData: Data
    @State var category: String
    @State private var subtype: String = "Unknown"
    @State private var color: String = "Unknown"
    @State private var selectedSeasons: Set<String> = ["All-Season"]
    @State private var style: String = "Casual"
    @State private var occasion: String = "Everyday"
    private let recognitionSource: String?
    private let recognitionSummary: String?
    private let recognitionConfidence: Double?
    private let rawCategory: String?
    private let rawSubtype: String?
    private let rawColor: String?
    private let rawStyle: String?
    private let rawOccasion: String?
    private let rawSeasons: [String]

    private let categories = ClothingTaxonomySupport.categories
    private let colors = ClothingTaxonomySupport.colors
    private let seasons = SeasonSelectionSupport.options
    private let styles = ClothingTaxonomySupport.styles
    private let occasions = ClothingTaxonomySupport.occasions

    init(imageData: Data, analysis: ClothingAnalysis) {
        self.imageData = imageData
        recognitionSource = analysis.source
        recognitionSummary = analysis.summary
        recognitionConfidence = analysis.confidence
        rawCategory = analysis.rawCategory
        rawSubtype = analysis.rawSubtype
        rawColor = analysis.rawColor
        rawStyle = analysis.rawStyle
        rawOccasion = analysis.rawOccasion
        rawSeasons = analysis.rawSeasons
        _category = State(initialValue: analysis.category)
        _subtype = State(initialValue: SubtypeSupport.normalized(analysis.subtype, for: analysis.category))
        _color = State(initialValue: analysis.color)
        _selectedSeasons = State(initialValue: analysis.seasons)
        _style = State(initialValue: analysis.style)
        _occasion = State(initialValue: analysis.occasion)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Preview") {
                    if let uiImage = UIImage(data: imageData) {
                        Image(uiImage: uiImage)
                            .resizable()
                            .scaledToFit()
                            .frame(maxHeight: 320)
                            .clipShape(RoundedRectangle(cornerRadius: 16))
                    } else {
                        Text("Could not load image")
                            .foregroundStyle(.secondary)
                    }
                }

                Section("Detected info (editable)") {
                    Picker("Category", selection: $category) {
                        ForEach(categories, id: \.self) { c in
                            Text(c).tag(c)
                        }
                    }
                    .onChange(of: category) { _, newCategory in
                        subtype = SubtypeSupport.normalized(subtype, for: newCategory)
                    }

                    Picker("Subtype", selection: $subtype) {
                        ForEach(SubtypeSupport.options(for: category), id: \.self) { option in
                            Text(option).tag(option)
                        }
                    }

                    HStack {
                        Text("Color")
                        Spacer()
                        Menu {
                            ForEach(colors, id: \.self) { c in
                                Button {
                                    color = c
                                } label: {
                                    colorMenuLabel(for: c)
                                }
                            }
                        } label: {
                            HStack(spacing: 8) {
                                colorDot(for: color)
                                Text(color)
                                Image(systemName: "chevron.up.chevron.down")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            .foregroundStyle(.secondary)
                        }
                    }

                    HStack {
                        Text("Season")
                        Spacer()
                        Menu {
                            ForEach(seasons, id: \.self) { s in
                                Button {
                                    selectedSeasons = SeasonSelectionSupport.toggled(s, in: selectedSeasons)
                                } label: {
                                    HStack {
                                        Text(s)
                                        Spacer()
                                        if selectedSeasons.contains(s) {
                                            Image(systemName: "checkmark")
                                        }
                                    }
                                }
                            }
                        } label: {
                            HStack(spacing: 8) {
                                Text(SeasonSelectionSupport.displayText(for: selectedSeasons))
                                    .multilineTextAlignment(.trailing)
                                Image(systemName: "chevron.up.chevron.down")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            .foregroundStyle(.secondary)
                        }
                    }

                    Picker("Style", selection: $style) {
                        ForEach(styles, id: \.self) { s in
                            Text(s).tag(s)
                        }
                    }

                    Picker("Occasion", selection: $occasion) {
                        ForEach(occasions, id: \.self) { o in
                            Text(o).tag(o)
                        }
                    }
                }
            }
            .navigationTitle("Add Item")
            .navigationBarTitleDisplayMode(.inline)
            .onAppear {
                if color == "Unknown", let detected = detectColor(from: imageData) {
                    color = detected
                }
            }
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Add") {
                        save()
                        dismiss()
                    }
                }
            }
        }
    }

    private func save() {
        let filename = UUID().uuidString + ".jpg"
        let url = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(filename)

        do {
            try imageData.write(to: url)
            let analysis = ClothingAnalysis(
                category: category,
                subtype: subtype == "Unknown" ? nil : subtype,
                color: color,
                seasons: selectedSeasons,
                style: style,
                occasion: occasion,
                confidence: recognitionConfidence,
                summary: recognitionSummary,
                source: recognitionSource ?? "Unknown",
                rawCategory: rawCategory,
                rawSubtype: rawSubtype,
                rawColor: rawColor,
                rawStyle: rawStyle,
                rawOccasion: rawOccasion,
                rawSeasons: rawSeasons
            )

            let item = ClothingItem(
                imageFilename: filename,
                category: category,
                subtype: analysis.subtype,
                color: color,
                season: SeasonSelectionSupport.encode(selectedSeasons),
                style: style,
                occasion: occasion,
                recognitionSource: recognitionSource,
                recognitionSummary: recognitionSummary,
                recognitionConfidence: recognitionConfidence,
                recognitionTagsJSON: RecognitionBackendSupport.tagsJSONString(from: analysis),
                recommendationFeatureJSON: RecognitionBackendSupport.featureJSONString(from: analysis)
            )
            modelContext.insert(item)

            let recognitionRecord = RecognitionRecord(
                clothingItemID: item.id,
                provider: analysis.source,
                modelName: analysis.source == "Gemini" ? "gemini-2.5-flash" : "local-category-classifier",
                modelVersion: nil,
                promptVersion: analysis.source == "Gemini" ? "gemini-clothing-v1" : nil,
                rawCategory: analysis.rawCategory,
                rawSubtype: analysis.rawSubtype,
                rawColor: analysis.rawColor,
                rawStyle: analysis.rawStyle,
                rawOccasion: analysis.rawOccasion,
                rawSeasonsJSON: jsonArrayString(analysis.rawSeasons),
                normalizedCategory: analysis.category,
                normalizedSubtype: analysis.subtype,
                normalizedColor: analysis.color,
                normalizedStyle: analysis.style,
                normalizedOccasion: analysis.occasion,
                normalizedSeasonsJSON: jsonArrayString(Array(analysis.seasons).sorted()) ?? "[]",
                confidence: analysis.confidence,
                summary: analysis.summary,
                rawResponseJSON: RecognitionBackendSupport.tagsJSONString(from: analysis)
            )
            modelContext.insert(recognitionRecord)

            let features = RecognitionBackendSupport.featureComponents(from: analysis)
            let featureSnapshot = ItemFeatureSnapshot(
                clothingItemID: item.id,
                recognitionRecordID: recognitionRecord.id,
                featureVersion: "v1",
                categoryVectorJSON: jsonArrayString(features.categoryVector) ?? "[]",
                colorVectorJSON: jsonArrayString(features.colorVector) ?? "[]",
                styleVectorJSON: jsonArrayString(features.styleVector) ?? "[]",
                occasionVectorJSON: jsonArrayString(features.occasionVector) ?? "[]",
                seasonVectorJSON: jsonArrayString(features.seasonVector) ?? "[]",
                embeddingVectorJSON: nil,
                extraFeaturesJSON: nil
            )
            modelContext.insert(featureSnapshot)
        } catch {
            print("Failed to save image:", error)
        }
    }

    private func jsonArrayString<T: Encodable>(_ values: [T]) -> String? {
        guard let data = try? JSONEncoder().encode(values) else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private func detectColor(from imageData: Data) -> String? {
        guard let ciImage = CIImage(data: imageData) else { return nil }

        let extent = ciImage.extent
        guard !extent.isEmpty else { return nil }

        // Focus on body/garment area to reduce background influence.
        let cropRect = CGRect(
            x: extent.origin.x + extent.width * 0.2,
            y: extent.origin.y + extent.height * 0.15,
            width: extent.width * 0.6,
            height: extent.height * 0.75
        ).intersection(extent)

        guard !cropRect.isEmpty else { return nil }

        let avgFilter = CIFilter.areaAverage()
        avgFilter.inputImage = ciImage.cropped(to: cropRect)
        avgFilter.extent = cropRect

        guard let outputImage = avgFilter.outputImage else { return nil }

        let context = CIContext()
        var rgba = [UInt8](repeating: 0, count: 4)
        context.render(
            outputImage,
            toBitmap: &rgba,
            rowBytes: 4,
            bounds: CGRect(x: 0, y: 0, width: 1, height: 1),
            format: .RGBA8,
            colorSpace: CGColorSpaceCreateDeviceRGB()
        )

        let red = Double(rgba[0]) / 255.0
        let green = Double(rgba[1]) / 255.0
        let blue = Double(rgba[2]) / 255.0

        return mapRGBToColorName(r: red, g: green, b: blue)
    }

    private func mapRGBToColorName(r: Double, g: Double, b: Double) -> String {
        let maxV = max(r, g, b)
        let minV = min(r, g, b)
        let delta = maxV - minV
        let brightness = maxV
        let saturation = maxV == 0 ? 0 : delta / maxV

        if brightness < 0.18 { return "Black" }
        if saturation < 0.08 && brightness > 0.88 { return "White" }
        if saturation < 0.12 { return "Gray" }

        var hue: Double = 0
        if delta != 0 {
            if maxV == r {
                hue = ((g - b) / delta).truncatingRemainder(dividingBy: 6)
            } else if maxV == g {
                hue = ((b - r) / delta) + 2
            } else {
                hue = ((r - g) / delta) + 4
            }
            hue /= 6
            if hue < 0 { hue += 1 }
        }

        if hue >= 0.56 && hue <= 0.72 && brightness < 0.45 { return "Navy" }
        if hue >= 0.06 && hue <= 0.14 && saturation > 0.35 && brightness < 0.65 { return "Brown" }
        if hue >= 0.08 && hue <= 0.16 && saturation < 0.35 && brightness > 0.65 { return "Beige" }

        switch hue {
        case 0.00...0.04, 0.96...1.00: return "Red"
        case 0.04...0.09: return "Orange"
        case 0.09...0.16: return "Yellow"
        case 0.16...0.42: return "Green"
        case 0.42...0.72: return "Blue"
        case 0.72...0.84: return "Purple"
        case 0.84...0.96: return "Pink"
        default: return "Unknown"
        }
    }

    @ViewBuilder
    private func colorMenuLabel(for colorName: String) -> some View {
        HStack(spacing: 8) {
            colorDot(for: colorName)
            Text(colorName)
        }
    }

    private func colorDot(for colorName: String) -> some View {
        Circle()
            .fill(colorSwatch(for: colorName))
            .frame(width: 12, height: 12)
            .overlay {
                Circle()
                    .stroke(.secondary.opacity(0.35), lineWidth: 0.5)
            }
    }

    private func colorSwatch(for colorName: String) -> Color {
        switch colorName {
        case "Black":
            return .black
        case "White":
            return .white
        case "Gray":
            return .gray
        case "Blue":
            return .blue
        case "Navy":
            return Color(red: 0.09, green: 0.17, blue: 0.39)
        case "Red":
            return .red
        case "Green":
            return .green
        case "Brown":
            return Color(red: 0.45, green: 0.28, blue: 0.14)
        case "Beige":
            return Color(red: 0.86, green: 0.78, blue: 0.64)
        case "Pink":
            return .pink
        case "Purple":
            return .purple
        case "Yellow":
            return .yellow
        case "Orange":
            return .orange
        default:
            return Color.secondary.opacity(0.7)
        }
    }
}
