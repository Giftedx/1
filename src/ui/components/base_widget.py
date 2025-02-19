from dataclasses import dataclass, field
from typing import Dict, Any

@dataclass
class WidgetConfig:
    id: str
    title: str
    type: str
    options: Dict[str, Any] = field(default_factory=dict)

class BaseWidget:
    def __init__(self, config: WidgetConfig):
        self.config = config
        self.template = ""

    def render(self) -> str:
        return self.template.format(widget=self)

    def get_client_js(self) -> str:
        return ""

    async def update(self) -> Dict[str, Any]:
        return {}