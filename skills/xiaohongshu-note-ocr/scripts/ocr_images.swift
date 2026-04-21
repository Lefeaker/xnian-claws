#!/usr/bin/env swift
import Foundation
import Vision

struct ManifestImage: Codable {
    let index: Int
    let path: String?
}

struct Manifest: Codable {
    let title: String?
    let source_url: String?
    let note_url: String?
    let images: [ManifestImage]
}

func argValue(_ name: String, in args: [String]) -> String? {
    guard let index = args.firstIndex(of: name), index + 1 < args.count else {
        return nil
    }
    return args[index + 1]
}

func usage() {
    print("""
    Usage:
      swift ocr_images.swift --manifest <manifest.json> --output <raw-ocr.md>
    """)
}

func ocrImage(_ url: URL) throws -> String {
    let handler = VNImageRequestHandler(url: url)
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.customWords = ["小红书", "盈余", "认识论", "菲洛波诺斯", "阿布", "哈希姆"]
    try handler.perform([request])

    let observations = (request.results ?? []).sorted {
        if abs($0.boundingBox.midY - $1.boundingBox.midY) > 0.01 {
            return $0.boundingBox.midY > $1.boundingBox.midY
        }
        return $0.boundingBox.minX < $1.boundingBox.minX
    }

    let avgHeight = observations.isEmpty
        ? 0.0
        : observations.map { $0.boundingBox.height }.reduce(0, +) / Double(observations.count)
    var lines: [String] = []
    var previous: VNRecognizedTextObservation?

    for observation in observations {
        guard let candidate = observation.topCandidates(1).first else { continue }
        let text = candidate.string.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty { continue }

        if let previous = previous {
            let gap = previous.boundingBox.minY - observation.boundingBox.maxY
            if gap > avgHeight * 0.65 {
                lines.append("")
            }
        }

        lines.append(text)
        previous = observation
    }

    return lines.joined(separator: "\n")
}

let args = CommandLine.arguments
if args.contains("--help") || args.count == 1 {
    usage()
    exit(0)
}

guard let manifestPath = argValue("--manifest", in: args),
      let outputPath = argValue("--output", in: args) else {
    usage()
    exit(2)
}

let manifestURL = URL(fileURLWithPath: NSString(string: manifestPath).expandingTildeInPath)
let outputURL = URL(fileURLWithPath: NSString(string: outputPath).expandingTildeInPath)
let manifestDir = manifestURL.deletingLastPathComponent()
let data = try Data(contentsOf: manifestURL)
let manifest = try JSONDecoder().decode(Manifest.self, from: data)

var markdown = "# \(manifest.title ?? "小红书笔记") OCR\n\n"
if let sourceURL = manifest.source_url {
    markdown += "- 来源: \(sourceURL)\n"
}
if let noteURL = manifest.note_url {
    markdown += "- 笔记页: \(noteURL)\n"
}
markdown += "- 图片数: \(manifest.images.count)\n\n"

for image in manifest.images.sorted(by: { $0.index < $1.index }) {
    guard let imagePath = image.path else {
        fputs("missing path for image \(image.index)\n", stderr)
        exit(3)
    }
    let imageURL: URL
    if imagePath.hasPrefix("/") {
        imageURL = URL(fileURLWithPath: imagePath)
    } else {
        imageURL = manifestDir.appendingPathComponent(imagePath)
    }
    let text = try ocrImage(imageURL)
    markdown += "## 图 \(String(format: "%02d", image.index))\n\n"
    markdown += "```text\n"
    markdown += text
    markdown += "\n```\n\n"
}

try FileManager.default.createDirectory(at: outputURL.deletingLastPathComponent(), withIntermediateDirectories: true)
try markdown.write(to: outputURL, atomically: true, encoding: .utf8)
print(outputURL.path)
