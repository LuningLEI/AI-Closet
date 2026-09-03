import Foundation

enum ImageURLResolver {
    static func resolve(_ rawValue: String) -> URL? {
        let trimmed = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }

        if let absoluteURL = URL(string: trimmed), absoluteURL.scheme != nil {
            return absoluteURL
        }

        if trimmed.hasPrefix("/") {
            return URL(string: trimmed, relativeTo: AppConfiguration.backendBaseURL)?.absoluteURL
        }

        if trimmed.hasPrefix("uploads/") {
            return URL(string: "/" + trimmed, relativeTo: AppConfiguration.backendBaseURL)?.absoluteURL
        }

        if trimmed.hasPrefix("storage/v1/"), let supabaseURL = AppConfiguration.supabaseURL {
            return URL(string: trimmed, relativeTo: supabaseURL)?.absoluteURL
        }

        return nil
    }
}
