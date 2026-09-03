import SwiftUI
import SwiftData

struct OutfitRecommendationView: View {
    let items: [ClothingItem]

    @State private var occasion = "Everyday"
    @State private var preferredStyle = "Any"
    @State private var temperatureF: Double = 68
    @State private var regenerationIndex = 0

    private let engine = OutfitRecommendationEngine()
    private let occasionOptions = ["Everyday", "Work", "Date", "Party", "Travel"]
    private let styleOptions = ["Any", "Casual", "Classic", "Sporty", "Elegant"]

    private var allRecommendations: [OutfitRecommendation] {
        engine.recommend(
            from: items,
            context: OutfitRecommendationContext(
                occasion: occasion,
                temperatureF: temperatureF,
                preferredStyle: preferredStyle == "Any" ? nil : preferredStyle
            ),
            limit: 20
        )
    }

    private var recommendations: [OutfitRecommendation] {
        guard !allRecommendations.isEmpty else { return [] }

        let start = regenerationIndex % allRecommendations.count
        let reordered = Array(allRecommendations[start...]) + Array(allRecommendations[..<start])
        return Array(reordered.prefix(3))
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                controlPanel

                if recommendations.isEmpty {
                    ContentUnavailableView(
                        "No Outfit Matches Yet",
                        systemImage: "hanger",
                        description: Text("Add more tops, bottoms, or shoes, or loosen the occasion and temperature filters.")
                    )
                } else {
                    ForEach(recommendations) { recommendation in
                        OutfitRecommendationCard(recommendation: recommendation)
                    }
                }
            }
            .padding(16)
        }
        .navigationTitle("Today")
        .onChange(of: occasion) { _, _ in regenerationIndex = 0 }
        .onChange(of: preferredStyle) { _, _ in regenerationIndex = 0 }
        .onChange(of: temperatureF) { _, _ in regenerationIndex = 0 }
    }

    private var controlPanel: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Recommendation Inputs")
                .font(.headline)

            HStack {
                Text("Occasion")
                Spacer()
                Picker("Occasion", selection: $occasion) {
                    ForEach(occasionOptions, id: \.self) { option in
                        Text(option).tag(option)
                    }
                }
                .pickerStyle(.menu)
            }

            HStack {
                Text("Style")
                Spacer()
                Picker("Style", selection: $preferredStyle) {
                    ForEach(styleOptions, id: \.self) { option in
                        Text(option).tag(option)
                    }
                }
                .pickerStyle(.menu)
            }

            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("Temperature")
                    Spacer()
                    Text("\(Int(temperatureF))F")
                        .foregroundStyle(.secondary)
                }

                Slider(value: $temperatureF, in: 20...95, step: 1)
            }

            Button {
                regenerate()
            } label: {
                Label("Regenerate", systemImage: "arrow.clockwise")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(allRecommendations.count <= 1)
        }
        .padding(18)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 20))
    }

    private func regenerate() {
        guard !allRecommendations.isEmpty else { return }
        regenerationIndex = (regenerationIndex + 1) % allRecommendations.count
    }
}

private struct OutfitRecommendationCard: View {
    let recommendation: OutfitRecommendation

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Match Score \(Int(recommendation.score))")
                    .font(.headline)
                Spacer()
                Text(scoreSummary)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 12) {
                    ForEach(recommendation.allItems, id: \.id) { item in
                        OutfitItemThumbnail(item: item)
                    }
                }
            }

            VStack(alignment: .leading, spacing: 6) {
                ForEach(recommendation.reasons, id: \.self) { reason in
                    Text("• \(reason)")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(18)
        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 22))
    }

    private var scoreSummary: String {
        switch recommendation.score {
        case 70...:
            return "Strong"
        case 55..<70:
            return "Good"
        default:
            return "Usable"
        }
    }
}

private struct OutfitItemThumbnail: View {
    let item: ClothingItem

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Group {
                if let image = loadImage(for: item) {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFill()
                } else {
                    RoundedRectangle(cornerRadius: 14)
                        .fill(Color.secondary.opacity(0.18))
                }
            }
            .frame(width: 90, height: 90)
            .clipShape(RoundedRectangle(cornerRadius: 14))

            Text(item.category)
                .font(.caption.weight(.semibold))
            Text(item.color)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(width: 90)
    }

    private func loadImage(for item: ClothingItem) -> UIImage? {
        let filename = item.coverImageFilename ?? item.imageFilename
        let url = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(filename)
        return UIImage(contentsOfFile: url.path)
    }
}
