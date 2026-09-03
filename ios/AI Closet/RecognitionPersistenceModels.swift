import Foundation
import SwiftData

@Model
final class RecognitionRecord {
    var id: UUID
    var clothingItemID: UUID

    var provider: String
    var modelName: String
    var modelVersion: String?
    var promptVersion: String?

    var rawCategory: String?
    var rawSubtype: String?
    var rawColor: String?
    var rawStyle: String?
    var rawOccasion: String?
    var rawSeasonsJSON: String?

    var normalizedCategory: String
    var normalizedSubtype: String?
    var normalizedColor: String
    var normalizedStyle: String
    var normalizedOccasion: String
    var normalizedSeasonsJSON: String

    var confidence: Double?
    var summary: String?
    var rawResponseJSON: String?

    var createdAt: Date

    init(
        clothingItemID: UUID,
        provider: String,
        modelName: String,
        modelVersion: String? = nil,
        promptVersion: String? = nil,
        rawCategory: String? = nil,
        rawSubtype: String? = nil,
        rawColor: String? = nil,
        rawStyle: String? = nil,
        rawOccasion: String? = nil,
        rawSeasonsJSON: String? = nil,
        normalizedCategory: String,
        normalizedSubtype: String? = nil,
        normalizedColor: String,
        normalizedStyle: String,
        normalizedOccasion: String,
        normalizedSeasonsJSON: String,
        confidence: Double? = nil,
        summary: String? = nil,
        rawResponseJSON: String? = nil,
        createdAt: Date = .now
    ) {
        self.id = UUID()
        self.clothingItemID = clothingItemID
        self.provider = provider
        self.modelName = modelName
        self.modelVersion = modelVersion
        self.promptVersion = promptVersion
        self.rawCategory = rawCategory
        self.rawSubtype = rawSubtype
        self.rawColor = rawColor
        self.rawStyle = rawStyle
        self.rawOccasion = rawOccasion
        self.rawSeasonsJSON = rawSeasonsJSON
        self.normalizedCategory = normalizedCategory
        self.normalizedSubtype = normalizedSubtype
        self.normalizedColor = normalizedColor
        self.normalizedStyle = normalizedStyle
        self.normalizedOccasion = normalizedOccasion
        self.normalizedSeasonsJSON = normalizedSeasonsJSON
        self.confidence = confidence
        self.summary = summary
        self.rawResponseJSON = rawResponseJSON
        self.createdAt = createdAt
    }
}

@Model
final class ItemFeatureSnapshot {
    var id: UUID
    var clothingItemID: UUID
    var recognitionRecordID: UUID?

    var featureVersion: String
    var categoryVectorJSON: String
    var colorVectorJSON: String
    var styleVectorJSON: String
    var occasionVectorJSON: String
    var seasonVectorJSON: String
    var embeddingVectorJSON: String?
    var extraFeaturesJSON: String?

    var createdAt: Date

    init(
        clothingItemID: UUID,
        recognitionRecordID: UUID? = nil,
        featureVersion: String,
        categoryVectorJSON: String,
        colorVectorJSON: String,
        styleVectorJSON: String,
        occasionVectorJSON: String,
        seasonVectorJSON: String,
        embeddingVectorJSON: String? = nil,
        extraFeaturesJSON: String? = nil,
        createdAt: Date = .now
    ) {
        self.id = UUID()
        self.clothingItemID = clothingItemID
        self.recognitionRecordID = recognitionRecordID
        self.featureVersion = featureVersion
        self.categoryVectorJSON = categoryVectorJSON
        self.colorVectorJSON = colorVectorJSON
        self.styleVectorJSON = styleVectorJSON
        self.occasionVectorJSON = occasionVectorJSON
        self.seasonVectorJSON = seasonVectorJSON
        self.embeddingVectorJSON = embeddingVectorJSON
        self.extraFeaturesJSON = extraFeaturesJSON
        self.createdAt = createdAt
    }
}
