import Foundation

struct GeminiClothingRecognitionService {
    private let session: URLSession
    private let endpoint = URL(string: "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent")!

    init(session: URLSession = .shared) {
        self.session = session
    }

    func analyze(imageData: Data) async throws -> ClothingAnalysis {
        let apiKey = try Self.apiKey()
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(apiKey, forHTTPHeaderField: "x-goog-api-key")

        let body = GeminiGenerateContentRequest(
            contents: [
                .init(parts: [
                    .text(prompt),
                    .inlineData(mimeType: "image/jpeg", data: imageData.base64EncodedString())
                ])
            ],
            generationConfig: .init(
                responseMimeType: "application/json",
                responseJsonSchema: Self.schema
            )
        )

        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw ClothingRecognitionError.invalidResponse
        }

        guard (200 ..< 300).contains(httpResponse.statusCode) else {
            if let apiError = try? JSONDecoder().decode(GeminiErrorEnvelope.self, from: data) {
                throw NSError(
                    domain: "GeminiClothingRecognitionService",
                    code: httpResponse.statusCode,
                    userInfo: [NSLocalizedDescriptionKey: apiError.error.message]
                )
            }

            throw NSError(
                domain: "GeminiClothingRecognitionService",
                code: httpResponse.statusCode,
                userInfo: [NSLocalizedDescriptionKey: "Gemini request failed with status \(httpResponse.statusCode)."]
            )
        }

        let envelope = try JSONDecoder().decode(GeminiGenerateContentResponse.self, from: data)
        guard let payload = envelope.firstTextPayload else {
            throw ClothingRecognitionError.noStructuredOutput
        }

        let parsed = try JSONDecoder().decode(StructuredAnalysis.self, from: Data(payload.utf8))
        return normalize(parsed)
    }

    private func normalize(_ parsed: StructuredAnalysis) -> ClothingAnalysis {
        let category = normalizedCategory(parsed.category, subtype: parsed.type)
        let subtype = SubtypeSupport.normalized(parsed.type, for: category)
        let color = normalizedColor(parsed.color)
        let seasons = normalizedSeasons(parsed.season)
        let style = normalizedStyle(parsed.style)
        let occasion = normalizedOccasion(parsed.occasion)

        return ClothingAnalysis(
            category: category,
            subtype: subtype == "Unknown" ? nil : subtype,
            color: color,
            seasons: seasons,
            style: style,
            occasion: occasion,
            confidence: parsed.confidence,
            summary: parsed.notes?.trimmingCharacters(in: .whitespacesAndNewlines),
            source: "Gemini",
            rawCategory: parsed.category,
            rawSubtype: parsed.type,
            rawColor: parsed.color,
            rawStyle: parsed.style,
            rawOccasion: parsed.occasion,
            rawSeasons: parsed.season
        )
    }

    private func normalizedCategory(_ category: String, subtype: String?) -> String {
        let normalized = [category, subtype]
            .compactMap { $0?.lowercased() }
            .joined(separator: " ")

        if normalized.contains("shoe") || normalized.contains("sneaker") || normalized.contains("boot") || normalized.contains("heel") || normalized.contains("sandal") || normalized.contains("loafer") {
            return "Shoes"
        }
        if normalized.contains("outerwear") || normalized.contains("jacket") || normalized.contains("coat") || normalized.contains("blazer") || normalized.contains("cardigan") {
            return "Outerwear"
        }
        if normalized.contains("accessor") || normalized.contains("bag") || normalized.contains("scarf") || normalized.contains("belt") || normalized.contains("hat") || normalized.contains("jewelry") || normalized.contains("jewellery") {
            return "Accessories"
        }
        if normalized.contains("bottom") || normalized.contains("pants") || normalized.contains("trouser") || normalized.contains("jean") || normalized.contains("shorts") || normalized.contains("skirt") || normalized.contains("leggings") {
            return "Bottoms"
        }
        if normalized.contains("top") || normalized.contains("shirt") || normalized.contains("tee") || normalized.contains("t-shirt") || normalized.contains("blouse") || normalized.contains("sweater") || normalized.contains("hoodie") || normalized.contains("pullover") {
            return "Tops"
        }
        return "Uncategorized"
    }

    private func normalizedColor(_ color: String) -> String {
        let normalized = color.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)

        switch normalized {
        case "black", "charcoal":
            return "Black"
        case "white", "ivory", "cream":
            return "White"
        case "off-white", "off white":
            return "Beige"
        case "gray", "grey", "silver":
            return "Gray"
        case "blue", "light blue", "sky blue", "denim blue":
            return "Blue"
        case "navy", "dark blue":
            return "Navy"
        case "red", "burgundy", "wine":
            return "Red"
        case "green", "olive", "sage":
            return "Green"
        case "brown", "tan", "camel", "khaki":
            return "Brown"
        case "beige", "taupe":
            return "Beige"
        case "pink", "rose":
            return "Pink"
        case "purple", "lavender", "violet":
            return "Purple"
        case "yellow", "mustard":
            return "Yellow"
        case "orange", "peach", "rust":
            return "Orange"
        default:
            return "Unknown"
        }
    }

    private func normalizedSeasons(_ seasons: [String]) -> Set<String> {
        let mapped = Set(
            seasons.compactMap { season -> String? in
                switch season.lowercased().trimmingCharacters(in: .whitespacesAndNewlines) {
                case "spring":
                    return "Spring"
                case "summer":
                    return "Summer"
                case "fall", "autumn":
                    return "Fall"
                case "winter":
                    return "Winter"
                case "all-season", "all season", "year-round", "year round":
                    return "All-Season"
                default:
                    return nil
                }
            }
        )

        return mapped.isEmpty ? ["All-Season"] : mapped
    }

    private func normalizedStyle(_ style: String) -> String {
        switch style.lowercased().trimmingCharacters(in: .whitespacesAndNewlines) {
        case "formal", "elegant":
            return "Formal"
        case "business", "business casual", "office":
            return "Business"
        case "sporty", "athleisure":
            return "Sporty"
        case "streetwear":
            return "Streetwear"
        case "minimal", "minimalist", "clean girl", "classic", "chic", "korean":
            return "Minimalist"
        default:
            return "Casual"
        }
    }

    private func normalizedOccasion(_ occasion: String) -> String {
        switch occasion.lowercased().trimmingCharacters(in: .whitespacesAndNewlines) {
        case "work", "office", "business":
            return "Work"
        case "party", "night out":
            return "Party"
        case "date", "date night":
            return "Date"
        case "travel", "vacation":
            return "Travel"
        case "workout", "gym", "sport":
            return "Workout"
        case "wedding", "formal event":
            return "Wedding"
        default:
            return "Everyday"
        }
    }

    private static func apiKey() throws -> String {
        if let value = Bundle.main.object(forInfoDictionaryKey: "GeminiAPIKey") as? String,
           !value.isEmpty,
           value != "$(GEMINI_API_KEY)" {
            return value
        }

        if let value = ProcessInfo.processInfo.environment["GEMINI_API_KEY"], !value.isEmpty {
            return value
        }

        throw ClothingRecognitionError.missingAPIKey
    }

    private var prompt: String {
        """
        Analyze the main clothing item in this image and return structured JSON only.
        Ignore faces, background, room context, mirrors, phones, and body parts except where needed to identify the garment.
        Focus on the garment that occupies the largest visible area. If pants or a skirt dominate the image, classify as Bottoms.

        Requirements:
        - category must be exactly one of: \(ClothingTaxonomySupport.categories.joined(separator: ", "))
        - type must be exactly one allowed frontend subtype value and must match the chosen category.
        - for Tops use only: \(SubtypeSupport.options(for: "Tops").joined(separator: ", "))
        - for Bottoms use only: \(SubtypeSupport.options(for: "Bottoms").joined(separator: ", "))
        - for Shoes use only: \(SubtypeSupport.options(for: "Shoes").joined(separator: ", "))
        - for Outerwear use only: \(SubtypeSupport.options(for: "Outerwear").joined(separator: ", "))
        - for Accessories use only: \(SubtypeSupport.options(for: "Accessories").joined(separator: ", "))
        - for Uncategorized use only: Unknown
        - color must be exactly one of: \(ClothingTaxonomySupport.colors.joined(separator: ", "))
        - season must be an array using only: \(SeasonSelectionSupport.options.joined(separator: ", "))
        - style must be exactly one of: \(ClothingTaxonomySupport.styles.joined(separator: ", "))
        - occasion must be exactly one of: \(ClothingTaxonomySupport.occasions.joined(separator: ", "))
        - confidence must be between 0 and 1
        - notes should be one short sentence summarizing the item
        """
    }

    private static var schema: [String: SchemaValue] {
        [
        "type": .string("object"),
        "properties": .object([
            "category": .object([
                "type": .string("string"),
                "enum": .array(ClothingTaxonomySupport.categories.map(SchemaValue.string))
            ]),
            "type": .object([
                "type": .string("string"),
                "enum": .array(ClothingTaxonomySupport.allSubtypeOptions.map(SchemaValue.string))
            ]),
            "color": .object([
                "type": .string("string"),
                "enum": .array(ClothingTaxonomySupport.colors.map(SchemaValue.string))
            ]),
            "season": .object([
                "type": .string("array"),
                "items": .object([
                    "type": .string("string"),
                    "enum": .array(SeasonSelectionSupport.options.map(SchemaValue.string))
                ])
            ]),
            "style": .object([
                "type": .string("string"),
                "enum": .array(ClothingTaxonomySupport.styles.map(SchemaValue.string))
            ]),
            "occasion": .object([
                "type": .string("string"),
                "enum": .array(ClothingTaxonomySupport.occasions.map(SchemaValue.string))
            ]),
            "confidence": .object([
                "type": .string("number"),
                "minimum": .number(0),
                "maximum": .number(1)
            ]),
            "notes": .object([
                "type": .array([.string("string"), .string("null")])
            ])
        ]),
        "required": .array([
            .string("category"),
            .string("type"),
            .string("color"),
            .string("season"),
            .string("style"),
            .string("occasion"),
            .string("confidence"),
            .string("notes")
        ]),
        "propertyOrdering": .array([
            .string("category"),
            .string("type"),
            .string("color"),
            .string("season"),
            .string("style"),
            .string("occasion"),
            .string("confidence"),
            .string("notes")
        ])
        ]
    }
}

private struct StructuredAnalysis: Decodable {
    let category: String
    let type: String
    let color: String
    let season: [String]
    let style: String
    let occasion: String
    let confidence: Double
    let notes: String?
}

private struct GeminiErrorEnvelope: Decodable {
    struct APIError: Decodable {
        let message: String
    }

    let error: APIError
}

private struct GeminiGenerateContentRequest: Encodable {
    struct Content: Encodable {
        let parts: [Part]
    }

    struct GenerationConfig: Encodable {
        let responseMimeType: String
        let responseJsonSchema: [String: SchemaValue]

        enum CodingKeys: String, CodingKey {
            case responseMimeType
            case responseJsonSchema = "responseJsonSchema"
        }
    }

    let contents: [Content]
    let generationConfig: GenerationConfig
}

private enum Part: Encodable {
    case text(String)
    case inlineData(mimeType: String, data: String)

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .text(let value):
            try container.encode(["text": value])
        case .inlineData(let mimeType, let data):
            try container.encode([
                "inlineData": [
                    "mimeType": mimeType,
                    "data": data
                ]
            ])
        }
    }
}

private struct GeminiGenerateContentResponse: Decodable {
    struct Candidate: Decodable {
        struct Content: Decodable {
            let parts: [TextPart]?
        }

        let content: Content?
    }

    struct TextPart: Decodable {
        let text: String?
    }

    let candidates: [Candidate]?

    var firstTextPayload: String? {
        candidates?
            .compactMap(\.content?.parts)
            .flatMap { $0 }
            .first(where: { $0.text?.isEmpty == false })?
            .text
    }
}

private enum SchemaValue: Encodable {
    case string(String)
    case bool(Bool)
    case number(Double)
    case object([String: SchemaValue])
    case array([SchemaValue])

    func encode(to encoder: Encoder) throws {
        switch self {
        case .string(let value):
            var container = encoder.singleValueContainer()
            try container.encode(value)
        case .bool(let value):
            var container = encoder.singleValueContainer()
            try container.encode(value)
        case .number(let value):
            var container = encoder.singleValueContainer()
            try container.encode(value)
        case .object(let value):
            var container = encoder.singleValueContainer()
            try container.encode(value)
        case .array(let value):
            var container = encoder.singleValueContainer()
            try container.encode(value)
        }
    }
}
