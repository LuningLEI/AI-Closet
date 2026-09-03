import Foundation

enum AppConfiguration {
    static let backendBaseURL = URL(string: "http://127.0.0.1:8000")!
    static let defaultSupabaseURL = URL(string: "https://hhwebmfsrcwcblaxnpdh.supabase.co")
    static let defaultSupabaseAnonKey = "sb_publishable_EpIWwWSRvI9jyovGvkwX5g_tQkde9Ki"

    static var supabaseURL: URL? {
        configuredURL(for: "SUPABASE_URL") ?? defaultSupabaseURL
    }

    static var supabaseAnonKey: String? {
        configuredString(for: "SUPABASE_ANON_KEY") ?? defaultSupabaseAnonKey
    }

    static var isSupabaseConfigured: Bool {
        supabaseURL != nil && supabaseAnonKey != nil
    }

    private static func configuredString(for key: String) -> String? {
        guard let value = Bundle.main.object(forInfoDictionaryKey: key) as? String else {
            return nil
        }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty || trimmed.hasPrefix("YOUR_") ? nil : trimmed
    }

    private static func configuredURL(for key: String) -> URL? {
        guard let value = configuredString(for: key) else { return nil }
        return URL(string: value)
    }
}
