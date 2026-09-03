import Foundation

enum ClothingTaxonomySupport {
    static let categories = ["Tops", "Bottoms", "Shoes", "Outerwear", "Accessories", "Uncategorized"]
    static let colors = ["Unknown", "Black", "White", "Gray", "Blue", "Navy", "Red", "Green", "Brown", "Beige", "Pink", "Purple", "Yellow", "Orange"]
    static let styles = ["Casual", "Formal", "Business", "Sporty", "Streetwear", "Elegant", "Minimalist"]
    static let occasions = ["Everyday", "Work", "Party", "Date", "Travel", "Workout", "Wedding"]

    static var allSubtypeOptions: [String] {
        let grouped = categories.flatMap { SubtypeSupport.options(for: $0) }
        return Array(NSOrderedSet(array: grouped)) as? [String] ?? ["Unknown"]
    }
}
