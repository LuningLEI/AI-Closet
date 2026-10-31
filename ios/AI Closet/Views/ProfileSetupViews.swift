import PhotosUI
import SwiftUI

struct OnboardingView: View {
    @EnvironmentObject private var authStore: AuthStore
    @EnvironmentObject private var appSettings: AppSettings
    @ObservedObject var viewModel: ProfileViewModel
    @State private var page = 0

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 22) {
                ProgressView(value: Double(page + 1), total: 4)
                Group {
                    switch page {
                    case 0:
                        BasicProfileEditor(viewModel: viewModel)
                    case 1:
                        PreferenceEditor(viewModel: viewModel)
                    case 2:
                        CategoryEditor(viewModel: viewModel)
                    default:
                        FinalProfileStep(viewModel: viewModel)
                    }
                }
                Spacer()
                HStack {
                    Button(appSettings.text("common.back")) {
                        page = max(page - 1, 0)
                    }
                    .disabled(page == 0)
                    Spacer()
                    Button(page == 3 ? appSettings.text("profile.finish_setup") : appSettings.text("common.next")) {
                        if page == 3 {
                            Task { await viewModel.save(token: await authStore.validAccessToken(), onboardingCompleted: true) }
                        } else {
                            page += 1
                        }
                    }
                    .buttonStyle(.borderedProminent)
                }
            }
            .padding(20)
            .navigationTitle(appSettings.text("profile.page.setup"))
        }
    }
}

struct RootContentView: View {
    @EnvironmentObject private var authStore: AuthStore
    @EnvironmentObject private var appSettings: AppSettings
    @StateObject private var profileViewModel = ProfileViewModel()

    var body: some View {
        Group {
            if profileViewModel.isLoading && profileViewModel.preferences == nil {
                ProgressView(appSettings.text("profile.loading"))
            } else if profileViewModel.preferences?.onboardingCompleted == false {
                OnboardingView(viewModel: profileViewModel)
            } else {
                HomeTabView()
            }
        }
        .task {
            await profileViewModel.load(token: await authStore.validAccessToken())
        }
        .onChange(of: profileViewModel.preferences?.onboardingCompleted) { _, completed in
            if completed == true {
                Task { await profileViewModel.load(token: await authStore.validAccessToken()) }
            }
        }
    }
}

struct ProfileEditorPage<Content: View>: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var appSettings: AppSettings
    let title: String
    let saveAction: @MainActor () async -> Void
    @ViewBuilder let content: Content

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                content
            }
            .padding(16)
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button(appSettings.text("common.save")) {
                    Task {
                        await saveAction()
                        dismiss()
                    }
                }
            }
        }
    }
}

struct PlannerSettingsPage: View {
    @EnvironmentObject private var appSettings: AppSettings
    let plannerOccasions: [String]
    @Binding var weekdayDefaultOccasion: String
    @Binding var skipFederalHolidays: Bool

    var body: some View {
        Form {
            Section(appSettings.text("profile.edit.weekday_default")) {
                Picker(appSettings.text("recommendations.occasion"), selection: $weekdayDefaultOccasion) {
                    ForEach(plannerOccasions, id: \.self) { occasion in
                        Text(appSettings.option(occasion)).tag(occasion)
                    }
                }
            }

            Section(appSettings.text("profile.edit.holiday_rule")) {
                Toggle(appSettings.text("profile.edit.skip_holidays"), isOn: $skipFederalHolidays)
            }
        }
        .navigationTitle(appSettings.text("profile.edit.planner_settings"))
        .navigationBarTitleDisplayMode(.inline)
    }
}

struct BasicProfileEditor: View {
    @EnvironmentObject private var appSettings: AppSettings
    @ObservedObject var viewModel: ProfileViewModel

    private let years = Array(stride(from: 2026, through: 1940, by: -1))
    private let genderOptions = ["Prefer not to say", "Woman", "Man", "Non-binary", "Self-describe"]

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            fieldTitle(appSettings.text("profile.edit.nickname"))
            TextField(appSettings.text("profile.edit.nickname"), text: $viewModel.nickname)
                .textFieldStyle(.roundedBorder)

            fieldTitle(appSettings.text("profile.edit.birth_year"))
            Picker(appSettings.text("profile.edit.birth_year"), selection: Binding(
                get: { viewModel.birthYear ?? 0 },
                set: { viewModel.birthYear = $0 == 0 ? nil : $0 }
            )) {
                Text(appSettings.option("Prefer not to say")).tag(0)
                ForEach(years, id: \.self) { Text(String($0)).tag($0) }
            }
            .labelsHidden()

            fieldTitle(appSettings.text("profile.edit.gender"))
            Picker(appSettings.text("profile.edit.gender"), selection: $viewModel.genderIdentity) {
                ForEach(genderOptions, id: \.self) { Text(appSettings.option($0)).tag($0) }
            }
            .labelsHidden()
        }
    }

    private func fieldTitle(_ title: String) -> some View {
        Text(title)
            .font(.caption.weight(.bold))
            .textCase(.uppercase)
            .foregroundStyle(.secondary)
    }
}

struct PreferenceEditor: View {
    @EnvironmentObject private var appSettings: AppSettings
    @ObservedObject var viewModel: ProfileViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            OptionGrid(
                title: appSettings.text("profile.edit.daily_occasions"),
                options: availableOccasions,
                selection: $viewModel.dailyOccasions
            )
            .onChange(of: viewModel.dailyOccasions) { _, _ in
                viewModel.reconcileOccasionStyles()
            }

            if !viewModel.dailyOccasions.isEmpty {
                Text(appSettings.text("profile.edit.styles_by_occasion"))
                    .font(.caption.weight(.bold))
                    .textCase(.uppercase)
                    .foregroundStyle(.secondary)

                VStack(spacing: 10) {
                    ForEach(viewModel.dailyOccasions, id: \.self) { occasion in
                        OccasionStyleRow(
                            occasion: occasion,
                            options: availableStyles,
                            selection: Binding(
                                get: { viewModel.occasionStylePreferences[occasion] ?? [] },
                                set: { styles in
                                    guard !styles.isEmpty else { return }
                                    viewModel.occasionStylePreferences[occasion] = styles
                                    viewModel.reconcileOccasionStyles()
                                }
                            )
                        )
                    }
                }
            }
        }
    }

    private var availableOccasions: [String] {
        unique(viewModel.catalogOccasions + viewModel.dailyOccasions)
    }

    private var availableStyles: [String] {
        unique(viewModel.catalogStyles + viewModel.stylePreferences)
    }

    private func unique(_ values: [String]) -> [String] {
        values.reduce(into: []) { result, value in
            if !result.contains(value) { result.append(value) }
        }
    }
}

struct OccasionStyleRow: View {
    @EnvironmentObject private var appSettings: AppSettings
    let occasion: String
    let options: [String]
    @Binding var selection: [String]
    @State private var expanded = true

    var body: some View {
        DisclosureGroup(isExpanded: $expanded) {
            FlowLayout(spacing: 8) {
                ForEach(options, id: \.self) { style in
                    let selected = selection.contains(style)
                    Button {
                        if selected {
                            guard selection.count > 1 else { return }
                            selection.removeAll { $0 == style }
                        } else {
                            selection.append(style)
                        }
                    } label: {
                        Text(appSettings.option(style))
                            .font(.subheadline.weight(.semibold))
                            .padding(.horizontal, 12)
                            .padding(.vertical, 8)
                            .background(selected ? Color.blue.opacity(0.14) : Color(.systemBackground), in: Capsule())
                            .foregroundStyle(selected ? .blue : .primary)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.top, 12)
        } label: {
            HStack {
                Text(appSettings.option(occasion)).font(.headline)
                Spacer()
                Text(selection.prefix(2).map(appSettings.option).joined(separator: ", "))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        .padding(14)
        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
    }
}

struct FinalProfileStep: View {
    @EnvironmentObject private var appSettings: AppSettings
    @ObservedObject var viewModel: ProfileViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Toggle(appSettings.text("profile.edit.allow_training"), isOn: Binding(
                get: { viewModel.modelTrainingConsent },
                set: { viewModel.modelTrainingConsent = $0 }
            ))
            Text(appSettings.text("profile.edit.update_later"))
                .foregroundStyle(.secondary)
        }
    }
}

struct OptionGrid: View {
    @EnvironmentObject private var appSettings: AppSettings
    let title: String
    let options: [String]
    @Binding var selection: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title)
                .font(.caption.weight(.bold))
                .textCase(.uppercase)
                .foregroundStyle(.secondary)
            FlowLayout(spacing: 8) {
                ForEach(options, id: \.self) { option in
                    let selected = selection.contains(option)
                    Button {
                        if selected {
                            selection.removeAll { $0 == option }
                        } else {
                            selection.append(option)
                        }
                    } label: {
                        Text(appSettings.option(option))
                            .font(.subheadline.weight(.semibold))
                            .padding(.horizontal, 12)
                            .padding(.vertical, 8)
                            .background(selected ? Color.blue.opacity(0.14) : Color(.secondarySystemBackground), in: Capsule())
                            .foregroundStyle(selected ? .blue : .primary)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }
}
