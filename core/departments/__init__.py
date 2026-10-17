"""Department cards -- what a department device holds, read from its data directory

A department is a folder, not code:

    data/devices/<name>/
    ├── department.json     the card: name, display name, description, sensitive columns
    ├── shared/             data the department's agent may read (any format)
    └── private/            restricted data: the agent reads it only after the device owner approves (optional)

department.json:

    {
      "name": "customer",
      "display_name": "Customer Department",
      "description": "what the data covers; sent to the orchestrator as the capability card",
      "record_label": "customer-level",
      "sensitive": [{"file": "customer_data.csv", "column": "customer_id"}],
      "restricted": "what private/ holds (optional); tells the agent when asking for it is worth it"
    }

Provides:
- DepartmentCard:       one department card plus its folder layout
- load_card:            read the card of a department folder
- DEVICES_DIR:          the default parent folder of the department folders

Key constraints:
- adding a department means adding a folder with a card; no code changes
- "sensitive" lists identifier columns of tabular files in shared/; the
  egress guard scans conclusions for their values before they leave the device
"""

import json
import os
from dataclasses import dataclass, field

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEVICES_DIR = os.path.join(PROJECT_ROOT, "data", "devices")
CARD_FILE = "department.json"


@dataclass(frozen=True)
class DepartmentCard:
    """One department.

    Attributes:
        name:           short id, used as the agent role and in fanout tasks.
        display_name:   e.g. "Customer Department".
        description:    what the department's data covers.
        record_label:   what one raw record is, used in the denial message.
        sensitive:      [{"file", "column"}] identifier columns that must never leave the device.
        restricted:     what private/ holds, shown to the agent.
        root:           the department folder.
    """
    name: str
    display_name: str
    description: str
    root: str
    record_label: str = "record-level"
    sensitive: tuple[dict, ...] = field(default_factory=tuple)
    restricted: str = ""

    @property
    def shared_dir(self) -> str:
        """The data the agent may read."""
        return os.path.join(self.root, "shared")

    @property
    def private_dir(self) -> str:
        """Restricted data: opened per task by the device owner."""
        return os.path.join(self.root, "private")

    @property
    def denial_message(self) -> str:
        """The answer to a raw-data export request."""
        return (f"Access denied. Raw {self.record_label} data cannot be exported from this device. "
                f"I can provide aggregate {self.display_name.lower()} insights instead.")


def load_card(root: str) -> DepartmentCard:
    """Read the department card of a department folder.

    Raises:
        FileNotFoundError / ValueError: when the card is missing or incomplete.
    """
    path = os.path.join(root, CARD_FILE)
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    missing = [k for k in ("name", "display_name", "description") if not raw.get(k)]
    if missing:
        raise ValueError(f"{path} is missing {missing}")
    return DepartmentCard(
        name=raw["name"],
        display_name=raw["display_name"],
        description=raw["description"],
        root=os.path.abspath(root),
        record_label=raw.get("record_label", "record-level"),
        sensitive=tuple(raw.get("sensitive", [])),
        restricted=raw.get("restricted", ""),
    )
