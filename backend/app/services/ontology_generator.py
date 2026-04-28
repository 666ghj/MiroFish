"""
Ontology generation service
Interface 1: Analyze the text content and produce entity/relationship type
definitions suitable for social simulation.
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional
from ..utils.llm_client import LLMClient
from ..utils.locale import get_language_instruction

logger = logging.getLogger(__name__)


def _to_pascal_case(name: str) -> str:
    """Convert any-format name to PascalCase (e.g. 'works_for' -> 'WorksFor', 'person' -> 'Person')."""
    # Split by non-alphanumeric characters
    parts = re.split(r'[^a-zA-Z0-9]+', name)
    # Then split on camelCase boundaries (e.g. 'camelCase' -> ['camel', 'Case'])
    words = []
    for part in parts:
        words.extend(re.sub(r'([a-z])([A-Z])', r'\1_\2', part).split('_'))
    # Capitalize each word and drop empty pieces
    result = ''.join(word.capitalize() for word in words if word)
    return result if result else 'Unknown'


# System prompt for ontology generation
ONTOLOGY_SYSTEM_PROMPT = """You are a professional knowledge-graph ontology design expert. Your task is to analyze the provided text content and simulation requirements, and design entity types and relationship types suitable for a **social-media public-opinion simulation**.

**IMPORTANT: You MUST output valid JSON-formatted data and nothing else.**

## Core Task Background

We are building a **social-media public-opinion simulation system**. In this system:
- Each entity is an "account" or "actor" that can speak, interact, and propagate information on social media
- Entities influence each other, repost, comment on, and respond to one another
- We need to simulate how the various sides react in a public-opinion event and how information spreads

Therefore, **entities must be real-world subjects that can speak and interact on social media**:

**Allowed**:
- Specific individuals (public figures, persons involved, opinion leaders, scholars/experts, ordinary people)
- Companies and businesses (including their official accounts)
- Organizations and institutions (universities, associations, NGOs, unions, etc.)
- Government departments and regulators
- Media outlets (newspapers, TV stations, self-media, websites)
- The social-media platforms themselves
- Representatives of specific groups (e.g., alumni associations, fan clubs, advocacy groups)

**Not allowed**:
- Abstract concepts (e.g., "public opinion", "sentiment", "trends")
- Topics/subjects (e.g., "academic integrity", "education reform")
- Stances/attitudes (e.g., "the supporting side", "the opposing side")

## Output Format

Output JSON with the following structure:

```json
{
    "entity_types": [
        {
            "name": "Entity type name (English, PascalCase)",
            "description": "Short description (English, no more than 100 characters)",
            "attributes": [
                {
                    "name": "Attribute name (English, snake_case)",
                    "type": "text",
                    "description": "Attribute description"
                }
            ],
            "examples": ["example entity 1", "example entity 2"]
        }
    ],
    "edge_types": [
        {
            "name": "Relationship type name (English, UPPER_SNAKE_CASE)",
            "description": "Short description (English, no more than 100 characters)",
            "source_targets": [
                {"source": "source entity type", "target": "target entity type"}
            ],
            "attributes": []
        }
    ],
    "analysis_summary": "A brief analytical summary of the text content"
}
```

## Design Guide (Extremely Important!)

### 1. Entity-Type Design — must be strictly followed

**Quantity requirement: exactly 10 entity types**

**Hierarchy requirement (must include both specific types and fallback types)**:

Your 10 entity types must cover the following hierarchy:

A. **Fallback types (must include; place at the end of the list, last 2)**:
   - `Person`: fallback type for any natural person. When a person does not fit any more specific person type, classify as Person.
   - `Organization`: fallback type for any organization/institution. When an organization does not fit any more specific organization type, classify as Organization.

B. **Specific types (8 of them, designed based on the text content)**:
   - For the main roles that appear in the text, design more specific types
   - Example: if the text concerns an academic event, you may have `Student`, `Professor`, `University`
   - Example: if the text concerns a business event, you may have `Company`, `CEO`, `Employee`

**Why fallback types are needed**:
- The text may mention various people such as "K-12 teachers", "a passerby", "some netizen"
- If no dedicated type matches, they should be classified as `Person`
- Likewise, small organizations and ad-hoc groups should be classified as `Organization`

**Design principles for specific types**:
- Identify the high-frequency or key role types from the text
- Each specific type should have clear boundaries — avoid overlap
- The description must clearly state the difference between this type and the fallback type

### 2. Relationship-Type Design

- Quantity: 6-10
- Relationships should reflect actual connections in social-media interactions
- Make sure the source_targets of each relationship cover the entity types you defined

### 3. Attribute Design

- 1-3 key attributes per entity type
- **Note**: attribute names cannot use `name`, `uuid`, `group_id`, `created_at`, `summary` (these are system reserved words)
- Recommended: `full_name`, `title`, `role`, `position`, `location`, `description`, etc.

## Entity Type References

**Person types (specific)**:
- Student: a student
- Professor: a professor / academic
- Journalist: a journalist
- Celebrity: a celebrity / influencer
- Executive: an executive
- Official: a government official
- Lawyer: a lawyer
- Doctor: a doctor

**Person types (fallback)**:
- Person: any natural person (use when none of the specific person types fit)

**Organization types (specific)**:
- University: a university / college
- Company: a company / business
- GovernmentAgency: a government agency
- MediaOutlet: a media outlet
- Hospital: a hospital
- School: a primary or secondary school
- NGO: a non-governmental organization

**Organization types (fallback)**:
- Organization: any organization (use when none of the specific organization types fit)

## Relationship Type References

- WORKS_FOR: works for
- STUDIES_AT: studies at
- AFFILIATED_WITH: affiliated with
- REPRESENTS: represents
- REGULATES: regulates
- REPORTS_ON: reports on
- COMMENTS_ON: comments on
- RESPONDS_TO: responds to
- SUPPORTS: supports
- OPPOSES: opposes
- COLLABORATES_WITH: collaborates with
- COMPETES_WITH: competes with
"""


class OntologyGenerator:
    """
    Ontology generator
    Analyzes text content and produces entity- and relationship-type definitions.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()

    def generate(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate ontology definitions

        Args:
            document_texts: List of document texts
            simulation_requirement: Simulation requirement description
            additional_context: Extra context

        Returns:
            Ontology definition (entity_types, edge_types, etc.)
        """
        # Build the user message
        user_message = self._build_user_message(
            document_texts,
            simulation_requirement,
            additional_context
        )

        lang_instruction = get_language_instruction()
        system_prompt = f"{ONTOLOGY_SYSTEM_PROMPT}\n\n{lang_instruction}\nIMPORTANT: Entity names MUST be in English. Entity type names MUST be in English PascalCase (e.g., 'PersonEntity', 'MediaOrganization'). Relationship type names MUST be in English UPPER_SNAKE_CASE (e.g., 'WORKS_FOR'). Attribute names MUST be in English snake_case. All entity node names extracted from the text MUST also be in English (translate any non-English names into English). Only description fields and analysis_summary should use the specified language above."
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        # Call the LLM
        result = self.llm_client.chat_json(
            messages=messages,
            temperature=0.3,
            max_tokens=4096
        )

        # Validate and post-process
        result = self._validate_and_process(result)

        return result

    # Maximum length of text passed to the LLM (50,000 characters)
    MAX_TEXT_LENGTH_FOR_LLM = 50000

    def _build_user_message(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str]
    ) -> str:
        """Build the user message"""

        # Concatenate the text
        combined_text = "\n\n---\n\n".join(document_texts)
        original_length = len(combined_text)

        # If the text exceeds 50,000 characters, truncate it
        # (only affects what is passed to the LLM, not graph construction)
        if len(combined_text) > self.MAX_TEXT_LENGTH_FOR_LLM:
            combined_text = combined_text[:self.MAX_TEXT_LENGTH_FOR_LLM]
            combined_text += f"\n\n...(original text is {original_length} characters; first {self.MAX_TEXT_LENGTH_FOR_LLM} characters used for ontology analysis)..."

        message = f"""## Simulation Requirement

{simulation_requirement}

## Document Content

{combined_text}
"""

        if additional_context:
            message += f"""
## Additional Notes

{additional_context}
"""

        message += """
Based on the content above, design entity types and relationship types suitable for a public-opinion simulation.

**Mandatory rules**:
1. Output exactly 10 entity types
2. The last 2 must be fallback types: Person (fallback for individuals) and Organization (fallback for organizations)
3. The first 8 are specific types designed for the text content
4. All entity types must be real-world subjects that can speak; they cannot be abstract concepts
5. Attribute names cannot use reserved words such as name, uuid, group_id; use full_name, org_name, etc. instead
"""

        return message

    def _validate_and_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and post-process the result"""

        # Make sure required fields exist
        if "entity_types" not in result:
            result["entity_types"] = []
        if "edge_types" not in result:
            result["edge_types"] = []
        if "analysis_summary" not in result:
            result["analysis_summary"] = ""

        # Validate entity types
        # Track original-name to PascalCase mapping so we can fix up edge source_targets later
        entity_name_map = {}
        for entity in result["entity_types"]:
            # Force entity name to PascalCase (Zep API requirement)
            if "name" in entity:
                original_name = entity["name"]
                entity["name"] = _to_pascal_case(original_name)
                if entity["name"] != original_name:
                    logger.warning(f"Entity type name '{original_name}' auto-converted to '{entity['name']}'")
                entity_name_map[original_name] = entity["name"]
            if "attributes" not in entity:
                entity["attributes"] = []
            if "examples" not in entity:
                entity["examples"] = []
            # Make sure description is no longer than 100 characters
            if len(entity.get("description", "")) > 100:
                entity["description"] = entity["description"][:97] + "..."

        # Validate relationship types
        for edge in result["edge_types"]:
            # Force edge name to SCREAMING_SNAKE_CASE (Zep API requirement)
            if "name" in edge:
                original_name = edge["name"]
                edge["name"] = original_name.upper()
                if edge["name"] != original_name:
                    logger.warning(f"Edge type name '{original_name}' auto-converted to '{edge['name']}'")
            # Fix up entity-name references inside source_targets to match the converted PascalCase
            for st in edge.get("source_targets", []):
                if st.get("source") in entity_name_map:
                    st["source"] = entity_name_map[st["source"]]
                if st.get("target") in entity_name_map:
                    st["target"] = entity_name_map[st["target"]]
            if "source_targets" not in edge:
                edge["source_targets"] = []
            if "attributes" not in edge:
                edge["attributes"] = []
            if len(edge.get("description", "")) > 100:
                edge["description"] = edge["description"][:97] + "..."

        # Zep API limits: at most 10 custom entity types and at most 10 custom edge types
        MAX_ENTITY_TYPES = 10
        MAX_EDGE_TYPES = 10

        # Deduplicate by name; keep the first occurrence
        seen_names = set()
        deduped = []
        for entity in result["entity_types"]:
            name = entity.get("name", "")
            if name and name not in seen_names:
                seen_names.add(name)
                deduped.append(entity)
            elif name in seen_names:
                logger.warning(f"Duplicate entity type '{name}' removed during validation")
        result["entity_types"] = deduped

        # Fallback type definitions
        person_fallback = {
            "name": "Person",
            "description": "Any individual person not fitting other specific person types.",
            "attributes": [
                {"name": "full_name", "type": "text", "description": "Full name of the person"},
                {"name": "role", "type": "text", "description": "Role or occupation"}
            ],
            "examples": ["ordinary citizen", "anonymous netizen"]
        }

        organization_fallback = {
            "name": "Organization",
            "description": "Any organization not fitting other specific organization types.",
            "attributes": [
                {"name": "org_name", "type": "text", "description": "Name of the organization"},
                {"name": "org_type", "type": "text", "description": "Type of organization"}
            ],
            "examples": ["small business", "community group"]
        }

        # Check whether the fallback types are already present
        entity_names = {e["name"] for e in result["entity_types"]}
        has_person = "Person" in entity_names
        has_organization = "Organization" in entity_names

        # Fallback types that need to be added
        fallbacks_to_add = []
        if not has_person:
            fallbacks_to_add.append(person_fallback)
        if not has_organization:
            fallbacks_to_add.append(organization_fallback)

        if fallbacks_to_add:
            current_count = len(result["entity_types"])
            needed_slots = len(fallbacks_to_add)

            # If adding the fallbacks would exceed 10, remove some existing types
            if current_count + needed_slots > MAX_ENTITY_TYPES:
                # Calculate how many to remove
                to_remove = current_count + needed_slots - MAX_ENTITY_TYPES
                # Remove from the end (keeping the more important specific types at the front)
                result["entity_types"] = result["entity_types"][:-to_remove]

            # Append the fallback types
            result["entity_types"].extend(fallbacks_to_add)

        # Final guarantee that we don't exceed the limits (defensive programming)
        if len(result["entity_types"]) > MAX_ENTITY_TYPES:
            result["entity_types"] = result["entity_types"][:MAX_ENTITY_TYPES]

        if len(result["edge_types"]) > MAX_EDGE_TYPES:
            result["edge_types"] = result["edge_types"][:MAX_EDGE_TYPES]

        return result

    def generate_python_code(self, ontology: Dict[str, Any]) -> str:
        """
        Convert the ontology definition into Python code (similar to ontology.py)

        Args:
            ontology: Ontology definition

        Returns:
            Python source-code string
        """
        code_lines = [
            '"""',
            'Custom entity-type definitions',
            'Auto-generated by MiroFish, used for public-opinion simulation',
            '"""',
            '',
            'from pydantic import Field',
            'from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel',
            '',
            '',
            '# ============== Entity type definitions ==============',
            '',
        ]

        # Generate entity types
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            desc = entity.get("description", f"A {name} entity.")

            code_lines.append(f'class {name}(EntityModel):')
            code_lines.append(f'    """{desc}"""')

            attrs = entity.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')

            code_lines.append('')
            code_lines.append('')

        code_lines.append('# ============== Relationship type definitions ==============')
        code_lines.append('')

        # Generate relationship types
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            # Convert to PascalCase class name
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            desc = edge.get("description", f"A {name} relationship.")

            code_lines.append(f'class {class_name}(EdgeModel):')
            code_lines.append(f'    """{desc}"""')

            attrs = edge.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')

            code_lines.append('')
            code_lines.append('')

        # Generate type-config dictionaries
        code_lines.append('# ============== Type configuration ==============')
        code_lines.append('')
        code_lines.append('ENTITY_TYPES = {')
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            code_lines.append(f'    "{name}": {name},')
        code_lines.append('}')
        code_lines.append('')
        code_lines.append('EDGE_TYPES = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            code_lines.append(f'    "{name}": {class_name},')
        code_lines.append('}')
        code_lines.append('')

        # Generate edge source_targets map
        code_lines.append('EDGE_SOURCE_TARGETS = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            source_targets = edge.get("source_targets", [])
            if source_targets:
                st_list = ', '.join([
                    f'{{"source": "{st.get("source", "Entity")}", "target": "{st.get("target", "Entity")}"}}'
                    for st in source_targets
                ])
                code_lines.append(f'    "{name}": [{st_list}],')
        code_lines.append('}')

        return '\n'.join(code_lines)

