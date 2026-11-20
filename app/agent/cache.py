"""The cache key. Two runs with the same key would produce the same label, so the second reuses it.

The key covers everything that can change a label:
  model_input          the exact text the models read (cleaned and rendered)
  policy_content_hash  the whole policy version, effects included
  agent_version        the prompt template and the rules in check and decide (app/agent/AGENT_VERSION)
  model_ids            which models screen and label
  screen_config        thresholds and flags such as the hints switch
Hashing the rendered input, not a list of fields, means a field added to the input later can never
be forgotten in the key. The eval runs with the cache off.
"""

from app.policy import stable_hash


def cache_key(
    model_input: str,
    policy_content_hash: str,
    agent_version: str,
    model_ids: dict[str, str],
    screen_config: dict,
) -> str:
    return stable_hash(
        {
            "input": model_input,
            "policy": policy_content_hash,
            "agent": agent_version,
            "models": model_ids,
            "screen": screen_config,
        }
    )
