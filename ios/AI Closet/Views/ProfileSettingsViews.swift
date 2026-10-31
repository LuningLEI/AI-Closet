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

            Section("Personalization") {
                NavigationLink("Learned taste profile") {
                    LearnedTasteProfilePage()
                }
            }
        }
        .navigationTitle(appSettings.text("settings.title"))
        .navigationBarTitleDisplayMode(.inline)
    }
}

struct LearnedTasteProfilePage: View {
    @EnvironmentObject private var authStore: AuthStore
    @State private var profile: TasteProfileDTO?
    @State private var errorMessage: String?
    @State private var loading = false
    @State private var confirmReset = false

    var body: some View {
        Form {
            if loading && profile == nil {
                ProgressView("Loading learned preferences…")
            } else if let profile {
                Section("Learning status") {
                    LabeledContent("Evidence", value: "\(profile.evidenceCount)")
                    LabeledContent("Profile version", value: "\(profile.profileVersion)")
                    LabeledContent("Exploration", value: "\(Int((profile.explorationRate * 100).rounded()))%")
                }
                Section("Learned preferences") {
                    featureList(profile.preferredFeatures, empty: "More feedback is needed before a preference is learned.")
                }
                Section("Learned avoidances") {
                    featureList(profile.avoidedFeatures, empty: "No repeated avoidances learned yet.")
                }
                if let summary = profile.freeTextSummary {
                    Section("Feedback summary") {
                        Text(summary.summary)
                        LabeledContent("Confidence", value: summary.confidence.capitalized)
                        if !summary.preferredCues.isEmpty {
                            Text("Prefers: \(summary.preferredCues.joined(separator: ", "))")
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                        if !summary.avoidedCues.isEmpty {
                            Text("Avoids: \(summary.avoidedCues.joined(separator: ", "))")
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                }
                Section("How learning works") {
                    Text("Inferred preferences fade slowly after \(profile.inferredPreferenceHalfLifeDays) days and keep a \(Int(profile.inferredPreferenceFloor * 100))% floor. Your explicit settings and exact likes do not decay.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section {
                    Button("Reset learned taste", role: .destructive) { confirmReset = true }
                }
            }
            if let errorMessage { Text(errorMessage).foregroundStyle(.red) }
        }
        .navigationTitle("Learned taste")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
        .confirmationDialog("Reset learned taste?", isPresented: $confirmReset, titleVisibility: .visible) {
            Button("Reset", role: .destructive) { Task { await reset() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Future feedback will start a new learning period. Your catalog and explicit style settings stay unchanged.")
        }
    }

    @ViewBuilder private func featureList(_ values: [String], empty: String) -> some View {
        if values.isEmpty { Text(empty).foregroundStyle(.secondary) }
        else { ForEach(values, id: \.self) { Text(readable($0)) } }
    }

    private func readable(_ value: String) -> String {
        value.replacingOccurrences(of: "_", with: " ").replacingOccurrences(of: ":", with: ": ")
    }

    @MainActor private func load() async {
        loading = true; defer { loading = false }
        do {
            profile = try await APIClient.shared.get("/api/v1/outfits/taste-profile", token: await authStore.validAccessToken())
            errorMessage = nil
        } catch { errorMessage = error.localizedDescription }
    }

    @MainActor private func reset() async {
        loading = true; defer { loading = false }
        do {
            try await APIClient.shared.delete("/api/v1/outfits/taste-profile", token: await authStore.validAccessToken())
            await load()
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
