"""World state CRUD: rules, locations, event log.

Stored in narrative/world_state.json. Missing file is treated as an empty
world so existing simulations (from pre-God-Mode versions) continue to work
without migration.
"""
import os
import json


class WorldStateStore:
    """Manages narrative/world_state.json for a single simulation."""

    def __init__(self, sim_dir: str):
        self.sim_dir = sim_dir
        self.narrative_dir = os.path.join(sim_dir, "narrative")
        self.path = os.path.join(self.narrative_dir, "world_state.json")

    def _ensure_dir(self) -> None:
        os.makedirs(self.narrative_dir, exist_ok=True)

    def load(self) -> dict:
        if not os.path.exists(self.path):
            return {"rules": [], "locations": {}, "event_log": []}
        with open(self.path, "r", encoding="utf-8") as f:
            world = json.load(f)
        # Fill in missing keys for forward compatibility
        world.setdefault("rules", [])
        world.setdefault("locations", {})
        world.setdefault("event_log", [])
        return world

    def save(self, world: dict) -> None:
        self._ensure_dir()
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(world, f, ensure_ascii=False, indent=2)

    def set_rules(self, rules: list[str]) -> None:
        world = self.load()
        world["rules"] = list(rules)
        self.save(world)

    def upsert_location(self, location: dict) -> dict:
        """Insert or update a location by id. Returns the stored entry."""
        if "id" not in location:
            raise ValueError("location requires 'id'")
        world = self.load()
        world["locations"][location["id"]] = location
        self.save(world)
        return location

    def append_event(self, event: dict) -> dict:
        """Append an event to event_log, assigning evt_N id automatically."""
        world = self.load()
        event = dict(event)
        event["id"] = f"evt_{len(world['event_log']) + 1}"
        world["event_log"].append(event)
        self.save(world)
        return event
