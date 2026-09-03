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
    @Published var selectedCategories: [String] = []
    @Published var customCategories: [String] = []
    @Published var modelTrainingConsent = false
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
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func save(token: String?, onboardingCompleted: Bool? = nil) async {
        errorMessage = nil
        do {
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
                selectedCategories: selectedCategories,
                customCategories: customCategories,
                modelTrainingConsent: modelTrainingConsent,
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
        selectedCategories = response.selectedCategories.isEmpty ? Self.defaultCategories : response.selectedCategories
        customCategories = response.customCategories
        modelTrainingConsent = response.modelTrainingConsent
    }

    private static func normalizedJPEGData(from data: Data) -> Data {
        guard let image = UIImage(data: data),
              let jpeg = image.jpegData(compressionQuality: 0.86) else {
            return data
        }
        return jpeg
    }

    private static let defaultCategories = [
        "Tops", "Bottoms", "Dresses", "Jumpsuits", "Sets", "Outerwear",
        "Shoes", "Bags", "Accessories", "Activewear", "Swimwear", "Intimates", "Uncategorized"
    ]
}
