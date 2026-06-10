"""
Ontology generation service
Interface 1: analyze text content to generate entity and relationship type definitions suitable for social simulation
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional
from ..utils.llm_client import LLMClient
from ..utils.locale import get_language_instruction

logger = logging.getLogger(__name__)


def _to_pascal_case(name: str) -> str:
    """Convert any-format name to PascalCase (e.g. 'works_for' -> 'WorksFor', 'person' -> 'Person')"""
    # Split by non-alphanumeric characters
    parts = re.split(r'[^a-zA-Z0-9]+', name)
    # Then split by camelCase boundaries (e.g. 'camelCase' -> ['camel', 'Case'])
    words = []
    for part in parts:
        words.extend(re.sub(r'([a-z])([A-Z])', r'\1_\2', part).split('_'))
    # Capitalize each word, filter out empty strings
    result = ''.join(word.capitalize() for word in words if word)
    return result if result else 'Unknown'


# System prompt for ontology generation
ONTOLOGY_SYSTEM_PROMPT = """You are a professional knowledge-graph ontology design expert. Your task is to analyze the given text content and simulation requirement, design entity types and relationship types suitable for **social media public-opinion simulation**.

**IMPORTANT: You MUST output valid JSON format data, and nothing else.**

## Core Task Background

We are building a **social media public-opinion simulation system**. In this system:
- Each entity is an "account" or "subject" that can speak out, interact, and spread information on social media
- Entities influence each other, repost, comment, and respond
- We need to simulate the reactions of all parties and the information propagation paths in public-opinion events

Therefore, **Entities must be real-world subjects that actually exist and can speak out and interact on social media**:

**Can be**:
- Specific individuals (public figures, parties involved, opinion leaders, experts and scholars, ordinary people)
- Companies, enterprises (including their official accounts)
- Organizations (universities, associations, NGOs, unions, etc.)
- Government departments, regulatory agencies
- Media organizations (newspapers, TV stations, self-media, websites)
- Social media platforms themselves
- Representatives of specific groups (e.g., alumni associations, fan groups, rights-advocacy groups, etc.)

**Cannot be**:
- Abstract concepts (e.g., "public opinion", "emotion", "trend")
- Themes/topics (e.g., "academic integrity", "education reform")
- Views/attitudes (e.g., "supporters", "opponents")

## Output Format

Please output JSON format containing the following structure:

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
            "examples": ["Example entity 1", "Example entity 2"]
        }
    ],
    "edge_types": [
        {
            "name": "Relationship type name (English, UPPER_SNAKE_CASE)",
            "description": "Short description (English, no more than 100 characters)",
            "source_targets": [
                {"source": "Source entity type", "target": "Target entity type"}
            ],
            "attributes": []
        }
    ],
    "analysis_summary": "Brief analysis and description of the text content"
}
```

## Design Guidelines (EXTREMELY IMPORTANT!)

### 1. Entity Type Design - MUST be strictly followed

**Quantity requirement: must be exactly 10 entity types**

**Hierarchy requirement (must include both specific types and fallback types)**:

Your 10 entity types must include the following levels:

A. **Fallback types (must be included, placed last 2 in the list)**:
   - `Person`: Fallback type for any individual person. When a person does not fit any other more specific person type, they are classified here.
   - `Organization`: Fallback type for any organization. When an organization does not fit any other more specific organization type, it is classified here.

B. **Specific types (8, designed from the text content)**:
   - Design more specific types for the main characters appearing in the text
   - For example: if the text involves an academic event, you may have `Student`, `Professor`, `University`
   - For example: if the text involves a business event, you may have `Company`, `CEO`, `Employee`

**Why fallback types are needed**:
- The text will contain various characters, such as "primary/secondary school teachers", "passerby A", "a certain netizen"
- If no specific type matches them, they should be classified as `Person`
- Similarly, small organizations, temporary groups, etc. should be classified as `Organization`

**Design principles for specific types**:
- Identify frequently occurring or key character types from the text
- Each specific type should have clear boundaries to avoid overlap
- The description must clearly explain the difference between this type and the fallback types

### 2. Relationship Type Design

- Quantity: 6-10
- Relationships should reflect real connections in social-media interactions
- Ensure the source_targets of relationships cover the entity types you defined

### 3. Attribute Design

- 1-3 key attributes per entity type
- **Note**: Attribute names must NOT use `name`, `uuid`, `group_id`, `created_at`, `summary` (these are system reserved words)
- Recommended: `full_name`, `title`, `role`, `position`, `location`, `description`, etc.

## Entity Type Reference

**Person types (specific)**:
- Student: Student
- Professor: Professor/Scholar
- Journalist: Journalist
- Celebrity: Celebrity/Internet celebrity
- Executive: Executive
- Official: Government official
- Lawyer: Lawyer
- Doctor: Doctor

**Person types (fallback)**:
- Person: Any individual (used when not fitting the specific types above)

**Organization types (specific)**:
- University: University/College
- Company: Company/Enterprise
- GovernmentAgency: Government agency
- MediaOutlet: Media organization
- Hospital: Hospital
- School: Primary/Secondary school
- NGO: Non-governmental organization

**Organization types (fallback)**:
- Organization: Any organization (used when not fitting the specific types above)

## Relationship Type Reference

- WORKS_FOR: Works for
- STUDIES_AT: Studies at
- AFFILIATED_WITH: Affiliated with
- REPRESENTS: Represents
- REGULATES: Regulates
- REPORTS_ON: Reports on
- COMMENTS_ON: Comments on
- RESPONDS_TO: Responds to
- SUPPORTS: Supports
- OPPOSES: Opposes
- COLLABORATES_WITH: Collaborates with
- COMPETES_WITH: Competes with
"""


class OntologyGenerator:
    """
    Ontology generator
    Analyze text content and generate entity and relationship type definitions
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
        Generate the ontology definition
        
        Args:
            document_texts: List of document texts
            simulation_requirement: Simulation requirement description
            additional_context: Additional context
            
        Returns:
            Ontology definition (entity_types, edge_types, etc.)
        """
        # Build user message
        user_message = self._build_user_message(
            document_texts, 
            simulation_requirement,
            additional_context
        )
        
        lang_instruction = get_language_instruction()
        system_prompt = f"{ONTOLOGY_SYSTEM_PROMPT}\n\n{lang_instruction}\nIMPORTANT: Entity type names MUST be in English PascalCase (e.g., 'PersonEntity', 'MediaOrganization'). Relationship type names MUST be in English UPPER_SNAKE_CASE (e.g., 'WORKS_FOR'). Attribute names MUST be in English snake_case. Only description fields and analysis_summary should use the specified language above."
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        # Call the LLM
        try:
            result = self.llm_client.chat_json(
                messages=messages,
                temperature=0.3,
                max_tokens=16384,
            )
        except ValueError as json_err:
            logger.warning(
                f"[ontology] first attempt failed (likely M3 JSON truncation): {json_err}; retrying with compact prompt"
            )
            # Compact retry: limit the number of entity/edge types, drop attributes
            compact_doc = "\n".join(document_texts)[:30000]
            compact_messages = [
                {
                    "role": "system",
                    "content": (
                        "Output ONLY valid JSON, no markdown, no commentary. "
                        "Schema: {entity_types:[{name:PascalCase,description:short}],"
                        "edge_types:[{name:UPPER_SNAKE_CASE,description:short}],"
                        "analysis_summary:one sentence}. "
                        "Limit to AT MOST 6 entity types and 6 edge types. "
                        "Do NOT include attributes arrays."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Text:\\n{compact_doc}\\n\\nRequirement: {simulation_requirement}\\n\\nReturn JSON.",
                },
            ]
            result = self.llm_client.chat_json(
                messages=compact_messages,
                temperature=0.2,
                max_tokens=8192,
            )

        # Validate and post-process
        result = self._validate_and_process(result)
        
        return result
    
    # Max text length to send to the LLM (50,000 chars)
    MAX_TEXT_LENGTH_FOR_LLM = 50000
    
    def _build_user_message(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str]
    ) -> str:
        """Build user message"""
        
        # Merge text
        combined_text = "\n\n---\n\n".join(document_texts)
        original_length = len(combined_text)
        
        # If text exceeds 50,000 chars, truncate (only affects what is sent to the LLM, not the graph construction)
        if len(combined_text) > self.MAX_TEXT_LENGTH_FOR_LLM:
            combined_text = combined_text[:self.MAX_TEXT_LENGTH_FOR_LLM]
            combined_text += f"\n\n...(original text is {original_length} chars, truncated to the first {self.MAX_TEXT_LENGTH_FOR_LLM} chars for ontology analysis)..."
        
        message = f"""## Simulation requirements

{simulation_requirement}

## Document content

{combined_text}
"""
        
        if additional_context:
            message += f"""
## Additional notes

{additional_context}
"""
        
        message += """
Please design entity types and edge types suitable for social opinion simulation based on the content above.

**Rules that must be followed**:
1. Output exactly 10 entity types
2. The last 2 must be fallback types: Person (individual fallback) and Organization (organization fallback)
3. The first 8 should be specific types designed from the text content
4. All entity types must be real-world entities capable of speaking out, not abstract concepts
5. Attribute names must not use reserved words like name, uuid, group_id; use full_name, org_name, etc. instead
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
        # Record the raw-name -> PascalCase mapping, used later to fix edge source_targets references
        entity_name_map = {}
        for entity in result["entity_types"]:
            # Force-convert entity name to PascalCase (Zep API requirement)
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
        
        # Validate edge types
        for edge in result["edge_types"]:
            # Force-convert edge name to SCREAMING_SNAKE_CASE (Zep API requirement)
            if "name" in edge:
                original_name = edge["name"]
                edge["name"] = original_name.upper()
                if edge["name"] != original_name:
                    logger.warning(f"Edge type name '{original_name}' auto-converted to '{edge['name']}'")
            # Fix entity name references in source_targets to match the converted PascalCase
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
        
        # Zep API limit: at most 10 custom entity types, at most 10 custom edge types
        MAX_ENTITY_TYPES = 10
        MAX_EDGE_TYPES = 10

        # Deduplicate by name, keep the first occurrence
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
        
        # Check whether fallback types already exist
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
            
            # If adding would exceed 10, we need to drop some existing types
            if current_count + needed_slots > MAX_ENTITY_TYPES:
                # Compute how many to remove
                to_remove = current_count + needed_slots - MAX_ENTITY_TYPES
                # Remove from the end (keep the more important specific types at the front)
                result["entity_types"] = result["entity_types"][:-to_remove]
            
            # Add fallback types
            result["entity_types"].extend(fallbacks_to_add)
        
        # Final guard to ensure the limit is not exceeded (defensive coding)
        if len(result["entity_types"]) > MAX_ENTITY_TYPES:
            result["entity_types"] = result["entity_types"][:MAX_ENTITY_TYPES]
        
        if len(result["edge_types"]) > MAX_EDGE_TYPES:
            result["edge_types"] = result["edge_types"][:MAX_EDGE_TYPES]
        
        return result
    
    def generate_python_code(self, ontology: Dict[str, Any]) -> str:
        """
        Convert the ontology definition to Python code (similar to ontology.py)
        
        Args:
            ontology: Ontology definition
            
        Returns:
            Python code string
        """
        code_lines = [
            '"""',
            'Custom entity type definitions',
            'Auto-generated by MiroFish, for social opinion simulation',
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
        
        code_lines.append('# ============== Edge type definitions ==============')
        code_lines.append('')
        
        # Generate edge types
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
        
        # Generate type dictionary
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

