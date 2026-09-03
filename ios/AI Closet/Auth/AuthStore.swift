import Foundation
import Combine

struct AuthUser: Codable, Equatable {
    let id: String
    let email: String?
}

struct AuthSession: Codable, Equatable {
    let accessToken: String
    let refreshToken: String?
    let expiresAt: Date?
    let user: AuthUser
}

@MainActor
final class AuthStore: ObservableObject {
    @Published private(set) var session: AuthSession?
    @Published private(set) var isLoading = false
    @Published var errorMessage: String?

    private let storageKey = "aiCloset.authSession"
    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()

    var isAuthenticated: Bool {
        session != nil
    }

    var accessToken: String? {
        session?.accessToken
    }

    init() {
        restoreSession()
    }

    func signIn(email: String, password: String) async {
        await authenticate(path: "/auth/v1/token?grant_type=password", email: email, password: password)
    }

    func signUp(email: String, password: String) async {
        await authenticate(path: "/auth/v1/signup", email: email, password: password)
    }

    func signOut() {
        session = nil
        UserDefaults.standard.removeObject(forKey: storageKey)
    }

    func refreshStoredSessionIfNeeded() async {
        _ = await validAccessToken()
    }

    func validAccessToken() async -> String? {
        guard let currentSession = session else { return nil }
        guard Self.isExpired(accessToken: currentSession.accessToken, expiresAt: currentSession.expiresAt) else {
            return currentSession.accessToken
        }
        return await refreshSession() ? session?.accessToken : nil
    }

    private func restoreSession() {
        guard let data = UserDefaults.standard.data(forKey: storageKey),
              let restored = try? decoder.decode(AuthSession.self, from: data) else {
            return
        }
        session = restored
    }

    private func persistSession(_ nextSession: AuthSession) {
        session = nextSession
        if let data = try? encoder.encode(nextSession) {
            UserDefaults.standard.set(data, forKey: storageKey)
        }
    }

    private func authenticate(path: String, email: String, password: String) async {
        guard let supabaseURL = AppConfiguration.supabaseURL,
              let anonKey = AppConfiguration.supabaseAnonKey else {
            errorMessage = "Supabase Auth is not configured."
            return
        }

        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            var request = URLRequest(url: supabaseURL.appendingPathComponent(path))
            if path.contains("?") {
                request = URLRequest(url: URL(string: supabaseURL.absoluteString + path)!)
            }
            request.httpMethod = "POST"
            request.setValue(anonKey, forHTTPHeaderField: "apikey")
            request.setValue("Bearer \(anonKey)", forHTTPHeaderField: "Authorization")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(AuthRequest(email: email, password: password))

            let (data, response) = try await Self.send(request)
            guard let httpResponse = response as? HTTPURLResponse else {
                throw APIError.invalidResponse
            }
            guard (200..<300).contains(httpResponse.statusCode) else {
                throw APIError.server(String(data: data, encoding: .utf8) ?? "Authentication failed.")
            }

            let authResponse = try decoder.decode(AuthResponse.self, from: data)
            guard let accessToken = authResponse.accessToken else {
                errorMessage = "Account created. Please sign in after email confirmation."
                return
            }
            persistSession(
                AuthSession(
                    accessToken: accessToken,
                    refreshToken: authResponse.refreshToken,
                    expiresAt: Self.resolvedExpiration(from: authResponse),
                    user: AuthUser(id: authResponse.user.id, email: authResponse.user.email)
                )
            )
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func refreshSession() async -> Bool {
        guard let currentSession = session,
              let refreshToken = currentSession.refreshToken,
              let supabaseURL = AppConfiguration.supabaseURL,
              let anonKey = AppConfiguration.supabaseAnonKey,
              let url = URL(string: supabaseURL.absoluteString + "/auth/v1/token?grant_type=refresh_token") else {
            signOut()
            errorMessage = "Session expired. Please sign in again."
            return false
        }

        do {
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue(anonKey, forHTTPHeaderField: "apikey")
            request.setValue("Bearer \(anonKey)", forHTTPHeaderField: "Authorization")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let body = try JSONEncoder().encode(RefreshRequest(refreshToken: refreshToken))
            request.setValue(String(body.count), forHTTPHeaderField: "Content-Length")
            request.httpBody = body

            let (data, response) = try await Self.send(request)
            guard let httpResponse = response as? HTTPURLResponse else {
                throw APIError.invalidResponse
            }
            guard (200..<300).contains(httpResponse.statusCode) else {
                throw APIError.server(String(data: data, encoding: .utf8) ?? "Session refresh failed.")
            }

            let authResponse = try decoder.decode(AuthResponse.self, from: data)
            guard let accessToken = authResponse.accessToken else {
                throw APIError.server("Session refresh did not return an access token.")
            }
            persistSession(
                AuthSession(
                    accessToken: accessToken,
                    refreshToken: authResponse.refreshToken ?? refreshToken,
                    expiresAt: Self.resolvedExpiration(from: authResponse),
                    user: AuthUser(id: authResponse.user.id, email: authResponse.user.email)
                )
            )
            return true
        } catch {
            signOut()
            errorMessage = "Session expired. Please sign in again."
            return false
        }
    }

    private static func resolvedExpiration(from response: AuthResponse) -> Date? {
        if let expiresAt = response.expiresAt {
            return Date(timeIntervalSince1970: TimeInterval(expiresAt))
        }
        if let expiresIn = response.expiresIn {
            return Date().addingTimeInterval(TimeInterval(expiresIn))
        }
        guard let accessToken = response.accessToken else { return nil }
        return jwtExpiration(accessToken)
    }

    private static func isExpired(accessToken: String, expiresAt: Date?) -> Bool {
        let refreshWindow = Date().addingTimeInterval(60)
        if let expiresAt {
            return expiresAt <= refreshWindow
        }
        guard let jwtExpiration = jwtExpiration(accessToken) else {
            return false
        }
        return jwtExpiration <= refreshWindow
    }

    private static func jwtExpiration(_ token: String) -> Date? {
        let parts = token.split(separator: ".")
        guard parts.count >= 2 else { return nil }
        var payload = String(parts[1])
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        let padding = payload.count % 4
        if padding > 0 {
            payload += String(repeating: "=", count: 4 - padding)
        }
        guard let data = Data(base64Encoded: payload),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let exp = json["exp"] as? Double else {
            return nil
        }
        return Date(timeIntervalSince1970: exp)
    }

    private static func send(_ request: URLRequest) async throws -> (Data, URLResponse) {
        try await withCheckedThrowingContinuation { continuation in
            let task = URLSession.shared.dataTask(with: request) { data, response, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }
                guard let response else {
                    continuation.resume(throwing: APIError.invalidResponse)
                    return
                }
                continuation.resume(returning: (data ?? Data(), response))
            }
            task.resume()
        }
    }
}

private struct AuthRequest: Encodable {
    let email: String
    let password: String
}

private struct RefreshRequest: Encodable {
    let refreshToken: String

    enum CodingKeys: String, CodingKey {
        case refreshToken = "refresh_token"
    }
}

private struct AuthResponse: Decodable {
    let accessToken: String?
    let refreshToken: String?
    let expiresIn: Int?
    let expiresAt: Int?
    let user: SupabaseUser

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
        case expiresIn = "expires_in"
        case expiresAt = "expires_at"
        case user
    }
}

private struct SupabaseUser: Decodable {
    let id: String
    let email: String?
}
