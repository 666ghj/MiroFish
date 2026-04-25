"""
Ontology generation service
Endpoint 1: Analyze text content and generate entity and relationship type definitions suitable for social simulation.
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional
from ..utils.llm_client import LLMClient
from ..utils.locale import get_language_instruction, t

logger = logging.getLogger(__name__)


def _to_pascal_case(name: str) -> str:
    """Convert a name in any format to PascalCase (e.g. 'works_for' -> 'WorksFor', 'person' -> 'Person')"""
    # Split on non-alphanumeric characters
    parts = re.split(r'[^a-zA-Z0-9]+', name)
    # Also split on camelCase boundaries (e.g. 'camelCase' -> ['camel', 'Case'])
    words = []
    for part in parts:
        words.extend(re.sub(r'([a-z])([A-Z])', r'\1_\2', part).split('_'))
    # Capitalize each word and filter empty strings
    result = ''.join(word.capitalize() for word in words if word)
    return result if result else 'Unknown'


# System prompt for ontology generation
ONTOLOGY_SYSTEM_PROMPT = """You are a professional knowledge graph ontology design expert. Your task is to analyze the given text content and simulation requirements, and design entity types and relationship types suitable for **social media opinion simulation**.

**Important: You must output valid JSON format data, and nothing else.**

## Core Task Background

We are building a **social media opinion simulation system**. In this system:
- Every entity is an "account" or "subject" that can speak out, interact, and spread information on social media
- Entities influence each other, repost, comment, and respond
- We need to simulate each party's reaction and the information propagation path during opinion events

Therefore, **entities must be real-world subjects that exist and can speak out and interact on social media**:

**Can be**:
- Specific individuals (public figures, persons involved, opinion leaders, experts and scholars, ordinary people)
- Companies and enterprises (including their official accounts)
- Organizations (universities, associations, NGOs, unions, etc.)
- Government departments and regulatory agencies
- Media organizations (newspapers, TV stations, self-media, websites)
- Social media platforms themselves
- Representatives of specific groups (e.g. alumni associations, fan clubs, rights-protection groups, etc.)

**Cannot be**:
- Abstract concepts (e.g. "public opinion", "emotion", "trend")
- Topics/themes (e.g. "academic integrity", "education reform")
- Viewpoints/attitudes (e.g. "supporters", "opponents")

## Output Format

Please output JSON format with the following structure:

```json
{
    "entity_types": [
        {
            "name": "Entity type name (PascalCase, in the language specified by the language instruction)",
            "description": "Brief description (in the language specified by the language instruction, max 100 characters)",
            "attributes": [
                {
                    "name": "Attribute name (snake_case, in the language specified by the language instruction)",
                    "type": "text",
                    "description": "Attribute description (in the language specified by the language instruction)"
                }
            ],
            "examples": ["Example entity 1 (in the language specified by the language instruction)", "Example entity 2"]
        }
    ],
    "edge_types": [
        {
            "name": "Relationship type name (UPPER_SNAKE_CASE, in the language specified by the language instruction)",
            "description": "Brief description (in the language specified by the language instruction, max 100 characters)",
            "source_targets": [
                {"source": "Source entity type", "target": "Target entity type"}
            ],
            "attributes": []
        }
    ],
    "analysis_summary": "Brief analysis summary of the text content (in the language specified by the language instruction)"
}
```

## Design Guidelines (Extremely Important!)

### 1. Entity Type Design — Must Be Strictly Followed

**Quantity requirement: exactly 20 entity types**

**Hierarchy requirement (must include both specific types and fallback types)**:

Your 20 entity types must include the following levels:

A. **Fallback types (required, placed as the last 2 in the list)**:
   - `Person`: Fallback type for any individual person. Use this when a person does not fit any other more specific person type.
   - `Organization`: Fallback type for any organization. Use this when an organization does not fit any other more specific organization type.

B. **Specific types (18 types, designed based on text content)**:
   - Design more specific types for the main roles that appear in the text
   - Example: if the text involves an academic event, you might have `Student`, `Professor`, `University`, `ResearchGroup`, `Alumni`, etc.
   - Example: if the text involves a business event, you might have `Company`, `CEO`, `Employee`, `Investor`, `Regulator`, etc.
   - Ensure broad coverage of all actor categories present in the text

**Why fallback types are needed**:
- Various people appear in text, such as "primary and secondary school teachers", "passersby", "some netizen"
- If there is no dedicated type to match them, they should fall into `Person`
- Similarly, small organizations, ad hoc groups, etc. should fall into `Organization`

**Principles for designing specific types**:
- Identify high-frequency or key role types from the text
- Each specific type should have clear boundaries and avoid overlap
- The description must clearly explain the difference between this type and the fallback types

### 2. Relationship Type Design

- Quantity: 12-20
- Relationships should reflect real connections in social media interactions
- Ensure the source_targets in relationships cover the entity types you have defined
- Aim for rich coverage: include hierarchical, collaborative, adversarial, and informational relationships

### 3. Attribute Design

- 1-3 key attributes per entity type
- **Note**: Attribute names must not use `name`, `uuid`, `group_id`, `created_at`, `summary` (these are system reserved words)
- Recommended: `full_name`, `title`, `role`, `position`, `location`, `description`, etc.

## Entity and Relationship Type Reference

Use the language specified in the language instruction for ALL names. Keep PascalCase for entity names and UPPER_SNAKE_CASE for relationship names, but use words from the target language.

**Individual type examples** (translate to target language):
- A person who is a student → StudentName in target language, PascalCase
- A person who is a journalist → JournalistName in target language, PascalCase
- Fallback for any individual → PersonName in target language, PascalCase

**Organization type examples** (translate to target language):
- A university → UniversityName in target language, PascalCase
- A government agency → AgencyName in target language, PascalCase
- Fallback for any organization → OrganizationName in target language, PascalCase

**Relationship type examples** (translate to target language):
- works for → WORKS_FOR translated to target language, UPPER_SNAKE_CASE
- reports on → REPORTS_ON translated to target language, UPPER_SNAKE_CASE
"""


class OntologyGenerator:
    """
    Ontology generator
    Analyzes text content and generates entity and relationship type definitions.
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
        Generate ontology definition.

        Args:
            document_texts: list of document texts
            simulation_requirement: simulation requirement description
            additional_context: additional context

        Returns:
            Ontology definition (entity_types, edge_types, etc.)
        """
        lang_instruction = get_language_instruction()

        # Build user message
        user_message = self._build_user_message(
            document_texts,
            simulation_requirement,
            additional_context,
            lang_instruction
        )

        system_prompt = f"LANGUAGE INSTRUCTION (HIGHEST PRIORITY — MUST BE FOLLOWED): {lang_instruction} ALL fields including names, descriptions, analysis_summary, and examples MUST be written in this language.\n\n{ONTOLOGY_SYSTEM_PROMPT}\n\n{lang_instruction}\nIMPORTANT: Entity type names MUST be in PascalCase (e.g., 'AgenciaGovern', 'FuncionariPublic'). Relationship type names MUST be in UPPER_SNAKE_CASE (e.g., 'TREBALLA_PER', 'RESPON_A'). Attribute names MUST be in snake_case. All names, descriptions, and examples must use the language specified above."
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        # Call LLM — 20 entity types + 20 edge types need more tokens than the old 10+10
        result = self.llm_client.chat_json(
            messages=messages,
            temperature=0.3,
            max_tokens=8192
        )

        # Validate and post-process
        result = self._validate_and_process(result)

        return result

    # Maximum text length passed to LLM (50,000 characters)
    MAX_TEXT_LENGTH_FOR_LLM = 50000

    def _build_user_message(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str],
        lang_instruction: str = ""
    ) -> str:
        """Build user message"""

        # Merge texts
        combined_text = "\n\n---\n\n".join(document_texts)
        original_length = len(combined_text)

        # If text exceeds 50,000 characters, truncate (only affects what is passed to LLM, not graph building)
        if len(combined_text) > self.MAX_TEXT_LENGTH_FOR_LLM:
            combined_text = combined_text[:self.MAX_TEXT_LENGTH_FOR_LLM]
            combined_text += f"\n\n...(text truncated at {self.MAX_TEXT_LENGTH_FOR_LLM} chars out of {original_length} total)..."

        message = f"""## Simulation requirement

{simulation_requirement}

## Document content

{combined_text}
"""

        if additional_context:
            message += f"""
## Additional context

{additional_context}
"""

        message += f"""
Based on the content above, design entity types and relationship types suitable for social opinion simulation.

**Mandatory rules**:
1. Output exactly 20 entity types
2. The last 2 must be fallback types: Person (individual fallback) and Organization (organization fallback)
3. The first 18 are specific types designed from the document content
4. All entity types must be real-world subjects capable of speaking out, not abstract concepts
5. Attribute names must not use reserved words: name, uuid, group_id — use full_name, org_name, etc. instead
6. Output 12-20 relationship types covering hierarchical, collaborative, adversarial, and informational relationships

{lang_instruction}
"""

        return message

    def _validate_and_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and post-process the result"""

        # Ensure required fields exist
        if "entity_types" not in result:
            result["entity_types"] = []
        if "edge_types" not in result:
            result["edge_types"] = []
        if "analysis_summary" not in result:
            result["analysis_summary"] = ""

        # Validate entity types
        # Record mapping from original name to PascalCase for fixing edge source_targets references later
        entity_name_map = {}
        for entity in result["entity_types"]:
            # Force entity name to PascalCase (required by Zep API)
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
            # Ensure description does not exceed 100 characters
            if len(entity.get("description", "")) > 100:
                entity["description"] = entity["description"][:97] + "..."

        # Validate relationship types
        for edge in result["edge_types"]:
            # Force edge name to SCREAMING_SNAKE_CASE (required by Zep API)
            if "name" in edge:
                original_name = edge["name"]
                edge["name"] = original_name.upper()
                if edge["name"] != original_name:
                    logger.warning(f"Edge type name '{original_name}' auto-converted to '{edge['name']}'")
            # Fix entity name references in source_targets to match converted PascalCase names
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

        # Limits: Graphiti/Neo4j has no hard cap; Zep Cloud allows max 10 of each.
        # We keep a generous cap for Graphiti and enforce Zep's limit at build time via config.
        MAX_ENTITY_TYPES = 20
        MAX_EDGE_TYPES = 20

        # Deduplicate: keep first occurrence by name
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

        # Fallback type definitions — names and descriptions come from i18n so they match
        # the locale used for the rest of the ontology (e.g. "Persona"/"Organització" in Catalan).
        person_fallback_name = _to_pascal_case(t("step1.ontologyFallbackPersonName") or "Person")
        org_fallback_name = _to_pascal_case(t("step1.ontologyFallbackOrgName") or "Organization")

        person_fallback = {
            "name": person_fallback_name,
            "description": t("step1.ontologyFallbackPersonDesc") or "Any individual person not fitting other specific person types.",
            "attributes": [
                {"name": "full_name", "type": "text", "description": "Full name of the person"},
                {"name": "role", "type": "text", "description": "Role or occupation"}
            ],
            "examples": t("step1.ontologyFallbackPersonExamples") or ["ordinary citizen", "anonymous netizen"]
        }

        organization_fallback = {
            "name": org_fallback_name,
            "description": t("step1.ontologyFallbackOrgDesc") or "Any organization not fitting other specific organization types.",
            "attributes": [
                {"name": "org_name", "type": "text", "description": "Name of the organization"},
                {"name": "org_type", "type": "text", "description": "Type of organization"}
            ],
            "examples": t("step1.ontologyFallbackOrgExamples") or ["small business", "community group"]
        }

        # Check whether fallback types already exist (match by i18n name)
        entity_names = {e["name"] for e in result["entity_types"]}
        has_person = person_fallback_name in entity_names
        has_organization = org_fallback_name in entity_names

        # Collect fallback types to add
        fallbacks_to_add = []
        if not has_person:
            fallbacks_to_add.append(person_fallback)
        if not has_organization:
            fallbacks_to_add.append(organization_fallback)

        if fallbacks_to_add:
            current_count = len(result["entity_types"])
            needed_slots = len(fallbacks_to_add)

            # If adding them would exceed the limit, remove some existing types from the end
            if current_count + needed_slots > MAX_ENTITY_TYPES:
                to_remove = current_count + needed_slots - MAX_ENTITY_TYPES
                result["entity_types"] = result["entity_types"][:-to_remove]

            # Add fallback types
            result["entity_types"].extend(fallbacks_to_add)

        # Final guard: ensure limits are not exceeded (defensive programming)
        if len(result["entity_types"]) > MAX_ENTITY_TYPES:
            result["entity_types"] = result["entity_types"][:MAX_ENTITY_TYPES]

        if len(result["edge_types"]) > MAX_EDGE_TYPES:
            result["edge_types"] = result["edge_types"][:MAX_EDGE_TYPES]

        return result

    def generate_python_code(self, ontology: Dict[str, Any]) -> str:
        """
        Convert the ontology definition to Python code (similar to ontology.py).

        Args:
            ontology: ontology definition

        Returns:
            Python code string
        """
        code_lines = [
            '"""',
            'Custom entity type definitions',
            'Auto-generated by MiroFish for social opinion simulation',
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

        # Generate type dictionaries
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

        # Generate edge source_targets mapping
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
