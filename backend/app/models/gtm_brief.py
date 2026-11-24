"""
GTMBrief model - stores a founder's GTM simulation brief.
"""

import os
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional, Dict, Any

from ..config import Config
from ..services.gtm_audience import normalize_audience


REQUIRED_FIELDS = [
    'product_name', 'product_description', 'icp',
    'pricing_model', 'target_market', 'sales_channel',
    'pain_point', 'gtm_goal',
]

FIELD_MIN_LENGTHS = {
    'product_name': 2,
    'product_description': 20,
    'icp': 20,
    'pricing_model': 2,
    'target_market': 5,
    'pain_point': 20,
}


@dataclass
class GTMBrief:
    brief_id: str
    product_name: str
    product_description: str
    icp: str
    pricing_model: str
    target_market: str
    sales_channel: str
    pain_point: str
    competitors: List[str]
    gtm_goal: str
    created_at: str
    company_stage: Optional[str] = None
    team_size: Optional[str] = None
    existing_problems: Optional[str] = None
    outreach_strategy: Optional[str] = None
    num_personas: int = 12
    num_messages: int = 3
    audience: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GTMBrief':
        return cls(
            brief_id=data['brief_id'],
            product_name=data['product_name'],
            product_description=data['product_description'],
            icp=data['icp'],
            pricing_model=data['pricing_model'],
            target_market=data['target_market'],
            sales_channel=data['sales_channel'],
            pain_point=data['pain_point'],
            competitors=data.get('competitors', []),
            gtm_goal=data['gtm_goal'],
            created_at=data['created_at'],
            company_stage=data.get('company_stage'),
            team_size=data.get('team_size'),
            existing_problems=data.get('existing_problems'),
            outreach_strategy=data.get('outreach_strategy'),
            num_personas=int(data.get('num_personas', 12)),
            num_messages=int(data.get('num_messages', 3)),
            audience=normalize_audience(data.get('audience')),
        )


class GTMBriefManager:

    @staticmethod
    def _brief_dir(brief_id: str) -> str:
        return os.path.join(Config.UPLOAD_FOLDER, 'gtm_briefs', brief_id)

    @staticmethod
    def _brief_path(brief_id: str) -> str:
        return os.path.join(GTMBriefManager._brief_dir(brief_id), 'brief.json')

    @staticmethod
    def validate(data: Dict[str, Any]) -> List[Dict[str, str]]:
        """Return list of {field, message} validation errors."""
        errors = []
        for f in REQUIRED_FIELDS:
            val = (data.get(f) or '').strip()
            if not val:
                errors.append({'field': f, 'message': f'{f} is required'})
            elif f in FIELD_MIN_LENGTHS and len(val) < FIELD_MIN_LENGTHS[f]:
                errors.append({
                    'field': f,
                    'message': f'{f} must be at least {FIELD_MIN_LENGTHS[f]} characters'
                })
        return errors

    @staticmethod
    def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
        """Trim strings, split competitors."""
        competitors = data.get('competitors', '')
        if isinstance(competitors, list):
            competitors = [c.strip() for c in competitors if c.strip()]
        elif isinstance(competitors, str):
            competitors = [c.strip() for c in competitors.split(',') if c.strip()]
        else:
            competitors = []

        return {
            'product_name': (data.get('product_name') or '').strip(),
            'product_description': (data.get('product_description') or '').strip(),
            'icp': (data.get('icp') or '').strip(),
            'pricing_model': (data.get('pricing_model') or '').strip(),
            'target_market': (data.get('target_market') or '').strip(),
            'sales_channel': (data.get('sales_channel') or '').strip(),
            'pain_point': (data.get('pain_point') or '').strip(),
            'competitors': competitors,
            'gtm_goal': (data.get('gtm_goal') or '').strip(),
            'company_stage': (data.get('company_stage') or '').strip() or None,
            'team_size': (data.get('team_size') or '').strip() or None,
            'existing_problems': (data.get('existing_problems') or '').strip() or None,
            'outreach_strategy': (data.get('outreach_strategy') or '').strip() or None,
            'num_personas': max(6, min(500, int(data.get('num_personas') or 12))),
            'num_messages': max(2, min(5, int(data.get('num_messages') or 3))),
            'audience': normalize_audience(data.get('audience')),
        }

    @staticmethod
    def create_brief(data: Dict[str, Any]) -> GTMBrief:
        """Validate, normalize, persist, and return a new GTMBrief."""
        normalized = GTMBriefManager._normalize(data)
        brief = GTMBrief(
            brief_id=str(uuid.uuid4()),
            created_at=datetime.now().isoformat(),
            **normalized,
        )
        brief_dir = GTMBriefManager._brief_dir(brief.brief_id)
        os.makedirs(brief_dir, exist_ok=True)
        with open(GTMBriefManager._brief_path(brief.brief_id), 'w', encoding='utf-8') as f:
            json.dump(brief.to_dict(), f, ensure_ascii=False, indent=2)
        return brief

    @staticmethod
    def get_brief(brief_id: str) -> Optional[GTMBrief]:
        path = GTMBriefManager._brief_path(brief_id)
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return GTMBrief.from_dict(json.load(f))

    @staticmethod
    def list_briefs(limit: int = 20) -> List[GTMBrief]:
        base = os.path.join(Config.UPLOAD_FOLDER, 'gtm_briefs')
        if not os.path.exists(base):
            return []
        briefs = []
        for brief_id in os.listdir(base):
            brief = GTMBriefManager.get_brief(brief_id)
            if brief:
                briefs.append(brief)
        briefs.sort(key=lambda b: b.created_at, reverse=True)
        return briefs[:limit]
