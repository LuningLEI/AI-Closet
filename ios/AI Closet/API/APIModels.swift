import Foundation

struct ClothingItemDTO: Identifiable, Codable, Equatable {
    let id: UUID
    let userId: String?
    let imageUrl: String
    let imagePath: String?
    let recognitionStatus: String?
    var category: String
    var subtype: String?
    var color: String
    var season: String
    var style: String
    var occasion: String
    var material: String?
    var pattern: String?
    var fit: String?
    var length: String?
    var sleeveLength: String?
    var neckline: String?
    var layeringRole: String?
    var warmthLevel: Int?
    var formalityScore: Int?
    var recognitionSource: String?
    var recognitionSummary: String?
    var recognitionConfidence: Double?
    let createdAt: String?

    var isRecognitionPending: Bool {
        let status = recognitionStatus?.lowercased()
        return status == "queued" || status == "processing"
    }

    var displayTitle: String {
        subtype?.isEmpty == false ? subtype! : category
    }
}

struct ClosetSummaryDTO: Codable {
    let totalItems: Int
    let categoryCounts: [String: Int]
    let recentItems: [ClothingItemDTO]
}

struct BatchUploadResponseDTO: Codable {
    let items: [ClothingItemDTO]
    let errors: [BatchUploadFailureDTO]
    let queued: [UploadQueueStatusDTO]
}

struct BatchUploadFailureDTO: Codable {
    let filename: String
    let detail: String
}

struct UploadQueueStatusDTO: Codable {
    let clothingItemId: String
    let recognitionStatus: String
    let imagePath: String?
}

struct ClothingItemUpdateRequestDTO: Encodable {
    let category: String
    let subtype: String?
    let color: String
    let season: String
    let style: String
    let occasion: String
    let recognitionSummary: String?
}

struct TaxonomyDTO: Codable {
    let categories: [String]
    let colors: [String]
    let styles: [String]
    let occasions: [String]
    let seasons: [String]
    let subtypes: [String: [String]]
}

struct UserPreferencesDTO: Codable {
    let userId: String
    let profileVersion: String?
    let taxonomyVersion: String?
    let stylePreferenceVersion: String?
    let onboardingCompleted: Bool
    let nickname: String?
    let avatarPath: String?
    let avatarUrl: String?
    let birthYear: Int?
    let genderIdentity: String?
    let dailyOccasions: [String]
    let stylePreferences: [String]
    let selectedCategories: [String]
    let customCategories: [String]
    let modelTrainingConsent: Bool
    let defaultLocationLabel: String?
    let defaultLatitude: Double?
    let defaultLongitude: Double?
    let temperatureUnit: String
}

struct UserPreferencesUpdateRequestDTO: Encodable {
    let profileVersion: String?
    let taxonomyVersion: String?
    let stylePreferenceVersion: String?
    let onboardingCompleted: Bool?
    let nickname: String?
    let avatarPath: String?
    let birthYear: Int?
    let genderIdentity: String?
    let dailyOccasions: [String]?
    let stylePreferences: [String]?
    let selectedCategories: [String]?
    let customCategories: [String]?
    let modelTrainingConsent: Bool?
    let defaultLocationLabel: String?
    let defaultLatitude: Double?
    let defaultLongitude: Double?
    let temperatureUnit: String?
}

struct RecommendationsRequestDTO: Encodable {
    let occasion: String
    let temperatureF: Double
    let preferredStyle: String?
    let preferredColor: String?
    let limit: Int
}

struct RecommendationsResponseDTO: Codable {
    let context: RecommendationContextDTO
    let recommendations: [OutfitRecommendationDTO]
}

struct TodayRecommendationResponseDTO: Codable {
    let location: WeatherLocationDTO
    let weather: WeatherDTO
    let context: RecommendationContextDTO
    let recommendations: [OutfitRecommendationDTO]
}

struct TodayWeatherResponseDTO: Codable {
    let location: WeatherLocationDTO
    let weather: WeatherDTO
}

struct RecommendationContextDTO: Codable {
    let occasion: String
    let temperatureF: Double
    let preferredStyle: String?
    let preferredColor: String?
    let limit: Int
}

struct WeatherLocationDTO: Codable {
    let label: String
    let detail: String
    let latitude: Double
    let longitude: Double
    let source: String
}

struct WeatherDTO: Codable {
    let temperatureF: Double
    let feelsLikeF: Double
    let precipitation: Double?
    let windMph: Double?
    let condition: String
    let weatherCode: Int?
    let source: String

    var temperatureC: Int {
        Int(((temperatureF - 32) * 5 / 9).rounded())
    }
}

struct RecommendationBreakdownDTO: Codable, Equatable {
    let semanticFit: Double
    let occasionFit: Double
    let weatherFit: Double
    let styleHarmony: Double
    let colorHarmony: Double
    let categoryBalance: Double
}

struct OutfitRecommendationDTO: Identifiable, Codable, Equatable {
    let id: String
    let title: String
    let score: Double
    let reasons: [String]
    let stylingNotes: [String]
    let missingSlots: [String]
    let breakdown: RecommendationBreakdownDTO
    let items: [ClothingItemDTO]
}

struct ChatRequestDTO: Encodable {
    let message: String
}

struct ChatMetadataDTO: Codable {
    let recommendations: [OutfitRecommendationDTO]?
}

struct ChatResponseDTO: Codable {
    let reply: String
    let metadata: ChatMetadataDTO?

    enum CodingKeys: String, CodingKey {
        case reply
        case metadata
    }
}

struct LocationPreset: Identifiable, Hashable {
    let id: String
    let label: String
    let latitude: Double
    let longitude: Double
}

enum LocationPresets {
    static let defaultLocation = LocationPreset(
        id: "san-jose",
        label: "San Jose, CA",
        latitude: 37.3387,
        longitude: -121.8853
    )

    static let options = [
        defaultLocation,
        LocationPreset(id: "san-francisco", label: "San Francisco, CA", latitude: 37.7749, longitude: -122.4194),
        LocationPreset(id: "new-york", label: "New York, NY", latitude: 40.7128, longitude: -74.0060),
        LocationPreset(id: "miami", label: "Miami, FL", latitude: 25.7617, longitude: -80.1918),
        LocationPreset(id: "los-angeles", label: "Los Angeles, CA", latitude: 34.0522, longitude: -118.2437)
    ]
}
