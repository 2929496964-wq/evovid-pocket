"""本地模板与可选大模型脚本规划。默认不联网，也不会下载模型。"""
import os, json, re, urllib.parse
import httpx
from .models import Storyboard, Scene

def template_plan(prompt:str):
    """可离线验证的确定性脚本；明确不是 LLM 生成。"""
    topic=prompt.strip()[:65]
    return Storyboard(title=topic,scenes=[Scene(title=topic,caption='A small idea. A clear story.'),
        Scene(title='Make the process visible',caption='Plan > Render > Inspect > Review'),
        Scene(title='Repair only what is measured',caption='Bounded retries, honest limits, local control'),
        Scene(title='Create. Inspect. Export.',caption='EvoVid Creative Workbench')])

def llm_plan(prompt:str,client=None):
    """调用用户配置的 OpenAI-compatible 端点；远程发送必须由配置明确允许。"""
    endpoint=os.getenv('EVOVID_LLM_BASE_URL','http://127.0.0.1:8081/v1').rstrip('/')
    parsed=urllib.parse.urlparse(endpoint)
    local=parsed.hostname in ('localhost','127.0.0.1','::1')
    if parsed.scheme not in ('http','https') or parsed.username or parsed.password:raise ValueError('Invalid LLM endpoint.')
    if not local and (parsed.scheme!='https' or os.getenv('EVOVID_ALLOW_REMOTE_LLM')!='1'):
        raise ValueError('Remote LLM is disabled. Explicit consent via EVOVID_ALLOW_REMOTE_LLM=1 is required.')
    model=os.getenv('EVOVID_LLM_MODEL','')
    if not model:raise ValueError('EVOVID_LLM_MODEL is not configured.')
    key=os.getenv('EVOVID_LLM_API_KEY','')
    schema=Storyboard.model_json_schema()
    payload={'model':model,'temperature':.3,'max_tokens':1100,'messages':[
        {'role':'system','content':'Create a 2-5 scene promotional storyboard. Return only JSON matching this schema. '
        'Do not claim to produce photographic footage. '+json.dumps(schema)}, {'role':'user','content':prompt}]}
    owned=client is None;c=client or httpx.Client(timeout=45,follow_redirects=False)
    try:
        r=c.post(endpoint+'/chat/completions',json=payload,headers={'Authorization':'Bearer '+key} if key else {})
        r.raise_for_status();text=r.json()['choices'][0]['message']['content']
        if not isinstance(text,str) or len(text)>30000:raise ValueError('Invalid or oversized model output.')
        text=re.sub(r'^```(?:json)?\s*|\s*```$','',text.strip())
        return Storyboard.model_validate_json(text)
    finally:
        if owned:c.close()
