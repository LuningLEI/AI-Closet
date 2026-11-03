import Foundation
import Combine
import PhotosUI
import SwiftUI
import UIKit

@MainActor
final class ProfileViewModel: ObservableObject {
    @Published var preferences: UserPreferencesDTO?
    @Published var nickname = "Closet user"
    @Published var birthYear: Int?
    @Published var genderIdentity = "Prefer not to say"
    @Published var dailyOccasions: [String] = []
    @Published var stylePreferences: [String] = []
    @Published var occasionStylePreferences: [String: [String]] = [:]
    @Published var selectedCategories: [String] = []
    @Published var customCategories: [String] = []
    @Published var catalogSubtypes: [String:[String]] = [:]
    @Published var catalogColors: [String] = []
    @Published var catalogStyles: [String] = []
    @Published var catalogOccasions: [String] = []
    @Published var catalogSeasons: [String] = []
    @Published var catalogLengths: [String] = []
    @Published var catalogSleeveLengths: [String] = []
    @Published var modelTrainingConsent = false
    @Published var personalizationEnabled = true
    @Published var feedbackLearningEnabled = true
    @Published var explorationLevel = "balanced"
    @Published var rotationLevel = "balanced"
    @Published var temperatureSensitivity = "neutral"
    @Published var isLoading = false
    @Published var errorMessage: String?

    private let apiClient = APIClient.shared

    var avatarURL: String? {
        preferences?.avatarUrl
    }

    func load(token: String?) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let response: UserPreferencesDTO = try await apiClient.get("/api/v1/preferences", token: token)
            apply(response)
            let taxonomy:TaxonomyDTO = try await apiClient.get("/api/v1/taxonomy",token:token)
            apply(taxonomy)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func save(token: String?, onboardingCompleted: Bool? = nil) async {
        errorMessage = nil
        do {
            reconcileOccasionStyles()
            let request = UserPreferencesUpdateRequestDTO(
                profileVersion: preferences?.profileVersion,
                taxonomyVersion: preferences?.taxonomyVersion,
                stylePreferenceVersion: preferences?.stylePreferenceVersion,
                onboardingCompleted: onboardingCompleted,
                nickname: nickname.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "Closet user" : nickname,
                avatarPath: preferences?.avatarPath,
                birthYear: birthYear,
                genderIdentity: genderIdentity,
                dailyOccasions: dailyOccasions,
                stylePreferences: stylePreferences,
                occasionStylePreferences: occasionStylePreferences,
                selectedCategories: selectedCategories,
                customCategories: customCategories,
                taxonomyCustomizations: TaxonomyCustomizationsDTO(
                    subtypes:catalogSubtypes,colors:catalogColors,styles:catalogStyles,
                    occasions:catalogOccasions,seasons:catalogSeasons,lengths:catalogLengths,
                    sleeveLengths:catalogSleeveLengths),
                modelTrainingConsent: modelTrainingConsent,
                personalizationEnabled: personalizationEnabled,
                feedbackLearningEnabled: feedbackLearningEnabled,
                explorationLevel: explorationLevel,
                rotationLevel: rotationLevel,
                temperatureSensitivity: temperatureSensitivity,
                defaultLocationLabel: preferences?.defaultLocationLabel,
                defaultLatitude: preferences?.defaultLatitude,
                defaultLongitude: preferences?.defaultLongitude,
                temperatureUnit: preferences?.temperatureUnit
            )
            let response: UserPreferencesDTO = try await apiClient.patch("/api/v1/preferences", token: token, body: request)
            apply(response)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func uploadAvatar(_ pickerItem: PhotosPickerItem?, token: String?) async {
        guard let pickerItem else { return }
        errorMessage = nil
        do {
            guard let data = try await pickerItem.loadTransferable(type: Data.self) else { return }
            let imageData = Self.normalizedJPEGData(from: data)
            let response = try await apiClient.uploadAvatar(imageData, token: token)
            apply(response)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func apply(_ response: UserPreferencesDTO) {
        preferences = response
        nickname = response.nickname?.isEmpty == false ? response.nickname! : "Closet user"
        birthYear = response.birthYear
        genderIdentity = response.genderIdentity ?? "Prefer not to say"
        dailyOccasions = response.dailyOccasions.isEmpty ? ["Everyday"] : response.dailyOccasions
        stylePreferences = response.stylePreferences.isEmpty ? ["Casual"] : response.stylePreferences
        occasionStylePreferences = response.occasionStylePreferences ?? Dictionary(
            uniqueKeysWithValues: dailyOccasions.map { ($0, stylePreferences) }
        )
        reconcileOccasionStyles()
        selectedCategories = response.selectedCategories
        customCategories = response.customCategories
        if let custom=response.taxonomyCustomizations {
            catalogSubtypes=custom.subtypes ?? catalogSubtypes
            catalogColors=custom.colors ?? catalogColors
            catalogStyles=custom.styles ?? catalogStyles
            catalogOccasions=custom.occasions ?? catalogOccasions
            catalogSeasons=custom.seasons ?? catalogSeasons
            catalogLengths=custom.lengths ?? catalogLengths
            catalogSleeveLengths=custom.sleeveLengths ?? catalogSleeveLengths
        }
        modelTrainingConsent = response.modelTrainingConsent
        personalizationEnabled = response.personalizationEnabled
        feedbackLearningEnabled = response.feedbackLearningEnabled
        explorationLevel = response.explorationLevel
        rotationLevel = response.rotationLevel
        temperatureSensitivity = response.temperatureSensitivity
    }

    private func apply(_ taxonomy:TaxonomyDTO) {
        ClothingTaxonomySupport.install(taxonomy)
        selectedCategories=taxonomy.categories
        catalogSubtypes=taxonomy.subtypes
        catalogColors=taxonomy.colors
        catalogStyles=taxonomy.styles
        catalogOccasions=taxonomy.occasions
        catalogSeasons=taxonomy.seasons
        catalogLengths=taxonomy.lengths
        catalogSleeveLengths=taxonomy.sleeveLengths
        reconcileOccasionStyles()
    }

    func reconcileOccasionStyles() {
        let fallback = stylePreferences.isEmpty ? [catalogStyles.first ?? "Casual"] : stylePreferences
        var normalized: [String: [String]] = [:]
        for occasion in dailyOccasions {
            let current = occasionStylePreferences.first(where: { $0.key.caseInsensitiveCompare(occasion) == .orderedSame })?.value ?? fallback
            let cleaned = current.reduce(into: [String]()) { values, style in
                let value = style.trimmingCharacters(in: .whitespacesAndNewlines)
                if !value.isEmpty, !values.contains(value) { values.append(value) }
            }
            normalized[occasion] = cleaned.isEmpty ? [catalogStyles.first ?? "Casual"] : cleaned
        }
        occasionStylePreferences = normalized
        stylePreferences = dailyOccasions.flatMap { normalized[$0] ?? [] }.reduce(into: [String]()) {
            if !$0.contains($1) { $0.append($1) }
        }
    }

    private static func normalizedJPEGData(from data: Data) -> Data {
        guard let image = UIImage(data: data),
              let jpeg = image.jpegData(compressionQuality: 0.86) else {
            return data
        }
        return jpeg
    }

}
