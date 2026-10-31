import PhotosUI
import SwiftUI

struct MyView: View {
    @EnvironmentObject private var authStore: AuthStore
    @EnvironmentObject private var appSettings: AppSettings
    @StateObject private var viewModel = ProfileViewModel()
    @State private var selectedAvatar: PhotosPickerItem?
    @State private var showAvatarPreview = false
    @State private var showSignOutConfirm = false
    @State private var selectedPlanningDate = Date()
    @State private var selectedPlanningOccasion = "Everyday"
    @AppStorage("profile.occasions.plans") private var storedOccasionPlans = ""
    @AppStorage("profile.occasions.weekdayDefault") private var weekdayDefaultOccasion = "Work"
    @AppStorage("profile.occasions.skipFederalHolidays") private var skipFederalHolidays = true

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 18) {
                    profileHeader
                    profileSections
                }
                .padding(16)
            }
            .confirmationDialog(appSettings.text("profile.sign_out.prompt"), isPresented: $showSignOutConfirm, titleVisibility: .visible) {
                Button(appSettings.text("profile.sign_out"), role: .destructive) {
                    authStore.signOut()
                }
                Button(appSettings.text("common.cancel"), role: .cancel) {}
            }
            .sheet(isPresented: $showAvatarPreview) {
                AvatarPreview(url: viewModel.avatarURL)
            }
            .task {
                await viewModel.load(token: await authStore.validAccessToken())
                syncPlanningOccasion()
            }
            .onChange(of: selectedAvatar) { _, item in
                Task { await viewModel.uploadAvatar(item, token: await authStore.validAccessToken()) }
            }
            .onChange(of: selectedPlanningDate) { _, _ in
                syncPlanningOccasion()
            }
        }
    }

    private var profileHeader: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 8) {
                Text(appSettings.text("profile.greeting"))
                    .font(.title2.weight(.semibold))
                    .foregroundStyle(.secondary)

                Text(displayNickname)
                    .font(.system(size: 34, weight: .bold))
                    .lineLimit(2)
                    .minimumScaleFactor(0.8)
            }
            .frame(minHeight: 92, alignment: .topLeading)

            Spacer()

            VStack(alignment: .trailing, spacing: 8) {
                Button {
                    showAvatarPreview = viewModel.avatarURL != nil
                } label: {
                    ZStack(alignment: .bottomTrailing) {
                        AvatarImage(url: viewModel.avatarURL, size: 64)
                        PhotosPicker(selection: $selectedAvatar, matching: .images) {
                            Image(systemName: "pencil")
                                .font(.caption.weight(.bold))
                                .foregroundStyle(.white)
                                .frame(width: 24, height: 24)
                                .background(Color.orange, in: Circle())
                                .overlay(Circle().stroke(.white, lineWidth: 2))
                        }
                    }
                }
                .buttonStyle(.plain)
            }
            .frame(minHeight: 92, alignment: .topTrailing)
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }

    private var profileSections: some View {
        VStack(spacing: 14) {
            occasionPlannerCard

            NavigationLink {
                ProfileEditorPage(title: appSettings.text("profile.section.basic"), saveAction: saveProfile) {
                    BasicProfileEditor(viewModel: viewModel)
                }
            } label: {
                profileRow(
                    title: appSettings.text("profile.section.basic"),
                    subtitle: basicProfileSummary
                )
            }

            NavigationLink {
                ProfileEditorPage(title: appSettings.text("profile.section.style"), saveAction: saveProfile) {
                    PreferenceEditor(viewModel: viewModel)
                }
            } label: {
                profileRow(
                    title: appSettings.text("profile.section.style"),
                    subtitle: stylePreferenceSummary
                )
            }

            NavigationLink {
                ProfileEditorPage(title: appSettings.text("profile.section.catalog"), saveAction: saveProfile) {
                    CategoryEditor(viewModel: viewModel)
                }
            } label: {
                profileRow(
                    title: appSettings.text("profile.section.catalog"),
                    subtitle: appSettings.text("profile.section.catalog.subtitle", viewModel.selectedCategories.count)
                )
            }

            NavigationLink {
                SystemSettingsPage()
            } label: {
                profileRow(
                    title: appSettings.text("profile.section.settings"),
                    subtitle: appSettings.text(
                        "profile.section.settings.subtitle",
                        appSettings.language == .english ? appSettings.text("settings.language.english") : appSettings.text("settings.language.chinese"),
                        appSettings.temperatureUnit == .fahrenheit ? appSettings.text("settings.temperature.fahrenheit") : appSettings.text("settings.temperature.celsius")
                    )
                )
            }

            if let errorMessage = viewModel.errorMessage {
                Text(errorMessage)
                    .font(.footnote.weight(.medium))
                    .foregroundStyle(.red)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(14)
                    .background(Color.red.opacity(0.08), in: RoundedRectangle(cornerRadius: 16))
            }

            Button(appSettings.text("profile.sign_out")) {
                showSignOutConfirm = true
            }
            .font(.headline.weight(.semibold))
            .foregroundStyle(.red)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 16)
            .background(Color(.systemBackground), in: RoundedRectangle(cornerRadius: 18))
        }
    }

    private var occasionPlannerCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .center) {
                Text(appSettings.text("profile.section.planner"))
                    .font(.title3.bold())
                Spacer()
                NavigationLink {
                    PlannerSettingsPage(
                        plannerOccasions: viewModel.catalogOccasions,
                        weekdayDefaultOccasion: $weekdayDefaultOccasion,
                        skipFederalHolidays: $skipFederalHolidays
                    )
                } label: {
                    Image(systemName: "pencil")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .frame(width: 32, height: 32)
                        .background(Color(.secondarySystemBackground), in: Circle())
                }
                .buttonStyle(.plain)
            }

            DatePicker(
                appSettings.text("profile.section.planner"),
                selection: $selectedPlanningDate,
                displayedComponents: .date
            )
            .datePickerStyle(.graphical)
            .labelsHidden()
            .tint(.blue)

            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(formattedSelectedDate)
                        .font(.headline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Picker(appSettings.text("recommendations.occasion"), selection: $selectedPlanningOccasion) {
                    ForEach(viewModel.catalogOccasions, id: \.self) { occasion in
                        Text(appSettings.option(occasion)).tag(occasion)
                    }
                }
                .pickerStyle(.menu)
                .labelsHidden()
                .onChange(of: selectedPlanningOccasion) { _, value in
                    saveOccasionPlan(occasion: value)
                }
            }
        }
        .padding(18)
        .background(Color(.systemBackground), in: RoundedRectangle(cornerRadius: 22))
    }

    private var basicProfileSummary: String {
        let year = viewModel.birthYear.map(String.init) ?? appSettings.text("common.not_set_birth_year")
        return "\(displayNickname) · \(year) · \(appSettings.option(viewModel.genderIdentity))"
    }

    private var stylePreferenceSummary: String {
        viewModel.dailyOccasions.prefix(2).map { occasion in
            let styles = (viewModel.occasionStylePreferences[occasion] ?? []).prefix(2).map(appSettings.option).joined(separator: ", ")
            return "\(appSettings.option(occasion)): \(styles)"
        }.joined(separator: " · ")
    }

    private func saveProfile() async {
        await viewModel.save(token: await authStore.validAccessToken(), onboardingCompleted: true)
    }

    private var formattedSelectedDate: String {
        Self.planDateFormatter.string(from: selectedPlanningDate)
    }

    private var savedOccasionTitle: String {
        if let saved = occasionPlans[Self.planKey(from: selectedPlanningDate)] {
            return appSettings.option(saved)
        }
        if let autoAssigned = automaticOccasion(for: selectedPlanningDate) {
            return appSettings.option(autoAssigned)
        }
        return appSettings.text("common.no_saved_occasion")
    }

    private var displayNickname: String {
        viewModel.nickname == "Closet user" ? appSettings.text("profile.default_nickname") : viewModel.nickname
    }

    private var occasionPlans: [String: String] {
        guard let data = storedOccasionPlans.data(using: .utf8),
              let decoded = try? JSONDecoder().decode([String: String].self, from: data) else {
            return [:]
        }
        return decoded
    }

    private func saveOccasionPlan(occasion: String) {
        var nextPlans = occasionPlans
        nextPlans[Self.planKey(from: selectedPlanningDate)] = occasion
        if let data = try? JSONEncoder().encode(nextPlans),
           let json = String(data: data, encoding: .utf8) {
            storedOccasionPlans = json
        }
    }

    private func syncPlanningOccasion() {
        if let saved = occasionPlans[Self.planKey(from: selectedPlanningDate)] {
            selectedPlanningOccasion = saved
            return
        }
        selectedPlanningOccasion = automaticOccasion(for: selectedPlanningDate) ?? "Everyday"
    }

    private func automaticOccasion(for date: Date) -> String? {
        let calendar = Calendar.current
        if calendar.isDateInWeekend(date) {
            return nil
        }
        if skipFederalHolidays && Self.isObservedUSFederalHoliday(date, calendar: calendar) {
            return nil
        }
        return weekdayDefaultOccasion
    }

    private func profileRow(title: String, subtitle: String) -> some View {
        HStack(spacing: 14) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.headline)
                    .foregroundStyle(.primary)
                Text(subtitle)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            Spacer()
            Image(systemName: "pencil")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
                .frame(width: 32, height: 32)
                .background(Color(.secondarySystemBackground), in: Circle())
        }
        .padding(18)
        .background(Color(.systemBackground), in: RoundedRectangle(cornerRadius: 18))
    }

    private static let planDateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        return formatter
    }()

    private static func planKey(from date: Date) -> String {
        let components = Calendar.current.dateComponents([.year, .month, .day], from: date)
        let year = components.year ?? 0
        let month = components.month ?? 0
        let day = components.day ?? 0
        return String(format: "%04d-%02d-%02d", year, month, day)
    }

    private static func isObservedUSFederalHoliday(_ date: Date, calendar: Calendar) -> Bool {
        let year = calendar.component(.year, from: date)
        let month = calendar.component(.month, from: date)
        let day = calendar.component(.day, from: date)

        let fixedHolidays = [
            observedDate(year: year, month: 1, day: 1, calendar: calendar),
            nthWeekday(year: year, month: 1, weekday: 2, occurrence: 3, calendar: calendar),
            nthWeekday(year: year, month: 2, weekday: 2, occurrence: 3, calendar: calendar),
            lastWeekday(year: year, month: 5, weekday: 2, calendar: calendar),
            observedDate(year: year, month: 6, day: 19, calendar: calendar),
            observedDate(year: year, month: 7, day: 4, calendar: calendar),
            nthWeekday(year: year, month: 9, weekday: 2, occurrence: 1, calendar: calendar),
            nthWeekday(year: year, month: 10, weekday: 2, occurrence: 2, calendar: calendar),
            observedDate(year: year, month: 11, day: 11, calendar: calendar),
            nthWeekday(year: year, month: 11, weekday: 5, occurrence: 4, calendar: calendar),
            observedDate(year: year, month: 12, day: 25, calendar: calendar)
        ]
        .compactMap { $0 }

        return fixedHolidays.contains {
            calendar.component(.year, from: $0) == year &&
            calendar.component(.month, from: $0) == month &&
            calendar.component(.day, from: $0) == day
        }
    }

    private static func observedDate(year: Int, month: Int, day: Int, calendar: Calendar) -> Date? {
        guard let raw = calendar.date(from: DateComponents(year: year, month: month, day: day)) else {
            return nil
        }
        switch calendar.component(.weekday, from: raw) {
        case 7:
            return calendar.date(byAdding: .day, value: -1, to: raw)
        case 1:
            return calendar.date(byAdding: .day, value: 1, to: raw)
        default:
            return raw
        }
    }

    private static func nthWeekday(year: Int, month: Int, weekday: Int, occurrence: Int, calendar: Calendar) -> Date? {
        guard let firstOfMonth = calendar.date(from: DateComponents(year: year, month: month, day: 1)) else {
            return nil
        }
        let firstWeekday = calendar.component(.weekday, from: firstOfMonth)
        let delta = (weekday - firstWeekday + 7) % 7
        let day = 1 + delta + (occurrence - 1) * 7
        return calendar.date(from: DateComponents(year: year, month: month, day: day))
    }

    private static func lastWeekday(year: Int, month: Int, weekday: Int, calendar: Calendar) -> Date? {
        guard let range = calendar.range(of: .day, in: .month, for: calendar.date(from: DateComponents(year: year, month: month, day: 1)) ?? Date()) else {
            return nil
        }
        let lastDay = range.count
        guard let lastOfMonth = calendar.date(from: DateComponents(year: year, month: month, day: lastDay)) else {
            return nil
        }
        let lastWeekday = calendar.component(.weekday, from: lastOfMonth)
        let delta = (lastWeekday - weekday + 7) % 7
        return calendar.date(byAdding: .day, value: -delta, to: lastOfMonth)
    }
}
