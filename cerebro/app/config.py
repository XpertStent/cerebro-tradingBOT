from pathlib import Path
import yaml

CONFIG_FILE = Path("/app/config/cerebro.yaml")

with CONFIG_FILE.open("r") as f:
    config = yaml.safe_load(f)
