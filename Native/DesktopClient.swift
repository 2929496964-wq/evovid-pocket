// 对接真实桌面 API。配对令牌只驻内存，不写入开源源码或演示截图。
import Foundation
import SwiftUI
struct JobResult: Decodable { let storyboard: Board; let llm_used: Bool; let repair_success: Bool }
struct Job: Decodable, Identifiable { let id: String; let status: String; let result: JobResult?; let error: String? }
@MainActor final class EvoClient: ObservableObject {
    @Published var base = "http://127.0.0.1:8080"
    @Published var token = ""
    @Published var prompt = "A local coffee shop. Slow mornings, carefully crafted coffee."
    @Published var planner = "template"
    @Published var faultTest = false
    @Published var job: Job?
    @Published var status = "Connect to your own desktop service."
    @Published var movieURL: URL?
    @Published var busy = false
    private var watch: Task<Void, Never>?
    private func request(_ path: String, method: String = "GET", body: Data? = nil) async throws -> Data {
        guard let url = URL(string: base.trimmingCharacters(in: .whitespacesAndNewlines) + path),
              ["https", "http"].contains(url.scheme ?? ""), let host = url.host,
              url.user == nil, url.password == nil else { throw URLError(.badURL) }
        // HTTP 仅面向本机/私网。远程服务必须 HTTPS；不是公网可用性证明。
        let privateHost = host == "localhost" || host == "127.0.0.1" || host.hasPrefix("192.168.") || host.hasPrefix("10.") || host.hasSuffix(".local")
        guard url.scheme == "https" || privateHost else { throw URLError(.appTransportSecurityRequiresSecureConnection) }
        guard token.count >= 32 else { throw NSError(domain: "EvoVid", code: 401, userInfo: [NSLocalizedDescriptionKey:"Enter the desktop pairing token."]) }
        var req = URLRequest(url: url); req.httpMethod = method; req.httpBody = body; req.timeoutInterval = 90
        req.setValue(token, forHTTPHeaderField: "X-EvoVid-Token")
        if body != nil { req.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        let (data, response) = try await URLSession.shared.data(for: req)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw NSError(domain:"EvoVid",code:1,userInfo:[NSLocalizedDescriptionKey:"The desktop request failed. Check pairing and server status."])
        }
        return data
    }
    func connect() async {
        do { _ = try await request("/api/status"); status = "Desktop connected. No cloud upload enabled." }
        catch { status = error.localizedDescription }
    }
    func create() async {
        guard !busy else { return }; busy = true
        do {
            let payload: [String:Any] = ["prompt":prompt,"planner":planner,"profile":"pocket","inject_dark_scene":faultTest]
            let data = try await request("/api/jobs",method:"POST",body:JSONSerialization.data(withJSONObject:payload))
            let result = try JSONDecoder().decode(Job.self,from:data)
            job = result; status = "Queued on your desktop."
            watch?.cancel()
            watch = Task { [weak self] in await self?.poll(result.id) }
        } catch { status = error.localizedDescription; busy = false }
    }
    private func poll(_ id: String) async {
        defer { busy = false }
        for _ in 0..<150 {
            if Task.isCancelled { return }
            do {
                let updated = try JSONDecoder().decode(Job.self,from:await request("/api/jobs/"+id))
                job = updated; status = updated.status
                if updated.status == "completed" {
                    let movie = try await request("/api/jobs/"+id+"/video")
                    let path = FileManager.default.temporaryDirectory.appendingPathComponent("evovid-"+id+".mp4")
                    try movie.write(to:path,options:.atomic)
                    if let old = movieURL, old != path { try? FileManager.default.removeItem(at:old) }
                    movieURL = path; status = "Video ready. Review the output before export."; return
                }
                if ["failed","cancelled","interrupted"].contains(updated.status) { status=updated.error ?? updated.status; return }
                try await Task.sleep(nanoseconds: 2_000_000_000)
            } catch { status = error.localizedDescription; return }
        }
        status = "Polling stopped. The desktop task may still be running."
    }
    func cancel() async {
        guard let id=job?.id else { return }
        do { _ = try await request("/api/jobs/"+id+"/cancel",method:"POST"); status="Cancel requested." }
        catch { status=error.localizedDescription }
    }
    func storyboardText() -> String {
        guard let board=job?.result?.storyboard else { return "No completed storyboard." }
        return board.title+"\n\n"+board.scenes.map { "\($0.title) (\($0.seconds)s)\n\($0.caption)" }.joined(separator:"\n\n")
    }
}
