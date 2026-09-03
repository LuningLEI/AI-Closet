//
//  PendingClothingDraft.swift
//  AI Closet
//
//  Created by Luning Lei on 2/18/26.
//


import Foundation

struct PendingClothingDraft: Identifiable {
    let id = UUID()
    let imageData: Data
    var analysis: ClothingAnalysis
}
