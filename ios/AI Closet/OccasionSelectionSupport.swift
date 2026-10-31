import Foundation

enum OccasionSelectionSupport {
    static func decode(_ storedValue: String, options: [String]) -> Set<String> {
        let parsed = storedValue
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .map { $0 == "Vacation" ? "Travel" : $0 }
            .filter { options.contains($0) }
        return Set(parsed)
    }

    static func encode(_ selection: Set<String>, options: [String]) -> String {
        let valid = selection.filter { options.contains($0) }
        let normalized = valid
        return options.filter { normalized.contains($0) }.joined(separator: ", ")
    }

    static func toggled(_ occasion: String, in selection: Set<String>, options: [String]) -> Set<String> {
        var updated = selection.filter { options.contains($0) }
        if updated.contains(occasion) {
            updated.remove(occasion)
        } else {
            updated.insert(occasion)
        }
        return updated
    }
}

// Colors retain the comma-separated API representation used by existing items.
enum ColorSelectionSupport {
    nonisolated static func decode(_ value: String) -> Set<String> {
        Set(value.split(separator: ",").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty })
    }
    nonisolated static func encode(_ selection: Set<String>, options: [String]) -> String {
        let ordered = options.filter { selection.contains($0) }
        return ordered.isEmpty ? "Unknown" : ordered.joined(separator: ", ")
    }
    nonisolated static func toggled(_ color: String, in selection: Set<String>) -> Set<String> {
        var result = selection
        if result.contains(color) { result.remove(color) }
        else {
            if color == "Unknown" { return ["Unknown"] }
            result.remove("Unknown")
            result.insert(color)
        }
        return result.isEmpty ? ["Unknown"] : result
    }
}
