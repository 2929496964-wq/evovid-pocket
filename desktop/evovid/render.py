"""真正渲染 H.264 MP4 的本地动效后备引擎。不是文生视频神经网络。"""
from pathlib import Path
import shutil, subprocess, os, textwrap
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageFont
from .models import Storyboard

def ffmpeg_path():
    """优先本机 FFmpeg，再用已安装 imageio-ffmpeg 自带二进制；不自动下载。"""
    p=shutil.which('ffmpeg')
    if p:return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:raise RuntimeError('FFmpeg unavailable. Install the runtime dependencies first.')

def font_path():
    """使用系统已有字体，不打包或上传字体文件。"""
    candidates=[os.getenv('EVOVID_FONT_PATH',''),r'C:\Windows\Fonts\msyh.ttc',r'C:\Windows\Fonts\arial.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/System/Library/Fonts/PingFang.ttc']
    return next((p for p in candidates if p and Path(p).is_file()),None)

def render_storyboard(board:Storyboard,target:Path,dark_scene=False,stop=lambda:False,width=640,height=360,fps=12):
    """逐镜头绘制文字/几何动效，然后编码视频。注入暗镜头仅用于显式故障测试。"""
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    raw=target.with_suffix('.avi');writer=cv2.VideoWriter(str(raw),cv2.VideoWriter_fourcc(*'MJPG'),fps,(width,height))
    if not writer.isOpened():raise RuntimeError('OpenCV VideoWriter failed to initialize.')
    fp=font_path();font=ImageFont.truetype(fp,25) if fp else ImageFont.load_default()
    small=ImageFont.truetype(fp,15) if fp else ImageFont.load_default()
    try:
        for si,scene in enumerate(board.scenes):
            for fi in range(scene.seconds*fps):
                if stop():raise InterruptedError('Cancelled by user.')
                im=Image.new('RGB',(width,height),(21+si*6,32+si*5,58+si*7));draw=ImageDraw.Draw(im)
                t=fi/(scene.seconds*fps);cx=int(70+(width-140)*t)
                draw.ellipse((cx-95,25,cx+95,215),fill=(47+si*10,80,114))
                draw.rounded_rectangle((25,235,width-25,height-20),radius=18,fill=(243,243,235))
                y=85
                # 中日韩按较短的行宽折行，字体由系统提供。
                line_width=21 if any(ord(ch)>0x3000 for ch in scene.title) else 36
                for line in textwrap.wrap(scene.title,width=line_width)[:3]:
                    draw.text((35,y),line,font=font,fill=(255,255,255));y+=34
                cap_width=34 if any(ord(ch)>0x3000 for ch in scene.caption) else 65
                for k,line in enumerate(textwrap.wrap(scene.caption,width=cap_width)[:2]):
                    draw.text((42,253+23*k),line,font=small,fill=(20,30,40))
                draw.text((35,25),f'EVOVID / SHOT {si+1:02d}',font=small,fill=(210,220,230))
                frame=cv2.cvtColor(np.array(im),cv2.COLOR_RGB2BGR)
                if dark_scene and si==1:frame=(frame.astype(np.float32)*.025).astype(np.uint8)
                writer.write(frame)
    except BaseException:
        writer.release();raw.unlink(missing_ok=True);raise
    finally:writer.release()
    if stop():
        raw.unlink(missing_ok=True);raise InterruptedError('Cancelled by user.')
    try:
        proc=subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y','-i',str(raw),'-an',
             '-c:v','libx264','-threads','2','-pix_fmt','yuv420p','-movflags','+faststart',str(target)],capture_output=True,timeout=90)
        if proc.returncode:raise RuntimeError('FFmpeg encoding failed: '+proc.stderr.decode(errors='replace')[-500:])
    finally:raw.unlink(missing_ok=True)
    return target
