"""Named agent configurations: which screen runs, which model escalates, and the switches.

The eval compares these by name; the worker runs one of them (the chosen one is jev_sonnet).
"""

import os
from dataclasses import dataclass, field

from app.config import HAIKU, SONNET, llm_backend

# How the escalation model is called. "effort" and "thinking" go to ChatAnthropic as they are.
# Sonnet 5.5 rejects thinking {"type": "disabled"}; {"type": "between_tools"} turns it off.
ESCALATION_PROFILES = {
    "sonnet": {"model": SONNET, "effort": "low"},
    "sonnet_thinking_off": {"model": SONNET, "thinking": {"type": "between_tools"}},
    "haiku": {"model": HAIKU},
}


@dataclass(frozen=True)
class AgentConfig:
    name: str
    screen: str  # "none", "jev" or "haiku"
    escalation: str  # a key of ESCALATION_PROFILES
    hints: bool = False  # pass the screen's scores to the escalation model
    cache: bool = True  # reuse a stored label for the same input (the eval turns this off)
    screen_settings: dict = field(default_factory=dict)

    @property
    def model(self) -> str:
        return ESCALATION_PROFILES[self.escalation]["model"]


CONFIGS = {
    config.name: config
    for config in (
        AgentConfig("sonnet_only", screen="none", escalation="sonnet"),
        AgentConfig("sonnet_thinking_off", screen="none", escalation="sonnet_thinking_off"),
        AgentConfig("jev_sonnet", screen="jev", escalation="sonnet"),
        AgentConfig("haiku_sonnet", screen="haiku", escalation="sonnet"),
        AgentConfig("haiku_only", screen="none", escalation="haiku"),
    )
}


def worker_config() -> AgentConfig:
    """The config the worker labels with: AGENT_CONFIG if set. Otherwise jev_sonnet, or haiku_sonnet
    when there is no TYPESAFE_API_KEY, or sonnet_only with the fake backend (which has no fake Jev)."""
    name = os.environ.get("AGENT_CONFIG")
    if not name:
        if llm_backend() == "fake":
            name = "sonnet_only"
        else:
            name = "jev_sonnet" if os.environ.get("TYPESAFE_API_KEY") else "haiku_sonnet"
    if name not in CONFIGS:
        raise ValueError(f"AGENT_CONFIG must be one of {sorted(CONFIGS)}, got {name!r}")
    return CONFIGS[name]


def missing_keys(config: AgentConfig) -> list[str]:
    """API keys this config needs that aren't set. Empty means the worker can label."""
    if llm_backend() == "fake":
        return []
    needed = ["ANTHROPIC_API_KEY"] + (["TYPESAFE_API_KEY"] if config.screen == "jev" else [])
    return [key for key in needed if not os.environ.get(key)]
