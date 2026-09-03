import CoreML
import CoreGraphics
import Foundation
import ImageIO
import Vision

struct LocalCategoryClassifier {
    private let maxClassificationDimension: CGFloat = 1024
    private let retryClassificationDimension: CGFloat = 640

    func predictCategory(from imageData: Data) async -> String? {
        guard let primaryImage = Self.makeDownsampledCGImage(from: imageData, maxDimension: maxClassificationDimension) else {
            print("FAILED TO DECODE IMAGE FOR LOCAL CLASSIFICATION")
            return nil
        }

        return await Task.detached(priority: .userInitiated) {
            if let category = Self.classifyWithCustomModel(from: primaryImage) {
                return category
            }

            if let category = Self.classifyCategory(from: primaryImage, usesCPUOnly: false) {
                return category
            }

            guard let retryImage = Self.makeDownsampledCGImage(from: imageData, maxDimension: retryClassificationDimension) else {
                return nil
            }

            print("RETRYING VISION WITH LOWER RESOLUTION")
            if let category = Self.classifyWithCustomModel(from: retryImage) {
                return category
            }

            if let category = Self.classifyCategory(from: retryImage, usesCPUOnly: false) {
                return category
            }

            print("RETRYING VISION WITH CPU ONLY")
            return Self.classifyCategory(from: retryImage, usesCPUOnly: true)
        }.value
    }

    private nonisolated static let customModelCandidateNames = [
        "model",
        "FashionProductArticleType",
        "FashionClassifier",
        "ClothingClassifier",
        "Model"
    ]

    private nonisolated static let customVisionModel: VNCoreMLModel? = {
        let config = MLModelConfiguration()
        config.computeUnits = .cpuOnly

        for name in customModelCandidateNames {
            guard let url = Bundle.main.url(forResource: name, withExtension: "mlmodelc") else {
                continue
            }
            if let model = try? MLModel(contentsOf: url, configuration: config),
               let vnModel = try? VNCoreMLModel(for: model) {
                print("USING CUSTOM CORE ML MODEL:", name)
                return vnModel
            }
        }

        print("NO CUSTOM CORE ML MODEL FOUND. Falling back to VNClassifyImageRequest.")
        return nil
    }()

    private nonisolated static func classifyWithCustomModel(from cgImage: CGImage) -> String? {
        guard let model = customVisionModel else { return nil }

        let request = VNCoreMLRequest(model: model)
        request.imageCropAndScaleOption = .centerCrop

        do {
            try VNImageRequestHandler(cgImage: cgImage, options: [:]).perform([request])
            guard let results = request.results as? [VNClassificationObservation] else {
                return nil
            }

            print("=== Custom model top predictions ===")
            for result in results.prefix(8) {
                print("•", result.identifier, result.confidence)
            }

            for result in results.prefix(8) where result.confidence > 0.25 {
                let normalized = result.identifier
                    .lowercased()
                    .replacingOccurrences(of: "_", with: " ")
                    .replacingOccurrences(of: "-", with: " ")

                if let mapped = mapLabelToCategory(normalized) {
                    return mapped
                }
            }
        } catch {
            print("CUSTOM MODEL ERROR:", error)
        }

        return nil
    }

    private nonisolated static func classifyCategory(from cgImage: CGImage, usesCPUOnly: Bool) -> String? {
        autoreleasepool {
            let request = VNClassifyImageRequest()
            request.usesCPUOnly = usesCPUOnly

            do {
                try VNImageRequestHandler(cgImage: cgImage, options: [:]).perform([request])
                guard let results = request.results else {
                    print("NO RESULTS:", String(describing: request.results))
                    return nil
                }

                print("=== Vision top predictions ===")
                for result in results.prefix(8) {
                    print("•", result.identifier, result.confidence)
                }

                for result in results.prefix(8) where result.confidence > 0.20 {
                    if let mapped = mapLabelToCategory(result.identifier.lowercased()) {
                        return mapped
                    }
                }
            } catch {
                print("VN PERFORM ERROR:", error)
            }

            return nil
        }
    }

    private nonisolated static func makeDownsampledCGImage(from imageData: Data, maxDimension: CGFloat) -> CGImage? {
        guard let source = CGImageSourceCreateWithData(imageData as CFData, nil) else { return nil }

        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: Int(maxDimension),
            kCGImageSourceShouldCacheImmediately: true
        ]

        return CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary)
    }

    private nonisolated static func mapLabelToCategory(_ label: String) -> String? {
        if label.contains("shoe") || label.contains("sneaker") || label.contains("boot") ||
            label.contains("heel") || label.contains("slipper") || label.contains("sandal") ||
            label.contains("loafer") || label.contains("flip flops") || label.contains("flats") {
            return "Shoes"
        }

        if label.contains("jean") || label.contains("pants") || label.contains("trouser") ||
            label.contains("skirt") || label.contains("shorts") || label.contains("leggings") ||
            label.contains("jogger") || label.contains("sweatpants") || label.contains("bottomwear") ||
            label.contains("track pants") || label.contains("palazzos") {
            return "Bottoms"
        }

        if label.contains("shirt") || label.contains("t-shirt") || label.contains("tshirt") ||
            label.contains("blouse") || label.contains("sweater") || label.contains("hoodie") ||
            label.contains("jersey") || label.contains("cardigan") || label.contains("pullover") ||
            label.contains("tank") || label.contains("top") || label.contains("kurta") ||
            label.contains("kurti") || label.contains("topwear") || label.contains("tops") ||
            label.contains("garment") || label.contains("apparel") || label.contains("clothing") {
            return "Tops"
        }

        if label.contains("jacket") || label.contains("coat") || label.contains("parka") ||
            label.contains("blazer") || label.contains("windbreaker") || label.contains("raincoat") {
            return "Outerwear"
        }

        if label.contains("hat") || label.contains("cap") || label.contains("bag") ||
            label.contains("backpack") || label.contains("scarf") || label.contains("belt") ||
            label.contains("purse") || label.contains("handbag") || label.contains("wallet") ||
            label.contains("sunglasses") || label.contains("watch") || label.contains("jewellery") {
            return "Accessories"
        }

        return nil
    }
}
