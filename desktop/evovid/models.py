"""受约束的任务协议；模型输出也必须经过相同验证，不能任意运行代码。"""
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict
class Scene(BaseModel):
    """单镜头文案和长度；不允许模型指定文件路径或系统命令。"""
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=70)
    caption: str = Field(default="", max_length=180)
    seconds: int = Field(default=3, ge=2, le=6)
class Storyboard(BaseModel):
    """用于可重复渲染的结构化脚本。"""
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=100)
    scenes: list[Scene] = Field(min_length=2, max_length=5)
class CreateJob(BaseModel):
    """明确区分可离线运行的模板与需要用户配置的真实大模型规划。"""
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=2, max_length=1000)
    planner: Literal["template", "llm"] = "template"
    profile: Literal["rise", "opencv", "pocket"] = "rise"
    renderer: Literal["motion", "comfy"] = "motion"
    inject_dark_scene: bool = False
