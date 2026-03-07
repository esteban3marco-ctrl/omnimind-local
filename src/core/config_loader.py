"""Load and validate YAML configuration files."""
import yaml
from pathlib import Path

def load_config(config_dir: str = "./configs") -> dict:
    config = {}
    config_path = Path(config_dir)
    for f in ["system.yaml", "models.yaml", "agents.yaml", "security.yaml", "learning.yaml"]:
        fp = config_path / f
        if fp.exists():
            with open(fp) as fh:
                config.update(yaml.safe_load(fh) or {})
    # Load system prompt
    prompt_file = config_path / "leo_system_prompt.yaml"
    if prompt_file.exists():
        with open(prompt_file) as fh:
            config["leo"] = yaml.safe_load(fh) or {}
    # Load personal knowledge
    kb_file = config_path / "personal_knowledge_base.yaml"
    if kb_file.exists():
        with open(kb_file) as fh:
            config["knowledge_base"] = yaml.safe_load(fh) or {}
    return config
