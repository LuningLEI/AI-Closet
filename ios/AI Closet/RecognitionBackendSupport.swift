import Foundation

struct RecognitionTagPayload: Codable {
    let source: String
    let rawCategory: String?
    let rawSubtype: String?
    let rawColor: String?
    let rawStyle: String?
    let rawOccasion: String?
    let rawSeasons: [String]
    let normalizedCategory: String
    let normalizedSubtype: String?
    let normalizedColor: String
    let normalizedStyle: String
    let normalizedOccasion: String
    let normalizedSeasons: [String]
    let confidence: Double?
    let summary: String?
}

struct RecommendationFeaturePayload: Codable {
    let categoryVector: [Double]
    let colorVector: [Double]
    let styleVector: [Double]
    let occasionVector: [Double]
    let seasonVector: [Double]
}

struct FeatureComponents {
    let categoryVector: [Double]
    let colorVector: [Double]
    let styleVector: [Double]
    let occasionVector: [Double]
    let seasonVector: [Double]
}

enum RecognitionBackendSupport {
    static func tagsJSONString(from analysis: ClothingAnalysis) -> String? {
        let payload = RecognitionTagPayload(
            source: analysis.source,
            rawCategory: analysis.rawCategory,
            rawSubtype: analysis.rawSubtype,
            rawColor: analysis.rawColor,
            rawStyle: analysis.rawStyle,
            rawOccasion: analysis.rawOccasion,
            rawSeasons: analysis.rawSeasons,
            normalizedCategory: analysis.category,
            normalizedSubtype: analysis.subtype,
            normalizedColor: analysis.color,
            normalizedStyle: analysis.style,
            normalizedOccasion: analysis.occasion,
            normalizedSeasons: Array(analysis.seasons).sorted(),
            confidence: analysis.confidence,
            summary: analysis.summary
        )
        return encode(payload)
    }

    static func featureJSONString(from analysis: ClothingAnalysis) -> String? {
        let components = featureComponents(from: analysis)
        let payload = RecommendationFeaturePayload(
            categoryVector: components.categoryVector,
            colorVector: components.colorVector,
            styleVector: components.styleVector,
            occasionVector: components.occasionVector,
            seasonVector: components.seasonVector
        )
        return encode(payload)
    }

    static func featureComponents(from analysis: ClothingAnalysis) -> FeatureComponents {
        FeatureComponents(
            categoryVector: oneHot(analysis.category, options: ["Tops", "Bottoms", "Shoes", "Outerwear", "Accessories", "Uncategorized"]),
            colorVector: colorVector(for: analysis.color),
            styleVector: oneHot(analysis.style, options: ["Casual", "Formal", "Business", "Sporty", "Streetwear", "Elegant", "Minimalist"]),
            occasionVector: oneHot(analysis.occasion, options: ["Everyday", "Work", "Party", "Date", "Travel", "Workout", "Wedding"]),
            seasonVector: multiHot(Array(analysis.seasons), options: ["All-Season", "Spring", "Summer", "Fall", "Winter"])
        )
    }

    private static func encode<T: Encodable>(_ value: T) -> String? {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        guard let data = try? encoder.encode(value) else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func oneHot(_ value: String, options: [String]) -> [Double] {
        options.map { $0 == value ? 1 : 0 }
    }

    private static func multiHot(_ values: [String], options: [String]) -> [Double] {
        let set = Set(values)
        return options.map { set.contains($0) ? 1 : 0 }
    }

    private static func colorVector(for color: String) -> [Double] {
        switch color {
        case "Black": return [0.05, 0.05, 0.05]
        case "White": return [0.95, 0.95, 0.95]
        case "Gray": return [0.60, 0.60, 0.60]
        case "Blue": return [0.24, 0.48, 0.92]
        case "Navy": return [0.09, 0.17, 0.39]
        case "Red": return [0.85, 0.20, 0.22]
        case "Green": return [0.27, 0.62, 0.33]
        case "Brown": return [0.45, 0.28, 0.14]
        case "Beige": return [0.86, 0.78, 0.64]
        case "Pink": return [0.93, 0.56, 0.71]
        case "Purple": return [0.58, 0.35, 0.89]
        case "Yellow": return [0.96, 0.86, 0.22]
        case "Orange": return [0.95, 0.55, 0.18]
        default: return [0.50, 0.50, 0.50]
        }
    }
}
