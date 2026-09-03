import Foundation

enum SeasonSelectionSupport {
    static let options = ["All-Season", "Spring", "Summer", "Fall", "Winter"]

    static func decode(_ storedValue: String) -> Set<String> {
        let parsed = storedValue
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }

        let valid = Set(parsed.filter { options.contains($0) })
        return valid.isEmpty ? ["All-Season"] : valid
    }

    static func encode(_ selection: Set<String>) -> String {
        let normalized = normalizedSelection(from: selection)
        return options.filter { normalized.contains($0) }.joined(separator: ", ")
    }

    static func displayText(for selection: Set<String>) -> String {
        let normalized = normalizedSelection(from: selection)
        return options.filter { normalized.contains($0) }.joined(separator: ", ")
    }

    static func toggled(_ season: String, in selection: Set<String>) -> Set<String> {
        var updated = normalizedSelection(from: selection)

        if season == "All-Season" {
            return ["All-Season"]
        }

        updated.remove("All-Season")
        if updated.contains(season) {
            updated.remove(season)
        } else {
            updated.insert(season)
        }

        return updated.isEmpty ? ["All-Season"] : updated
    }

    private static func normalizedSelection(from selection: Set<String>) -> Set<String> {
        let valid = selection.filter { options.contains($0) }
        return valid.isEmpty ? ["All-Season"] : valid
    }
}
