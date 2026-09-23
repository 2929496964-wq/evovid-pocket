// 隔离的参赛原生版；无个人记忆、私密 API key 或自动支付。
import SwiftUI
import AVKit
@main struct EvoVidPocketApp:App {var body:some Scene{WindowGroup{PocketView()}}}
struct PocketView:View {
    @StateObject private var studio=Studio()
    @StateObject private var store=EntitlementStore()
    @StateObject private var desktop=EvoClient()
    @State private var testKey=""
    @State private var showingPreview=false
    var body:some View {
        TabView {
            NavigationStack {
                ScrollView {
                    VStack(alignment:.leading,spacing:20){
                        Label("YOUR IDEA. YOUR DEVICE.",systemImage:"sparkles").font(.caption.bold()).foregroundStyle(.teal)
                        Text("A small story,\nready to move.").font(.largeTitle.bold())
                        Text("Offline by default. From a short brief to a video you can review.").foregroundStyle(.secondary)
                        GroupBox("1 · Brief"){
                            VStack(alignment:.leading,spacing:10){
                                TextEditor(text:$studio.brief).frame(height:80).accessibilityIdentifier("brief")
                                Button("Build editable storyboard"){studio.plan()}.disabled(studio.busy)
                                Text("Deterministic template, not an LLM. Nothing is uploaded.").font(.caption).foregroundStyle(.secondary)
                            }.padding(5)
                        }
                        GroupBox("2 · Storyboard"){
                            VStack(alignment:.leading,spacing:12){
                                ForEach(studio.board.scenes.indices,id:\.self){i in
                                    VStack(alignment:.leading,spacing:6){
                                        Text("SHOT \(i+1) · \(studio.board.scenes[i].seconds) SEC").font(.caption.bold()).foregroundStyle(.teal)
                                        TextField("Title",text:$studio.board.scenes[i].title).textFieldStyle(.roundedBorder)
                                        TextField("Caption",text:$studio.board.scenes[i].caption,axis:.vertical).textFieldStyle(.roundedBorder)
                                    }
                                }
                            }.padding(5).disabled(studio.busy)
                        }
                        GroupBox("3 · Local video"){
                            VStack(alignment:.leading,spacing:12){
                                Button(studio.busy ? "Rendering…" : "Render local video"){studio.render()}.buttonStyle(.borderedProminent).disabled(studio.busy).accessibilityIdentifier("renderLocal")
                                if studio.busy{ProgressView();Button("Cancel render"){studio.cancel()}}
                                Text(studio.status).accessibilityIdentifier("localStatus")
                                Text("720 × 1280 · Silent MP4 · Native motion graphics, not neural video").font(.caption).foregroundStyle(.secondary)
                                if let url=studio.movieURL{
                                    Button("Preview video"){showingPreview=true}.accessibilityIdentifier("previewVideo")
                                    ShareLink(item:url){Label("Share video · Free",systemImage:"square.and.arrow.up")}
                                }
                                if store.isPro{ShareLink(item:studio.board.text){Label("Export storyboard · Pro",systemImage:"doc.text")}.accessibilityIdentifier("proExport")}
                                else{Label("Storyboard export · Pro locked",systemImage:"lock").font(.caption)}
                            }.padding(5)
                        }
                    }.padding(22).frame(maxWidth:720)
                }.navigationTitle("EvoVid Pocket")
            }.tabItem{Label("Create",systemImage:"square.and.pencil")}
            NavigationStack {
                ScrollView{
                    VStack(alignment:.leading,spacing:20){
                        Text("Keep the core free.").font(.largeTitle.bold())
                        Text("Video rendering stays free. Pro unlocks portable storyboard export.").foregroundStyle(.secondary)
                        Label("TEST STORE ONLY · NO REAL CHARGE",systemImage:"checkmark.shield").font(.caption.bold()).foregroundStyle(.teal)
                        SecureField("Public Test Store SDK key (test_)",text:$testKey).textFieldStyle(.roundedBorder).textInputAutocapitalization(.never).autocorrectionDisabled()
                        Button("Connect RevenueCat Test Store"){store.configure(testKey)}.disabled(store.busy)
                        Text(store.status).accessibilityIdentifier("purchaseState")
                        ForEach(store.packages,id:\.identifier){item in
                            Button("Test purchase · "+item.storeProduct.localizedPriceString){store.purchase(item)}.buttonStyle(.borderedProminent).disabled(store.busy)
                        }
                        HStack{Button("Refresh status"){store.refresh()};Button("Restore purchases"){store.restore()}}.disabled(!store.configured || store.busy)
                        if store.busy{ProgressView()}
                        Label(store.isPro ? "SDK returned active pro" : "Pro locked",systemImage:store.isPro ? "lock.open":"lock")
                        Text("Only an active RevenueCat entitlement unlocks export. No hardcoded success flag.").font(.caption).foregroundStyle(.secondary)
                        Text(store.proof).font(.caption.monospaced()).textSelection(.enabled)
                        if store.isPro{ShareLink(item:store.proof){Text("Share redacted verification record")}}
                    }.padding(22).frame(maxWidth:720)
                }.navigationTitle("Test Store")
            }.tabItem{Label("Test Store",systemImage:"creditcard")}
            NavigationStack{
                ScrollView{
                    VStack(alignment:.leading,spacing:18){
                        Text("Your desktop, connected.").font(.largeTitle.bold())
                        Text("Optional. Pair only with your own running EvoVid Workbench. Native offline rendering needs no server.").foregroundStyle(.secondary)
                        TextField("Desktop URL",text:$desktop.base).textFieldStyle(.roundedBorder).textInputAutocapitalization(.never).autocorrectionDisabled()
                        SecureField("Pairing token",text:$desktop.token).textFieldStyle(.roundedBorder)
                        Button("Pair desktop"){Task{await desktop.connect()}}
                        Picker("Planner",selection:$desktop.planner){Text("Offline template").tag("template");Text("Configured LLM").tag("llm")}
                        Text("LLM mode uses your desktop provider and quota only after you start a task.").font(.caption).foregroundStyle(.secondary)
                        Button("Send this brief to desktop"){desktop.prompt=studio.brief;Task{await desktop.create()}}.disabled(desktop.busy)
                        Button("Cancel desktop task"){Task{await desktop.cancel()}}.disabled(!desktop.busy)
                        Text(desktop.status)
                        if let url=desktop.movieURL{ShareLink(item:url){Text("Share desktop result")}}
                    }.padding(22).frame(maxWidth:720)
                }.navigationTitle("EvoBridge")
            }.tabItem{Label("Desktop",systemImage:"desktopcomputer")}
        }.tint(.teal).sheet(isPresented:$showingPreview){
            NavigationStack{if let url=studio.movieURL{PlayerView(url:url).navigationTitle("Video preview").toolbar{ToolbarItem(placement:.confirmationAction){Button("Done"){showingPreview=false}}}}}
        }
    }
}
private struct PlayerView:View {
    let url:URL
    @State private var player:AVPlayer?
    var body:some View{VideoPlayer(player:player).onAppear{player=AVPlayer(url:url);player?.play()}.onDisappear{player?.pause()}}
}
