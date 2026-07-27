"""HTTP surface. Clinical logic lives in the layers; the API only serves contracts."""

from wellbeing.api.main import create_app

__all__ = ["create_app"]
