import SwiftUI
import UIKit

struct CropCanvas: View {
    let image: UIImage
    let cropSide: CGFloat

    @Binding var dragOffset: CGSize
    @Binding var committedOffset: CGSize
    @Binding var zoomScale: CGFloat
    @Binding var committedZoomScale: CGFloat

    var body: some View {
        let imageSize = image.size
        let baseScale = max(cropSide / imageSize.width, cropSide / imageSize.height)
        let scaledSize = CGSize(
            width: imageSize.width * baseScale * zoomScale,
            height: imageSize.height * baseScale * zoomScale
        )
        let maxHorizontalShift = max((scaledSize.width - cropSide) / 2, 0)
        let maxVerticalShift = max((scaledSize.height - cropSide) / 2, 0)

        ZStack {
            Image(uiImage: image)
                .resizable()
                .interpolation(.medium)
                .frame(width: scaledSize.width, height: scaledSize.height)
                .offset(dragOffset)

            RoundedRectangle(cornerRadius: 24)
                .stroke(Color.white.opacity(0.95), lineWidth: 2)
        }
        .frame(width: cropSide, height: cropSide)
        .clipped()
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .contentShape(RoundedRectangle(cornerRadius: 24))
        .gesture(
            SimultaneousGesture(
                DragGesture()
                    .onChanged { value in
                        dragOffset = clampedOffset(
                            CGSize(
                                width: committedOffset.width + value.translation.width,
                                height: committedOffset.height + value.translation.height
                            ),
                            maxHorizontalShift: maxHorizontalShift,
                            maxVerticalShift: maxVerticalShift
                        )
                    }
                    .onEnded { _ in
                        committedOffset = dragOffset
                    },
                MagnificationGesture()
                    .onChanged { value in
                        zoomScale = clampedZoomScale(committedZoomScale * value)
                        let currentScaledSize = CGSize(
                            width: imageSize.width * baseScale * zoomScale,
                            height: imageSize.height * baseScale * zoomScale
                        )
                        dragOffset = clampedOffset(
                            dragOffset,
                            maxHorizontalShift: max((currentScaledSize.width - cropSide) / 2, 0),
                            maxVerticalShift: max((currentScaledSize.height - cropSide) / 2, 0)
                        )
                    }
                    .onEnded { value in
                        zoomScale = clampedZoomScale(committedZoomScale * value)
                        committedZoomScale = zoomScale
                        let currentScaledSize = CGSize(
                            width: imageSize.width * baseScale * zoomScale,
                            height: imageSize.height * baseScale * zoomScale
                        )
                        let clamped = clampedOffset(
                            dragOffset,
                            maxHorizontalShift: max((currentScaledSize.width - cropSide) / 2, 0),
                            maxVerticalShift: max((currentScaledSize.height - cropSide) / 2, 0)
                        )
                        dragOffset = clamped
                        committedOffset = clamped
                    }
            )
        )
    }

    private func clampedOffset(
        _ offset: CGSize,
        maxHorizontalShift: CGFloat,
        maxVerticalShift: CGFloat
    ) -> CGSize {
        CGSize(
            width: min(max(offset.width, -maxHorizontalShift), maxHorizontalShift),
            height: min(max(offset.height, -maxVerticalShift), maxVerticalShift)
        )
    }

    private func clampedZoomScale(_ value: CGFloat) -> CGFloat {
        min(max(value, 1), 4)
    }
}

extension UIImage {
    func normalizedImage() -> UIImage {
        if imageOrientation == .up {
            return self
        }

        let renderer = UIGraphicsImageRenderer(size: size)
        return renderer.image { _ in
            draw(in: CGRect(origin: .zero, size: size))
        }
    }

    func resizedForEditing(maxDimension: CGFloat) -> UIImage {
        let longestSide = max(size.width, size.height)
        guard longestSide > maxDimension, longestSide > 0 else {
            return self
        }

        let scaleRatio = maxDimension / longestSide
        let targetSize = CGSize(width: size.width * scaleRatio, height: size.height * scaleRatio)
        let renderer = UIGraphicsImageRenderer(size: targetSize)
        return renderer.image { _ in
            draw(in: CGRect(origin: .zero, size: targetSize))
        }
    }

    func rotatedQuarterTurns(_ quarterTurns: Int) -> UIImage {
        switch quarterTurns {
        case 1:
            return rotated(by: .pi / 2)
        case 2:
            return rotated(by: .pi)
        case 3:
            return rotated(by: -.pi / 2)
        default:
            return self
        }
    }

    func rotated(by angle: CGFloat) -> UIImage {
        let normalized = normalizedImage()
        let rotatedBounds = CGRect(origin: .zero, size: normalized.size)
            .applying(CGAffineTransform(rotationAngle: angle))
            .integral
        let outputSize = CGSize(width: abs(rotatedBounds.width), height: abs(rotatedBounds.height))

        let renderer = UIGraphicsImageRenderer(size: outputSize)
        return renderer.image { context in
            let cgContext = context.cgContext
            cgContext.translateBy(x: outputSize.width / 2, y: outputSize.height / 2)
            cgContext.rotate(by: angle)
            normalized.draw(
                in: CGRect(
                    x: -normalized.size.width / 2,
                    y: -normalized.size.height / 2,
                    width: normalized.size.width,
                    height: normalized.size.height
                )
            )
        }
    }
}
