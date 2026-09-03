import SwiftUI

struct RecommendationsView: View {
    @EnvironmentObject private var authStore: AuthStore
    @EnvironmentObject private var appSettings: AppSettings
    @StateObject private var viewModel = RecommendationViewModel()
    @State private var showingChat = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    controls
                    results
                }
                .padding(16)
            }
            .navigationTitle(appSettings.text("recommendations.title"))
            .overlay(alignment: .bottomTrailing) {
                floatingChatButton
            }
            .navigationDestination(isPresented: $showingChat) {
                ChatBoxView(embedsInExistingNavigation: true)
            }
            .task {
                let token = await authStore.validAccessToken()
                await viewModel.loadTaxonomy(token: token)
                await viewModel.generate(token: token)
            }
        }
    }

    private var controls: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 6) {
                Text(appSettings.text("recommendations.occasion"))
                    .font(.caption.weight(.bold))
                    .textCase(.uppercase)
                    .foregroundStyle(.secondary)
                optionMenu(
                    title: appSettings.option(viewModel.selectedOccasion)
                ) {
                    ForEach(ClosetSelectionSupport.plannerOccasions, id: \.self) { occasion in
                        Button {
                            viewModel.selectedOccasion = occasion
                        } label: {
                            HStack {
                                Text(appSettings.option(occasion))
                                if viewModel.selectedOccasion == occasion {
                                    Spacer()
                                    Image(systemName: "checkmark")
                                }
                            }
                        }
                    }
                }
            }

            VStack(alignment: .leading, spacing: 6) {
                Text(appSettings.text("recommendations.style"))
                    .font(.caption.weight(.bold))
                    .textCase(.uppercase)
                    .foregroundStyle(.secondary)
                optionMenu(
                    title: viewModel.selectedStyle == "Any" ? appSettings.text("common.any") : appSettings.option(viewModel.selectedStyle)
                ) {
                    ForEach(["Any"] + viewModel.taxonomy.styles, id: \.self) { style in
                        Button {
                            viewModel.selectedStyle = style
                        } label: {
                            HStack {
                                Text(style == "Any" ? appSettings.text("common.any") : appSettings.option(style))
                                if viewModel.selectedStyle == style {
                                    Spacer()
                                    Image(systemName: "checkmark")
                                }
                            }
                        }
                    }
                }
            }

            VStack(alignment: .leading, spacing: 6) {
                Text(appSettings.text("recommendations.color"))
                    .font(.caption.weight(.bold))
                    .textCase(.uppercase)
                    .foregroundStyle(.secondary)
                colorMenu
            }

            VStack(alignment: .leading) {
                Text(appSettings.text("recommendations.temperature", appSettings.displayedTemperature(fahrenheit: viewModel.temperatureF)))
                    .font(.headline)
                Slider(value: $viewModel.temperatureF, in: 30...105, step: 1)
            }

            Button {
                Task { await viewModel.generate(token: await authStore.validAccessToken()) }
            } label: {
                if viewModel.isLoading {
                    ProgressView()
                        .tint(.white)
                        .frame(maxWidth: .infinity)
                } else {
                    Label(appSettings.text("recommendations.generate"), systemImage: "sparkles")
                        .frame(maxWidth: .infinity)
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(viewModel.isLoading)

            if let errorMessage = viewModel.errorMessage {
                Text(errorMessage)
                    .font(.footnote.weight(.medium))
                    .foregroundStyle(.red)
            }
        }
        .padding(18)
        .background(Color(.systemBackground), in: RoundedRectangle(cornerRadius: 22))
    }

    private var colorMenu: some View {
        optionMenu(
            title: viewModel.selectedColor == "Any" ? appSettings.text("common.any") : appSettings.option(viewModel.selectedColor),
            leading: {
                if viewModel.selectedColor != "Any" {
                    ColorSwatchCircle(colorName: viewModel.selectedColor)
                }
            }
        ) {
            Button {
                viewModel.selectedColor = "Any"
            } label: {
                HStack {
                    Text(appSettings.text("common.any"))
                    if viewModel.selectedColor == "Any" {
                        Spacer()
                        Image(systemName: "checkmark")
                    }
                }
            }

            ForEach(viewModel.taxonomy.colors, id: \.self) { color in
                Button {
                    viewModel.selectedColor = color
                } label: {
                    Label {
                        Text(appSettings.option(color))
                    } icon: {
                        ColorSwatchCircle(colorName: color)
                    }
                    .overlay(alignment: .trailing) {
                        if viewModel.selectedColor == color {
                            Image(systemName: "checkmark")
                        }
                    }
                }
            }
        }
    }

    private func optionMenu<MenuContent: View, Leading: View>(
        title: String,
        @ViewBuilder leading: () -> Leading = { EmptyView() },
        @ViewBuilder content: () -> MenuContent
    ) -> some View {
        Menu {
            content()
        } label: {
            HStack(spacing: 8) {
                leading()
                Text(title)
                    .lineLimit(1)
                Spacer(minLength: 0)
                Image(systemName: "chevron.up.chevron.down")
                    .font(.caption.weight(.semibold))
            }
            .foregroundStyle(.blue)
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 12))
        }
    }

    @ViewBuilder
    private var results: some View {
        if let active = viewModel.activeRecommendation {
            APIOutfitRecommendationCard(
                recommendation: active,
                index: viewModel.activeIndex,
                total: viewModel.recommendations.count,
                onPrevious: { viewModel.move(-1, count: viewModel.recommendations.count) },
                onNext: { viewModel.move(1, count: viewModel.recommendations.count) }
            )
            .id(active.id)
            .transition(.asymmetric(insertion: .move(edge: .trailing).combined(with: .opacity), removal: .move(edge: .leading).combined(with: .opacity)))
        } else if viewModel.isLoading {
            ProgressView(appSettings.text("recommendations.loading"))
                .frame(maxWidth: .infinity, minHeight: 260)
        } else {
            ContentUnavailableView(appSettings.text("recommendations.no_matches"), systemImage: "sparkles", description: Text(appSettings.text("recommendations.no_matches_desc")))
        }
    }

    private var floatingChatButton: some View {
        Button {
            showingChat = true
        } label: {
            Image(systemName: "message.fill")
                .font(.headline.weight(.semibold))
                .foregroundStyle(.primary)
                .frame(width: 56, height: 56)
                .background(.ultraThinMaterial, in: Circle())
                .overlay {
                    Circle()
                        .stroke(Color.white.opacity(0.6), lineWidth: 1)
                }
                .shadow(color: .black.opacity(0.12), radius: 18, x: 0, y: 10)
        }
        .padding(.trailing, 20)
        .padding(.bottom, 28)
        .accessibilityLabel(appSettings.text("recommendations.chat_open"))
    }
}
