"""安全读取可选 config.local.env。只接受白名单键，不使用 shell/eval，不覆盖已有系统变量。"""
from pathlib import Path
import os
ALLOWED={'EVOVID_HOME','EVOVID_LLM_BASE_URL','EVOVID_LLM_MODEL','EVOVID_LLM_API_KEY',
    'EVOVID_ALLOW_REMOTE_LLM','EVOVID_FONT_PATH','EVOVID_COMFY_URL','EVOVID_COMFY_WORKFLOW','EVOVID_COMFY_WORKFLOW_SHA256'}


def load_local_config(path:Path):
    """空值忽略；已配置的系统环境优先。此文件不能加入公开仓库。"""
    if not path.exists():return
    if path.stat().st_size>16384:raise ValueError('Local config is too large.')
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        key,sep,value=line.partition('=');key=key.strip();value=value.strip()
        if not sep or key not in ALLOWED:raise ValueError('Unsupported local config key.')
        if len(value)>=2 and value[0]==value[-1] and value[0] in '\"\'':value=value[1:-1]
        if value:os.environ.setdefault(key,value)
