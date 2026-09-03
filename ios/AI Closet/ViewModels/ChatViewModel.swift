import Foundation
import Combine

struct ChatMessage: Identifiable, Equatable {
    let id = UUID()
    let role: ChatRole
    let text: String
    let recommendations: [OutfitRecommendationDTO]
}

enum ChatRole {
    case user
    case assistant
}

@MainActor
final class ChatViewModel: ObservableObject {
    static let samplePrompt = "我要去迈阿密度假五天，帮我搭配五套衣服"

    @Published var messages: [ChatMessage] = []
    @Published var draft = ""
    @Published var isSending = false
    @Published var errorMessage: String?

    private let apiClient = APIClient.shared

    func send(token: String?) async {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }

        draft = ""
        errorMessage = nil
        isSending = true
        messages.append(ChatMessage(role: .user, text: text, recommendations: []))
        defer { isSending = false }

        do {
            let response: ChatResponseDTO = try await apiClient.post("/api/v1/chat", token: token, body: ChatRequestDTO(message: text))
            messages.append(
                ChatMessage(
                    role: .assistant,
                    text: response.reply,
                    recommendations: response.metadata?.recommendations ?? []
                )
            )
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
