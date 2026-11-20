"""The labeling agent: the graph's nodes and the rules they apply.

AGENT_VERSION is part of the cache key and of each label's model_version. Bump it whenever the
prompt template or the rules in check.py and decide.py change, so no label made by older code is
reused as if it were current.
"""

AGENT_VERSION = "2"
