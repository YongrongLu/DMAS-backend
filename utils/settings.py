"""Application settings, loaded from .env

Provides:
- settings:     the global Settings instance

Key constraints:
- every field can be overridden in .env (LLM_BASE_URL, LLM_MODEL, ...)
- the model endpoint is any OpenAI-compatible server (DeepSeek in
  development, vLLM on Brev serving Qwen3-8B or Nemotron 3.5 Lightning);
  switching is a .env change only
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global settings."""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenAI 兼容的模型服务；所有 Agent 共用同一个
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-flash"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 8192
    # vLLM 上的 Qwen3 / Nemotron：通过 chat_template_kwargs 开关思考；留空就不发送（两者默认都思考）
    llm_enable_thinking: bool | None = None
    # 写最终报告时是否思考：思考太长会把 token 用完，报告就是空的
    llm_report_thinking: bool = False

    # 分布式：orchestrator 内嵌的 hub
    hub_host: str = "127.0.0.1"
    hub_port: int = 8800
    task_timeout_seconds: float = 600

    # 部门设备上的人在回路：dialog（macOS 弹窗）/ terminal（终端 y/n）/ auto（全部放行）
    approval_mode: str = "dialog"
    approval_timeout_seconds: float = 300

    log_level: str = "INFO"


settings = Settings()
