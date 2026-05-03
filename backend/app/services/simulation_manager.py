"""
OASIS simulation manager
Manages parallel simulation on both Twitter and Reddit platforms.
Uses preset scripts with LLM-generated configuration parameters.
"""

import os
import json
import shutil
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..config import Config
from ..utils.logger import get_logger
from .zep_entity_reader import ZepEntityReader, FilteredEntities
from .oasis_profile_generator import OasisProfileGenerator, OasisAgentProfile
from .simulation_config_generator import SimulationConfigGenerator, SimulationParameters
from ..utils.locale import t

logger = get_logger('mirofish.simulation')


class SimulationStatus(str, Enum):
    """Simulation status"""
    CREATED = "created"
    PREPARING = "preparing"
    PROFILES_READY = "profiles_ready"   # agents generated, awaiting user confirmation for Fase B
    CONFIGURING = "configuring"          # generating behavior config async
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"      # Simulation manually stopped
    COMPLETED = "completed"  # Simulation naturally completed
    FAILED = "failed"


class PlatformType(str, Enum):
    """Platform type"""
    TWITTER = "twitter"
    REDDIT = "reddit"


@dataclass
class SimulationState:
    """Simulation state"""
    simulation_id: str
    project_id: str
    graph_id: str

    # Platform enable flags
    enable_twitter: bool = True
    enable_reddit: bool = True

    # Status
    status: SimulationStatus = SimulationStatus.CREATED

    # Preparation phase data
    entities_count: int = 0
    profiles_count: int = 0
    entity_types: List[str] = field(default_factory=list)

    # Config generation info
    config_generated: bool = False
    config_reasoning: str = ""

    # Runtime data
    current_round: int = 0
    twitter_status: str = "not_started"
    reddit_status: str = "not_started"

    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # Error message
    error: Optional[str] = None

    # F2-A+B fields
    parent_simulation_id: Optional[str] = None   # set when cloned from another simulation
    graph_id_simulation: Optional[str] = None    # per-simulation Neo4j group_id

    def to_dict(self) -> Dict[str, Any]:
        """Full state dictionary (internal use)"""
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "enable_twitter": self.enable_twitter,
            "enable_reddit": self.enable_reddit,
            "status": self.status.value,
            "entities_count": self.entities_count,
            "profiles_count": self.profiles_count,
            "entity_types": self.entity_types,
            "config_generated": self.config_generated,
            "config_reasoning": self.config_reasoning,
            "current_round": self.current_round,
            "twitter_status": self.twitter_status,
            "reddit_status": self.reddit_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "parent_simulation_id": self.parent_simulation_id,
            "graph_id_simulation": self.graph_id_simulation,
        }

    def to_simple_dict(self) -> Dict[str, Any]:
        """Simplified state dictionary (used for API responses)"""
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "status": self.status.value,
            "entities_count": self.entities_count,
            "profiles_count": self.profiles_count,
            "entity_types": self.entity_types,
            "config_generated": self.config_generated,
            "error": self.error,
            "parent_simulation_id": self.parent_simulation_id,
            "graph_id_simulation": self.graph_id_simulation,
        }


class SimulationManager:
    """
    Simulation manager

    Core functions:
    1. Read and filter entities from the Zep graph
    2. Generate OASIS Agent Profiles
    3. Use LLM to intelligently generate simulation configuration parameters
    4. Prepare all files required by the preset scripts
    """

    # Simulation data storage directory
    SIMULATION_DATA_DIR = os.path.join(
        os.path.dirname(__file__),
        '../../uploads/simulations'
    )

    def __init__(self):
        # Ensure directory exists
        os.makedirs(self.SIMULATION_DATA_DIR, exist_ok=True)

        # In-memory simulation state cache
        self._simulations: Dict[str, SimulationState] = {}

    def _get_simulation_dir(self, simulation_id: str) -> str:
        """Get the simulation data directory"""
        sim_dir = os.path.join(self.SIMULATION_DATA_DIR, simulation_id)
        os.makedirs(sim_dir, exist_ok=True)
        return sim_dir

    def _save_simulation_state(self, state: SimulationState):
        """Save simulation state to file"""
        sim_dir = self._get_simulation_dir(state.simulation_id)
        state_file = os.path.join(sim_dir, "state.json")

        state.updated_at = datetime.now().isoformat()

        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)

        self._simulations[state.simulation_id] = state

    def _load_simulation_state(self, simulation_id: str) -> Optional[SimulationState]:
        """Load simulation state from file"""
        if simulation_id in self._simulations:
            return self._simulations[simulation_id]

        sim_dir = self._get_simulation_dir(simulation_id)
        state_file = os.path.join(sim_dir, "state.json")

        if not os.path.exists(state_file):
            return None

        with open(state_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        state = SimulationState(
            simulation_id=simulation_id,
            project_id=data.get("project_id", ""),
            graph_id=data.get("graph_id", ""),
            enable_twitter=data.get("enable_twitter", True),
            enable_reddit=data.get("enable_reddit", True),
            status=SimulationStatus(data.get("status", "created")),
            entities_count=data.get("entities_count", 0),
            profiles_count=data.get("profiles_count", 0),
            entity_types=data.get("entity_types", []),
            config_generated=data.get("config_generated", False),
            config_reasoning=data.get("config_reasoning", ""),
            current_round=data.get("current_round", 0),
            twitter_status=data.get("twitter_status", "not_started"),
            reddit_status=data.get("reddit_status", "not_started"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            error=data.get("error"),
            parent_simulation_id=data.get("parent_simulation_id"),
            graph_id_simulation=data.get("graph_id_simulation"),
        )

        self._simulations[simulation_id] = state
        return state

    def create_simulation(
        self,
        project_id: str,
        graph_id: str,
        enable_twitter: bool = True,
        enable_reddit: bool = True,
    ) -> SimulationState:
        """
        Create a new simulation.

        Args:
            project_id: project ID
            graph_id: Zep graph ID
            enable_twitter: whether to enable Twitter simulation
            enable_reddit: whether to enable Reddit simulation

        Returns:
            SimulationState
        """
        import uuid
        simulation_id = f"sim_{uuid.uuid4().hex[:12]}"

        state = SimulationState(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            enable_twitter=enable_twitter,
            enable_reddit=enable_reddit,
            status=SimulationStatus.CREATED,
        )

        self._save_simulation_state(state)
        logger.info(f"Simulation created: {simulation_id}, project={project_id}, graph={graph_id}")

        return state

    def prepare_simulation(
        self,
        simulation_id: str,
        simulation_requirement: str,
        document_text: str,
        defined_entity_types: Optional[List[str]] = None,
        use_llm_for_profiles: bool = True,
        progress_callback: Optional[callable] = None,
        parallel_profile_count: int = 3
    ) -> SimulationState:
        """
        Prepare the simulation environment (fully automated).

        Steps:
        1. Read and filter entities from the Zep graph
        2. Generate an OASIS Agent Profile for each entity (optional LLM enhancement, supports parallelism)
        3. Use LLM to intelligently generate simulation configuration parameters (time, activity level, posting frequency, etc.)
        4. Save configuration files and profile files
        5. Copy preset scripts to the simulation directory

        Args:
            simulation_id: simulation ID
            simulation_requirement: simulation requirement description (used for LLM config generation)
            document_text: original document content (used for LLM background understanding)
            defined_entity_types: predefined entity types (optional)
            use_llm_for_profiles: whether to use LLM to generate detailed personas
            progress_callback: progress callback function (stage, progress, message)
            parallel_profile_count: number of profiles to generate in parallel, default 3

        Returns:
            SimulationState
        """
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"Simulation not found: {simulation_id}")

        try:
            state.status = SimulationStatus.PREPARING
            self._save_simulation_state(state)

            sim_dir = self._get_simulation_dir(simulation_id)

            # ========== Stage 1: Read and filter entities ==========
            if progress_callback:
                progress_callback("reading", 0, t('progress.connectingZepGraph'))

            reader = ZepEntityReader()

            if progress_callback:
                progress_callback("reading", 30, t('progress.readingNodeData'))

            filtered = reader.filter_defined_entities(
                graph_id=state.graph_id,
                defined_entity_types=defined_entity_types,
                enrich_with_edges=True
            )

            state.entities_count = filtered.filtered_count
            state.entity_types = list(filtered.entity_types)

            if progress_callback:
                progress_callback(
                    "reading", 100,
                    t('progress.readingComplete', count=filtered.filtered_count),
                    current=filtered.filtered_count,
                    total=filtered.filtered_count
                )

            if filtered.filtered_count == 0:
                state.status = SimulationStatus.FAILED
                state.error = "No qualifying entities found. Please check that the graph was built correctly."
                self._save_simulation_state(state)
                return state

            # ========== Stage 2: Generate Agent Profiles ==========
            total_entities = len(filtered.entities)

            if progress_callback:
                progress_callback(
                    "generating_profiles", 0,
                    t('progress.startGenerating'),
                    current=0,
                    total=total_entities
                )

            # Pass graph_id to enable Zep retrieval for richer context
            generator = OasisProfileGenerator(graph_id=state.graph_id)

            def profile_progress(current, total, msg):
                if progress_callback:
                    progress_callback(
                        "generating_profiles",
                        int(current / total * 100),
                        msg,
                        current=current,
                        total=total,
                        item_name=msg
                    )

            # Set real-time save path (prefer Reddit JSON format)
            realtime_output_path = None
            realtime_platform = "reddit"
            if state.enable_reddit:
                realtime_output_path = os.path.join(sim_dir, "reddit_profiles.json")
                realtime_platform = "reddit"
            elif state.enable_twitter:
                realtime_output_path = os.path.join(sim_dir, "twitter_profiles.csv")
                realtime_platform = "twitter"

            profiles = generator.generate_profiles_from_entities(
                entities=filtered.entities,
                use_llm=use_llm_for_profiles,
                progress_callback=profile_progress,
                graph_id=state.graph_id,       # Pass graph_id for Zep retrieval
                parallel_count=parallel_profile_count,  # Parallel generation count
                realtime_output_path=realtime_output_path,  # Real-time save path
                output_platform=realtime_platform           # Output format
            )

            state.profiles_count = len(profiles)

            # Save profile files (note: Twitter uses CSV format, Reddit uses JSON format)
            # Reddit has already been saved incrementally during generation; save once more to ensure completeness
            if progress_callback:
                progress_callback(
                    "generating_profiles", 95,
                    t('progress.savingProfiles'),
                    current=total_entities,
                    total=total_entities
                )

            if state.enable_reddit:
                generator.save_profiles(
                    profiles=profiles,
                    file_path=os.path.join(sim_dir, "reddit_profiles.json"),
                    platform="reddit"
                )

            if state.enable_twitter:
                # Twitter uses CSV format — this is a requirement of OASIS
                generator.save_profiles(
                    profiles=profiles,
                    file_path=os.path.join(sim_dir, "twitter_profiles.csv"),
                    platform="twitter"
                )

            if progress_callback:
                progress_callback(
                    "generating_profiles", 100,
                    t('progress.profilesComplete', count=len(profiles)),
                    current=len(profiles),
                    total=len(profiles)
                )

            # ========== Stage 3: LLM intelligent simulation configuration generation ==========
            if progress_callback:
                progress_callback(
                    "generating_config", 0,
                    t('progress.analyzingRequirements'),
                    current=0,
                    total=3
                )

            config_generator = SimulationConfigGenerator()

            if progress_callback:
                progress_callback(
                    "generating_config", 30,
                    t('progress.callingLLMConfig'),
                    current=1,
                    total=3
                )

            sim_params = config_generator.generate_config(
                simulation_id=simulation_id,
                project_id=state.project_id,
                graph_id=state.graph_id,
                simulation_requirement=simulation_requirement,
                document_text=document_text,
                entities=filtered.entities,
                enable_twitter=state.enable_twitter,
                enable_reddit=state.enable_reddit
            )

            if progress_callback:
                progress_callback(
                    "generating_config", 70,
                    t('progress.savingConfigFiles'),
                    current=2,
                    total=3
                )

            # Save configuration file
            config_path = os.path.join(sim_dir, "simulation_config.json")
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(sim_params.to_json())

            state.config_generated = True
            state.config_reasoning = sim_params.generation_reasoning

            if progress_callback:
                progress_callback(
                    "generating_config", 100,
                    t('progress.configComplete'),
                    current=3,
                    total=3
                )

            # Note: run scripts remain in backend/scripts/; they are not copied to the simulation directory.
            # When starting a simulation, simulation_runner runs scripts from the scripts/ directory.

            # Update status
            state.status = SimulationStatus.READY
            self._save_simulation_state(state)

            logger.info(f"Simulation preparation complete: {simulation_id}, "
                        f"entities={state.entities_count}, profiles={state.profiles_count}")

            return state

        except Exception as e:
            logger.error(f"Simulation preparation failed: {simulation_id}, error={str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            state.status = SimulationStatus.FAILED
            state.error = str(e)
            self._save_simulation_state(state)
            raise

    def get_simulation(self, simulation_id: str) -> Optional[SimulationState]:
        """Get simulation state"""
        return self._load_simulation_state(simulation_id)

    def list_simulations(self, project_id: Optional[str] = None) -> List[SimulationState]:
        """List all simulations"""
        simulations = []

        if os.path.exists(self.SIMULATION_DATA_DIR):
            for sim_id in os.listdir(self.SIMULATION_DATA_DIR):
                # Skip hidden files (e.g. .DS_Store) and non-directory entries
                sim_path = os.path.join(self.SIMULATION_DATA_DIR, sim_id)
                if sim_id.startswith('.') or not os.path.isdir(sim_path):
                    continue

                state = self._load_simulation_state(sim_id)
                if state:
                    if project_id is None or state.project_id == project_id:
                        simulations.append(state)

        return simulations

    def get_profiles(self, simulation_id: str, platform: str = "reddit") -> List[Dict[str, Any]]:
        """Get agent profiles for a simulation"""
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"Simulation not found: {simulation_id}")

        sim_dir = self._get_simulation_dir(simulation_id)
        profile_path = os.path.join(sim_dir, f"{platform}_profiles.json")

        if not os.path.exists(profile_path):
            return []

        with open(profile_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def get_simulation_config(self, simulation_id: str) -> Optional[Dict[str, Any]]:
        """Get simulation configuration"""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")

        if not os.path.exists(config_path):
            return None

        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def get_run_instructions(self, simulation_id: str) -> Dict[str, str]:
        """Get run instructions"""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        scripts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts'))

        return {
            "simulation_dir": sim_dir,
            "scripts_dir": scripts_dir,
            "config_file": config_path,
            "commands": {
                "twitter": f"python {scripts_dir}/run_twitter_simulation.py --config {config_path}",
                "reddit": f"python {scripts_dir}/run_reddit_simulation.py --config {config_path}",
                "parallel": f"python {scripts_dir}/run_parallel_simulation.py --config {config_path}",
            },
            "instructions": (
                f"1. Activate conda environment: conda activate MiroFish\n"
                f"2. Run simulation (scripts located at {scripts_dir}):\n"
                f"   - Twitter only: python {scripts_dir}/run_twitter_simulation.py --config {config_path}\n"
                f"   - Reddit only: python {scripts_dir}/run_reddit_simulation.py --config {config_path}\n"
                f"   - Both platforms in parallel: python {scripts_dir}/run_parallel_simulation.py --config {config_path}"
            )
        }

    def patch_agent_profile(self, simulation_id: str, user_id: int, fields: dict) -> dict:
        """
        Update an agent's profile fields and set manually_edited=True.
        Raises ValueError if simulation not found.
        Raises PermissionError if simulation status is running or completed.
        Raises LookupError if agent user_id not found.
        Uses atomic write: backup → write → delete backup on success, restore on failure.
        """
        state = self.get_simulation(simulation_id)
        if not state:
            raise ValueError(f"Simulation {simulation_id} not found")

        immutable = {SimulationStatus.RUNNING, SimulationStatus.COMPLETED}
        if state.status in immutable:
            raise PermissionError(f"Cannot edit agent while simulation is {state.status.value}")

        sim_dir = self._get_simulation_dir(simulation_id)
        profiles_file = os.path.join(sim_dir, "reddit_profiles.json")
        backup_file = profiles_file + ".bak"

        if not os.path.exists(profiles_file):
            raise FileNotFoundError(f"reddit_profiles.json not found for {simulation_id}")

        with open(profiles_file, 'r', encoding='utf-8') as f:
            profiles = json.load(f)

        target = next((p for p in profiles if p.get("user_id") == user_id), None)
        if target is None:
            raise LookupError(f"Agent user_id={user_id} not found in simulation {simulation_id}")

        allowed = {
            "name", "bio", "persona", "age", "gender", "mbti",
            "country", "profession", "interested_topics", "stance", "sentiment_bias",
            "posts_per_hour", "comments_per_hour", "active_hours",
            "response_delay_min", "response_delay_max", "activity_level", "influence_weight",
        }
        for k, v in fields.items():
            if k in allowed:
                target[k] = v
        target["manually_edited"] = True

        import shutil
        shutil.copy2(profiles_file, backup_file)
        try:
            with open(profiles_file, 'w', encoding='utf-8') as f:
                json.dump(profiles, f, ensure_ascii=False, indent=2)
            os.remove(backup_file)
        except Exception:
            shutil.copy2(backup_file, profiles_file)
            os.remove(backup_file)
            raise

        return target

    def delete_agent_profile(self, simulation_id: str, user_id: int) -> None:
        """
        Remove an agent from reddit_profiles.json.
        Raises ValueError if simulation not found.
        Raises PermissionError if status is running or completed.
        Raises LookupError if agent not found.
        Atomic write.
        """
        state = self.get_simulation(simulation_id)
        if not state:
            raise ValueError(f"Simulation {simulation_id} not found")

        immutable = {SimulationStatus.RUNNING, SimulationStatus.COMPLETED}
        if state.status in immutable:
            raise PermissionError(f"Cannot delete agent while simulation is {state.status.value}")

        sim_dir = self._get_simulation_dir(simulation_id)
        profiles_file = os.path.join(sim_dir, "reddit_profiles.json")
        backup_file = profiles_file + ".bak"

        with open(profiles_file, 'r', encoding='utf-8') as f:
            profiles = json.load(f)

        original_len = len(profiles)
        profiles = [p for p in profiles if p.get("user_id") != user_id]
        if len(profiles) == original_len:
            raise LookupError(f"Agent user_id={user_id} not found")

        shutil.copy2(profiles_file, backup_file)
        try:
            with open(profiles_file, 'w', encoding='utf-8') as f:
                json.dump(profiles, f, ensure_ascii=False, indent=2)
            os.remove(backup_file)
        except Exception:
            shutil.copy2(backup_file, profiles_file)
            os.remove(backup_file)
            raise

    def patch_simulation_config(self, simulation_id: str, fields: dict) -> dict:
        """
        Update global simulation config parameters (Fase B).
        Supported top-level: total_simulation_hours, minutes_per_round, agents_per_hour_min,
        agents_per_hour_max, following_probability, recsys_type, twitter_config (dict merged),
        reddit_config (dict merged).
        Atomic write.
        """
        state = self.get_simulation(simulation_id)
        if not state:
            raise ValueError(f"Simulation {simulation_id} not found")

        immutable = {SimulationStatus.RUNNING, SimulationStatus.COMPLETED}
        if state.status in immutable:
            raise PermissionError(f"Cannot edit config while simulation is {state.status.value}")

        sim_dir = self._get_simulation_dir(simulation_id)
        config_file = os.path.join(sim_dir, "simulation_config.json")
        backup_file = config_file + ".bak"

        if not os.path.exists(config_file):
            raise FileNotFoundError("simulation_config.json not found")

        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

        time_fields = {"total_simulation_hours", "minutes_per_round",
                       "agents_per_hour_min", "agents_per_hour_max"}
        time_config = config.setdefault("time_config", {})
        for k in time_fields:
            if k in fields:
                time_config[k] = fields[k]

        for k in ("following_probability", "recsys_type"):
            if k in fields:
                config[k] = fields[k]

        for nested in ("twitter_config", "reddit_config"):
            if nested in fields and isinstance(fields[nested], dict):
                config.setdefault(nested, {}).update(fields[nested])

        shutil.copy2(config_file, backup_file)
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            os.remove(backup_file)
        except Exception:
            shutil.copy2(backup_file, config_file)
            os.remove(backup_file)
            raise

        return config
