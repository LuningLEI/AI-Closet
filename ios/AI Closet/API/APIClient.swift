import Foundation
import UIKit

enum APIError: LocalizedError {
    case missingSession
    case invalidResponse
    case server(String)

    var errorDescription: String? {
        switch self {
        case .missingSession:
            return "Please sign in first."
        case .invalidResponse:
            return "The server returned an invalid response."
        case .server(let message):
            return message
        }
    }
}

final class APIClient {
    static let shared = APIClient()

    private enum Timeout {
        static let request: TimeInterval = 60
        static let uploadRequest: TimeInterval = 180
        static let uploadResource: TimeInterval = 300
    }

    private let baseURL: URL
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    init(baseURL: URL = AppConfiguration.backendBaseURL, session: URLSession? = nil) {
        self.baseURL = baseURL
        if let session {
            self.session = session
        } else {
            let configuration = URLSessionConfiguration.default
            configuration.timeoutIntervalForRequest = Timeout.request
            configuration.timeoutIntervalForResource = Timeout.uploadResource
            self.session = URLSession(configuration: configuration)
        }
        decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
    }

    func get<T: Decodable>(_ path: String, token: String?, queryItems: [URLQueryItem] = []) async throws -> T {
        let request = try makeRequest(path, method: "GET", token: token, queryItems: queryItems)
        return try await perform(request)
    }

    func post<Body: Encodable, T: Decodable>(_ path: String, token: String?, body: Body) async throws -> T {
        try await requestWithBody(path, method: "POST", token: token, body: body)
    }

    func patch<Body: Encodable, T: Decodable>(_ path: String, token: String?, body: Body) async throws -> T {
        try await requestWithBody(path, method: "PATCH", token: token, body: body)
    }

    func delete(_ path: String, token: String?) async throws {
        let request = try makeRequest(path, method: "DELETE", token: token)
        try await performEmpty(request)
    }

    func uploadImages(_ images: [Data], token: String?) async throws -> BatchUploadResponseDTO {
        guard let token else { throw APIError.missingSession }
        let url = try makeURL("/api/v1/items/upload-batch")
        var request = URLRequest(url: url)
        let boundary = "Boundary-\(UUID().uuidString)"
        let body = multipartBody(images: images, fieldName: "files", boundary: boundary)
        request.httpMethod = "POST"
        request.timeoutInterval = Timeout.uploadRequest
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.setValue(String(body.count), forHTTPHeaderField: "Content-Length")
        request.httpBody = body
        return try await perform(request)
    }

    func uploadAvatar(_ image: Data, token: String?) async throws -> UserPreferencesDTO {
        try await uploadSingleImage("/api/v1/profile/avatar", image: image, token: token)
    }

    func replaceItemImage(_ image: Data, itemID: UUID, token: String?) async throws -> ClothingItemDTO {
        try await uploadSingleImage("/api/v1/items/\(itemID.uuidString)/image", image: image, token: token)
    }

    private static func tokenSummary(_ token: String?) -> String {
        guard let token else { return "nil" }
        return "len=\(token.count),prefix=\(String(token.prefix(16)))"
    }

    private func uploadSingleImage<T: Decodable>(_ path: String, image: Data, token: String?) async throws -> T {
        guard let token else { throw APIError.missingSession }
        guard !image.isEmpty else {
            print("[APIClient] uploadSingleImage blocked", "path=\(path)", "reason=empty_image_data")
            throw APIError.server("The edited photo is empty. Please try again.")
        }
        let url = try makeURL(path)
        var request = URLRequest(url: url)
        let boundary = "Boundary-\(UUID().uuidString)"
        let body = multipartBody(images: [image], fieldName: "file", boundary: boundary)
        request.httpMethod = "POST"
        request.timeoutInterval = Timeout.uploadRequest
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.setValue(String(body.count), forHTTPHeaderField: "Content-Length")
        request.httpBody = body
        print(
            "[APIClient] uploadSingleImage",
            "path=\(path)",
            "bytes=\(image.count)",
            "token=\(Self.tokenSummary(token))"
        )
        return try await perform(request)
    }

    private func requestWithBody<T: Decodable, Body: Encodable>(
        _ path: String,
        method: String,
        token: String?,
        body: Body
    ) async throws -> T {
        var request = try makeRequest(path, method: method, token: token)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let encodedBody = try encoder.encode(body)
        request.setValue(String(encodedBody.count), forHTTPHeaderField: "Content-Length")
        request.httpBody = encodedBody
        return try await perform(request)
    }

    private func makeRequest(
        _ path: String,
        method: String,
        token: String?,
        queryItems: [URLQueryItem] = []
    ) throws -> URLRequest {
        let url = try makeURL(path, queryItems: queryItems)

        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = Timeout.request
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return request
    }

    private func makeURL(_ path: String, queryItems: [URLQueryItem] = []) throws -> URL {
        guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else {
            throw APIError.invalidResponse
        }
        let basePath = components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let requestPath = path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        components.path = "/" + [basePath, requestPath]
            .filter { !$0.isEmpty }
            .joined(separator: "/")
        components.queryItems = queryItems.isEmpty ? nil : queryItems
        guard let url = components.url else {
            throw APIError.invalidResponse
        }
        guard url.scheme == "http" || url.scheme == "https" else {
            throw APIError.invalidResponse
        }
        return url
    }

    private func perform<T: Decodable>(_ request: URLRequest) async throws -> T {
        let (data, response) = try await send(request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            let message = Self.errorMessage(from: data) ?? "Request failed with status \(httpResponse.statusCode)."
            print(
                "[APIClient] request failed",
                "method=\(request.httpMethod ?? "UNKNOWN")",
                "url=\(request.url?.absoluteString ?? "nil")",
                "status=\(httpResponse.statusCode)",
                "response=\(String(data: data, encoding: .utf8) ?? "<non-utf8>")"
            )
            throw APIError.server(message)
        }
        return try decoder.decode(T.self, from: data)
    }

    private func performEmpty(_ request: URLRequest) async throws {
        let (data, response) = try await send(request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            let message = Self.errorMessage(from: data) ?? "Request failed with status \(httpResponse.statusCode)."
            print(
                "[APIClient] request failed",
                "method=\(request.httpMethod ?? "UNKNOWN")",
                "url=\(request.url?.absoluteString ?? "nil")",
                "status=\(httpResponse.statusCode)",
                "response=\(String(data: data, encoding: .utf8) ?? "<non-utf8>")"
            )
            throw APIError.server(message)
        }
    }

    private func send(_ request: URLRequest) async throws -> (Data, URLResponse) {
        try await withCheckedThrowingContinuation { continuation in
            let task = session.dataTask(with: request) { data, response, error in
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

    private func multipartBody(images: [Data], fieldName: String, boundary: String) -> Data {
        var body = Data()
        for image in images {
            body.append("--\(boundary)\r\n")
            body.append("Content-Disposition: form-data; name=\"\(fieldName)\"; filename=\"\(UUID().uuidString).jpg\"\r\n")
            body.append("Content-Type: image/jpeg\r\n\r\n")
            body.append(image)
            body.append("\r\n")
        }
        body.append("--\(boundary)--\r\n")
        return body
    }

    private static func errorMessage(from data: Data) -> String? {
        guard !data.isEmpty else { return nil }
        if let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if let detail = payload["detail"] as? String {
                return detail
            }
            if let message = payload["message"] as? String {
                return message
            }
            if let detail = payload["detail"] {
                return String(describing: detail)
            }
        }
        return String(data: data, encoding: .utf8)
    }
}

private extension Data {
    mutating func append(_ string: String) {
        append(Data(string.utf8))
    }
}
