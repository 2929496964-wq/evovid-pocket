// 原生创作状态机：先验收输出再显示成功，取消/异常不覆盖旧成果。
import Foundation
import SwiftUI
@MainActor final class Studio:ObservableObject {
    @Published var brief="A neighborhood coffee shop. Slow mornings, carefully crafted coffee."
    @Published var board=Board.template("A neighborhood coffee shop. Slow mornings, carefully crafted coffee.")
    @Published var movieURL:URL?
    @Published var status="Offline template ready. Edit the brief or scenes before rendering."
    @Published var busy=false
    private var task:Task<Void,Never>?
    // 只产生可编辑分镜，不自动开始编码。
    func plan(){guard !busy else{return};board=Board.template(brief);status="Three scenes from an offline template, not an LLM."}
    // 后台非隔离 async 函数负责 CPU/GPU 编码，主 actor 只更新界面。
    func render(){
        guard !busy else{return}
        let snapshot=board
        do{try snapshot.validate()}catch{status=error.localizedDescription;return}
        busy=true;status="Rendering on this device. No upload or neural model."
        task=Task{[weak self] in
            do{let url=try await LocalRenderer.render(snapshot);self?.movieURL=url;self?.status="Video ready: 720 × 1280, silent MP4. Review before sharing."}
            catch is CancellationError{self?.status="Cancelled. No finished video claimed."}
            catch{self?.status=error.localizedDescription}
            self?.busy=false
        }
    }
    func cancel(){task?.cancel()}
}
