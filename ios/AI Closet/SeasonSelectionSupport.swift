import Foundation

@MainActor
enum SeasonSelectionSupport {
    static var options: [String] { ClothingTaxonomySupport.seasons }

    static func decode(_ storedValue: String) -> Set<String> { decode(storedValue, options: options) }

    static func decode(_ storedValue: String,options available:[String]) -> Set<String> {
        let tokens = storedValue.split(separator: ",").map { $0.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }
        if tokens.contains(where: { ["all-season", "all season", "year-round", "year round"].contains($0) }) { return Set(available) }
        let normalized = tokens.map { $0 == "autumn" ? "fall" : $0 }
        let valid = Set(available.filter { normalized.contains($0.lowercased()) })
        return valid.isEmpty ? Set(available) : valid
    }

    static func encode(_ selection: Set<String>) -> String { encode(selection, options: options) }

    static func encode(_ selection: Set<String>,options available:[String]) -> String {
        let normalized = normalizedSelection(from: selection,options:available)
        return available.filter { normalized.contains($0) }.joined(separator: ", ")
    }

    static func displayText(for selection: Set<String>) -> String { encode(selection) }

    static func displayText(for selection: Set<String>,options available:[String]) -> String { encode(selection,options:available) }

    static func toggled(_ season: String, in selection: Set<String>) -> Set<String> { toggled(season, in: selection, options: options) }

    static func toggled(_ season: String, in selection: Set<String>,options available:[String]) -> Set<String> {
        var updated = normalizedSelection(from: selection,options:available)
        guard available.contains(season) else { return updated }
        if updated.contains(season) {
            if updated.count > 1 { updated.remove(season) }
        } else { updated.insert(season) }
        return updated
    }

    private static func normalizedSelection(from selection: Set<String>,options available:[String]) -> Set<String> {
        decode(selection.joined(separator: ","),options:available)
    }
}
