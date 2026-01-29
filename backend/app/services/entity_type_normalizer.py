"""
Entity type normalization.

The extractor/ontology may produce fine-grained entity types that are unstable across chunks.
To reduce duplicate nodes, we normalize types into a small canonical set:
  Person / Organization / Product / Location
"""

from __future__ import annotations

import re
from typing import Optional


CANONICAL_PERSON = "Person"
CANONICAL_ORGANIZATION = "Organization"
CANONICAL_PRODUCT = "Product"
CANONICAL_LOCATION = "Location"


def canonicalize_entity_type(raw_type: Optional[str]) -> str:
    t = (raw_type or "").strip()
    if not t:
        return "Entity"

    # Exact matches (most common)
    if t in {CANONICAL_PERSON, CANONICAL_ORGANIZATION, CANONICAL_PRODUCT, CANONICAL_LOCATION}:
        return t

    tl = t.lower()

    # Chinese hints (best-effort)
    if any(k in t for k in ("人物", "个人", "人", "当事人")):
        return CANONICAL_PERSON
    if any(k in t for k in ("组织", "机构", "公司", "企业", "政府", "部门", "媒体", "平台", "账号", "协会", "大学")):
        return CANONICAL_ORGANIZATION
    if any(k in t for k in ("产品", "应用", "软件", "系统", "品牌", "模型")):
        return CANONICAL_PRODUCT
    if any(k in t for k in ("地点", "位置", "城市", "国家", "地区", "省", "市", "县", "区")):
        return CANONICAL_LOCATION

    # Heuristic buckets (English-ish types from ontology)
    person_tokens = {
        "person",
        "people",
        "individual",
        "actor",
        "leader",
        "celebrity",
        "expert",
        "scholar",
        "journalist",
        "student",
        "citizen",
        "witness",
        "victim",
        "perpetrator",
        "influencer",
        "opinionleader",
        "kols",
        "kol",
    }
    org_tokens = {
        "organization",
        "org",
        "company",
        "enterprise",
        "brand",
        "agency",
        "department",
        "government",
        "regulator",
        "university",
        "school",
        "institute",
        "ngo",
        "union",
        "association",
        "foundation",
        "media",
        "newspaper",
        "tv",
        "platform",
        "committee",
        "community",
        "account",
    }
    product_tokens = {
        "product",
        "app",
        "application",
        "service",
        "tool",
        "model",
        "software",
        "system",
        "api",
        "framework",
        "device",
        "game",
    }
    location_tokens = {
        "location",
        "place",
        "city",
        "country",
        "province",
        "region",
        "state",
        "county",
        "district",
        "area",
    }

    def _tokenize(s: str) -> set[str]:
        parts = re.split(r"[^a-z0-9]+", s.lower())
        return {p for p in parts if p}

    tokens = _tokenize(tl)

    if tokens & person_tokens:
        return CANONICAL_PERSON
    if tokens & location_tokens:
        return CANONICAL_LOCATION
    if tokens & product_tokens:
        return CANONICAL_PRODUCT
    if tokens & org_tokens:
        return CANONICAL_ORGANIZATION

    # PascalCase hints
    if any(k in tl for k in ("account", "agency", "company", "org", "platform", "media", "university", "school")):
        return CANONICAL_ORGANIZATION
    if any(k in tl for k in ("product", "app", "model", "service", "system", "software")):
        return CANONICAL_PRODUCT
    if any(k in tl for k in ("location", "place", "city", "country", "province", "region", "district")):
        return CANONICAL_LOCATION
    if any(k in tl for k in ("person", "individual", "actor", "leader", "expert", "student", "journalist")):
        return CANONICAL_PERSON

    # Unknown: keep original to avoid over-merging
    return t
