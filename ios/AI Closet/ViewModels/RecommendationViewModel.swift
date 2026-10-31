import Foundation
import Combine
import CoreLocation

@MainActor
final class RecommendationViewModel: NSObject, ObservableObject, CLLocationManagerDelegate {
    private enum StorageKeys {
        static let selectedCityQuery = "today.selectedCityQuery"
    }

    @Published var todayLocation: WeatherLocationDTO?
    @Published var todayWeather: WeatherDTO?
    @Published var todayRecommendations: [OutfitRecommendationDTO] = []
    @Published private(set) var todayWearStatus: OutfitWearStatusDTO?
    @Published var recommendations: [OutfitRecommendationDTO] = []
    @Published var taxonomy = TaxonomyDTO(categories: [], colors: [], styles: [], occasions: [], seasons: [], subtypes: [:],lengths:[],sleeveLengths:[])
    @Published var cityQuery = LocationPresets.defaultLocation.label
    @Published var selectedOccasion = "Everyday"
    @Published var selectedStyle = "Any"
    @Published var selectedColor = "Any"
    @Published var temperatureF = 72.0
    @Published var activeIndex = 0
    @Published var isLoading = false
    @Published var isLoadingTodayWeather = false
    @Published var isLoadingTodayRecommendations = false
    @Published var errorMessage: String?
    @Published var todayWeatherErrorMessage: String?
    @Published var todayRecommendationErrorMessage: String?

    private let apiClient = APIClient.shared
    private let defaults = UserDefaults.standard
    private var todayLoadSequence = 0

    override init() {
        super.init()
        restoreSelectedCity()
    }

    var activeTodayRecommendation: OutfitRecommendationDTO? {
        guard todayRecommendations.indices.contains(activeIndex) else { return nil }
        return todayRecommendations[activeIndex]
    }

    var hasSelectedTodayOutfit: Bool { todayWearStatus?.selectedToday != nil }

    var selectedTodayRecommendation: OutfitRecommendationDTO? {
        guard let event=todayWearStatus?.selectedToday,
              let items=todayWearStatus?.selectedTodayItems,!items.isEmpty else { return nil }
        return OutfitRecommendationDTO(
            id:"today-selection-\(event.id.uuidString)",title:"Today's outfit",score:0,reasons:[],
            stylingNotes:[],missingSlots:[],
            breakdown:RecommendationBreakdownDTO(semanticFit:0,occasionFit:0,weatherFit:0,
                                                 styleHarmony:0,colorHarmony:0,categoryBalance:0),
            items:items)
    }

    var activeRecommendation: OutfitRecommendationDTO? {
        guard recommendations.indices.contains(activeIndex) else { return nil }
        return recommendations[activeIndex]
    }

    var isRefreshingToday: Bool {
        isLoadingTodayWeather || isLoadingTodayRecommendations
    }

    func loadTaxonomy(token: String?) async {
        do {
            taxonomy = try await apiClient.get("/api/v1/taxonomy", token: token)
            ClothingTaxonomySupport.install(taxonomy)
            selectedOccasion = taxonomy.occasions.contains(selectedOccasion) ? selectedOccasion : taxonomy.occasions.first ?? selectedOccasion
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func loadToday(token: String?) async {
        await loadToday(token: token, cityQuery: cityQuery, occasion: selectedOccasion)
    }

    func bootstrapToday(token: String?, occasion: String) async {
        await loadToday(token: token, cityQuery: cityQuery, occasion: occasion)
    }

    func loadToday(token: String?, cityQuery: String, occasion: String) async {
        await refreshTodaySelection(token:token)
        let normalizedQuery = normalizedCityQuery(cityQuery)
        guard !normalizedQuery.isEmpty else {
            todayWeatherErrorMessage = "l10n:today.city_required"
            todayLocation = nil
            todayWeather = nil
            todayRecommendations = []
            return
        }

        todayLoadSequence += 1
        let requestID = todayLoadSequence
        self.cityQuery = normalizedQuery
        defaults.set(normalizedQuery, forKey: StorageKeys.selectedCityQuery)
        todayWeatherErrorMessage = nil
        todayRecommendationErrorMessage = nil
        activeIndex = 0
        isLoadingTodayWeather = true
        isLoadingTodayRecommendations = false

        do {
            let weatherResponse: TodayWeatherResponseDTO = try await apiClient.get(
                "/api/v1/today/weather",
                token: token,
                queryItems: [
                    URLQueryItem(name: "location", value: normalizedQuery)
                ]
            )
            guard requestID == todayLoadSequence else { return }
            todayLocation = weatherResponse.location
            todayWeather = weatherResponse.weather
            self.cityQuery = weatherResponse.location.label
            defaults.set(weatherResponse.location.label, forKey: StorageKeys.selectedCityQuery)
        } catch {
            guard requestID == todayLoadSequence else { return }
            todayLocation = nil
            todayWeather = nil
            todayRecommendations = []
            todayWeatherErrorMessage = error.localizedDescription
            isLoadingTodayWeather = false
            isLoadingTodayRecommendations = false
            return
        }
        guard requestID == todayLoadSequence else { return }
        isLoadingTodayWeather = false

        guard let weather = todayWeather else { return }

        isLoadingTodayRecommendations = true
        todayRecommendations = []
        do {
            let response = try await loadTodayRecommendations(token: token, weather: weather, occasion: occasion)
            guard requestID == todayLoadSequence else { return }
            todayRecommendations = response.recommendations
        } catch {
            guard requestID == todayLoadSequence else { return }
            todayRecommendations = []
            todayRecommendationErrorMessage = error.localizedDescription
        }
        guard requestID == todayLoadSequence else { return }
        isLoadingTodayRecommendations = false
    }

    var citySuggestions: [String] {
        let normalizedQuery = normalizedCityQuery(cityQuery).lowercased()
        let options = LocationPresets.options.map(\.label)
        guard !normalizedQuery.isEmpty else { return Array(options.prefix(6)) }

        let prefixMatches = options.filter { $0.lowercased().hasPrefix(normalizedQuery) }
        let containsMatches = options.filter {
            !prefixMatches.contains($0) && $0.lowercased().contains(normalizedQuery)
        }
        return Array((prefixMatches + containsMatches).prefix(6))
    }

    func applyCitySuggestion(_ suggestion: String) {
        cityQuery = suggestion
    }

    func submitCityQuery(token: String?, occasion: String) async {
        await loadToday(token: token, cityQuery: cityQuery, occasion: occasion)
    }

    func refreshTodayRecommendations(token: String?, occasion: String) async {
        guard let weather = todayWeather else { return }

        todayLoadSequence += 1
        let requestID = todayLoadSequence
        todayRecommendationErrorMessage = nil
        activeIndex = 0
        isLoadingTodayRecommendations = true
        todayRecommendations = []

        do {
            let response = try await loadTodayRecommendations(token: token, weather: weather, occasion: occasion)
            guard requestID == todayLoadSequence else { return }
            todayRecommendations = response.recommendations
        } catch {
            guard requestID == todayLoadSequence else { return }
            todayRecommendations = []
            todayRecommendationErrorMessage = error.localizedDescription
        }

        guard requestID == todayLoadSequence else { return }
        isLoadingTodayRecommendations = false
    }

    func selectForToday(_ recommendation: OutfitRecommendationDTO,token:String?) async {
        todayRecommendations.removeAll { $0.id == recommendation.id }
        activeIndex = min(activeIndex, max(0, todayRecommendations.count - 1))
        await refreshTodaySelection(token:token)
    }

    func clearTodaySelection(token:String?) async {
        await refreshTodaySelection(token:token)
    }

    func refreshTodaySelection(token:String?) async {
        do {
            todayWearStatus = try await apiClient.get(
                "/api/v1/outfits/wear/status",token:token,
                queryItems:[URLQueryItem(name:"wear_date",value:Self.localDateString())])
        } catch {
            todayRecommendationErrorMessage=error.localizedDescription
        }
    }

    func generate(token: String?) async {
        isLoading = true
        errorMessage = nil
        activeIndex = 0
        defer { isLoading = false }

        do {
            let request = RecommendationsRequestDTO(
                occasion: selectedOccasion,
                temperatureF: temperatureF,
                preferredStyle: selectedStyle == "Any" ? nil : selectedStyle,
                preferredColor: selectedColor == "Any" ? nil : selectedColor,
                limit: 5
            )
            let response: RecommendationsResponseDTO = try await apiClient.post("/api/v1/recommendations", token: token, body: request)
            recommendations = response.recommendations
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func move(_ direction: Int, count: Int) {
        guard count > 0 else { return }
        activeIndex = (activeIndex + direction + count) % count
    }

    func removeTodayRecommendation(id: String) {
        todayRecommendations.removeAll { $0.id == id }
        if todayRecommendations.isEmpty { activeIndex = 0 }
        else { activeIndex = min(activeIndex, todayRecommendations.count - 1) }
    }

    private func loadTodayRecommendations(
        token: String?,
        weather: WeatherDTO,
        occasion: String
    ) async throws -> RecommendationsResponseDTO {
        let request = RecommendationsRequestDTO(
            occasion: occasion,
            temperatureF: weather.feelsLikeF,
            preferredStyle: nil,
            preferredColor: nil,
            limit: 5
        )

        do {
            return try await apiClient.post("/api/v1/recommendations", token: token, body: request)
        } catch {
            guard Self.isTimeoutError(error) else { throw error }
            return try await apiClient.post("/api/v1/recommendations", token: token, body: request)
        }
    }

    private static func isTimeoutError(_ error: Error) -> Bool {
        let nsError = error as NSError
        if nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorTimedOut {
            return true
        }
        return error.localizedDescription.localizedCaseInsensitiveContains("timed out")
    }

    private func restoreSelectedCity() {
        cityQuery = defaults.string(forKey: StorageKeys.selectedCityQuery) ?? LocationPresets.defaultLocation.label
    }

    private func normalizedCityQuery(_ query: String) -> String {
        query.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func localDateString(_ date:Date=Date())->String {
        let formatter = DateFormatter()
        formatter.calendar = .current
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: date)
    }
}
