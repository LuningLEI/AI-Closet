import SwiftUI

struct APIOutfitRecommendationCard: View {
    @State private var editedItems: [ClothingItemDTO]?
    var surface: OutfitActionSurface = .recommendations
    var isSelectedToday = false
    let recommendation: OutfitRecommendationDTO
    let index: Int
    let total: Int
    let onPrevious: () -> Void
    let onNext: () -> Void
    var onDisliked: () -> Void = {}
    var onWorn: () -> Void = {}
    var onWearUndone: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    if !isSelectedToday {
                        Text("Match score \(Int(recommendation.score.rounded()))")
                            .font(.caption.weight(.bold))
                            .textCase(.uppercase)
                            .foregroundStyle(.blue)
                    }
                    Text(recommendation.title)
                        .font(.title2.bold())
                }
                Spacer()
                if !isSelectedToday {
                    Text("\(index + 1) / \(total)")
                        .font(.subheadline.weight(.semibold))
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .background(Color(.secondarySystemBackground), in: Capsule())
                }
            }

            if let original = recommendation.originalScore, let penalty = recommendation.wearPenalty, penalty > 0, editedItems == nil {
                Text("Original \(Int(original.rounded())) − recent wear \(Int(penalty.rounded()))")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if editedItems != nil { Text("Your saved version · refresh to recalculate its score").font(.caption).foregroundStyle(.secondary) }
            outfitLineup
            OutfitActions(surface: surface, outfitID: persistentOutfitID,
                          items: editedItems ?? recommendation.items,
                          onSaved: { editedItems = $0 }, onDisliked: onDisliked,
                          onWorn: onWorn, onWearUndone: onWearUndone)
        }
        .onChange(of: recommendation.id) { _, _ in editedItems = nil }
        .padding(18)
        .background(Color(.systemBackground), in: RoundedRectangle(cornerRadius: 22))
        .overlay(alignment: .leading) {
            if !isSelectedToday && total > 1 {
                arrowButton(systemName: "chevron.left", action: onPrevious).offset(x: -18)
            }
        }
        .overlay(alignment: .trailing) {
            if !isSelectedToday && total > 1 {
                arrowButton(systemName: "chevron.right", action: onNext).offset(x: 18)
            }
        }
        .shadow(color: .black.opacity(0.06), radius: 18, y: 10)
        .animation(.spring(response: 0.35, dampingFraction: 0.82), value: recommendation.id)
    }

    private var persistentOutfitID: UUID? {
        UUID(uuidString: recommendation.id.split(separator: ":", maxSplits: 1).first.map(String.init) ?? "")
    }

    private var outfitLineup: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(alignment: .top, spacing: 12) {
                ForEach(editedItems ?? recommendation.items) { item in
                    VStack(alignment: .leading, spacing: 8) {
                        ClosetAsyncImage(url: item.imageUrl, itemID: item.id)
                            .frame(width: 156, height: 188)
                            .clipped()
                            .clipShape(RoundedRectangle(cornerRadius: 18))
                        Text(item.displayTitle)
                            .font(.subheadline.weight(.semibold))
                            .lineLimit(2)
                        Text([item.category, item.color, item.style].filter { !$0.isEmpty }.joined(separator: " · "))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                    .padding(10)
                    .frame(width: 176, alignment: .leading)
                    .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 18))
                }
            }
        }
    }

    private func arrowButton(systemName: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.headline.weight(.bold))
                .frame(width: 46, height: 46)
                .background(Color(.systemBackground), in: Circle())
                .shadow(color: .black.opacity(0.12), radius: 12, y: 6)
        }
        .buttonStyle(.plain)
    }
}
