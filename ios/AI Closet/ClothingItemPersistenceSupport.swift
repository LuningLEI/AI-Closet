import Foundation
import SwiftData

enum ClothingItemPersistenceSupport {
    static func purgeDerivedData(for item: ClothingItem, in modelContext: ModelContext) {
        purgeDerivedData(for: item.id, in: modelContext)
        item.recognitionSource = nil
        item.recognitionSummary = nil
        item.recognitionConfidence = nil
        item.recognitionTagsJSON = nil
        item.recommendationFeatureJSON = nil
    }

    static func purgeDerivedData(for itemID: UUID, in modelContext: ModelContext) {
        let recognitionDescriptor = FetchDescriptor<RecognitionRecord>(
            predicate: #Predicate<RecognitionRecord> { $0.clothingItemID == itemID }
        )
        let featureDescriptor = FetchDescriptor<ItemFeatureSnapshot>(
            predicate: #Predicate<ItemFeatureSnapshot> { $0.clothingItemID == itemID }
        )

        if let recognitionRecords = try? modelContext.fetch(recognitionDescriptor) {
            for record in recognitionRecords {
                modelContext.delete(record)
            }
        }

        if let featureSnapshots = try? modelContext.fetch(featureDescriptor) {
            for snapshot in featureSnapshots {
                modelContext.delete(snapshot)
            }
        }
    }

    static func deleteItem(_ item: ClothingItem, in modelContext: ModelContext) {
        purgeDerivedData(for: item.id, in: modelContext)
        modelContext.delete(item)
    }

    @discardableResult
    static func removeOrphanedDerivedData(in modelContext: ModelContext) -> Int {
        let clothingDescriptor = FetchDescriptor<ClothingItem>()
        let recognitionDescriptor = FetchDescriptor<RecognitionRecord>()
        let featureDescriptor = FetchDescriptor<ItemFeatureSnapshot>()

        guard let itemIDs = try? modelContext.fetch(clothingDescriptor).map(\.id) else {
            return 0
        }

        let validItemIDs = Set(itemIDs)
        var deletedCount = 0

        if let recognitionRecords = try? modelContext.fetch(recognitionDescriptor) {
            for record in recognitionRecords where !validItemIDs.contains(record.clothingItemID) {
                modelContext.delete(record)
                deletedCount += 1
            }
        }

        if let featureSnapshots = try? modelContext.fetch(featureDescriptor) {
            for snapshot in featureSnapshots where !validItemIDs.contains(snapshot.clothingItemID) {
                modelContext.delete(snapshot)
                deletedCount += 1
            }
        }

        if deletedCount > 0 {
            try? modelContext.save()
        }

        return deletedCount
    }
}
