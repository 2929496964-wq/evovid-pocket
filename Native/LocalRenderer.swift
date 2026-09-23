// 本机 AVFoundation 编码；后台只绘制通用文字/几何图案，绝非神经视频生成。
import Foundation
import AVFoundation
import UIKit
import CoreVideo
struct LocalRenderer {
    // 编码失败删除不完整输出，成功前不会返回成片路径。
    static func render(_ board:Board) async throws -> URL {
        try board.validate()
        let folder=FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0]
        let url=folder.appendingPathComponent("evovid-\(UUID().uuidString).mp4")
        let writer=try AVAssetWriter(outputURL:url,fileType:.mp4)
        let width=720,height=1280,fps=24
        let input=AVAssetWriterInput(mediaType:.video,outputSettings:[
            AVVideoCodecKey:AVVideoCodecType.h264,AVVideoWidthKey:width,AVVideoHeightKey:height,
            AVVideoCompressionPropertiesKey:[AVVideoAverageBitRateKey:2_000_000]])
        input.expectsMediaDataInRealTime=false
        let adaptor=AVAssetWriterInputPixelBufferAdaptor(assetWriterInput:input,sourcePixelBufferAttributes:[
            kCVPixelBufferPixelFormatTypeKey as String:kCVPixelFormatType_32ARGB,
            kCVPixelBufferWidthKey as String:width,kCVPixelBufferHeightKey as String:height,
            kCVPixelBufferCGImageCompatibilityKey as String:true,kCVPixelBufferCGBitmapContextCompatibilityKey as String:true])
        guard writer.canAdd(input) else {throw StudioError.encoding("Input unavailable")}
        writer.add(input)
        guard writer.startWriting() else {throw StudioError.encoding(writer.error?.localizedDescription ?? "Could not start")}
        writer.startSession(atSourceTime:.zero)
        var index=0
        let deadline=Date().addingTimeInterval(110)
        do {
            for (sceneIndex,scene) in board.scenes.enumerated() {
                for frame in 0..<(scene.seconds*fps) {
                    try Task.checkCancellation()
                    while !input.isReadyForMoreMediaData {
                        guard writer.status != .failed else {throw StudioError.encoding(writer.error?.localizedDescription ?? "Encoder failed")}
                        guard Date()<deadline else {throw StudioError.timeout}
                        try await Task.sleep(nanoseconds:10_000_000);try Task.checkCancellation()
                    }
                    guard Date()<deadline else {throw StudioError.timeout}
                    let pixel=try autoreleasepool {try draw(scene,index:sceneIndex,progress:Double(frame)/Double(scene.seconds*fps),width:width,height:height)}
                    guard adaptor.append(pixel,withPresentationTime:CMTime(value:Int64(index),timescale:Int32(fps))) else {
                        throw StudioError.encoding(writer.error?.localizedDescription ?? "Append failed")
                    }
                    index+=1
                }
            }
            input.markAsFinished()
            writer.endSession(atSourceTime:CMTime(value:Int64(index),timescale:Int32(fps)))
            await writer.finishWriting()
            guard writer.status == .completed else {throw StudioError.encoding(writer.error?.localizedDescription ?? "Incomplete file")}
            return url
        } catch {writer.cancelWriting();try? FileManager.default.removeItem(at:url);throw error}
    }
    // 每帧使用系统字体和自绘背景，不包含私人图像或第三方字体。
    private static func draw(_ scene:SceneItem,index:Int,progress:Double,width:Int,height:Int) throws -> CVPixelBuffer {
        var result:CVPixelBuffer?
        let attrs:[CFString:Any]=[kCVPixelBufferCGImageCompatibilityKey:true,kCVPixelBufferCGBitmapContextCompatibilityKey:true]
        guard CVPixelBufferCreate(kCFAllocatorDefault,width,height,kCVPixelFormatType_32ARGB,attrs as CFDictionary,&result)==kCVReturnSuccess,
              let pixel=result else {throw StudioError.encoding("Pixel buffer unavailable")}
        CVPixelBufferLockBaseAddress(pixel,[]);defer{CVPixelBufferUnlockBaseAddress(pixel,[])}
        guard let ctx=CGContext(data:CVPixelBufferGetBaseAddress(pixel),width:width,height:height,bitsPerComponent:8,bytesPerRow:CVPixelBufferGetBytesPerRow(pixel),space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:CGImageAlphaInfo.noneSkipFirst.rawValue) else {throw StudioError.encoding("No drawing context")}
        ctx.translateBy(x:0,y:CGFloat(height));ctx.scaleBy(x:1,y:-1)
        UIGraphicsPushContext(ctx);defer{UIGraphicsPopContext()}
        UIColor(red:0.04,green:0.09,blue:0.15,alpha:1).setFill();ctx.fill(CGRect(x:0,y:0,width:CGFloat(width),height:CGFloat(height)))
        UIColor(red:0.05,green:0.38,blue:0.38,alpha:1).setFill();ctx.fillEllipse(in:CGRect(x:CGFloat(300+progress*70),y:110,width:650,height:650))
        let style=NSMutableParagraphStyle();style.lineBreakMode = .byWordWrapping
        func text(_ value:String,_ size:CGFloat,_ color:UIColor,_ rect:CGRect) {
            (value as NSString).draw(in:rect,withAttributes:[.font:UIFont.systemFont(ofSize:size,weight:.semibold),.foregroundColor:color,.paragraphStyle:style])
        }
        text("EVOVID POCKET / \(index+1)",25,.white,CGRect(x:58,y:75,width:600,height:65))
        text(scene.title,62,.white,CGRect(x:58,y:350,width:595,height:250))
        text(scene.caption,32,UIColor(white:0.9,alpha:1),CGRect(x:58,y:660,width:595,height:300))
        text("LOCAL MOTION GRAPHICS · SILENT VIDEO",20,UIColor(white:0.7,alpha:1),CGRect(x:58,y:1130,width:610,height:70))
        UIColor.systemTeal.setFill();ctx.fill(CGRect(x:58,y:1070,width:CGFloat(604*progress),height:6))
        return pixel
    }
}
