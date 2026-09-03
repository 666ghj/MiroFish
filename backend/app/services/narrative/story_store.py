"""File-based persistence for narrative state.

Each simulation gets a `narrative/` subdirectory inside its data dir,
containing three files:
  - story_beats.json: chronological list of generated story passages
  - translator_state.json: tracks file offset per platform's actions.jsonl
  - characters.json: extended character profiles with emotional state
"""
import os
import json
from typing import Optional


class StoryStore:
    """Manages narrative/*.json files for a single simulation."""

    def __init__(self, sim_dir: str):
        self.sim_dir = sim_dir
        self.narrative_dir = os.path.join(sim_dir, "narrative")
        self.beats_path = os.path.join(self.narrative_dir, "story_beats.json")
        self.translator_state_path = os.path.join(
            self.narrative_dir, "translator_state.json"
        )
        self.characters_path = os.path.join(self.narrative_dir, "characters.json")

    def _ensure_dir(self) -> None:
        os.makedirs(self.narrative_dir, exist_ok=True)

    def append_beat(self, beat: dict) -> None:
        self._ensure_dir()
        beats = self.get_all_beats()
        beats.append(beat)
        with open(self.beats_path, "w", encoding="utf-8") as f:
            json.dump(beats, f, ensure_ascii=False, indent=2)

    def get_all_beats(self) -> list:
        if not os.path.exists(self.beats_path):
            return []
        with open(self.beats_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_beat_by_round(self, round_num: int) -> Optional[dict]:
        for beat in self.get_all_beats():
            if beat.get("round") == round_num:
                return beat
        return None

    def get_file_offset(self, platform: str) -> int:
        if not os.path.exists(self.translator_state_path):
            return 0
        with open(self.translator_state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        return state.get(f"{platform}_offset", 0)

    def set_file_offset(self, platform: str, offset: int) -> None:
        self._ensure_dir()
        state = {}
        if os.path.exists(self.translator_state_path):
            with open(self.translator_state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
        state[f"{platform}_offset"] = offset
        with open(self.translator_state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

    def save_characters(self, characters: list) -> None:
        self._ensure_dir()
        with open(self.characters_path, "w", encoding="utf-8") as f:
            json.dump(characters, f, ensure_ascii=False, indent=2)

    def load_characters(self) -> list:
        if not os.path.exists(self.characters_path):
            return []
        with open(self.characters_path, "r", encoding="utf-8") as f:
            return json.load(f)
