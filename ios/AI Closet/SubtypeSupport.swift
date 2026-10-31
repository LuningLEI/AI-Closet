import Foundation

/// Normalization against the latest backend-owned taxonomy cache.
@MainActor
enum SubtypeSupport {
    static func options(for category: String) -> [String] {
        ClothingTaxonomySupport.taxonomy.subtypes[category] ?? []
    }

    static func normalized(_ subtype: String?, for category: String) -> String {
        let options = options(for: category)
        guard let subtype else { return options.first ?? "Unknown" }
        return options.first(where: { $0.caseInsensitiveCompare(subtype) == .orderedSame })
            ?? options.first
            ?? "Unknown"
    }
}
