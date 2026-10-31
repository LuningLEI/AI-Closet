import Foundation

/// Runtime cache only. The backend `/api/v1/taxonomy` response is the sole
/// default taxonomy; the app does not ship a second catalog.
@MainActor
enum ClothingTaxonomySupport {
    private(set) static var taxonomy = TaxonomyDTO(
        categories: [], colors: [], styles: [], occasions: [], seasons: [],
        subtypes: [:], lengths: [], sleeveLengths: []
    )

    static func install(_ value: TaxonomyDTO) {
        taxonomy = value
    }

    static var categories: [String] { taxonomy.categories }
    static var colors: [String] { taxonomy.colors }
    static var styles: [String] { taxonomy.styles }
    static var occasions: [String] { taxonomy.occasions }
    static var seasons: [String] { taxonomy.seasons }
    static var allSubtypeOptions: [String] {
        Array(Set(taxonomy.subtypes.values.flatMap { $0 })).sorted()
    }
}
