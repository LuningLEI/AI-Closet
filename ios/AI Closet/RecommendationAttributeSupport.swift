import Foundation

struct RecommendationProfile {
    let formality: String
    let warmth: String
    let layerRole: String
    let versatility: String
}

enum RecommendationAttributeSupport {
    static func profile(for item: ClothingItem) -> RecommendationProfile {
        RecommendationProfile(
            formality: formality(for: item),
            warmth: warmth(for: item),
            layerRole: layerRole(for: item),
            versatility: versatility(for: item)
        )
    }

    private static func formality(for item: ClothingItem) -> String {
        switch item.occasion {
        case "Wedding": return "Formal"
        case "Work": return item.style == "Casual" ? "Smart casual" : "Business casual"
        case "Party", "Date": return item.style == "Formal" ? "Formal" : "Smart casual"
        default:
            switch item.style {
            case "Formal", "Elegant": return "Smart casual"
            case "Business": return "Business casual"
            default: return "Casual"
            }
        }
    }

    private static func warmth(for item: ClothingItem) -> String {
        let seasons = SeasonSelectionSupport.decode(item.season)
        if item.category == "Outerwear" || seasons.contains("Winter") {
            return "Warm"
        }
        if seasons.contains("Fall") || seasons.contains("Spring") {
            return "Medium"
        }
        return "Light"
    }

    private static func layerRole(for item: ClothingItem) -> String {
        switch item.category {
        case "Outerwear":
            return "Outer"
        case "Accessories":
            return "Accent"
        case "Shoes":
            return "Base"
        default:
            return "Main"
        }
    }

    private static func versatility(for item: ClothingItem) -> String {
        let seasons = SeasonSelectionSupport.decode(item.season)
        let seasonCount = seasons.contains("All-Season") ? 4 : seasons.count
        let neutralColors = Set(["Black", "White", "Gray", "Navy", "Beige", "Brown"])
        let isNeutral = neutralColors.contains(item.color)
        let score = seasonCount + (isNeutral ? 1 : 0) + (item.occasion == "Everyday" ? 1 : 0)

        switch score {
        case 5...:
            return "High"
        case 3...4:
            return "Medium"
        default:
            return "Low"
        }
    }
}
