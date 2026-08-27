from __future__ import annotations

import copy


def normalize_output_schema(schema: dict) -> dict:
    result = copy.deepcopy(schema)

    def visit(value):
        if isinstance(value, dict):
            value.pop("default", None)
            properties = value.get("properties")
            if value.get("type") == "object" and isinstance(properties, dict):
                value["additionalProperties"] = False
                value["required"] = list(properties)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(result)
    return result
