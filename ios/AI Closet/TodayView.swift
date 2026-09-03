import SwiftUI

struct TodayView: View {
    @EnvironmentObject private var authStore: AuthStore
    @EnvironmentObject private var appSettings: AppSettings
    @StateObject private var viewModel = RecommendationViewModel()
    @FocusState private var cityFieldFocused: Bool
    @State private var selectedTodayOccasion = "Everyday"
    @State private var isEditingCity = false
    @AppStorage("profile.occasions.plans") private var storedOccasionPlans = ""
    @AppStorage("profile.occasions.weekdayDefault") private var weekdayDefaultOccasion = "Work"
    @AppStorage("profile.occasions.skipFederalHolidays") private var skipFederalHolidays = true

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    header
                    weatherCard
                    recommendationSection
                }
                .padding(16)
            }
            .navigationTitle(appSettings.text("tab.today"))
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        Task { await viewModel.submitCityQuery(token: await authStore.validAccessToken()) }
                    } label: {
                        if viewModel.isRefreshingToday {
                            ProgressView()
                        } else {
                            Image(systemName: "arrow.clockwise")
                        }
                    }
                    .disabled(viewModel.isRefreshingToday)
                }
            }
            .refreshable {
                await viewModel.submitCityQuery(token: await authStore.validAccessToken())
            }
            .task {
                await viewModel.bootstrapToday(token: await authStore.validAccessToken())
                syncTodayOccasion()
            }
            .onAppear {
                syncTodayOccasion()
            }
        }
    }

    private var header: some View {
        EmptyView()
    }

    private var weatherCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let weather = viewModel.todayWeather, let location = viewModel.todayLocation {
                HStack(alignment: .lastTextBaseline, spacing: 10) {
                    Text(appSettings.displayedTemperature(fahrenheit: weather.temperatureF))
                        .font(.title.bold())

                    Text(location.label)
                        .font(.title3.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.7)
                }

                Text(weather.condition)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)

                VStack(alignment: .leading, spacing: 10) {
                    if isEditingCity {
                        HStack(spacing: 10) {
                            TextField(appSettings.text("today.city_placeholder"), text: $viewModel.cityQuery)
                                .textInputAutocapitalization(.words)
                                .autocorrectionDisabled()
                                .submitLabel(.search)
                                .focused($cityFieldFocused)
                                .onSubmit {
                                    Task {
                                        cityFieldFocused = false
                                        await viewModel.submitCityQuery(token: await authStore.validAccessToken())
                                        isEditingCity = false
                                    }
                                }

                            Button(appSettings.text("today.update")) {
                                Task {
                                    cityFieldFocused = false
                                    await viewModel.submitCityQuery(token: await authStore.validAccessToken())
                                    isEditingCity = false
                                }
                            }
                            .font(.subheadline.weight(.semibold))
                            .disabled(viewModel.cityQuery.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isRefreshingToday)
                        }
                        .padding(.horizontal, 14)
                        .padding(.vertical, 12)
                        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))

                        if cityFieldFocused || (viewModel.todayLocation == nil && !viewModel.citySuggestions.isEmpty) {
                            citySuggestions
                        }
                    } else {
                        Button {
                            isEditingCity = true
                            cityFieldFocused = true
                        } label: {
                            HStack(spacing: 10) {
                                Text(appSettings.text("today.city_placeholder"))
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                                Spacer()
                                Image(systemName: "pencil")
                                    .font(.subheadline.weight(.semibold))
                                    .foregroundStyle(.blue)
                            }
                            .padding(.horizontal, 14)
                            .padding(.vertical, 12)
                            .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
                        }
                        .buttonStyle(.plain)
                    }
                }

                todayOccasionRow
            } else if viewModel.isLoadingTodayWeather {
                ProgressView(appSettings.text("today.loading_weather"))
                    .frame(maxWidth: .infinity, minHeight: 160)
            } else {
                Text(appSettings.text("today.weather_unavailable"))
                    .font(.headline)
            }

            if let errorMessage = viewModel.todayWeatherErrorMessage {
                Text(appSettings.resolvedText(errorMessage))
                    .font(.footnote.weight(.medium))
                    .foregroundStyle(.red)
            }
        }
        .padding(18)
        .background(Color(.systemBackground), in: RoundedRectangle(cornerRadius: 22))
    }

    private var citySuggestions: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(viewModel.citySuggestions, id: \.self) { suggestion in
                    Button {
                        viewModel.applyCitySuggestion(suggestion)
                        Task {
                            cityFieldFocused = false
                            await viewModel.submitCityQuery(token: await authStore.validAccessToken())
                        }
                    } label: {
                        Text(suggestion)
                            .font(.subheadline)
                            .foregroundStyle(.blue)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 8)
                            .background(Color.blue.opacity(0.08), in: Capsule())
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private var todayOccasionRow: some View {
        HStack(spacing: 8) {
            Text(appSettings.text("today.occasion"))
                .font(.caption.weight(.bold))
                .textCase(.uppercase)
                .foregroundStyle(.secondary)
            Picker(appSettings.text("today.occasion"), selection: $selectedTodayOccasion) {
                ForEach(ClosetSelectionSupport.plannerOccasions, id: \.self) { occasion in
                    Text(appSettings.option(occasion)).tag(occasion)
                }
            }
            .pickerStyle(.menu)
            .labelsHidden()
            .tint(.primary)
            .onChange(of: selectedTodayOccasion) { _, value in
                saveTodayOccasion(value)
                Task {
                    await viewModel.refreshTodayRecommendations(
                        token: await authStore.validAccessToken(),
                        occasion: value
                    )
                }
            }
        }
    }

    private var todayOccasion: String {
        let today = Date()
        if let saved = occasionPlans[Self.planKey(from: today)] {
            return appSettings.option(saved)
        }
        return appSettings.option(automaticOccasion(for: today) ?? "Everyday")
    }

    private var occasionPlans: [String: String] {
        guard let data = storedOccasionPlans.data(using: .utf8),
              let decoded = try? JSONDecoder().decode([String: String].self, from: data) else {
            return [:]
        }
        return decoded
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

    private func saveTodayOccasion(_ occasion: String) {
        var nextPlans = occasionPlans
        nextPlans[Self.planKey(from: Date())] = occasion
        if let data = try? JSONEncoder().encode(nextPlans),
           let json = String(data: data, encoding: .utf8) {
            storedOccasionPlans = json
        }
    }

    private func syncTodayOccasion() {
        let today = Date()
        if let saved = occasionPlans[Self.planKey(from: today)] {
            selectedTodayOccasion = saved
            return
        }
        selectedTodayOccasion = automaticOccasion(for: today) ?? "Everyday"
    }

    @ViewBuilder
    private var recommendationSection: some View {
        let recommendations = viewModel.todayRecommendations
        if let active = viewModel.activeTodayRecommendation {
            APIOutfitRecommendationCard(
                recommendation: active,
                index: viewModel.activeIndex,
                total: recommendations.count,
                onPrevious: { viewModel.move(-1, count: recommendations.count) },
                onNext: { viewModel.move(1, count: recommendations.count) }
            )
            .id(active.id)
            .transition(.asymmetric(insertion: .move(edge: .trailing).combined(with: .opacity), removal: .move(edge: .leading).combined(with: .opacity)))
        } else if viewModel.isLoadingTodayRecommendations {
            ProgressView(appSettings.text("today.loading_outfits"))
                .frame(maxWidth: .infinity, minHeight: 260)
        } else {
            ContentUnavailableView(
                viewModel.todayRecommendationErrorMessage == nil ? appSettings.text("today.no_recommendations") : appSettings.text("today.recommendations_unavailable"),
                systemImage: "sparkles",
                description: Text(viewModel.todayRecommendationErrorMessage.map(appSettings.resolvedText) ?? appSettings.text("today.recommendations_empty"))
            )
        }
    }

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
        guard let anchor = calendar.date(from: DateComponents(year: year, month: month, day: 1)),
              let range = calendar.range(of: .day, in: .month, for: anchor) else {
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
