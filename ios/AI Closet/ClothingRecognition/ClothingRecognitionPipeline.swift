import Foundation

struct ClothingRecognitionPipeline {
    private let apiService = GeminiClothingRecognitionService()
    private let localClassifier = LocalCategoryClassifier()

    func analyze(imageData: Data, fallbackCategory: String? = nil) async -> ClothingAnalysis {
        do {
            let analysis = try await apiService.analyze(imageData: imageData)
            print("GEMINI ANALYSIS:", analysis)
            return merged(analysis, fallbackCategory: fallbackCategory)
        } catch {
            print("GEMINI CLOTHING ANALYSIS FAILED:", error.localizedDescription)
        }

        let category = await localClassifier.predictCategory(from: imageData) ?? fallbackCategory ?? "Uncategorized"
        return ClothingAnalysis(
            category: category,
            subtype: nil,
            color: "Unknown",
            seasons: ["All-Season"],
            style: "Casual",
            occasion: "Everyday",
            confidence: nil,
            summary: nil,
            source: "Local Fallback",
            rawCategory: category,
            rawSubtype: nil,
            rawColor: nil,
            rawStyle: nil,
            rawOccasion: nil,
            rawSeasons: []
        )
    }

    private func merged(_ analysis: ClothingAnalysis, fallbackCategory: String?) -> ClothingAnalysis {
        var merged = analysis
        if merged.category == "Uncategorized", let fallbackCategory {
            merged.category = fallbackCategory
        }
        return merged
    }
}
