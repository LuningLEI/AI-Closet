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
                        plannerOccasions: ClosetSelectionSupport.plannerOccasions,
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
                    ForEach(ClosetSelectionSupport.plannerOccasions, id: \.self) { occasion in
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
        let occasions = viewModel.dailyOccasions.prefix(2).map(appSettings.option).joined(separator: ", ")
        let styles = viewModel.stylePreferences.prefix(2).map(appSettings.option).joined(separator: ", ")
        return [occasions, styles].filter { !$0.isEmpty }.joined(separator: " · ")
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

private struct ProfileEditorPage<Content: View>: View {
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

private struct PlannerSettingsPage: View {
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

private struct BasicProfileEditor: View {
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

private struct PreferenceEditor: View {
    @EnvironmentObject private var appSettings: AppSettings
    @ObservedObject var viewModel: ProfileViewModel

    private let occasions = ["Everyday", "Work", "School", "Date", "Party", "Travel", "Formal", "Workout"]
    private let styles = ["Casual", "Elegant", "Streetwear", "Minimal", "Romantic", "Classic", "Sporty", "Business"]

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            OptionGrid(title: appSettings.text("profile.edit.daily_occasions"), options: occasions, selection: $viewModel.dailyOccasions)
            OptionGrid(title: appSettings.text("profile.edit.preferred_styles"), options: styles, selection: $viewModel.stylePreferences)
        }
    }
}

private struct CategoryEditor: View {
    @EnvironmentObject private var appSettings: AppSettings
    @ObservedObject var viewModel: ProfileViewModel
    @State private var customTag = ""

    private let categories = ["Tops", "Bottoms", "Dresses", "Jumpsuits", "Sets", "Outerwear", "Shoes", "Bags", "Accessories", "Activewear", "Swimwear", "Intimates", "Uncategorized"]

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            OptionGrid(title: appSettings.text("profile.edit.recognition_categories"), options: categories, selection: $viewModel.selectedCategories)

            HStack {
                TextField(appSettings.text("profile.edit.custom_tag"), text: $customTag)
                    .textFieldStyle(.roundedBorder)
                Button(appSettings.text("common.add")) {
                    let tag = customTag.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !tag.isEmpty, !viewModel.customCategories.contains(tag) else { return }
                    viewModel.customCategories.append(tag)
                    viewModel.selectedCategories.append(tag)
                    customTag = ""
                }
            }

            if !viewModel.customCategories.isEmpty {
                OptionGrid(title: appSettings.text("profile.edit.custom_tags"), options: viewModel.customCategories, selection: $viewModel.selectedCategories)
            }
        }
    }
}

private struct FinalProfileStep: View {
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

private struct OptionGrid: View {
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

private struct SystemSettingsPage: View {
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

private struct FlowLayout<Content: View>: View {
    let spacing: CGFloat
    @ViewBuilder let content: Content

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 100), spacing: spacing)], alignment: .leading, spacing: spacing) {
            content
        }
    }
}

private struct AvatarImage: View {
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

private struct AvatarPreview: View {
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
