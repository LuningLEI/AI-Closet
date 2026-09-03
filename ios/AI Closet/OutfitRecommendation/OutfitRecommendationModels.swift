import Foundation

struct OutfitRecommendationContext {
    var occasion: String
    var temperatureF: Double
    var preferredStyle: String?

    static let `default` = OutfitRecommendationContext(
        occasion: "Everyday",
        temperatureF: 68,
        preferredStyle: nil
    )
}

struct OutfitScoreBreakdown {
    var occasionFit: Double = 0
    var weatherFit: Double = 0
    var styleHarmony: Double = 0
    var colorHarmony: Double = 0
    var categoryBalance: Double = 0

    var total: Double {
        occasionFit + weatherFit + styleHarmony + colorHarmony + categoryBalance
    }
}

struct OutfitRecommendation: Identifiable {
    let id: String
    let top: ClothingItem
    let bottom: ClothingItem
    let shoes: ClothingItem?
    let outerwear: ClothingItem?
    let accessory: ClothingItem?
    let breakdown: OutfitScoreBreakdown
    let reasons: [String]

    var score: Double { breakdown.total }

    var allItems: [ClothingItem] {
        [top, bottom, shoes, outerwear, accessory].compactMap { $0 }
    }
}

struct OutfitRecommendationInput {
    let groupedItems: [String: [ClothingItem]]
    let context: OutfitRecommendationContext
}

protocol OutfitScoringRule {
    func score(candidate: OutfitRecommendationCandidate, input: OutfitRecommendationInput) -> (Double, String?)
}

struct OutfitRecommendationCandidate {
    let top: ClothingItem
    let bottom: ClothingItem
    let shoes: ClothingItem?
    let outerwear: ClothingItem?
    let accessory: ClothingItem?

    var allItems: [ClothingItem] {
        [top, bottom, shoes, outerwear, accessory].compactMap { $0 }
    }

    var identifier: String {
        allItems.map(\.id.uuidString).joined(separator: "-")
    }
}
