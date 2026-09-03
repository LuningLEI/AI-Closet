import Foundation

struct OutfitRecommendationEngine {
    private let occasionRule = OccasionFitRule()
    private let weatherRule = WeatherFitRule()
    private let styleRule = StyleHarmonyRule()
    private let colorRule = ColorHarmonyRule()
    private let balanceRule = CategoryBalanceRule()

    func recommend(
        from items: [ClothingItem],
        context: OutfitRecommendationContext,
        limit: Int = 3
    ) -> [OutfitRecommendation] {
        let grouped = Dictionary(grouping: items, by: \.category)
        let input = OutfitRecommendationInput(groupedItems: grouped, context: context)
        let candidates = generateCandidates(from: grouped, context: context)

        return candidates
            .compactMap { candidate in
                makeRecommendation(from: candidate, input: input)
            }
            .sorted { lhs, rhs in
                if lhs.score == rhs.score {
                    return lhs.id < rhs.id
                }
                return lhs.score > rhs.score
            }
            .prefix(limit)
            .map { $0 }
    }

    private func generateCandidates(
        from grouped: [String: [ClothingItem]],
        context: OutfitRecommendationContext
    ) -> [OutfitRecommendationCandidate] {
        let tops = grouped["Tops", default: []]
        let bottoms = grouped["Bottoms", default: []]
        let shoes = grouped["Shoes", default: []]
        let outerwearOptions = [nil] + grouped["Outerwear", default: []].map(Optional.some)
        let accessoryOptions = [nil] + grouped["Accessories", default: []].map(Optional.some)

        guard !tops.isEmpty, !bottoms.isEmpty else { return [] }

        let footwearOptions = [nil] + shoes.map(Optional.some)
        var seen = Set<String>()
        var candidates: [OutfitRecommendationCandidate] = []

        for top in tops {
            guard itemMatchesContext(top, context: context) else { continue }

            for bottom in bottoms {
                guard itemMatchesContext(bottom, context: context) else { continue }

                for shoes in footwearOptions {
                    if let shoes, !itemMatchesContext(shoes, context: context) {
                        continue
                    }

                    for outerwear in outerwearOptions {
                        if let outerwear, !itemMatchesContext(outerwear, context: context) {
                            continue
                        }

                        for accessory in accessoryOptions {
                            if let accessory, !itemMatchesContext(accessory, context: context) {
                                continue
                            }

                            let candidate = OutfitRecommendationCandidate(
                                top: top,
                                bottom: bottom,
                                shoes: shoes,
                                outerwear: outerwear,
                                accessory: accessory
                            )

                            if seen.insert(candidate.identifier).inserted {
                                candidates.append(candidate)
                            }
                        }
                    }
                }
            }
        }

        return candidates
    }

    private func makeRecommendation(
        from candidate: OutfitRecommendationCandidate,
        input: OutfitRecommendationInput
    ) -> OutfitRecommendation? {
        var breakdown = OutfitScoreBreakdown()
        var reasons: [String] = []

        let occasion = occasionRule.score(candidate: candidate, input: input)
        breakdown.occasionFit = occasion.0
        if let reason = occasion.1 { reasons.append(reason) }

        let weather = weatherRule.score(candidate: candidate, input: input)
        breakdown.weatherFit = weather.0
        if let reason = weather.1 { reasons.append(reason) }

        let style = styleRule.score(candidate: candidate, input: input)
        breakdown.styleHarmony = style.0
        if let reason = style.1 { reasons.append(reason) }

        let color = colorRule.score(candidate: candidate, input: input)
        breakdown.colorHarmony = color.0
        if let reason = color.1 { reasons.append(reason) }

        let balance = balanceRule.score(candidate: candidate, input: input)
        breakdown.categoryBalance = balance.0
        if let reason = balance.1 { reasons.append(reason) }

        guard breakdown.total > 30 else { return nil }

        return OutfitRecommendation(
            id: candidate.identifier,
            top: candidate.top,
            bottom: candidate.bottom,
            shoes: candidate.shoes,
            outerwear: candidate.outerwear,
            accessory: candidate.accessory,
            breakdown: breakdown,
            reasons: Array(reasons.prefix(3))
        )
    }

    private func itemMatchesContext(_ item: ClothingItem, context: OutfitRecommendationContext) -> Bool {
        let normalizedOccasion = item.occasion.lowercased()
        let requestedOccasion = context.occasion.lowercased()
        let matchesOccasion =
            normalizedOccasion == "everyday"
            || normalizedOccasion == requestedOccasion
            || requestedOccasion == "everyday"

        let allowedSeasons = allowedSeasons(for: context.temperatureF)
        let itemSeasons = normalizedSeasons(for: item.season)
        let matchesSeason =
            itemSeasons.contains("all-season")
            || !itemSeasons.isDisjoint(with: allowedSeasons)

        return matchesOccasion && matchesSeason
    }

    private func normalizedSeasons(for season: String) -> Set<String> {
        let decoded = SeasonSelectionSupport.decode(season)
        if !decoded.isEmpty {
            return Set(decoded.map { normalizedSeasonToken($0) })
        }
        return [normalizedSeasonToken(season)]
    }

    private func normalizedSeasonToken(_ season: String) -> String {
        season
            .lowercased()
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: " ", with: "-")
    }

    private func allowedSeasons(for temperatureF: Double) -> Set<String> {
        switch temperatureF {
        case ..<45:
            return ["winter", "fall", "all-season"]
        case 45..<65:
            return ["spring", "fall", "all-season"]
        case 65..<72:
            return ["spring", "summer", "all-season"]
        case 72..<82:
            return ["summer", "all-season"]
        default:
            return ["summer", "all-season"]
        }
    }
}

private struct OccasionFitRule: OutfitScoringRule {
    func score(candidate: OutfitRecommendationCandidate, input: OutfitRecommendationInput) -> (Double, String?) {
        let exactMatches = candidate.allItems.filter {
            $0.occasion.caseInsensitiveCompare(input.context.occasion) == .orderedSame
        }.count
        let score = min(Double(exactMatches) * 6 + 7, 25)
        let reason = exactMatches > 0 ? "Matches your \(input.context.occasion.lowercased()) plan." : "Keeps the outfit flexible for everyday wear."
        return (score, reason)
    }
}

private struct WeatherFitRule: OutfitScoringRule {
    func score(candidate: OutfitRecommendationCandidate, input: OutfitRecommendationInput) -> (Double, String?) {
        let temperature = input.context.temperatureF
        let hasOuterwear = candidate.outerwear != nil
        let score: Double
        let reason: String

        switch temperature {
        case ..<45:
            score = hasOuterwear ? 20 : 10
            reason = hasOuterwear ? "Adds outerwear for colder weather." : "Could use an extra layer in the cold."
        case 45..<65:
            score = hasOuterwear ? 18 : 15
            reason = "Balanced for mild temperatures."
        case 65..<78:
            score = hasOuterwear ? 12 : 18
            reason = hasOuterwear ? "Layered option for cooler indoor spaces." : "Light enough for moderate weather."
        default:
            score = hasOuterwear ? 6 : 20
            reason = hasOuterwear ? "A bit layered for warmer weather." : "Keeps things light for warm weather."
        }

        return (score, reason)
    }
}

private struct StyleHarmonyRule: OutfitScoringRule {
    func score(candidate: OutfitRecommendationCandidate, input: OutfitRecommendationInput) -> (Double, String?) {
        let styles = candidate.allItems.map { normalizedStyle($0.style) }
        let dominantStyle = Dictionary(grouping: styles, by: { $0 })
            .max(by: { $0.value.count < $1.value.count })?
            .key ?? "casual"

        var score = Double(styles.filter { $0 == dominantStyle }.count) * 4
        if let preferredStyle = input.context.preferredStyle?.lowercased(),
           dominantStyle == preferredStyle {
            score += 6
        }
        score = min(score, 20)

        let reason = dominantStyle == "casual"
            ? "Keeps the outfit visually consistent."
            : "Leans into a \(dominantStyle) styling direction."
        return (score, reason)
    }

    private func normalizedStyle(_ style: String) -> String {
        style.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

private struct ColorHarmonyRule: OutfitScoringRule {
    private let neutralColors: Set<String> = ["black", "white", "gray", "grey", "beige", "brown", "navy", "unknown"]

    func score(candidate: OutfitRecommendationCandidate, input: OutfitRecommendationInput) -> (Double, String?) {
        let colors = candidate.allItems.map { $0.color.lowercased() }
        let uniqueColors = Set(colors)
        let neutralCount = colors.filter { neutralColors.contains($0) }.count

        let score: Double
        let reason: String

        if uniqueColors.count <= 2 {
            score = 20
            reason = "Tight color palette helps the look feel polished."
        } else if neutralCount >= 2 {
            score = 16
            reason = "Neutral pieces keep the colors under control."
        } else if uniqueColors.count == colors.count {
            score = 10
            reason = "More color variety makes the look bolder."
        } else {
            score = 14
            reason = "Color mix stays reasonably coordinated."
        }

        return (score, reason)
    }
}

private struct CategoryBalanceRule: OutfitScoringRule {
    func score(candidate: OutfitRecommendationCandidate, input: OutfitRecommendationInput) -> (Double, String?) {
        var score = 6.0
        if candidate.shoes != nil { score += 2 }
        if candidate.accessory != nil { score += 1 }
        if candidate.outerwear != nil { score += 1 }
        return (min(score, 10), "Builds a complete outfit instead of isolated pieces.")
    }
}
