import SwiftUI

struct ChatBoxView: View {
    @EnvironmentObject private var authStore: AuthStore
    @StateObject private var viewModel = ChatViewModel()
    private let embedsInExistingNavigation: Bool

    init(embedsInExistingNavigation: Bool = false) {
        self.embedsInExistingNavigation = embedsInExistingNavigation
    }

    var body: some View {
        Group {
            if embedsInExistingNavigation {
                chatContent
                    .navigationTitle("Agent Chat")
            } else {
                NavigationStack {
                    chatContent
                        .navigationTitle("Agent Chat")
                }
            }
        }
    }

    private var chatContent: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 12) {
                        if viewModel.messages.isEmpty {
                            examplePromptCard
                        }
                        ForEach(viewModel.messages) { message in
                            ChatBubble(message: message)
                                .id(message.id)
                        }
                        if viewModel.isSending {
                            HStack {
                                ProgressView()
                                Text("Thinking")
                                    .foregroundStyle(.secondary)
                                Spacer()
                            }
                            .padding(.horizontal)
                        }
                    }
                    .padding(16)
                }
                .onChange(of: viewModel.messages) { _, messages in
                    if let last = messages.last {
                        withAnimation {
                            proxy.scrollTo(last.id, anchor: .bottom)
                        }
                    }
                }
            }

            if let errorMessage = viewModel.errorMessage {
                Text(errorMessage)
                    .font(.footnote.weight(.medium))
                    .foregroundStyle(.red)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal)
            }

            HStack(spacing: 10) {
                TextField("Ask your closet agent", text: $viewModel.draft, axis: .vertical)
                    .lineLimit(1...4)
                    .textFieldStyle(.roundedBorder)
                Button {
                    Task { await viewModel.send(token: await authStore.validAccessToken()) }
                } label: {
                    Image(systemName: "arrow.up")
                        .font(.headline.bold())
                }
                .buttonStyle(.borderedProminent)
                .disabled(viewModel.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isSending)
            }
            .padding(16)
            .background(.bar)
        }
    }

    private var examplePromptCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Try asking")
                .font(.caption.weight(.bold))
                .textCase(.uppercase)
                .foregroundStyle(.secondary)
            Button {
                viewModel.draft = ChatViewModel.samplePrompt
            } label: {
                Text(ChatViewModel.samplePrompt)
                    .font(.subheadline)
                    .foregroundStyle(.primary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(14)
                    .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
            }
            .buttonStyle(.plain)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct ChatBubble: View {
    let message: ChatMessage

    var body: some View {
        HStack(alignment: .top) {
            if message.role == .user { Spacer(minLength: 42) }
            VStack(alignment: .leading, spacing: 12) {
                Text(message.text)
                    .padding(12)
                    .background(message.role == .user ? Color.blue : Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
                    .foregroundStyle(message.role == .user ? .white : .primary)

                if !message.recommendations.isEmpty {
                    ChatRecommendationList(recommendations: message.recommendations)
                }
            }
            .frame(maxWidth: 320, alignment: message.role == .user ? .trailing : .leading)
            if message.role == .assistant { Spacer(minLength: 42) }
        }
    }
}

private struct ChatRecommendationList: View {
    let recommendations: [OutfitRecommendationDTO]

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(Array(recommendations.enumerated()), id: \.element.id) { index, recommendation in
                VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        Text("Look \(index + 1)")
                            .font(.caption.weight(.bold))
                            .textCase(.uppercase)
                            .foregroundStyle(.blue)
                        Spacer()
                        Text("\(Int(recommendation.score.rounded()))")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary)
                    }

                    Text(recommendation.title)
                        .font(.headline)

                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 10) {
                            ForEach(recommendation.items) { item in
                                VStack(alignment: .leading, spacing: 6) {
                                    ClosetAsyncImage(url: item.imageUrl)
                                        .frame(width: 108, height: 132)
                                        .clipShape(RoundedRectangle(cornerRadius: 14))
                                    Text(item.displayTitle)
                                        .font(.caption.weight(.semibold))
                                        .lineLimit(2)
                                }
                                .frame(width: 108, alignment: .leading)
                            }
                        }
                    }
                }
                .padding(12)
                .background(Color(.systemBackground), in: RoundedRectangle(cornerRadius: 16))
                .overlay {
                    RoundedRectangle(cornerRadius: 16)
                        .stroke(Color(.separator).opacity(0.22))
                }
            }
        }
    }
}
