import SwiftUI
import UIKit

enum ImageEditorSaveResult {
    case success
    case failure(String)
}

struct ClothingImageEditorSheet: View {
    typealias SaveAction = @MainActor (Data, ImageEditMetadataDTO) async -> ImageEditorSaveResult

    @Environment(\.dismiss) private var dismiss

    let imageURL: String
    let title: String
    let refreshImageURL: @MainActor () async throws -> String
    let onSave: SaveAction

    @State private var originalImage: UIImage?
    @State private var previewImage: UIImage?
    @State private var retryCount = 0
    @State private var isLoading = true
    @State private var isSaving = false
    @State private var isRotating = false
    @State private var errorMessage: String?
    @State private var dragOffset: CGSize = .zero
    @State private var committedOffset: CGSize = .zero
    @State private var zoomScale: CGFloat = 1
    @State private var committedZoomScale: CGFloat = 1
    @State private var editorSide: CGFloat = 0
    @State private var rotationQuarterTurns = 0

    private let previewMaxDimension: CGFloat = 1_280
    private let exportMaxDimension: CGFloat = 2_048
    private let exportJPEGQuality: CGFloat = 0.82

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 18) {
                Text("Adjust the photo to control how it appears on your clothing card.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 20)

                editorCanvas

                HStack(spacing: 12) {
                    Button {
                        Task {
                            await rotate(byQuarterTurns: -1)
                        }
                    } label: {
                        Label("Rotate left", systemImage: "rotate.left")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    .disabled(previewImage == nil || isSaving || isRotating)

                    Button {
                        Task {
                            await rotate(byQuarterTurns: 1)
                        }
                    } label: {
                        Label("Rotate right", systemImage: "rotate.right")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    .disabled(previewImage == nil || isSaving || isRotating)
                }
                .padding(.horizontal, 20)

                if let errorMessage {
                    Text(errorMessage)
                        .font(.footnote)
                        .foregroundStyle(.red)
                        .padding(.horizontal, 20)
                }

                Spacer(minLength: 0)
            }
            .padding(.top, 18)
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") {
                        dismiss()
                    }
                    .disabled(isSaving)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(isSaving ? "Saving..." : "Save") {
                        Task {
                            await save()
                        }
                    }
                    .disabled(previewImage == nil || originalImage == nil || isLoading || isSaving || isRotating)
                }
            }
        }
        .task(id: retryCount) {
            await loadImage()
        }
    }

    @ViewBuilder
    private var editorCanvas: some View {
        if isLoading {
            ProgressView("Loading photo")
                .frame(maxWidth: .infinity, minHeight: 360)
        } else if let previewImage {
            GeometryReader { proxy in
                let side = min(proxy.size.width, proxy.size.height)

                ZStack {
                    RoundedRectangle(cornerRadius: 24)
                        .fill(Color(.secondarySystemBackground))

                    CropCanvas(
                        image: previewImage,
                        cropSide: side,
                        dragOffset: $dragOffset,
                        committedOffset: $committedOffset,
                        zoomScale: $zoomScale,
                        committedZoomScale: $committedZoomScale
                    )
                }
                .frame(width: side, height: side)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                .onAppear {
                    editorSide = side
                }
                .onChange(of: side) { _, newValue in
                    editorSide = newValue
                }
            }
            .frame(height: 420)
            .padding(.horizontal, 20)
        } else {
            VStack(spacing: 16) {
                ContentUnavailableView("Photo unavailable", systemImage: "photo")
                Button("Retry photo") { retryCount += 1 }
                    .buttonStyle(.bordered)
            }
            .frame(maxWidth: .infinity, minHeight: 360)
        }
    }

    @MainActor
    private func loadImage() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            let image: UIImage
            do {
                image = try await downloadImage(imageURL)
            } catch {
                try Task.checkCancellation()
                let freshURL = try await refreshImageURL()
                try Task.checkCancellation()
                image = try await downloadImage(freshURL)
            }
            try Task.checkCancellation()
            originalImage = image
            previewImage = Self.makePreviewImage(from: image, maxDimension: previewMaxDimension)
            rotationQuarterTurns = 0
            resetEditorState()
        } catch {
            guard !Task.isCancelled else { return }
            // Signed URLs contain credentials; keep them out of logs and errors.
            print("[ClothingImageEditorSheet] image_load_failed")
            errorMessage = "The photo could not be loaded. Please try again."
        }
    }

    @MainActor
    private func downloadImage(_ rawURL: String) async throws -> UIImage {
        guard let url = ImageURLResolver.resolve(rawURL) else {
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 30
        request.cachePolicy = .reloadIgnoringLocalCacheData
        let (data, response) = try await URLSession.shared.data(for: request)
        try Task.checkCancellation()
        guard let httpResponse = response as? HTTPURLResponse,
              (200..<300).contains(httpResponse.statusCode) else {
            throw URLError(.badServerResponse)
        }
        guard let image = UIImage(data: data)?.normalizedImage() else {
            throw URLError(.cannotDecodeContentData)
        }
        return image
    }

    private func rotate(byQuarterTurns delta: Int) async {
        guard let previewImage else { return }
        isRotating = true
        errorMessage = nil
        self.previewImage = Self.rotateImage(previewImage, quarterTurns: delta)
        rotationQuarterTurns = Self.normalizedQuarterTurns(rotationQuarterTurns + delta)
        resetEditorState()
        isRotating = false
    }

    private func save() async {
        print(
            "[ClothingImageEditorSheet] save tapped",
            "title=\(title)",
            "editor_side=\(Int(editorSide.rounded()))",
            "rotation_quarter_turns=\(rotationQuarterTurns)",
            "zoom_scale=\(String(format: "%.3f", zoomScale))",
            "drag_x=\(String(format: "%.2f", dragOffset.width))",
            "drag_y=\(String(format: "%.2f", dragOffset.height))"
        )
        guard let renderedData = await renderCroppedJPEGData() else {
            print("[ClothingImageEditorSheet] save failed", "reason=render_returned_nil")
            errorMessage = "The edited photo could not be prepared."
            return
        }
        let ownedRenderedData = Self.ownedDataCopy(renderedData)
        guard !ownedRenderedData.isEmpty else {
            print("[ClothingImageEditorSheet] save failed", "reason=render_returned_empty_data")
            errorMessage = "The edited photo is empty. Please try rotating or cropping again."
            return
        }

        print(
            "[ClothingImageEditorSheet] save prepared",
            "rendered_bytes=\(renderedData.count)",
            "owned_rendered_bytes=\(ownedRenderedData.count)"
        )

        isSaving = true
        errorMessage = nil
        let payload = ownedRenderedData
        let editMetadata = ImageEditMetadataDTO(
            rotationQuarterTurns: rotationQuarterTurns,
            zoomScale: Double(zoomScale),
            dragX: Double(dragOffset.width),
            dragY: Double(dragOffset.height),
            editorSide: Double(editorSide)
        )
        let result = await onSave(payload, editMetadata)
        isSaving = false

        switch result {
        case .success:
            dismiss()
        case .failure(let message):
            errorMessage = message
        }
    }

    private func resetEditorState() {
        dragOffset = .zero
        committedOffset = .zero
        zoomScale = 1
        committedZoomScale = 1
    }

    private func renderCroppedJPEGData() async -> Data? {
        guard let originalImage,
              editorSide > 0 else {
            print(
                "[ClothingImageEditorSheet] render aborted",
                "has_original_image=\(originalImage != nil)",
                "editor_side=\(editorSide)"
            )
            return nil
        }

        let rotationQuarterTurns = rotationQuarterTurns
        let dragOffset = dragOffset
        let zoomScale = zoomScale
        let editorSide = editorSide

        let rotatedImage = originalImage.rotatedQuarterTurns(rotationQuarterTurns)
        guard let cgImage = rotatedImage.cgImage else {
            print("[ClothingImageEditorSheet] render failed", "reason=missing_cgimage_after_rotation")
            return nil
        }

        let imageSize = CGSize(width: cgImage.width, height: cgImage.height)
        let squareSide = editorSide
        let baseScale = max(squareSide / imageSize.width, squareSide / imageSize.height)
        let totalScale = baseScale * zoomScale
        let scaledSize = CGSize(width: imageSize.width * totalScale, height: imageSize.height * totalScale)
        let maxHorizontalShift = max((scaledSize.width - squareSide) / 2, 0)
        let maxVerticalShift = max((scaledSize.height - squareSide) / 2, 0)

        let clampedX = min(max(dragOffset.width, -maxHorizontalShift), maxHorizontalShift)
        let clampedY = min(max(dragOffset.height, -maxVerticalShift), maxVerticalShift)

        let originX = ((scaledSize.width - squareSide) / 2 - clampedX) / totalScale
        let originY = ((scaledSize.height - squareSide) / 2 - clampedY) / totalScale
        let cropSide = squareSide / totalScale
        let cropRect = CGRect(x: originX, y: originY, width: cropSide, height: cropSide)
            .intersection(CGRect(origin: .zero, size: imageSize))
            .integral

        print(
            "[ClothingImageEditorSheet] render crop",
            "image_width=\(cgImage.width)",
            "image_height=\(cgImage.height)",
            "base_scale=\(String(format: "%.5f", baseScale))",
            "total_scale=\(String(format: "%.5f", totalScale))",
            "crop_x=\(Int(cropRect.origin.x.rounded()))",
            "crop_y=\(Int(cropRect.origin.y.rounded()))",
            "crop_w=\(Int(cropRect.width.rounded()))",
            "crop_h=\(Int(cropRect.height.rounded()))"
        )

        guard cropRect.width > 1, cropRect.height > 1 else {
            print("[ClothingImageEditorSheet] render failed", "reason=invalid_crop_rect")
            return nil
        }

        guard let croppedCGImage = cgImage.cropping(to: cropRect) else {
            print("[ClothingImageEditorSheet] render failed", "reason=cgimage_crop_failed")
            return nil
        }

        let croppedImage = UIImage(cgImage: croppedCGImage)
        let exportImage = croppedImage.resizedForEditing(maxDimension: exportMaxDimension)
        guard let jpegData = exportImage.jpegData(compressionQuality: exportJPEGQuality) else {
            print("[ClothingImageEditorSheet] render failed", "reason=jpeg_encoding_failed")
            return nil
        }
        let ownedJPEGData = Data(jpegData)
        print(
            "[ClothingImageEditorSheet] render success",
            "export_width=\(Int(exportImage.size.width.rounded()))",
            "export_height=\(Int(exportImage.size.height.rounded()))",
            "jpeg_bytes=\(jpegData.count)",
            "owned_jpeg_bytes=\(ownedJPEGData.count)"
        )
        return ownedJPEGData
    }

    private static func makePreviewImage(from image: UIImage, maxDimension: CGFloat) -> UIImage {
        image.resizedForEditing(maxDimension: maxDimension)
    }

    private static func rotateImage(_ image: UIImage, quarterTurns: Int) -> UIImage {
        let normalizedQuarterTurns = normalizedQuarterTurns(quarterTurns)
        guard normalizedQuarterTurns != 0 else {
            return image
        }
        return image.rotatedQuarterTurns(normalizedQuarterTurns)
    }

    private static func normalizedQuarterTurns(_ turns: Int) -> Int {
        let remainder = turns % 4
        return remainder >= 0 ? remainder : remainder + 4
    }

    private static func ownedDataCopy(_ data: Data) -> Data {
        data.withUnsafeBytes { Data($0) }
    }
}
