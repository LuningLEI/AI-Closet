import SwiftUI

enum ClosetSelectionSupport {
    static let plannerOccasions = ["Everyday", "Work", "School", "Date", "Party", "Travel", "Formal", "Workout"]

    static func needsBorder(for colorName: String) -> Bool {
        ["white", "ivory", "cream", "beige", "yellow"].contains(normalizedColorName(colorName))
    }

    static func swatchColor(for colorName: String) -> Color {
        switch normalizedColorName(colorName) {
        case "black":
            return .black
        case "white":
            return .white
        case "gray", "grey":
            return .gray
        case "blue", "navy":
            return .blue
        case "light_blue", "sky_blue":
            return Color(red: 0.51, green: 0.76, blue: 0.98)
        case "green":
            return .green
        case "olive":
            return Color(red: 0.5, green: 0.54, blue: 0.2)
        case "red":
            return .red
        case "pink":
            return .pink
        case "purple":
            return .purple
        case "yellow":
            return .yellow
        case "orange":
            return .orange
        case "brown", "tan":
            return .brown
        case "beige":
            return Color(red: 0.89, green: 0.83, blue: 0.7)
        case "cream", "ivory":
            return Color(red: 0.98, green: 0.97, blue: 0.9)
        case "gold":
            return Color(red: 0.83, green: 0.69, blue: 0.22)
        case "silver":
            return Color(red: 0.75, green: 0.77, blue: 0.8)
        default:
            return Color(.systemGray4)
        }
    }

    private static func normalizedColorName(_ colorName: String) -> String {
        colorName
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: "[^a-z0-9]+", with: "_", options: .regularExpression)
            .trimmingCharacters(in: CharacterSet(charactersIn: "_"))
    }
}

struct ColorSwatchCircle: View {
    let colorName: String

    var body: some View {
        Circle()
            .fill(ClosetSelectionSupport.swatchColor(for: colorName))
            .frame(width: 16, height: 16)
            .overlay {
                Circle()
                    .stroke(Color(.separator).opacity(0.5), lineWidth: ClosetSelectionSupport.needsBorder(for: colorName) ? 1 : 0)
            }
    }
}
