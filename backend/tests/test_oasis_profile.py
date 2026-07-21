"""
Unit tests for OasisAgentProfile and helper functions.

These tests verify the profile format conversion logic without requiring
external dependencies (LLM, Zep, Flask, etc.).

Note: Full integration tests require Flask app initialization and external
services. These tests focus on isolated logic that can be tested without
those dependencies.

The OasisAgentProfile class and helper functions are imported from
oasis_models.py, which is the single source of truth. This ensures tests
are actually testing the production code, not a copy.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from importlib.util import spec_from_loader, module_from_spec
from importlib.machinery import SourceFileLoader

import pytest

# Add backend to path for imports
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

# oasis_models.py has no external dependencies (only stdlib), so we can
# import it directly without triggering Flask app initialization.
# This is the key fix - we import the REAL OasisAgentProfile, not a test copy.
#
# We use importlib to load the module directly from file to avoid going
# through the app package which would trigger Flask initialization.
import importlib

# Clear any cached app modules
for mod_name in list(sys.modules.keys()):
    if mod_name.startswith('app'):
        del sys.modules[mod_name]

# Load oasis_models directly from file
oasis_models_path = backend_path / "app" / "services" / "oasis_models.py"
spec = spec_from_loader("oasis_models", SourceFileLoader("oasis_models", str(oasis_models_path)))
oasis_models = module_from_spec(spec)
spec.loader.exec_module(oasis_models)

OasisAgentProfile = oasis_models.OasisAgentProfile
_generate_username = oasis_models._generate_username
_normalize_gender = oasis_models._normalize_gender
_is_individual_entity = oasis_models._is_individual_entity
_is_group_entity = oasis_models._is_group_entity
INDIVIDUAL_ENTITY_TYPES = oasis_models.INDIVIDUAL_ENTITY_TYPES
GROUP_ENTITY_TYPES = oasis_models.GROUP_ENTITY_TYPES


class TestOasisAgentProfile:
    """Tests for OasisAgentProfile dataclass."""

    def create_test_profile(
        self,
        user_id: int = 0,
        user_name: str = "test_user",
        name: str = "Test User",
        bio: str = "A test user",
        persona: str = "Test User is enthusiastic",
        karma: int = 1000,
        friend_count: int = 100,
        follower_count: int = 200,
        statuses_count: int = 500,
        age: int = 25,
        gender: str = "male",
        mbti: str = "INTJ",
        country: str = "China",
        profession: str = "Student",
        interested_topics: list = None,
        source_entity_uuid: str = "test-uuid-123",
        source_entity_type: str = "student",
    ) -> OasisAgentProfile:
        """Helper to create a test profile with default values."""
        if interested_topics is None:
            interested_topics = ["Technology", "Education"]
        return OasisAgentProfile(
            user_id=user_id,
            user_name=user_name,
            name=name,
            bio=bio,
            persona=persona,
            karma=karma,
            friend_count=friend_count,
            follower_count=follower_count,
            statuses_count=statuses_count,
            age=age,
            gender=gender,
            mbti=mbti,
            country=country,
            profession=profession,
            interested_topics=interested_topics,
            source_entity_uuid=source_entity_uuid,
            source_entity_type=source_entity_type,
        )

    # ===== to_reddit_format() tests =====

    def test_to_reddit_format_basic(self):
        """Test basic Reddit format conversion."""
        profile = self.create_test_profile()
        reddit = profile.to_reddit_format()

        assert reddit["user_id"] == 0
        assert reddit["username"] == "test_user"
        assert reddit["name"] == "Test User"
        assert reddit["bio"] == "A test user"
        assert reddit["persona"] == "Test User is enthusiastic"
        assert reddit["karma"] == 1000

    def test_to_reddit_format_includes_optional_fields(self):
        """Test that optional fields are included when present."""
        profile = self.create_test_profile(
            age=30,
            gender="female",
            mbti="ENFP",
            country="USA",
            profession="Engineer",
        )
        reddit = profile.to_reddit_format()

        assert reddit["age"] == 30
        assert reddit["gender"] == "female"
        assert reddit["mbti"] == "ENFP"
        assert reddit["country"] == "USA"
        assert reddit["profession"] == "Engineer"
        assert "interested_topics" in reddit

    def test_to_reddit_format_excludes_none_fields(self):
        """Test that None optional fields are excluded."""
        profile = self.create_test_profile(
            age=None,
            gender=None,
            mbti=None,
            country=None,
            profession=None,
            interested_topics=[],
        )
        reddit = profile.to_reddit_format()

        assert "age" not in reddit
        assert "gender" not in reddit
        assert "mbti" not in reddit
        assert "country" not in reddit
        assert "profession" not in reddit
        assert "interested_topics" not in reddit

    def test_to_reddit_format_uses_username_not_user_name(self):
        """Test that Reddit format uses 'username' key, not 'user_name'."""
        profile = self.create_test_profile(user_name="test_user")
        reddit = profile.to_reddit_format()

        assert "username" in reddit
        assert "user_name" not in reddit
        assert reddit["username"] == "test_user"

    # ===== to_twitter_format() tests =====

    def test_to_twitter_format_basic(self):
        """Test basic Twitter format conversion."""
        profile = self.create_test_profile()
        twitter = profile.to_twitter_format()

        assert twitter["user_id"] == 0
        assert twitter["username"] == "test_user"
        assert twitter["name"] == "Test User"
        assert twitter["friend_count"] == 100
        assert twitter["follower_count"] == 200
        assert twitter["statuses_count"] == 500

    def test_to_twitter_format_includes_optional_fields(self):
        """Test that optional fields are included when present."""
        profile = self.create_test_profile(
            age=30,
            gender="male",
            mbti="INTJ",
            country="UK",
            profession="Designer",
        )
        twitter = profile.to_twitter_format()

        assert twitter["age"] == 30
        assert twitter["gender"] == "male"
        assert twitter["mbti"] == "INTJ"
        assert twitter["country"] == "UK"
        assert twitter["profession"] == "Designer"

    def test_to_twitter_format_excludes_karma(self):
        """Test that Reddit-specific karma field is excluded from Twitter format."""
        profile = self.create_test_profile(karma=5000)
        twitter = profile.to_twitter_format()

        assert "karma" not in twitter

    # ===== to_dict() tests =====

    def test_to_dict_includes_all_fields(self):
        """Test that to_dict includes all fields."""
        profile = self.create_test_profile()
        d = profile.to_dict()

        assert d["user_id"] == 0
        assert d["user_name"] == "test_user"
        assert d["name"] == "Test User"
        assert d["bio"] == "A test user"
        assert d["persona"] == "Test User is enthusiastic"
        assert d["karma"] == 1000
        assert d["friend_count"] == 100
        assert d["follower_count"] == 200
        assert d["statuses_count"] == 500
        assert d["age"] == 25
        assert d["gender"] == "male"
        assert d["mbti"] == "INTJ"
        assert d["country"] == "China"
        assert d["profession"] == "Student"
        assert d["source_entity_uuid"] == "test-uuid-123"
        assert d["source_entity_type"] == "student"

    def test_to_dict_with_empty_interests(self):
        """Test to_dict with empty interested_topics."""
        profile = self.create_test_profile(interested_topics=[])
        d = profile.to_dict()

        assert d["interested_topics"] == []

    def test_to_dict_with_multiple_interests(self):
        """Test to_dict with multiple interested_topics."""
        profile = self.create_test_profile(interested_topics=["AI", "Music", "Travel"])
        d = profile.to_dict()

        assert d["interested_topics"] == ["AI", "Music", "Travel"]

    # ===== Default values tests =====

    def test_default_karma(self):
        """Test that karma defaults to 1000."""
        profile = OasisAgentProfile(
            user_id=1,
            user_name="user",
            name="Name",
            bio="Bio",
            persona="Persona",
        )
        assert profile.karma == 1000

    def test_default_social_counts(self):
        """Test default social media counts."""
        profile = OasisAgentProfile(
            user_id=1,
            user_name="user",
            name="Name",
            bio="Bio",
            persona="Persona",
        )
        assert profile.friend_count == 100
        assert profile.follower_count == 150
        assert profile.statuses_count == 500

    def test_default_created_at_format(self):
        """Test that created_at is in YYYY-MM-DD format."""
        import re
        profile = OasisAgentProfile(
            user_id=1,
            user_name="user",
            name="Name",
            bio="Bio",
            persona="Persona",
        )
        assert re.match(r"\d{4}-\d{2}-\d{2}", profile.created_at)


class TestHelperFunctions:
    """Tests for helper functions from oasis_models."""

    def test_generate_username_basic(self):
        """Test username generation from name."""
        username = _generate_username("John Doe")
        assert username.startswith("john_doe_")
        assert len(username.split("_")) == 3  # john, doe, 3-digit-suffix

    def test_generate_username_removes_special_chars(self):
        """Test that username generation removes special characters."""
        username = _generate_username("John@Doe#123")
        assert "@" not in username
        assert "#" not in username
        assert username.startswith("johndoe123_")

    def test_generate_username_allows_underscores(self):
        """Test that underscores are preserved in username."""
        username = _generate_username("John_Doe_Smith")
        assert "_" in username
        assert username.startswith("john_doe_smith_")


class TestGenderNormalization:
    """Tests for gender normalization function."""

    def test_normalize_gender_english(self):
        """Test gender normalization for English values."""
        assert _normalize_gender("male") == "male"
        assert _normalize_gender("female") == "female"
        assert _normalize_gender("other") == "other"

    def test_normalize_gender_chinese(self):
        """Test gender normalization for Chinese values."""
        assert _normalize_gender("男") == "male"
        assert _normalize_gender("女") == "female"
        assert _normalize_gender("其他") == "other"

    def test_normalize_gender_none(self):
        """Test gender normalization for None/empty values."""
        assert _normalize_gender(None) == "other"
        assert _normalize_gender("") == "other"
        assert _normalize_gender("unknown") == "other"

    def test_normalize_gender_case_insensitive(self):
        """Test that gender normalization is case-insensitive."""
        assert _normalize_gender("MALE") == "male"
        assert _normalize_gender("Female") == "female"
        assert _normalize_gender("OTHER") == "other"


class TestEntityTypeDetection:
    """Tests for entity type detection functions."""

    def test_is_individual_entity_positive(self):
        """Test individual entity type detection - should be individual."""
        assert _is_individual_entity("student") is True
        assert _is_individual_entity("STUDENT") is True
        assert _is_individual_entity("professor") is True
        assert _is_individual_entity("person") is True
        assert _is_individual_entity("alumni") is True
        assert _is_individual_entity("publicfigure") is True
        assert _is_individual_entity("expert") is True
        assert _is_individual_entity("faculty") is True

    def test_is_individual_entity_negative(self):
        """Test individual entity type detection - should NOT be individual."""
        assert _is_individual_entity("university") is False
        assert _is_individual_entity("company") is False
        assert _is_individual_entity("organization") is False
        assert _is_individual_entity("ngo") is False
        assert _is_individual_entity("governmentagency") is False

    def test_is_group_entity_positive(self):
        """Test group entity type detection - should be group."""
        assert _is_group_entity("university") is True
        assert _is_group_entity("UNIVERSITY") is True
        assert _is_group_entity("company") is True
        assert _is_group_entity("governmentagency") is True
        assert _is_group_entity("ngo") is True
        assert _is_group_entity("mediaoutlet") is True

    def test_is_group_entity_negative(self):
        """Test group entity type detection - should NOT be group."""
        assert _is_group_entity("student") is False
        assert _is_group_entity("professor") is False
        assert _is_group_entity("person") is False
        assert _is_group_entity("alumni") is False