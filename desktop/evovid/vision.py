"""可解释的 OpenCV 质量检测。不能由亮度/锐度推断人物身份或画面语义。"""
from pathlib import Path
import cv2, numpy as np, time

def require_opencv5():
    """正式 OpenCV 赛道执行严格版本门，不将 4.x 实测冒充 5.x。"""
    if cv2.__version__.split('.')[0] != '5':
        raise RuntimeError(f'OpenCV 5 is required for competition validation; installed: {cv2.__version__}')

def analyze_video(path: Path, sample_count: int=24, strict: bool=False):
    """均匀取样亮度、暗像素、拉普拉斯方差和帧差；冻结/模糊仅供人工复核。"""
    if strict: require_opencv5()
    start=time.perf_counter(); cap=cv2.VideoCapture(str(path))
    if not cap.isOpened(): raise ValueError('Video cannot be decoded.')
    try:
        total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); fps=float(cap.get(cv2.CAP_PROP_FPS))
        width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH));height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if total<=0 or fps<=0 or not np.isfinite(fps): raise ValueError('Invalid frame metadata.')
        if min(width,height)<=0 or max(width,height)>1920 or min(width,height)>1080 or total/fps>180: raise ValueError('Limit: 1080p and 180 seconds per audit.')
        frames=[];prev=None
        for idx in np.linspace(0,total-1,min(max(2,sample_count),60,total),dtype=int):
            cap.set(cv2.CAP_PROP_POS_FRAMES,int(idx));ok,frame=cap.read()
            if not ok: continue
            gray=cv2.cvtColor(cv2.resize(frame,(320,180)),cv2.COLOR_BGR2GRAY)
            item={'frame':int(idx),'time':round(idx/fps,3),'mean_luma':round(float(gray.mean()),3),
                  'dark_fraction':round(float((gray<12).mean()),4),
                  'sharpness':round(float(cv2.Laplacian(gray,cv2.CV_64F).var()),3),
                  'frame_delta':None if prev is None else round(float(cv2.absdiff(gray,prev).mean()),3)}
            frames.append(item);prev=gray
        if len(frames)<2:raise ValueError('Insufficient decodable samples.')
        dark=[f for f in frames if f['mean_luma']<20 or f['dark_fraction']>.95]
        issues=[]
        if dark: issues.append({'code':'underexposed','sample_ratio':round(len(dark)/len(frames),3),
            'severity':'review','reason':'Brightness heuristic; an intentional dark shot is not necessarily an error.'})
        deltas=[f['frame_delta'] for f in frames if f['frame_delta'] is not None]
        if deltas and max(deltas)<.6: issues.append({'code':'possibly_static','severity':'info',
            'reason':'Static slides can be intentional. Not automatically rejected or repaired.'})
        return {'opencv_version':cv2.__version__,'opencv5_verified':cv2.__version__.startswith('5.'),
            'width':width,'height':height,'fps':fps,'duration_seconds':round(total/fps,3),
            'sample_count':len(frames),'mean_luma':round(float(np.mean([f['mean_luma'] for f in frames])),3),
            'underexposed':bool(dark),'issues':issues,'samples':frames,
            'analysis_seconds':round(time.perf_counter()-start,4),
            'limitations':['Heuristics are not semantic or identity checks.','Sparse sampling can miss transient defects.',
            'The current demo has no audio stream.','Brightness thresholds have not been calibrated on a real-user dataset.']}
    finally: cap.release()
