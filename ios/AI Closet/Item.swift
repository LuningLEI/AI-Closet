//
//  Item.swift
//  AI Closet
//
//  Created by Luning Lei on 2/15/26.
//

import Foundation
import SwiftData

@Model
final class ClothingItem {
    var id: UUID
    var imageFilename: String
    var coverImageFilename: String?
    var category: String
    var subtype: String?
    var color: String = "Unknown"
    var season: String = "All-Season"
    var style: String = "Casual"
    var occasion: String = "Everyday"
    var recognitionSource: String?
    var recognitionSummary: String?
    var recognitionConfidence: Double?
    var recognitionTagsJSON: String?
    var recommendationFeatureJSON: String?
    var createdAt: Date

    init(
        imageFilename: String,
        coverImageFilename: String? = nil,
        category: String,
        subtype: String? = nil,
        color: String = "Unknown",
        season: String = "All-Season",
        style: String = "Casual",
        occasion: String = "Everyday",
        recognitionSource: String? = nil,
        recognitionSummary: String? = nil,
        recognitionConfidence: Double? = nil,
        recognitionTagsJSON: String? = nil,
        recommendationFeatureJSON: String? = nil,
        createdAt: Date = .now
    ) {
        self.id = UUID()
        self.imageFilename = imageFilename
        self.coverImageFilename = coverImageFilename
        self.category = category
        self.subtype = subtype
        self.color = color
        self.season = season
        self.style = style
        self.occasion = occasion
        self.recognitionSource = recognitionSource
        self.recognitionSummary = recognitionSummary
        self.recognitionConfidence = recognitionConfidence
        self.recognitionTagsJSON = recognitionTagsJSON
        self.recommendationFeatureJSON = recommendationFeatureJSON
        self.createdAt = createdAt
    }
}
