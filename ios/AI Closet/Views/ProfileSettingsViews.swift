import PhotosUI
import SwiftUI

struct SystemSettingsPage: View {
    @EnvironmentObject private var appSettings: AppSettings

    var body: some View {
        Form {
            Section(appSettings.text("settings.language")) {
                Picker(appSettings.text("settings.language"), selection: $appSettings.language) {
                    Text(appSettings.text("settings.language.english")).tag(AppLanguage.english)
                    Text(appSettings.text("settings.language.chinese")).tag(AppLanguage.simplifiedChinese)
                }
                .pickerStyle(.menu)
            }

            Section(appSettings.text("settings.temperature_unit")) {
                Picker(appSettings.text("settings.temperature_unit"), selection: $appSettings.temperatureUnit) {
                    Text(appSettings.text("settings.temperature.fahrenheit")).tag(TemperatureUnitPreference.fahrenheit)
                    Text(appSettings.text("settings.temperature.celsius")).tag(TemperatureUnitPreference.celsius)
                }
                .pickerStyle(.menu)
            }

        }
        .navigationTitle(appSettings.text("settings.title"))
        .navigationBarTitleDisplayMode(.inline)
    }
}

struct PersonalizationSettingsPage: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var appSettings: AppSettings
    @ObservedObject var viewModel: ProfileViewModel
    let saveAction: @MainActor () async -> Void

    var body: some View {
        Form {
            Section(appSettings.text("personalization.explicit")) {
                NavigationLink(appSettings.text("personalization.styles")) {
                    ProfileEditorPage(title: appSettings.text("profile.section.style"), saveAction: saveAction) {
                        PreferenceEditor(viewModel: viewModel)
                    }
                }
            }
            Section {
                Toggle(appSettings.text("personalization.enabled"), isOn: $viewModel.personalizationEnabled)
                Text(appSettings.text("personalization.enabled.help"))
                    .font(.footnote).foregroundStyle(.secondary)
                Toggle(appSettings.text("personalization.learning"), isOn: $viewModel.feedbackLearningEnabled)
                    .disabled(!viewModel.personalizationEnabled)
                Text(appSettings.text("personalization.learning.help"))
                    .font(.footnote).foregroundStyle(.secondary)
            } header: { Text(appSettings.text("personalization.behavior")) }
            Section(appSettings.text("personalization.discovery")) {
                Picker(appSettings.text("personalization.discovery"), selection: $viewModel.explorationLevel) {
                    Text(appSettings.text("personalization.discovery.familiar")).tag("familiar")
                    Text(appSettings.text("personalization.discovery.balanced")).tag("balanced")
                    Text(appSettings.text("personalization.discovery.adventurous")).tag("adventurous")
                }.pickerStyle(.inline).labelsHidden()
            }.disabled(!viewModel.personalizationEnabled)
            Section(appSettings.text("personalization.rotation")) {
                Picker(appSettings.text("personalization.rotation"), selection: $viewModel.rotationLevel) {
                    Text(appSettings.text("personalization.rotation.repeat")).tag("repeat_freely")
                    Text(appSettings.text("personalization.rotation.balanced")).tag("balanced")
                    Text(appSettings.text("personalization.rotation.variety")).tag("more_variety")
                }.pickerStyle(.inline).labelsHidden()
            }
            Section(appSettings.text("personalization.comfort")) {
                Picker(appSettings.text("personalization.comfort"), selection: $viewModel.temperatureSensitivity) {
                    Text(appSettings.text("personalization.comfort.cold")).tag("runs_cold")
                    Text(appSettings.text("personalization.comfort.neutral")).tag("neutral")
                    Text(appSettings.text("personalization.comfort.warm")).tag("runs_warm")
                }.pickerStyle(.inline).labelsHidden()
            }
        }
        .navigationTitle(appSettings.text("profile.section.personalization"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button(appSettings.text("common.save")) { Task { await saveAction(); dismiss() } }
            }
        }
    }
}

struct DataPrivacySettingsPage: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var authStore: AuthStore
    @EnvironmentObject private var appSettings: AppSettings
    @ObservedObject var viewModel: ProfileViewModel
    let saveAction: @MainActor () async -> Void
    @State private var errorMessage: String?
    @State private var loading = false
    @State private var confirmReset = false

    var body: some View {
        Form {
            Section {
                Toggle(appSettings.text("privacy.training"), isOn: $viewModel.modelTrainingConsent)
                Text(appSettings.text("privacy.training.help"))
                    .font(.footnote).foregroundStyle(.secondary)
            }
            Section {
                Button(appSettings.text("privacy.reset"), role: .destructive) { confirmReset = true }
                    .disabled(loading)
                Text(appSettings.text("privacy.reset.help"))
                    .font(.footnote).foregroundStyle(.secondary)
            }
            if let errorMessage { Text(errorMessage).foregroundStyle(.red) }
        }
        .navigationTitle(appSettings.text("profile.section.privacy"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button(appSettings.text("common.save")) { Task { await saveAction(); dismiss() } }
            }
        }
        .confirmationDialog(appSettings.text("privacy.reset.prompt"), isPresented: $confirmReset, titleVisibility: .visible) {
            Button(appSettings.text("privacy.reset"), role: .destructive) { Task { await reset() } }
            Button(appSettings.text("common.cancel"), role: .cancel) {}
        } message: {
            Text(appSettings.text("privacy.reset.help"))
        }
    }

    @MainActor private func reset() async {
        loading = true; defer { loading = false }
        do {
            try await APIClient.shared.delete("/api/v1/outfits/taste-profile", token: await authStore.validAccessToken())
            errorMessage = nil
        } catch { errorMessage = error.localizedDescription }
    }
}

struct FlowLayout<Content: View>: View {
    let spacing: CGFloat
    @ViewBuilder let content: Content

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 100), spacing: spacing)], alignment: .leading, spacing: spacing) {
            content
        }
    }
}

struct AvatarImage: View {
    let url: String?
    let size: CGFloat

    var body: some View {
        AsyncImage(url: url.flatMap(URL.init(string:))) { phase in
            switch phase {
            case .success(let image):
                image.resizable().scaledToFill()
            default:
                Image(systemName: "person.fill")
                    .font(.system(size: size * 0.36))
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(Color(.secondarySystemBackground))
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
        .overlay(Circle().stroke(Color(.secondarySystemBackground), lineWidth: 6))
    }
}

struct AvatarPreview: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var appSettings: AppSettings
    let url: String?

    var body: some View {
        NavigationStack {
            ZStack {
                Color.black.ignoresSafeArea()
                AsyncImage(url: url.flatMap(URL.init(string:))) { phase in
                    switch phase {
                    case .success(let image):
                        image.resizable().scaledToFit()
                    default:
                        ProgressView().tint(.white)
                    }
                }
                .padding()
            }
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(appSettings.text("common.done")) { dismiss() }
                }
            }
        }
    }
}
