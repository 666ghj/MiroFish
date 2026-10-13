"""Report text must stay readable and parseable after translating its headings."""

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from app.services.zep_tools import (
    AgentInterview, InsightForgeResult, InterviewResult, NodeInfo,
    PanoramaResult, SearchResult,
)


def test_english_report_text_and_frontend_parsers():
    outputs = {
        'parseInsightForge': InsightForgeResult(
            query='Why?', simulation_requirement='Forecast demand', sub_queries=['What changed?'],
            semantic_facts=['Demand rose.'], entity_insights=[
                {'name': 'Alice', 'type': 'Person', 'summary': 'A customer', 'related_facts': ['Demand rose.']}],
            relationship_chains=['Alice --[likes]--> Product'], total_facts=1, total_entities=1,
            total_relationships=1,
        ).to_text(),
        'parsePanorama': PanoramaResult(
            query='Demand', all_nodes=[NodeInfo('1', 'Alice', ['Person'], 'Customer', {})],
            active_facts=['Demand rose.'], historical_facts=['Demand was low.'],
            total_nodes=1, total_edges=2, active_count=1, historical_count=1,
        ).to_text(),
        'parseInterview': InterviewResult(
            interview_topic='Demand', interview_questions=['Why?'],
            interviews=[AgentInterview('Alice', 'Customer', 'Likes products', 'Why?',
                '[Twitter response]\nUseful.\n\n[Reddit response]\nGood value.',
                ['The product is useful.'])],
            summary='Customers see value.', total_agents=2, interviewed_count=1,
        ).to_text(),
        'parseQuickSearch': SearchResult(['Demand rose.'], [], [], 'Demand', 1).to_text(),
    }
    assert not re.search(r'[\u4e00-\u9fff]', '\n'.join(outputs.values()))
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for the frontend parser contract check')
    component = Path(__file__).resolve().parents[2] / 'frontend/src/components/Step4Report.vue'
    source = component.read_text()
    parsers = source[source.index('const parseInsightForge ='):source.index('// ========== Sub Components')]
    script = parsers + '''
const data = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const results = {};
for (const [name, text] of Object.entries(data)) results[name] = eval(name)(text);
process.stdout.write(JSON.stringify(results));
'''
    response = subprocess.run([node, '-e', script], input=json.dumps(outputs),
                              text=True, capture_output=True, check=True)
    result = json.loads(response.stdout)
    insight = result['parseInsightForge']
    assert insight['query'] == 'Why?'
    assert insight['stats'] == {'facts': 1, 'entities': 1, 'relationships': 1}
    assert len(insight['facts']) == len(insight['entities']) == len(insight['relations']) == 1
    panorama = result['parsePanorama']
    assert panorama['query'] == 'Demand'
    assert len(panorama['activeFacts']) == len(panorama['historicalFacts']) == 1
    interview = result['parseInterview']
    assert interview['topic'] == 'Demand'
    assert interview['summary'] == 'Customers see value.'
    assert interview['interviews'][0]['bio'] == 'Likes products'
    assert interview['interviews'][0]['twitterAnswer'] == 'Useful.'
    assert interview['interviews'][0]['redditAnswer'] == 'Good value.'
    assert interview['interviews'][0]['quotes'] == ['The product is useful.']
    assert result['parseQuickSearch']['query'] == 'Demand'
    assert len(result['parseQuickSearch']['facts']) == 1
