"""
Ontology schema normalization helpers.
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def normalize_attribute_definitions(
    attribute_defs: Any,
    owner_label: str,
) -> List[Dict[str, str]]:
    """Normalize attribute definitions into the expected name/type/description shape."""
    if not attribute_defs:
        return []

    if isinstance(attribute_defs, dict):
        attribute_defs = [attribute_defs]

    if not isinstance(attribute_defs, list):
        logger.warning(
            "Invalid attribute definitions for %s: expected list, got %s",
            owner_label,
            type(attribute_defs).__name__,
        )
        return []

    normalized: List[Dict[str, str]] = []
    seen_names = set()

    for index, attr_def in enumerate(attribute_defs):
        if not isinstance(attr_def, dict):
            logger.warning(
                "Skipping invalid attribute definition for %s at index %s: expected dict, got %s",
                owner_label,
                index,
                type(attr_def).__name__,
            )
            continue

        # Legacy payloads store one mapping of {attr_name: attr_description}.
        if "name" not in attr_def:
            logger.warning(
                "Normalizing legacy attribute map for %s at index %s",
                owner_label,
                index,
            )
            candidate_items = [
                {
                    "name": attr_name,
                    "type": "text",
                    "description": attr_desc,
                }
                for attr_name, attr_desc in attr_def.items()
            ]
        else:
            candidate_items = [attr_def]

        for candidate in candidate_items:
            attr_name = str(candidate.get("name", "")).strip()
            if not attr_name:
                logger.warning(
                    "Skipping attribute with empty name for %s at index %s",
                    owner_label,
                    index,
                )
                continue

            if attr_name in seen_names:
                logger.warning(
                    "Duplicate attribute '%s' removed for %s",
                    attr_name,
                    owner_label,
                )
                continue

            seen_names.add(attr_name)
            description = candidate.get("description")
            normalized.append(
                {
                    "name": attr_name,
                    "type": str(candidate.get("type") or "text"),
                    "description": str(description).strip() if description else attr_name,
                }
            )

    return normalized


def normalize_ontology_schema(ontology: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of ontology with normalized entity and edge attributes."""
    if not isinstance(ontology, dict):
        logger.warning(
            "Invalid ontology payload: expected dict, got %s",
            type(ontology).__name__,
        )
        return {}

    normalized = dict(ontology)

    entity_types = []
    for entity in ontology.get("entity_types", []):
        if not isinstance(entity, dict):
            logger.warning(
                "Skipping invalid entity definition: expected dict, got %s",
                type(entity).__name__,
            )
            continue

        normalized_entity = dict(entity)
        normalized_entity["attributes"] = normalize_attribute_definitions(
            entity.get("attributes", []),
            f"entity '{entity.get('name', 'unknown')}'",
        )
        entity_types.append(normalized_entity)

    edge_types = []
    for edge in ontology.get("edge_types", []):
        if not isinstance(edge, dict):
            logger.warning(
                "Skipping invalid edge definition: expected dict, got %s",
                type(edge).__name__,
            )
            continue

        normalized_edge = dict(edge)
        normalized_edge["attributes"] = normalize_attribute_definitions(
            edge.get("attributes", []),
            f"edge '{edge.get('name', 'unknown')}'",
        )
        edge_types.append(normalized_edge)

    normalized["entity_types"] = entity_types
    normalized["edge_types"] = edge_types
    return normalized
