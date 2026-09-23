"""可选 ComfyUI 接口。仅使用用户已审查并以 SHA256 批准的本地工作流，不下载模型。"""
from pathlib import Path, PurePosixPath
import hashlib,json,os,time,uuid,urllib.parse
import httpx


def approved_workflow():
    """工作流在启动机器上配置；HTTP 调用者不能指定路径、节点代码或外部服务器。"""
    path=Path(os.environ.get('EVOVID_COMFY_WORKFLOW','__missing_workflow__'))
    expected=os.environ.get('EVOVID_COMFY_WORKFLOW_SHA256','')
    if not path.is_file() or path.stat().st_size>1024*1024:
        raise ValueError('A reviewed ComfyUI API workflow is required (maximum 1 MB).')
    raw=path.read_bytes()
    if len(expected)!=64 or hashlib.sha256(raw).hexdigest()!=expected:
        raise ValueError('ComfyUI workflow SHA256 approval is missing or no longer matches.')
    board=json.loads(raw)
    if not isinstance(board,dict) or not board or len(board)>200:
        raise ValueError('Expected a bounded exported API workflow, not a UI project file.')
    if not all(isinstance(v,dict) and isinstance(v.get('class_type'),str) and isinstance(v.get('inputs'),dict) for v in board.values()):
        raise ValueError('Invalid ComfyUI API workflow nodes.')
    # Custom nodes are executable local software; approval requires reviewing their network/model behavior.
    return board


def run_comfy(prompt:str,target:Path,stop=lambda:False,client=None,max_wait:float=180):
    """提交、按本任务 ID 轮询、下载一个 MP4。超时只取消本任务排队项，不全局 interrupt。"""
    base=os.environ.get('EVOVID_COMFY_URL','http://127.0.0.1:8188').rstrip('/')
    p=urllib.parse.urlparse(base)
    if p.hostname not in ('127.0.0.1','localhost','::1') or p.scheme not in ('http','https') or p.username or p.password or p.query or p.fragment:
        raise ValueError('ComfyUI is restricted to a loopback server in this build.')
    workflow=approved_workflow();replacements=0
    def replace(v):
        """只替换文本占位符，不执行模型文本或把用户输入当工作流 JSON。"""
        nonlocal replacements
        if isinstance(v,str) and '{{EVOVID_PROMPT}}' in v:
            replacements+=1;return v.replace('{{EVOVID_PROMPT}}',prompt)
        if isinstance(v,dict):return {k:replace(x) for k,x in v.items()}
        if isinstance(v,list):return [replace(x) for x in v]
        return v
    workflow=replace(workflow)
    if replacements==0:raise ValueError('The reviewed workflow must contain {{EVOVID_PROMPT}} in a text input.')
    c=client or httpx.Client(timeout=20,follow_redirects=False);owned=client is None
    prompt_id=None;complete=False;started=time.monotonic()
    try:
        if stop():raise InterruptedError('Cancelled.')
        r=c.post(base+'/prompt',json={'prompt':workflow,'client_id':'evovid-'+uuid.uuid4().hex})
        r.raise_for_status();prompt_id=r.json().get('prompt_id')
        if not isinstance(prompt_id,str) or len(prompt_id)>100 or not all(x.isalnum() or x in '-_' for x in prompt_id):
            raise ValueError('Invalid ComfyUI prompt id.')
        while time.monotonic()-started<max_wait:
            if stop():raise InterruptedError('Cancelled; an already-running local ComfyUI job may still finish.')
            r=c.get(base+'/history/'+prompt_id);r.raise_for_status();history=r.json().get(prompt_id,{})
            if history.get('status',{}).get('status_str')=='error':raise RuntimeError('ComfyUI reported execution error.')
            candidates=[]
            for node in history.get('outputs',{}).values():
                if not isinstance(node,dict):continue
                for value in node.values():
                    if isinstance(value,list):
                        candidates.extend(x for x in value if isinstance(x,dict) and str(x.get('filename','')).lower().endswith('.mp4'))
            if candidates:
                item=candidates[0];name=item['filename'];sub=str(item.get('subfolder',''));kind=item.get('type','output')
                if '/' in name or '\\' in name or '..' in PurePosixPath(sub).parts or sub.startswith('/') or '\\' in sub or kind not in ('output','temp'):
                    raise ValueError('Unsafe ComfyUI output descriptor.')
                target=Path(target);temp=target.with_suffix('.part');target.parent.mkdir(parents=True,exist_ok=True)
                try:
                    with c.stream('GET',base+'/view',params={'filename':name,'subfolder':sub,'type':kind}) as response:
                        response.raise_for_status();size=0
                        with temp.open('wb') as out:
                            for chunk in response.iter_bytes():
                                if stop():raise InterruptedError('Cancelled while downloading local output.')
                                size+=len(chunk)
                                if size>32*1024*1024:raise ValueError('ComfyUI output exceeds 32 MB.')
                                out.write(chunk)
                    if not size:raise ValueError('Empty ComfyUI output.')
                    temp.replace(target);complete=True;return target
                finally:temp.unlink(missing_ok=True)
            if history.get('status',{}).get('completed'):raise ValueError('Workflow completed without MP4; configure an MP4 output node.')
            time.sleep(.5)
        raise TimeoutError('ComfyUI timed out; an already-running workflow may still finish.')
    finally:
        if prompt_id and not complete:
            try:c.post(base+'/queue',json={'delete':[prompt_id]})
            except Exception:pass
        if owned:c.close()
