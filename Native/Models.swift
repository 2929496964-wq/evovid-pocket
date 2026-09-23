// 可验证的本地分镜协议。模板输出并非 LLM 推理；所有长度在编码前校验。
import Foundation
struct SceneItem: Codable, Equatable, Sendable {
    var title: String; var caption: String; var seconds: Int
}
struct Board: Codable, Equatable, Sendable {
    var title: String; var scenes: [SceneItem]
    var text: String { title + "\n\n" + scenes.enumerated().map { "\($0.offset+1). \($0.element.title) (\($0.element.seconds)s)\n\($0.element.caption)" }.joined(separator: "\n\n") }
    func validate() throws {
        guard !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              title.count <= 160, (1...6).contains(scenes.count),
              scenes.allSatisfy({ (1...8).contains($0.seconds) && !$0.title.isEmpty && $0.title.count <= 100 && $0.caption.count <= 500 }),
              scenes.reduce(0, { $0+$1.seconds }) <= 30 else { throw StudioError.invalidBoard }
    }
    // 此离线模板可编辑，不使用云服务、不调用模型。
    static func template(_ prompt: String) -> Board {
        let s=String(prompt.trimmingCharacters(in: .whitespacesAndNewlines).prefix(120))
        return Board(title:s.isEmpty ? "A small story" : s,scenes:[
            .init(title:"A moment to pause",caption:s.isEmpty ? "Start with one clear idea." : s,seconds:4),
            .init(title:"The detail matters",caption:"Show the care behind what you create.",seconds:4),
            .init(title:"Make it yours",caption:"One small story. A reason to connect.",seconds:4)])
    }
}
enum StudioError: LocalizedError {
    case invalidBoard, encoding(String), timeout
    var errorDescription:String? {
        switch self {
        case .invalidBoard:return "Use 1-6 scenes, 1-8 seconds each, at most 30 seconds total."
        case .encoding(let message):return "Video export failed: "+message
        case .timeout:return "Encoding timed out. No finished video is claimed."
        }
    }
}
