import Foundation

enum SubtypeSupport {
    static func options(for category: String) -> [String] {
        switch category {
        case "Tops":
            return ["Unknown", "T-shirt", "Tank Top", "Blouse", "Shirt", "Sweater", "Hoodie", "Cardigan", "Pullover", "Crop Top"]
        case "Bottoms":
            return ["Unknown", "Jeans", "Wide-leg Pants", "Straight-leg Pants", "Trousers", "Leggings", "Joggers", "Shorts", "Skirt"]
        case "Shoes":
            return ["Unknown", "Sneakers", "Boots", "Sandals", "Heels", "Loafers", "Flats", "Slippers"]
        case "Outerwear":
            return ["Unknown", "Jacket", "Coat", "Blazer", "Cardigan", "Puffer", "Windbreaker", "Trench Coat"]
        case "Accessories":
            return ["Unknown", "Bag", "Hat", "Scarf", "Belt", "Jewelry", "Watch", "Sunglasses"]
        default:
            return ["Unknown"]
        }
    }

    static func normalized(_ subtype: String?, for category: String) -> String {
        let options = options(for: category)
        guard let subtype, !subtype.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return options.first ?? "Unknown"
        }
        if options.contains(subtype) {
            return subtype
        }

        let normalized = subtype.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)

        switch category {
        case "Bottoms":
            if normalized.contains("wide") && (normalized.contains("pant") || normalized.contains("jean")) {
                return "Wide-leg Pants"
            }
            if normalized.contains("straight") && (normalized.contains("pant") || normalized.contains("jean")) {
                return "Straight-leg Pants"
            }
            if normalized.contains("jean") {
                return "Jeans"
            }
            if normalized.contains("trouser") || normalized.contains("pant") {
                return "Trousers"
            }
            if normalized.contains("legging") {
                return "Leggings"
            }
            if normalized.contains("jogger") || normalized.contains("sweatpant") {
                return "Joggers"
            }
            if normalized.contains("short") {
                return "Shorts"
            }
            if normalized.contains("skirt") {
                return "Skirt"
            }
        case "Tops":
            if normalized.contains("t-shirt") || normalized.contains("tee") {
                return "T-shirt"
            }
            if normalized.contains("tank") {
                return "Tank Top"
            }
            if normalized.contains("blouse") {
                return "Blouse"
            }
            if normalized.contains("shirt") {
                return "Shirt"
            }
            if normalized.contains("sweater") {
                return "Sweater"
            }
            if normalized.contains("hoodie") {
                return "Hoodie"
            }
            if normalized.contains("cardigan") {
                return "Cardigan"
            }
            if normalized.contains("pullover") {
                return "Pullover"
            }
            if normalized.contains("crop") {
                return "Crop Top"
            }
        case "Shoes":
            if normalized.contains("sneaker") {
                return "Sneakers"
            }
            if normalized.contains("boot") {
                return "Boots"
            }
            if normalized.contains("sandal") {
                return "Sandals"
            }
            if normalized.contains("heel") {
                return "Heels"
            }
            if normalized.contains("loafer") {
                return "Loafers"
            }
            if normalized.contains("flat") {
                return "Flats"
            }
            if normalized.contains("slipper") {
                return "Slippers"
            }
        case "Outerwear":
            if normalized.contains("jacket") {
                return "Jacket"
            }
            if normalized.contains("coat") {
                return "Coat"
            }
            if normalized.contains("blazer") {
                return "Blazer"
            }
            if normalized.contains("cardigan") {
                return "Cardigan"
            }
            if normalized.contains("puffer") {
                return "Puffer"
            }
            if normalized.contains("windbreaker") {
                return "Windbreaker"
            }
            if normalized.contains("trench") {
                return "Trench Coat"
            }
        case "Accessories":
            if normalized.contains("bag") {
                return "Bag"
            }
            if normalized.contains("hat") {
                return "Hat"
            }
            if normalized.contains("scarf") {
                return "Scarf"
            }
            if normalized.contains("belt") {
                return "Belt"
            }
            if normalized.contains("jew") {
                return "Jewelry"
            }
            if normalized.contains("watch") {
                return "Watch"
            }
            if normalized.contains("sunglass") {
                return "Sunglasses"
            }
        default:
            break
        }

        return options.first ?? "Unknown"
    }
}
