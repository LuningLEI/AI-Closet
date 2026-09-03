import Foundation

struct ClothingAnalysis: Equatable {
    var category: String
    var subtype: String?
    var color: String
    var seasons: Set<String>
    var style: String
    var occasion: String
    var confidence: Double?
    var summary: String?
    var source: String
    var rawCategory: String?
    var rawSubtype: String?
    var rawColor: String?
    var rawStyle: String?
    var rawOccasion: String?
    var rawSeasons: [String]

    static let empty = ClothingAnalysis(
        category: "Uncategorized",
        subtype: nil,
        color: "Unknown",
        seasons: ["All-Season"],
        style: "Casual",
        occasion: "Everyday",
        confidence: nil,
        summary: nil,
        source: "Unknown",
        rawCategory: nil,
        rawSubtype: nil,
        rawColor: nil,
        rawStyle: nil,
        rawOccasion: nil,
        rawSeasons: []
    )
}

enum ClothingRecognitionError: LocalizedError {
    case missingAPIKey
    case invalidResponse
    case noStructuredOutput

    var errorDescription: String? {
        switch self {
        case .missingAPIKey:
            return "Missing Gemini API key."
        case .invalidResponse:
            return "The clothing recognition API returned an invalid response."
        case .noStructuredOutput:
            return "The clothing recognition API did not return structured output."
        }
    }
}
