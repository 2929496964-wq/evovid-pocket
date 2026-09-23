"""生成原创合成测试片：正常曝光、带纹理的低曝光、正常曝光；不冒充实拍。"""
from pathlib import Path
import json, subprocess, sys
import cv2, numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evovid.render import ffmpeg_path
from evovid.vision import analyze_video
from evovid.review import proposal_for, digest_file
ROOT=Path(__file__).resolve().parents[1]


def make_clip(target: Path, scenario: str='lowlight', seconds: int=8) -> None:
    """在固定种子下渲染视频，测试用简单图案不需要外部版权素材或模型。"""
    target.parent.mkdir(parents=True,exist_ok=True)
    raw=target.with_suffix('.avi'); w,h,fps=640,360,15
    writer=cv2.VideoWriter(str(raw),cv2.VideoWriter_fourcc(*'MJPG'),fps,(w,h))
    if not writer.isOpened():raise RuntimeError('Fixture writer unavailable')
    yy,xx=np.mgrid[:h,:w]
    base=np.zeros((h,w,3),np.uint8)
    base[:,:,0]=60+(xx//25%2)*22
    base[:,:,1]=85+(yy//20%2)*25
    base[:,:,2]=105+((xx+yy)//25%2)*26
    try:
        for i in range(seconds*fps):
            t=i/fps; frame=base.copy()
            cv2.rectangle(frame,(20,20),(620,67),(22,31,38),-1)
            cv2.putText(frame,'EVOVID / SYNTHETIC TEST FOOTAGE',(32,50),cv2.FONT_HERSHEY_SIMPLEX,.64,(238,245,235),1,cv2.LINE_AA)
            cv2.circle(frame,(int(70+500*((t%2)/2)),174),42,(60,180,222),-1)
            cv2.putText(frame,'Visible texture. Traceable decisions.',(35,280),cv2.FONT_HERSHEY_SIMPLEX,.7,(240,230,210),2,cv2.LINE_AA)
            cv2.putText(frame,f'{t:04.1f}s / NOT CAMERA FOOTAGE',(35,329),cv2.FONT_HERSHEY_SIMPLEX,.48,(215,237,247),1,cv2.LINE_AA)
            if scenario in ('lowlight','intentional_night') and 2<=t<4:
                frame=(frame.astype(np.float32)*.15).astype(np.uint8)
            elif scenario=='black' and 2<=t<4:
                frame[:]=0
            elif scenario=='static':
                frame=base.copy()
            writer.write(frame)
    finally:writer.release()
    try:
        # 音轨是合成低音量测试音；用于验证预览不会丢掉原有音轨。
        subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y','-i',str(raw),
            '-f','lavfi','-i',f'sine=frequency=440:sample_rate=44100:duration={seconds}',
            '-map','0:v:0','-map','1:a:0','-c:v','libx264','-crf','22','-threads','2',
            '-filter_threads','1','-pix_fmt','yuv420p','-af','volume=0.025','-c:a','aac',
            '-b:a','64k','-shortest','-movflags','+faststart',str(target)],check=True,timeout=60)
    finally:raw.unlink(missing_ok=True)


if __name__=='__main__':
    file=ROOT/'submission-assets'/'demo-input.mp4';make_clip(file)
    report=analyze_video(file, sample_count=60)
    evidence={'origin':'Original programmatically rendered synthetic test fixture, not neural video or camera footage',
        'scenario':'2.0–4.0 seconds deliberately dimmed to 15% of source signal; synthesized low-volume test tone',
        'sha256':digest_file(file),'metrics':report,'proposal':proposal_for(report)}
    (ROOT/'submission-assets'/'demo-provenance.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print(json.dumps({'file':str(file),'mean':report['mean_luma'],'proposal':evidence['proposal']}))
