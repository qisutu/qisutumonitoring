"""Authentication configuration for tests which instantiate the web dispatcher."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor"))
from netzmonitor.server import set_password, write_config


def configuration(directory):
    if (Path(directory) / 'config.json').exists():
        return
    config = {'language': 'de'}
    set_password(config, 'Fixture-password-2026')
    write_config(directory, config)
