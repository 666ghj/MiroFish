"""
Report Agent service
Uses LangChain + Zep to implement the ReACT pattern for simulation report generation

Features:
1. Generate reports based on simulation requirements and Zep graph information
2. First plan the table of contents, then generate section by section
3. Each section uses the ReACT multi-round thinking and reflection pattern
4. Support conversations with the user, autonomously calling retrieval tools during the conversation
"""

import os
import json
import time
import re
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..config import Config
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from ..utils.locale import get_language_instruction, t
from .zep_tools import (
    ZepToolsService, 
    SearchResult, 
    InsightForgeResult, 
    PanoramaResult,
    InterviewResult
)

logger = get_logger('mirofish.report_agent')


class ReportLogger:
    """
    Detailed logger for Report Agent

    Generates an agent_log.jsonl file in the report folder, recording every detailed action.
    Each line is a complete JSON object containing timestamps, action types, detailed content, etc.
    """

    def __init__(self, report_id: str):
        """
        Initialize the logger

        Args:
            report_id: Report ID, used to determine the log file path
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'agent_log.jsonl'
        )
        self.start_time = datetime.now()
        self._ensure_log_file()
    
    def _ensure_log_file(self):
        """Ensure the directory containing the log file exists"""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)

    def _get_elapsed_time(self) -> float:
        """Get the elapsed time in seconds since the start"""
        return (datetime.now() - self.start_time).total_seconds()

    def log(
        self,
        action: str,
        stage: str,
        details: Dict[str, Any],
        section_title: str = None,
        section_index: int = None
    ):
        """
        Record a log entry

        Args:
            action: Action type, e.g. 'start', 'tool_call', 'llm_response', 'section_complete', etc.
            stage: Current stage, e.g. 'planning', 'generating', 'completed'
            details: Detailed content dictionary, not truncated
            section_title: Current section title (optional)
            section_index: Current section index (optional)
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": round(self._get_elapsed_time(), 2),
            "report_id": self.report_id,
            "action": action,
            "stage": stage,
            "section_title": section_title,
            "section_index": section_index,
            "details": details
        }
        
        # Append to JSONL file
        with open(self.log_file_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')

    def log_start(self, simulation_id: str, graph_id: str, simulation_requirement: str):
        """Record the start of report generation"""
        self.log(
            action="report_start",
            stage="pending",
            details={
                "simulation_id": simulation_id,
                "graph_id": graph_id,
                "simulation_requirement": simulation_requirement,
                "message": t('report.taskStarted')
            }
        )

    def log_planning_start(self):
        """Record the start of outline planning"""
        self.log(
            action="planning_start",
            stage="planning",
            details={"message": t('report.planningStart')}
        )

    def log_planning_context(self, context: Dict[str, Any]):
        """Record the context information obtained during planning"""
        self.log(
            action="planning_context",
            stage="planning",
            details={
                "message": t('report.fetchSimContext'),
                "context": context
            }
        )

    def log_planning_complete(self, outline_dict: Dict[str, Any]):
        """Record the completion of outline planning"""
        self.log(
            action="planning_complete",
            stage="planning",
            details={
                "message": t('report.planningComplete'),
                "outline": outline_dict
            }
        )

    def log_section_start(self, section_title: str, section_index: int):
        """Record the start of section generation"""
        self.log(
            action="section_start",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={"message": t('report.sectionStart', title=section_title)}
        )

    def log_react_thought(self, section_title: str, section_index: int, iteration: int, thought: str):
        """Record the ReACT thinking process"""
        self.log(
            action="react_thought",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "thought": thought,
                "message": t('report.reactThought', iteration=iteration)
            }
        )

    def log_tool_call(
        self,
        section_title: str,
        section_index: int,
        tool_name: str,
        parameters: Dict[str, Any],
        iteration: int
    ):
        """Record a tool call"""
        self.log(
            action="tool_call",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "parameters": parameters,
                "message": t('report.toolCall', toolName=tool_name)
            }
        )

    def log_tool_result(
        self,
        section_title: str,
        section_index: int,
        tool_name: str,
        result: str,
        iteration: int
    ):
        """Record the tool call result (full content, not truncated)"""
        self.log(
            action="tool_result",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "result": result,  # Full result, not truncated
                "result_length": len(result),
                "message": t('report.toolResult', toolName=tool_name)
            }
        )

    def log_llm_response(
        self,
        section_title: str,
        section_index: int,
        response: str,
        iteration: int,
        has_tool_calls: bool,
        has_final_answer: bool
    ):
        """Record the LLM response (full content, not truncated)"""
        self.log(
            action="llm_response",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "response": response,  # Full response, not truncated
                "response_length": len(response),
                "has_tool_calls": has_tool_calls,
                "has_final_answer": has_final_answer,
                "message": t('report.llmResponse', hasToolCalls=has_tool_calls, hasFinalAnswer=has_final_answer)
            }
        )

    def log_section_content(
        self,
        section_title: str,
        section_index: int,
        content: str,
        tool_calls_count: int
    ):
        """Record the completion of section content generation (only records content, not the whole section)"""
        self.log(
            action="section_content",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": content,  # Full content, not truncated
                "content_length": len(content),
                "tool_calls_count": tool_calls_count,
                "message": t('report.sectionContentDone', title=section_title)
            }
        )

    def log_section_full_complete(
        self,
        section_title: str,
        section_index: int,
        full_content: str
    ):
        """
        Record the completion of section generation

        The frontend should listen to this log to determine whether a section is truly complete
        and to obtain the full content.
        """
        self.log(
            action="section_complete",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": full_content,
                "content_length": len(full_content),
                "message": t('report.sectionComplete', title=section_title)
            }
        )

    def log_report_complete(self, total_sections: int, total_time_seconds: float):
        """Record the completion of report generation"""
        self.log(
            action="report_complete",
            stage="completed",
            details={
                "total_sections": total_sections,
                "total_time_seconds": round(total_time_seconds, 2),
                "message": t('report.reportComplete')
            }
        )

    def log_error(self, error_message: str, stage: str, section_title: str = None):
        """Record an error"""
        self.log(
            action="error",
            stage=stage,
            section_title=section_title,
            section_index=None,
            details={
                "error": error_message,
                "message": t('report.errorOccurred', error=error_message)
            }
        )


class ReportConsoleLogger:
    """
    Console-style logger for Report Agent

    Writes console-style logs (INFO, WARNING, etc.) to the console_log.txt file in the report folder.
    These logs are different from agent_log.jsonl and are plain-text console output.
    """

    def __init__(self, report_id: str):
        """
        Initialize the console logger

        Args:
            report_id: Report ID, used to determine the log file path
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'console_log.txt'
        )
        self._ensure_log_file()
        self._file_handler = None
        self._setup_file_handler()
    
    def _ensure_log_file(self):
        """Ensure the log file directory exists"""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)
    
    def _setup_file_handler(self):
        """Set up the file handler to also write logs to a file"""
        import logging

        # Create the file handler
        self._file_handler = logging.FileHandler(
            self.log_file_path,
            mode='a',
            encoding='utf-8'
        )
        self._file_handler.setLevel(logging.INFO)

        # Use the same concise format as the console
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        self._file_handler.setFormatter(formatter)

        # Attach to report_agent-related loggers
        loggers_to_attach = [
            'mirofish.report_agent',
            'mirofish.zep_tools',
        ]

        for logger_name in loggers_to_attach:
            target_logger = logging.getLogger(logger_name)
            # Avoid adding duplicates
            if self._file_handler not in target_logger.handlers:
                target_logger.addHandler(self._file_handler)

    def close(self):
        """Close the file handler and remove it from the logger"""
        import logging

        if self._file_handler:
            loggers_to_detach = [
                'mirofish.report_agent',
                'mirofish.zep_tools',
            ]

            for logger_name in loggers_to_detach:
                target_logger = logging.getLogger(logger_name)
                if self._file_handler in target_logger.handlers:
                    target_logger.removeHandler(self._file_handler)

            self._file_handler.close()
            self._file_handler = None

    def __del__(self):
        """Ensure the file handler is closed on destruction"""
        self.close()


class ReportStatus(str, Enum):
    """Report status"""
    PENDING = "pending"
    PLANNING = "planning"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ReportSection:
    """Report section"""
    title: str
    content: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content
        }

    def to_markdown(self, level: int = 2) -> str:
        """Convert to Markdown format"""
        md = f"{'#' * level} {self.title}\n\n"
        if self.content:
            md += f"{self.content}\n\n"
        return md


@dataclass
class ReportOutline:
    """Report outline"""
    title: str
    summary: str
    sections: List[ReportSection]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "sections": [s.to_dict() for s in self.sections]
        }

    def to_markdown(self) -> str:
        """Convert to Markdown format"""
        md = f"# {self.title}\n\n"
        md += f"> {self.summary}\n\n"
        for section in self.sections:
            md += section.to_markdown()
        return md


@dataclass
class Report:
    """Complete report"""
    report_id: str
    simulation_id: str
    graph_id: str
    simulation_requirement: str
    status: ReportStatus
    outline: Optional[ReportOutline] = None
    markdown_content: str = ""
    created_at: str = ""
    completed_at: str = ""
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "simulation_id": self.simulation_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "status": self.status.value,
            "outline": self.outline.to_dict() if self.outline else None,
            "markdown_content": self.markdown_content,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error
        }


# ═══════════════════════════════════════════════════════════════
# Prompt template constants
# ═══════════════════════════════════════════════════════════════

# ── Tool descriptions ──

TOOL_DESC_INSIGHT_FORGE = """\
[Deep Insight Retrieval - Powerful Retrieval Tool]
This is our powerful retrieval function, designed for in-depth analysis. It will:
1. Automatically decompose your question into multiple sub-questions
2. Retrieve information from the simulation graph across multiple dimensions
3. Integrate the results of semantic search, entity analysis, and relationship chain tracing
4. Return the most comprehensive and deepest retrieval content

[Usage Scenarios]
- When you need in-depth analysis of a specific topic
- When you need to understand multiple aspects of an event
- When you need rich material to support a report section

[Returned Content]
- Original text of relevant facts (can be quoted directly)
- Core entity insights
- Relationship chain analysis"""

TOOL_DESC_PANORAMA_SEARCH = """\
[Broad Search - Get the Big Picture]
This tool is used to obtain the complete picture of simulation results and is especially suited for understanding how an event evolved. It will:
1. Fetch all relevant nodes and relationships
2. Distinguish currently valid facts from historical/expired ones
3. Help you understand how public opinion evolved

[Usage Scenarios]
- When you need the full development arc of an event
- When you need to compare public opinion changes across phases
- When you need comprehensive entity and relationship information

[Returned Content]
- Currently valid facts (latest simulation results)
- Historical/expired facts (records of evolution)
- All entities involved"""

TOOL_DESC_QUICK_SEARCH = """\
[Simple Search - Quick Retrieval]
A lightweight, fast retrieval tool suitable for simple, direct information lookups.

[Usage Scenarios]
- When you need to quickly find a specific piece of information
- When you need to verify a fact
- Simple information retrieval

[Returned Content]
- List of facts most relevant to the query"""

TOOL_DESC_INTERVIEW_AGENTS = """\
[Deep Interview - Real Agent Interviews (Dual Platform)]
Calls the OASIS simulation environment's interview API to conduct real interviews with the running simulation Agents!
This is not LLM simulation — it calls real interview endpoints to get raw answers from the simulation Agents.
By default it interviews on both Twitter and Reddit simultaneously, yielding a more comprehensive set of viewpoints.

Workflow:
1. Automatically read the persona files to learn about all simulation Agents
2. Intelligently select the Agents most relevant to the interview topic (e.g. students, media, officials)
3. Automatically generate interview questions
4. Call the /api/simulation/interview/batch endpoint to perform real interviews on both platforms
5. Integrate all interview results and provide multi-perspective analysis

[Usage Scenarios]
- When you need to understand different roles' views of the event (How do students see it? How does the media see it? What do officials say?)
- When you need to collect opinions and positions from multiple sides
- When you need real answers from simulation Agents (from the OASIS simulation environment)
- When you want the report to be more vivid, including "interview transcripts"

[Returned Content]
- Identity information of interviewed Agents
- Interview answers from each Agent on both Twitter and Reddit
- Key quotes (can be cited directly)
- Interview summary and comparison of viewpoints

[Important] This feature requires the OASIS simulation environment to be running!"""

# ── Outline planning prompt ──

PLAN_SYSTEM_PROMPT = """\
You are a "Future Prediction Report" writing expert with a "God's-eye view" of the simulation world — you can observe the behavior, speech, and interactions of every Agent in the simulation.

[Core Philosophy]
We build a simulation world and inject a specific "simulation requirement" as a variable. The evolution of the simulation world is a prediction of what could happen in the future. What you are observing is not "experimental data", but a "rehearsal of the future".

[Your Task]
Write a "Future Prediction Report" that answers:
1. Under the conditions we set, what happened in the future?
2. How do various Agents (crowds) react and act?
3. What future trends and risks does this simulation reveal that deserve attention?

[Report Positioning]
- ✅ This is a future prediction report based on a simulation, revealing "if this happens, the future will look like this"
- ✅ Focus on the predicted outcomes: event trajectories, group reactions, emergent phenomena, potential risks
- ✅ Agents' words and actions in the simulation world are predictions of future crowd behavior
- ❌ It is NOT an analysis of the current state of the real world
- ❌ It is NOT a generic overview of public opinion

[Section Count Limit]
- Minimum 2 sections, maximum 5 sections
- No sub-sections needed; each section should be written as complete content
- Keep content focused and refined, focusing on the core prediction findings
- The section structure is up to you, based on the prediction results

Please output the report outline in JSON format as follows:
{
    "title": "Report title",
    "summary": "Report summary (one-sentence summary of the core prediction finding)",
    "sections": [
        {
            "title": "Section title",
            "description": "Description of the section content"
        }
    ]
}

Note: the sections array must contain at least 2 and at most 5 elements!"""

PLAN_USER_PROMPT_TEMPLATE = """\
[Prediction Scenario Settings]
The variable (simulation requirement) we injected into the simulation world: {simulation_requirement}

[Simulation World Scale]
- Number of entities participating in the simulation: {total_nodes}
- Number of relationships generated between entities: {total_edges}
- Distribution of entity types: {entity_types}
- Number of active Agents: {total_entities}

[Sample of Future Facts Predicted by the Simulation]
{related_facts_json}

Please review this future rehearsal with a "God's-eye view":
1. Under the conditions we set, what state did the future take on?
2. How did various groups of people (Agents) react and act?
3. What future trends does this simulation reveal that deserve attention?

Based on the prediction results, design the most appropriate report section structure.

[Reminder] Report section count: minimum 2, maximum 5, with content focused and refined on the core prediction findings."""

# ── Section generation prompt ──

SECTION_SYSTEM_PROMPT_TEMPLATE = """\
You are a "Future Prediction Report" writing expert, currently writing a section of the report.

Report title: {report_title}
Report summary: {report_summary}
Prediction scenario (simulation requirement): {simulation_requirement}

The section you are writing right now: {section_title}

═══════════════════════════════════════════════════════════════
[Core Philosophy]
═══════════════════════════════════════════════════════════════

The simulation world is a rehearsal of the future. We inject specific conditions (the simulation requirement) into the simulation world, and the behavior and interactions of Agents in the simulation are predictions of future crowd behavior.

Your task is to:
- Reveal what happened in the future under the set conditions
- Predict how various groups of people (Agents) react and act
- Identify future trends, risks, and opportunities that deserve attention

❌ Do not write this as an analysis of the current state of the real world
✅ Focus on "what the future will look like" — the simulation results are the predicted future

═══════════════════════════════════════════════════════════════
[Most Important Rules - Must Be Followed]
═══════════════════════════════════════════════════════════════

1. [You MUST call tools to observe the simulation world]
   - You are observing the future rehearsal with a "God's-eye view"
   - All content must come from events and Agent speech/actions that occurred in the simulation world
   - It is forbidden to use your own knowledge to write the report content
   - Each section must call tools at least 3 times (and at most 5 times) to observe the simulation world, which represents the future

2. [You MUST quote the Agents' original words and actions]
   - Agents' speech and behavior are predictions of future crowd behavior
   - Use the quote format in the report to display these predictions, for example:
     > "A certain group of people would say: original text..."
   - These quotes are the core evidence of the simulation's predictions

3. [Language consistency — quoted content must be translated to the report language]
   - Content returned by tools may include expressions in a language different from the report language
   - The report must be written entirely in the language specified by the user
   - When quoting content returned by tools in other languages, you must translate it into the report language before writing it in
   - Preserve the original meaning during translation, and ensure the expression is natural and fluent
   - This rule applies to both the body text and the content in quote blocks (> format)

4. [Faithfully present the prediction results]
   - The report content must reflect the simulation results in the simulation world that represent the future
   - Do not add information that does not exist in the simulation
   - If information is insufficient in some aspect, state this honestly

═══════════════════════════════════════════════════════════════
[⚠️ Format Specification - Extremely Important!]
═══════════════════════════════════════════════════════════════

[One section = the smallest content unit]
- Each section is the smallest chunked unit of the report
- ❌ Do NOT use any Markdown headings (#, ##, ###, ####, etc.) inside a section
- ❌ Do NOT add the section's main title at the beginning of the content
- ✅ The section title is added automatically by the system; you only need to write plain body content
- ✅ Use **bold**, paragraph breaks, quotes, and lists to organize content, but do not use headings

[Correct Example]
```
This section analyzes the spread of public opinion around the event. Through in-depth analysis of the simulation data, we found...

**Outbreak Phase**

Weibo served as the on-site first mover for public opinion, playing the core role of breaking the news first:

> "Weibo contributed 68% of the first-wave volume..."

**Amplification Phase**

Douyin further amplified the event's impact:

- Strong visual impact
- High emotional resonance
```

[Incorrect Example]
```
## Executive Summary          ← Wrong! Do not add any headings
### 1. Outbreak Phase     ← Wrong! Do not use ### to split subsections
#### 1.1 Detailed Analysis   ← Wrong! Do not use #### for further subdivision

This section analyzes...
```

═══════════════════════════════════════════════════════════════
[Available Retrieval Tools] (call 3-5 times per section)
═══════════════════════════════════════════════════════════════

{tools_description}

[Tool usage suggestions — please mix different tools, do not use only one]
- insight_forge: in-depth insight analysis that automatically decomposes questions and retrieves facts and relationships across multiple dimensions
- panorama_search: broad panoramic search to understand the full picture, timeline, and evolution of an event
- quick_search: quickly verify a specific information point
- interview_agents: interview simulation Agents to obtain first-person perspectives and real reactions from different roles

═══════════════════════════════════════════════════════════════
[Workflow]
═══════════════════════════════════════════════════════════════

Each turn you may only do one of the following two things (never both):

Option A — Call a tool:
Output your thinking, then call one tool in the following format:
<tool_call>
{{"name": "tool name", "parameters": {{"param name": "param value"}}}}
</tool_call>
The system will execute the tool and return the result to you. You do not need to and must not write the tool's return result yourself.

Option B — Output the final content:
When you have gathered enough information from the tools, output the section content starting with "Final Answer:".

⚠️ Strictly forbidden:
- It is forbidden to include both a tool call and Final Answer in the same turn
- It is forbidden to fabricate tool return results (Observation) yourself; all tool results are injected by the system
- A maximum of one tool call per turn

═══════════════════════════════════════════════════════════════
[Section Content Requirements]
═══════════════════════════════════════════════════════════════

1. Content must be based on the simulation data retrieved by tools
2. Heavily quote original text to demonstrate the simulation's effects
3. Use Markdown format (but do not use headings):
   - Use **bold text** to mark emphasis (replacing sub-headings)
   - Use lists (- or 1.2.3.) to organize key points
   - Use blank lines to separate different paragraphs
   - ❌ Do not use any heading syntax such as #, ##, ###, ####
4. [Quote format specification — must stand as its own paragraph]
   Quotes must stand alone as a paragraph, with a blank line before and after, and must not be mixed into a paragraph:

   ✅ Correct format:
   ```
   The school's response was considered to lack substantive content.

   > "The school's response pattern appears rigid and slow in the rapidly changing social media environment."

   This assessment reflects the public's general dissatisfaction.
   ```

   ❌ Incorrect format:
   ```
   The school's response was considered to lack substantive content.> "The school's response pattern..." This assessment reflects...
   ```
5. Maintain logical consistency with other sections
6. [Avoid repetition] Carefully read the completed section content below and do not repeat the same information
7. [Re-emphasizing] Do not add any headings! Use **bold** in place of sub-headings"""

SECTION_USER_PROMPT_TEMPLATE = """\
Completed section content (please read carefully and avoid repetition):
{previous_content}

═══════════════════════════════════════════════════════════════
[Current Task] Write the section: {section_title}
═══════════════════════════════════════════════════════════════

[Important Reminders]
1. Carefully read the completed sections above and avoid repeating the same content!
2. You must call tools to obtain simulation data before starting
3. Please mix different tools, do not use only one
4. Report content must come from the retrieval results, not from your own knowledge

[⚠️ Format Warning - Must Be Followed]
- ❌ Do not write any headings (no #, ##, ###, ####)
- ❌ Do not write "{section_title}" as the opening
- ✅ Section titles are added automatically by the system
- ✅ Write the body directly, use **bold** in place of sub-headings

Please start:
1. First think (Thought) about what information this section needs
2. Then call a tool (Action) to obtain simulation data
3. Once enough information is collected, output the Final Answer (plain body text, no headings of any kind)"""

# ── Message templates inside the ReACT loop ──

REACT_OBSERVATION_TEMPLATE = """\
Observation (retrieval result):

═══ Tool {tool_name} returned ═══
{result}

═══════════════════════════════════════════════════════════════
Tool has been called {tool_calls_count}/{max_tool_calls} times (used: {used_tools_str}){unused_hint}
- If information is sufficient: start output with "Final Answer:" (must quote the original text above)
- If more information is needed: call one tool to continue retrieval
═══════════════════════════════════════════════════════════════"""

REACT_INSUFFICIENT_TOOLS_MSG = (
    "[Notice] You have only called the tool {tool_calls_count} times; at least {min_tool_calls} are required."
    " Please call tools to obtain more simulation data before outputting Final Answer. {unused_hint}"
)

REACT_INSUFFICIENT_TOOLS_MSG_ALT = (
    "You have only called tools {tool_calls_count} times; at least {min_tool_calls} are required."
    " Please call tools to obtain simulation data. {unused_hint}"
)

REACT_TOOL_LIMIT_MSG = (
    "The tool call limit has been reached ({tool_calls_count}/{max_tool_calls}); no more tool calls are allowed."
    ' Please immediately output the section content starting with "Final Answer:" based on the information you have already obtained.'
)

REACT_UNUSED_TOOLS_HINT = "\n💡 You haven't used yet: {unused_list}; it is recommended to try different tools to get information from multiple angles"

REACT_FORCE_FINAL_MSG = "The tool call limit has been reached; please directly output Final Answer: and generate the section content."

# ── Chat prompt ──

CHAT_SYSTEM_PROMPT_TEMPLATE = """\
You are a concise and efficient simulation prediction assistant.

[Background]
Prediction conditions: {simulation_requirement}

[Generated Analysis Report]
{report_content}

[Rules]
1. Prioritize answering questions based on the report content above
2. Answer questions directly, avoiding lengthy deliberation
3. Only call tools to retrieve more data when the report content is insufficient
4. Answers should be concise, clear, and well-organized

[Available Tools] (use only when needed, call at most 1-2 times)
{tools_description}

[Tool Call Format]
<tool_call>
{{"name": "tool name", "parameters": {{"param name": "param value"}}}}
</tool_call>

[Answer Style]
- Be concise and direct; no long-winded essays
- Use the > format to quote key content
- Give the conclusion first, then explain the reasons"""

CHAT_OBSERVATION_SUFFIX = "\n\nPlease answer the question concisely."


# ═══════════════════════════════════════════════════════════════
# ReportAgent main class
# ═══════════════════════════════════════════════════════════════


class ReportAgent:
    """
    Report Agent - Simulation Report Generation Agent

    Adopts the ReACT (Reasoning + Acting) pattern:
    1. Planning phase: analyze simulation requirements and plan the report structure
    2. Generation phase: generate content section by section, with multiple tool calls per section
    3. Reflection phase: check content completeness and accuracy
    """

    # Maximum number of tool calls (per section)
    MAX_TOOL_CALLS_PER_SECTION = 5

    # Maximum reflection rounds
    MAX_REFLECTION_ROUNDS = 3

    # Maximum number of tool calls in a conversation
    MAX_TOOL_CALLS_PER_CHAT = 2

    def __init__(
        self,
        graph_id: str,
        simulation_id: str,
        simulation_requirement: str,
        llm_client: Optional[LLMClient] = None,
        zep_tools: Optional[ZepToolsService] = None
    ):
        """
        Initialize the Report Agent

        Args:
            graph_id: Graph ID
            simulation_id: Simulation ID
            simulation_requirement: Description of the simulation requirement
            llm_client: LLM client (optional)
            zep_tools: Zep tools service (optional)
        """
        self.graph_id = graph_id
        self.simulation_id = simulation_id
        self.simulation_requirement = simulation_requirement
        
        self.llm = llm_client or LLMClient()
        self.zep_tools = zep_tools or ZepToolsService()
        
        # Tool definitions
        self.tools = self._define_tools()

        # Logger (initialized in generate_report)
        self.report_logger: Optional[ReportLogger] = None
        # Console logger (initialized in generate_report)
        self.console_logger: Optional[ReportConsoleLogger] = None

        logger.info(t('report.agentInitDone', graphId=graph_id, simulationId=simulation_id))

    def _define_tools(self) -> Dict[str, Dict[str, Any]]:
        """Define the available tools"""
        return {
            "insight_forge": {
                "name": "insight_forge",
                "description": TOOL_DESC_INSIGHT_FORGE,
                "parameters": {
                    "query": "The question or topic you want to analyze in depth",
                    "report_context": "Context of the current report section (optional, helps generate more precise sub-questions)"
                }
            },
            "panorama_search": {
                "name": "panorama_search",
                "description": TOOL_DESC_PANORAMA_SEARCH,
                "parameters": {
                    "query": "Search query, used for relevance ranking",
                    "include_expired": "Whether to include expired/historical content (default True)"
                }
            },
            "quick_search": {
                "name": "quick_search",
                "description": TOOL_DESC_QUICK_SEARCH,
                "parameters": {
                    "query": "Search query string",
                    "limit": "Number of results to return (optional, default 10)"
                }
            },
            "interview_agents": {
                "name": "interview_agents",
                "description": TOOL_DESC_INTERVIEW_AGENTS,
                "parameters": {
                    "interview_topic": "Interview topic or requirement description (e.g. 'Learn students' views on the dormitory formaldehyde incident')",
                    "max_agents": "Maximum number of Agents to interview (optional, default 5, max 10)"
                }
            }
        }

    def _execute_tool(self, tool_name: str, parameters: Dict[str, Any], report_context: str = "") -> str:
        """
        Execute a tool call

        Args:
            tool_name: Tool name
            parameters: Tool parameters
            report_context: Report context (used by InsightForge)

        Returns:
            Tool execution result (in text format)
        """
        logger.info(t('report.executingTool', toolName=tool_name, params=parameters))
        
        try:
            if tool_name == "insight_forge":
                query = parameters.get("query", "")
                ctx = parameters.get("report_context", "") or report_context
                result = self.zep_tools.insight_forge(
                    graph_id=self.graph_id,
                    query=query,
                    simulation_requirement=self.simulation_requirement,
                    report_context=ctx
                )
                return result.to_text()
            
            elif tool_name == "panorama_search":
                # Broad search - get the big picture
                query = parameters.get("query", "")
                include_expired = parameters.get("include_expired", True)
                if isinstance(include_expired, str):
                    include_expired = include_expired.lower() in ['true', '1', 'yes']
                result = self.zep_tools.panorama_search(
                    graph_id=self.graph_id,
                    query=query,
                    include_expired=include_expired
                )
                return result.to_text()
            
            elif tool_name == "quick_search":
                # Simple search - quick retrieval
                query = parameters.get("query", "")
                limit = parameters.get("limit", 10)
                if isinstance(limit, str):
                    limit = int(limit)
                result = self.zep_tools.quick_search(
                    graph_id=self.graph_id,
                    query=query,
                    limit=limit
                )
                return result.to_text()
            
            elif tool_name == "interview_agents":
                # Deep interview - call the real OASIS interview API to obtain simulation Agent responses (dual platform)
                interview_topic = parameters.get("interview_topic", parameters.get("query", ""))
                max_agents = parameters.get("max_agents", 5)
                if isinstance(max_agents, str):
                    max_agents = int(max_agents)
                max_agents = min(max_agents, 10)
                result = self.zep_tools.interview_agents(
                    simulation_id=self.simulation_id,
                    interview_requirement=interview_topic,
                    simulation_requirement=self.simulation_requirement,
                    max_agents=max_agents
                )
                return result.to_text()
            
            # ========== Backward-compatible legacy tools (internally redirected to new tools) ==========

            elif tool_name == "search_graph":
                # Redirect to quick_search
                logger.info(t('report.redirectToQuickSearch'))
                return self._execute_tool("quick_search", parameters, report_context)
            
            elif tool_name == "get_graph_statistics":
                result = self.zep_tools.get_graph_statistics(self.graph_id)
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            elif tool_name == "get_entity_summary":
                entity_name = parameters.get("entity_name", "")
                result = self.zep_tools.get_entity_summary(
                    graph_id=self.graph_id,
                    entity_name=entity_name
                )
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            elif tool_name == "get_simulation_context":
                # Redirect to insight_forge because it is more powerful
                logger.info(t('report.redirectToInsightForge'))
                query = parameters.get("query", self.simulation_requirement)
                return self._execute_tool("insight_forge", {"query": query}, report_context)
            
            elif tool_name == "get_entities_by_type":
                entity_type = parameters.get("entity_type", "")
                nodes = self.zep_tools.get_entities_by_type(
                    graph_id=self.graph_id,
                    entity_type=entity_type
                )
                result = [n.to_dict() for n in nodes]
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            else:
                return f"Unknown tool: {tool_name}. Please use one of the following tools: insight_forge, panorama_search, quick_search"

        except Exception as e:
            logger.error(t('report.toolExecFailed', toolName=tool_name, error=str(e)))
            return f"Tool execution failed: {str(e)}"

    # Set of valid tool names, used for validation during bare-JSON fallback parsing
    VALID_TOOL_NAMES = {"insight_forge", "panorama_search", "quick_search", "interview_agents"}

    def _parse_tool_calls(self, response: str) -> List[Dict[str, Any]]:
        """
        Parse tool calls from the LLM response

        Supported formats (in priority order):
        1. <tool_call>{"name": "tool_name", "parameters": {...}}</tool_call>
        2. Bare JSON (the entire response or a single line is a tool call JSON)
        """
        tool_calls = []

        # Format 1: XML-style (standard format)
        xml_pattern = r'<tool_call>\s*(\{.*?\})\s*</tool_call>'
        for match in re.finditer(xml_pattern, response, re.DOTALL):
            try:
                call_data = json.loads(match.group(1))
                tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        if tool_calls:
            return tool_calls

        # Format 2: Fallback - LLM directly outputs bare JSON (without <tool_call> tags)
        # Only tried when Format 1 did not match, to avoid false matches of JSON in body text
        stripped = response.strip()
        if stripped.startswith('{') and stripped.endswith('}'):
            try:
                call_data = json.loads(stripped)
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
                    return tool_calls
            except json.JSONDecodeError:
                pass

        # The response may contain thinking text + bare JSON; try extracting the last JSON object
        json_pattern = r'(\{"(?:name|tool)"\s*:.*?\})\s*$'
        match = re.search(json_pattern, stripped, re.DOTALL)
        if match:
            try:
                call_data = json.loads(match.group(1))
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        return tool_calls

    def _is_valid_tool_call(self, data: dict) -> bool:
        """Validate whether the parsed JSON is a legitimate tool call"""
        # Support both {"name": ..., "parameters": ...} and {"tool": ..., "params": ...} key names
        tool_name = data.get("name") or data.get("tool")
        if tool_name and tool_name in self.VALID_TOOL_NAMES:
            # Unify the key names to name / parameters
            if "tool" in data:
                data["name"] = data.pop("tool")
            if "params" in data and "parameters" not in data:
                data["parameters"] = data.pop("params")
            return True
        return False

    def _get_tools_description(self) -> str:
        """Generate the tool description text"""
        desc_parts = ["Available tools:"]
        for name, tool in self.tools.items():
            params_desc = ", ".join([f"{k}: {v}" for k, v in tool["parameters"].items()])
            desc_parts.append(f"- {name}: {tool['description']}")
            if params_desc:
                desc_parts.append(f"  Parameters: {params_desc}")
        return "\n".join(desc_parts)
    
    def plan_outline(
        self,
        progress_callback: Optional[Callable] = None
    ) -> ReportOutline:
        """
        Plan the report outline

        Use the LLM to analyze simulation requirements and plan the report's table of contents.

        Args:
            progress_callback: Progress callback function

        Returns:
            ReportOutline: The report outline
        """
        logger.info(t('report.startPlanningOutline'))

        if progress_callback:
            progress_callback("planning", 0, t('progress.analyzingRequirements'))

        # First, obtain the simulation context
        context = self.zep_tools.get_simulation_context(
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement
        )

        if progress_callback:
            progress_callback("planning", 30, t('progress.generatingOutline'))

        system_prompt = f"{PLAN_SYSTEM_PROMPT}\n\n{get_language_instruction()}"
        user_prompt = PLAN_USER_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            total_nodes=context.get('graph_statistics', {}).get('total_nodes', 0),
            total_edges=context.get('graph_statistics', {}).get('total_edges', 0),
            entity_types=list(context.get('graph_statistics', {}).get('entity_types', {}).keys()),
            total_entities=context.get('total_entities', 0),
            related_facts_json=json.dumps(context.get('related_facts', [])[:10], ensure_ascii=False, indent=2),
        )

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )

            if progress_callback:
                progress_callback("planning", 80, t('progress.parsingOutline'))

            # Parse the outline
            sections = []
            for section_data in response.get("sections", []):
                sections.append(ReportSection(
                    title=section_data.get("title", ""),
                    content=""
                ))

            outline = ReportOutline(
                title=response.get("title", "Simulation Analysis Report"),
                summary=response.get("summary", ""),
                sections=sections
            )

            if progress_callback:
                progress_callback("planning", 100, t('progress.outlinePlanComplete'))

            logger.info(t('report.outlinePlanDone', count=len(sections)))
            return outline

        except Exception as e:
            logger.error(t('report.outlinePlanFailed', error=str(e)))
            # Return the default outline (3 sections, as a fallback)
            return ReportOutline(
                title="Future Prediction Report",
                summary="Future trend and risk analysis based on simulation predictions",
                sections=[
                    ReportSection(title="Prediction Scenario and Core Findings"),
                    ReportSection(title="Crowd Behavior Prediction Analysis"),
                    ReportSection(title="Trend Outlook and Risk Warning")
                ]
            )
    
    def _generate_section_react(
        self,
        section: ReportSection,
        outline: ReportOutline,
        previous_sections: List[str],
        progress_callback: Optional[Callable] = None,
        section_index: int = 0
    ) -> str:
        """
        Generate a single section's content using the ReACT pattern

        ReACT loop:
        1. Thought - analyze what information is needed
        2. Action - call tools to obtain information
        3. Observation - analyze the tool's returned results
        4. Repeat until enough information is gathered or the maximum number of calls is reached
        5. Final Answer - generate the section content

        Args:
            section: The section to generate
            outline: The full outline
            previous_sections: Content of previous sections (used to maintain consistency)
            progress_callback: Progress callback
            section_index: Section index (used for logging)

        Returns:
            The section content (in Markdown format)
        """
        logger.info(t('report.reactGenerateSection', title=section.title))

        # Record the section start log
        if self.report_logger:
            self.report_logger.log_section_start(section.title, section_index)

        system_prompt = SECTION_SYSTEM_PROMPT_TEMPLATE.format(
            report_title=outline.title,
            report_summary=outline.summary,
            simulation_requirement=self.simulation_requirement,
            section_title=section.title,
            tools_description=self._get_tools_description(),
        )
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}"

        # Build the user prompt - up to 4000 chars per completed section are passed in
        if previous_sections:
            previous_parts = []
            for sec in previous_sections:
                # Up to 4000 chars per section
                truncated = sec[:4000] + "..." if len(sec) > 4000 else sec
                previous_parts.append(truncated)
            previous_content = "\n\n---\n\n".join(previous_parts)
        else:
            previous_content = "(This is the first section)"

        user_prompt = SECTION_USER_PROMPT_TEMPLATE.format(
            previous_content=previous_content,
            section_title=section.title,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        # ReACT loop
        tool_calls_count = 0
        max_iterations = 5  # Maximum number of iterations
        min_tool_calls = 3  # Minimum number of tool calls
        conflict_retries = 0  # Number of consecutive conflicts where tool calls and Final Answer appear together
        used_tools = set()  # Records the names of tools that have been called
        all_tools = {"insight_forge", "panorama_search", "quick_search", "interview_agents"}

        # Report context, used for InsightForge's sub-question generation
        report_context = f"Section title: {section.title}\nSimulation requirement: {self.simulation_requirement}"
        
        for iteration in range(max_iterations):
            if progress_callback:
                progress_callback(
                    "generating", 
                    int((iteration / max_iterations) * 100),
                    t('progress.deepSearchAndWrite', current=tool_calls_count, max=self.MAX_TOOL_CALLS_PER_SECTION)
                )
            
            # Call the LLM
            response = self.llm.chat(
                messages=messages,
                temperature=0.5,
                max_tokens=4096
            )

            # Check whether the LLM response is None (API exception or empty content)
            if response is None:
                logger.warning(t('report.sectionIterNone', title=section.title, iteration=iteration + 1))
                # If iterations remain, add a message and retry
                if iteration < max_iterations - 1:
                    messages.append({"role": "assistant", "content": "(response is empty)"})
                    messages.append({"role": "user", "content": "Please continue generating content."})
                    continue
                # The last iteration also returned None; break out of the loop into forced finalization
                break

            logger.debug(f"LLM response: {response[:200]}...")

            # Parse once and reuse the result
            tool_calls = self._parse_tool_calls(response)
            has_tool_calls = bool(tool_calls)
            has_final_answer = "Final Answer:" in response

            # ── Conflict handling: LLM output both a tool call and Final Answer ──
            if has_tool_calls and has_final_answer:
                conflict_retries += 1
                logger.warning(
                    t('report.sectionConflict', title=section.title, iteration=iteration+1, conflictCount=conflict_retries)
                )

                if conflict_retries <= 2:
                    # First two attempts: discard this response and ask the LLM to reply again
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": (
                            "[Format Error] You included both a tool call and Final Answer in a single reply, which is not allowed.\n"
                            "Each reply can only do one of the following two things:\n"
                            "- Call a tool (output one <tool_call> block, do not write Final Answer)\n"
                            "- Output the final content (start with 'Final Answer:', do not include <tool_call>)\n"
                            "Please reply again and do only one of them."
                        ),
                    })
                    continue
                else:
                    # Third attempt: graceful degradation, truncate to the first tool call and force execution
                    logger.warning(
                        t('report.sectionConflictDowngrade', title=section.title, conflictCount=conflict_retries)
                    )
                    first_tool_end = response.find('</tool_call>')
                    if first_tool_end != -1:
                        response = response[:first_tool_end + len('</tool_call>')]
                        tool_calls = self._parse_tool_calls(response)
                        has_tool_calls = bool(tool_calls)
                    has_final_answer = False
                    conflict_retries = 0

            # Log the LLM response
            if self.report_logger:
                self.report_logger.log_llm_response(
                    section_title=section.title,
                    section_index=section_index,
                    response=response,
                    iteration=iteration + 1,
                    has_tool_calls=has_tool_calls,
                    has_final_answer=has_final_answer
                )

            # ── Case 1: LLM output Final Answer ──
            if has_final_answer:
                # Tool call count is insufficient; reject and require more tool calls
                if tool_calls_count < min_tool_calls:
                    messages.append({"role": "assistant", "content": response})
                    unused_tools = all_tools - used_tools
                    unused_hint = f"(These tools have not been used yet; we recommend giving them a try: {', '.join(unused_tools)})" if unused_tools else ""
                    messages.append({
                        "role": "user",
                        "content": REACT_INSUFFICIENT_TOOLS_MSG.format(
                            tool_calls_count=tool_calls_count,
                            min_tool_calls=min_tool_calls,
                            unused_hint=unused_hint,
                        ),
                    })
                    continue

                # Normal end
                final_answer = response.split("Final Answer:")[-1].strip()
                logger.info(t('report.sectionGenDone', title=section.title, count=tool_calls_count))

                if self.report_logger:
                    self.report_logger.log_section_content(
                        section_title=section.title,
                        section_index=section_index,
                        content=final_answer,
                        tool_calls_count=tool_calls_count
                    )
                return final_answer

            # ── Case 2: LLM attempted to call a tool ──
            if has_tool_calls:
                # Tool quota exhausted → state explicitly and require Final Answer
                if tool_calls_count >= self.MAX_TOOL_CALLS_PER_SECTION:
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": REACT_TOOL_LIMIT_MSG.format(
                            tool_calls_count=tool_calls_count,
                            max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        ),
                    })
                    continue

                # Only execute the first tool call
                call = tool_calls[0]
                if len(tool_calls) > 1:
                    logger.info(t('report.multiToolOnlyFirst', total=len(tool_calls), toolName=call['name']))

                if self.report_logger:
                    self.report_logger.log_tool_call(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        parameters=call.get("parameters", {}),
                        iteration=iteration + 1
                    )

                result = self._execute_tool(
                    call["name"],
                    call.get("parameters", {}),
                    report_context=report_context
                )

                if self.report_logger:
                    self.report_logger.log_tool_result(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        result=result,
                        iteration=iteration + 1
                    )

                tool_calls_count += 1
                used_tools.add(call['name'])

                # Build the unused-tools hint
                unused_tools = all_tools - used_tools
                unused_hint = ""
                if unused_tools and tool_calls_count < self.MAX_TOOL_CALLS_PER_SECTION:
                    unused_hint = REACT_UNUSED_TOOLS_HINT.format(unused_list="、".join(unused_tools))

                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": REACT_OBSERVATION_TEMPLATE.format(
                        tool_name=call["name"],
                        result=result,
                        tool_calls_count=tool_calls_count,
                        max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        used_tools_str=", ".join(used_tools),
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # ── Case 3: Neither a tool call nor a Final Answer ──
            messages.append({"role": "assistant", "content": response})

            if tool_calls_count < min_tool_calls:
                # Tool call count insufficient; recommend unused tools
                unused_tools = all_tools - used_tools
                unused_hint = f"(These tools have not been used yet; we recommend giving them a try: {', '.join(unused_tools)})" if unused_tools else ""

                messages.append({
                    "role": "user",
                    "content": REACT_INSUFFICIENT_TOOLS_MSG_ALT.format(
                        tool_calls_count=tool_calls_count,
                        min_tool_calls=min_tool_calls,
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # Tool call count is sufficient; the LLM output content but did not include "Final Answer:" prefix
            # Use this content as the final answer directly, no more spinning
            logger.info(t('report.sectionNoPrefix', title=section.title, count=tool_calls_count))
            final_answer = response.strip()

            if self.report_logger:
                self.report_logger.log_section_content(
                    section_title=section.title,
                    section_index=section_index,
                    content=final_answer,
                    tool_calls_count=tool_calls_count
                )
            return final_answer
        
        # Maximum iterations reached; force content generation
        logger.warning(t('report.sectionMaxIter', title=section.title))
        messages.append({"role": "user", "content": REACT_FORCE_FINAL_MSG})

        response = self.llm.chat(
            messages=messages,
            temperature=0.5,
            max_tokens=4096
        )

        # Check whether the LLM returned None during forced finalization
        if response is None:
            logger.error(t('report.sectionForceFailed', title=section.title))
            final_answer = t('report.sectionGenFailedContent')
        elif "Final Answer:" in response:
            final_answer = response.split("Final Answer:")[-1].strip()
        else:
            final_answer = response

        # Record the section content generation complete log
        if self.report_logger:
            self.report_logger.log_section_content(
                section_title=section.title,
                section_index=section_index,
                content=final_answer,
                tool_calls_count=tool_calls_count
            )

        return final_answer
    
    def generate_report(
        self,
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
        report_id: Optional[str] = None
    ) -> Report:
        """
        Generate the complete report (streaming output section by section)

        Each section is saved to the folder as soon as it is generated, without waiting
        for the entire report to finish.

        File structure:
        reports/{report_id}/
            meta.json       - report metadata
            outline.json    - report outline
            progress.json   - generation progress
            section_01.md   - section 1
            section_02.md   - section 2
            ...
            full_report.md  - full report

        Args:
            progress_callback: Progress callback function (stage, progress, message)
            report_id: Report ID (optional; auto-generated if not provided)

        Returns:
            Report: The complete report
        """
        import uuid

        # If no report_id is provided, auto-generate one
        if not report_id:
            report_id = f"report_{uuid.uuid4().hex[:12]}"
        start_time = datetime.now()

        report = Report(
            report_id=report_id,
            simulation_id=self.simulation_id,
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement,
            status=ReportStatus.PENDING,
            created_at=datetime.now().isoformat()
        )

        # List of completed section titles (used for progress tracking)
        completed_section_titles = []

        try:
            # Initialization: create the report folder and save the initial state
            ReportManager._ensure_report_folder(report_id)

            # Initialize the structured logger (agent_log.jsonl)
            self.report_logger = ReportLogger(report_id)
            self.report_logger.log_start(
                simulation_id=self.simulation_id,
                graph_id=self.graph_id,
                simulation_requirement=self.simulation_requirement
            )

            # Initialize the console logger (console_log.txt)
            self.console_logger = ReportConsoleLogger(report_id)

            ReportManager.update_progress(
                report_id, "pending", 0, t('progress.initReport'),
                completed_sections=[]
            )
            ReportManager.save_report(report)

            # Phase 1: plan the outline
            report.status = ReportStatus.PLANNING
            ReportManager.update_progress(
                report_id, "planning", 5, t('progress.startPlanningOutline'),
                completed_sections=[]
            )

            # Log the start of planning
            self.report_logger.log_planning_start()

            if progress_callback:
                progress_callback("planning", 0, t('progress.startPlanningOutline'))

            outline = self.plan_outline(
                progress_callback=lambda stage, prog, msg:
                    progress_callback(stage, prog // 5, msg) if progress_callback else None
            )
            report.outline = outline

            # Log the completion of planning
            self.report_logger.log_planning_complete(outline.to_dict())

            # Save the outline to a file
            ReportManager.save_outline(report_id, outline)
            ReportManager.update_progress(
                report_id, "planning", 15, t('progress.outlineDone', count=len(outline.sections)),
                completed_sections=[]
            )
            ReportManager.save_report(report)

            logger.info(t('report.outlineSavedToFile', reportId=report_id))

            # Phase 2: generate section by section (saving per section)
            report.status = ReportStatus.GENERATING

            total_sections = len(outline.sections)
            generated_sections = []  # Saved content for context

            for i, section in enumerate(outline.sections):
                section_num = i + 1
                base_progress = 20 + int((i / total_sections) * 70)

                # Update progress
                ReportManager.update_progress(
                    report_id, "generating", base_progress,
                    t('progress.generatingSection', title=section.title, current=section_num, total=total_sections),
                    current_section=section.title,
                    completed_sections=completed_section_titles
                )

                if progress_callback:
                    progress_callback(
                        "generating",
                        base_progress,
                        t('progress.generatingSection', title=section.title, current=section_num, total=total_sections)
                    )

                # Generate the main section content
                section_content = self._generate_section_react(
                    section=section,
                    outline=outline,
                    previous_sections=generated_sections,
                    progress_callback=lambda stage, prog, msg:
                        progress_callback(
                            stage,
                            base_progress + int(prog * 0.7 / total_sections),
                            msg
                        ) if progress_callback else None,
                    section_index=section_num
                )

                section.content = section_content
                generated_sections.append(f"## {section.title}\n\n{section_content}")

                # Save the section
                ReportManager.save_section(report_id, section_num, section)
                completed_section_titles.append(section.title)

                # Log section completion
                full_section_content = f"## {section.title}\n\n{section_content}"

                if self.report_logger:
                    self.report_logger.log_section_full_complete(
                        section_title=section.title,
                        section_index=section_num,
                        full_content=full_section_content.strip()
                    )

                logger.info(t('report.sectionSaved', reportId=report_id, sectionNum=f"{section_num:02d}"))

                # Update progress
                ReportManager.update_progress(
                    report_id, "generating",
                    base_progress + int(70 / total_sections),
                    t('progress.sectionDone', title=section.title),
                    current_section=None,
                    completed_sections=completed_section_titles
                )

            # Phase 3: assemble the full report
            if progress_callback:
                progress_callback("generating", 95, t('progress.assemblingReport'))

            ReportManager.update_progress(
                report_id, "generating", 95, t('progress.assemblingReport'),
                completed_sections=completed_section_titles
            )

            # Use ReportManager to assemble the full report
            report.markdown_content = ReportManager.assemble_full_report(report_id, outline)
            report.status = ReportStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()

            # Calculate total elapsed time
            total_time_seconds = (datetime.now() - start_time).total_seconds()

            # Log report completion
            if self.report_logger:
                self.report_logger.log_report_complete(
                    total_sections=total_sections,
                    total_time_seconds=total_time_seconds
                )

            # Save the final report
            ReportManager.save_report(report)
            ReportManager.update_progress(
                report_id, "completed", 100, t('progress.reportComplete'),
                completed_sections=completed_section_titles
            )

            if progress_callback:
                progress_callback("completed", 100, t('progress.reportComplete'))

            logger.info(t('report.reportGenDone', reportId=report_id))

            # Close the console logger
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None

            return report

        except Exception as e:
            logger.error(t('report.reportGenFailed', error=str(e)))
            report.status = ReportStatus.FAILED
            report.error = str(e)

            # Log the error
            if self.report_logger:
                self.report_logger.log_error(str(e), "failed")

            # Save the failure state
            try:
                ReportManager.save_report(report)
                ReportManager.update_progress(
                    report_id, "failed", -1, t('progress.reportFailed', error=str(e)),
                    completed_sections=completed_section_titles
                )
            except Exception:
                pass  # Ignore errors when saving the failure state

            # Close the console logger
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None

            return report
    
    def chat(
        self,
        message: str,
        chat_history: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Converse with the Report Agent

        During the conversation, the Agent can autonomously call retrieval tools to answer questions.

        Args:
            message: User message
            chat_history: Conversation history

        Returns:
            {
                "response": "Agent's reply",
                "tool_calls": [list of tools called],
                "sources": [information sources]
            }
        """
        logger.info(t('report.agentChat', message=message[:50]))

        chat_history = chat_history or []

        # Get the content of the generated report
        report_content = ""
        try:
            report = ReportManager.get_report_by_simulation(self.simulation_id)
            if report and report.markdown_content:
                # Limit the report length to avoid overly long context
                report_content = report.markdown_content[:15000]
                if len(report.markdown_content) > 15000:
                    report_content += "\n\n... [Report content truncated] ..."
        except Exception as e:
            logger.warning(t('report.fetchReportFailed', error=e))

        system_prompt = CHAT_SYSTEM_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            report_content=report_content if report_content else "(No report yet)",
            tools_description=self._get_tools_description(),
        )
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}"

        # Build the messages
        messages = [{"role": "system", "content": system_prompt}]

        # Add the conversation history
        for h in chat_history[-10:]:  # Limit the history length
            messages.append(h)

        # Add the user message
        messages.append({
            "role": "user",
            "content": message
        })

        # ReACT loop (simplified)
        tool_calls_made = []
        max_iterations = 2  # Reduced number of iterations

        for iteration in range(max_iterations):
            response = self.llm.chat(
                messages=messages,
                temperature=0.5
            )

            # Parse tool calls
            tool_calls = self._parse_tool_calls(response)

            if not tool_calls:
                # No tool calls; return the response directly
                clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', response, flags=re.DOTALL)
                clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)

                return {
                    "response": clean_response.strip(),
                    "tool_calls": tool_calls_made,
                    "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
                }

            # Execute tool calls (limited)
            tool_results = []
            for call in tool_calls[:1]:  # At most 1 tool call per turn
                if len(tool_calls_made) >= self.MAX_TOOL_CALLS_PER_CHAT:
                    break
                result = self._execute_tool(call["name"], call.get("parameters", {}))
                tool_results.append({
                    "tool": call["name"],
                    "result": result[:1500]  # Limit the result length
                })
                tool_calls_made.append(call)

            # Append the result to messages
            messages.append({"role": "assistant", "content": response})
            observation = "\n".join([f"[{r['tool']} result]\n{r['result']}" for r in tool_results])
            messages.append({
                "role": "user",
                "content": observation + CHAT_OBSERVATION_SUFFIX
            })

        # Maximum iterations reached; obtain the final response
        final_response = self.llm.chat(
            messages=messages,
            temperature=0.5
        )

        # Clean the response
        clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', final_response, flags=re.DOTALL)
        clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)

        return {
            "response": clean_response.strip(),
            "tool_calls": tool_calls_made,
            "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
        }


class ReportManager:
    """
    Report Manager
    
    Responsible for the persistent storage and retrieval of reports
    
    File structure (per-section output)：
    reports/
      {report_id}/
        meta.json          - Report metadata and status
        outline.json       - Report outline
        progress.json      - Generation progress
        section_01.md      - Section 1
        section_02.md      - Section 2
        ...
        full_report.md     - Full report
    """
    
    # Report storage directory
    REPORTS_DIR = os.path.join(Config.UPLOAD_FOLDER, 'reports')
    
    @classmethod
    def _ensure_reports_dir(cls):
        """Ensure the report root directory exists"""
        os.makedirs(cls.REPORTS_DIR, exist_ok=True)
    
    @classmethod
    def _get_report_folder(cls, report_id: str) -> str:
        """Get the report folder path"""
        return os.path.join(cls.REPORTS_DIR, report_id)
    
    @classmethod
    def _ensure_report_folder(cls, report_id: str) -> str:
        """Ensure the report folder exists and return the path"""
        folder = cls._get_report_folder(report_id)
        os.makedirs(folder, exist_ok=True)
        return folder
    
    @classmethod
    def _get_report_path(cls, report_id: str) -> str:
        """Get the report metadata file path"""
        return os.path.join(cls._get_report_folder(report_id), "meta.json")
    
    @classmethod
    def _get_report_markdown_path(cls, report_id: str) -> str:
        """Get the full report Markdown file path"""
        return os.path.join(cls._get_report_folder(report_id), "full_report.md")
    
    @classmethod
    def _get_outline_path(cls, report_id: str) -> str:
        """Get the outline file path"""
        return os.path.join(cls._get_report_folder(report_id), "outline.json")
    
    @classmethod
    def _get_progress_path(cls, report_id: str) -> str:
        """Get the progress file path"""
        return os.path.join(cls._get_report_folder(report_id), "progress.json")
    
    @classmethod
    def _get_section_path(cls, report_id: str, section_index: int) -> str:
        """Get the section Markdown file path"""
        return os.path.join(cls._get_report_folder(report_id), f"section_{section_index:02d}.md")
    
    @classmethod
    def _get_agent_log_path(cls, report_id: str) -> str:
        """Get the Agent log file path"""
        return os.path.join(cls._get_report_folder(report_id), "agent_log.jsonl")
    
    @classmethod
    def _get_console_log_path(cls, report_id: str) -> str:
        """Get the console log file path"""
        return os.path.join(cls._get_report_folder(report_id), "console_log.txt")
    
    @classmethod
    def get_console_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        Get the console log content
        
        This is the console output log (INFO, WARNING, etc.) produced during report
        generation, distinct from the structured log stored in agent_log.jsonl.
        
        Args:
            report_id: The report ID
            from_line: The line number to start reading from (for incremental fetch, 0 means from the beginning)
            
        Returns:
            {
                "logs": [List of log lines],
                "total_lines": Total number of lines,
                "from_line": Starting line number,
                "has_more": Whether more logs are available
            }
        """
        log_path = cls._get_console_log_path(report_id)
        
        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }
        
        logs = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    # Keep the original log line, stripping the trailing newline
                    logs.append(line.rstrip('\n\r'))
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # Already read to the end
        }
    
    @classmethod
    def get_console_log_stream(cls, report_id: str) -> List[str]:
        """
        Get the full console log (fetch all at once)
        
        Args:
            report_id: The report ID
            
        Returns:
            List of log lines
        """
        result = cls.get_console_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def get_agent_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        Get the Agent log content
        
        Args:
            report_id: The report ID
            from_line: The line number to start reading from (for incremental fetch, 0 means from the beginning)
            
        Returns:
            {
                "logs": [List of log entries],
                "total_lines": Total number of lines,
                "from_line": Starting line number,
                "has_more": Whether more logs are available
            }
        """
        log_path = cls._get_agent_log_path(report_id)
        
        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }
        
        logs = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    try:
                        log_entry = json.loads(line.strip())
                        logs.append(log_entry)
                    except json.JSONDecodeError:
                        # Skip lines that failed to parse
                        continue
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # Already read to the end
        }
    
    @classmethod
    def get_agent_log_stream(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        Get the full Agent log (for fetching all entries at once)
        
        Args:
            report_id: The report ID
            
        Returns:
            List of log entries
        """
        result = cls.get_agent_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def save_outline(cls, report_id: str, outline: ReportOutline) -> None:
        """
        Save the report outline
        
        Called immediately after the planning phase completes
        """
        cls._ensure_report_folder(report_id)
        
        with open(cls._get_outline_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(outline.to_dict(), f, ensure_ascii=False, indent=2)
        
        logger.info(t('report.outlineSaved', reportId=report_id))
    
    @classmethod
    def save_section(
        cls,
        report_id: str,
        section_index: int,
        section: ReportSection
    ) -> str:
        """
        Save a single section

        Called immediately after each section is generated, enabling per-section output

        Args:
            report_id: The report ID
            section_index: The section index (1-based)
            section: The section object

        Returns:
            The saved file path
        """
        cls._ensure_report_folder(report_id)

        # Build the section Markdown content - clean up any potentially duplicate headings
        cleaned_content = cls._clean_section_content(section.content, section.title)
        md_content = f"## {section.title}\n\n"
        if cleaned_content:
            md_content += f"{cleaned_content}\n\n"

        # Save the file
        file_suffix = f"section_{section_index:02d}.md"
        file_path = os.path.join(cls._get_report_folder(report_id), file_suffix)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        logger.info(t('report.sectionFileSaved', reportId=report_id, fileSuffix=file_suffix))
        return file_path
    
    @classmethod
    def _clean_section_content(cls, content: str, section_title: str) -> str:
        """
        Clean up the section content
        
        1. Remove Markdown heading lines at the start of the content that duplicate the section title
        2. Convert all ### and lower-level headings to bold text
        
        Args:
            content: The original content
            section_title: The section title
            
        Returns:
            The cleaned content
        """
        import re
        
        if not content:
            return content
        
        content = content.strip()
        lines = content.split('\n')
        cleaned_lines = []
        skip_next_empty = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # Check whether this is a Markdown heading line
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title_text = heading_match.group(2).strip()
                
                # Check whether this heading duplicates the section title (skip duplicates within the first 5 lines)
                if i < 5:
                    if title_text == section_title or title_text.replace(' ', '') == section_title.replace(' ', ''):
                        skip_next_empty = True
                        continue
                
                # Convert all heading levels (#, ##, ###, ####, etc.) to bold
                # The section title is added by the system, so the content should not contain any headings
                cleaned_lines.append(f"**{title_text}**")
                cleaned_lines.append("")  # Add a blank line
                continue
            
            # If the previous line was a skipped heading and the current line is empty, skip it as well
            if skip_next_empty and stripped == '':
                skip_next_empty = False
                continue
            
            skip_next_empty = False
            cleaned_lines.append(line)
        
        # Remove leading blank lines
        while cleaned_lines and cleaned_lines[0].strip() == '':
            cleaned_lines.pop(0)
        
        # Remove leading separator lines
        while cleaned_lines and cleaned_lines[0].strip() in ['---', '***', '___']:
            cleaned_lines.pop(0)
            # Also remove blank lines that follow a separator
            while cleaned_lines and cleaned_lines[0].strip() == '':
                cleaned_lines.pop(0)
        
        return '\n'.join(cleaned_lines)
    
    @classmethod
    def update_progress(
        cls, 
        report_id: str, 
        status: str, 
        progress: int, 
        message: str,
        current_section: str = None,
        completed_sections: List[str] = None
    ) -> None:
        """
        Update the report generation progress
        
        The frontend can read progress.json to obtain real-time progress
        """
        cls._ensure_report_folder(report_id)
        
        progress_data = {
            "status": status,
            "progress": progress,
            "message": message,
            "current_section": current_section,
            "completed_sections": completed_sections or [],
            "updated_at": datetime.now().isoformat()
        }
        
        with open(cls._get_progress_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(progress_data, f, ensure_ascii=False, indent=2)
    
    @classmethod
    def get_progress(cls, report_id: str) -> Optional[Dict[str, Any]]:
        """Get the report generation progress"""
        path = cls._get_progress_path(report_id)
        
        if not os.path.exists(path):
            return None
        
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @classmethod
    def get_generated_sections(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        Get the list of generated sections
        
        Return information about all saved section files
        """
        folder = cls._get_report_folder(report_id)
        
        if not os.path.exists(folder):
            return []
        
        sections = []
        for filename in sorted(os.listdir(folder)):
            if filename.startswith('section_') and filename.endswith('.md'):
                file_path = os.path.join(folder, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Parse the section index from the filename
                parts = filename.replace('.md', '').split('_')
                section_index = int(parts[1])

                sections.append({
                    "filename": filename,
                    "section_index": section_index,
                    "content": content
                })

        return sections
    
    @classmethod
    def assemble_full_report(cls, report_id: str, outline: ReportOutline) -> str:
        """
        Assemble the full report
        
        Assemble the full report from the saved section files, with heading cleanup
        """
        folder = cls._get_report_folder(report_id)
        
        # Build the report header
        md_content = f"# {outline.title}\n\n"
        md_content += f"> {outline.summary}\n\n"
        md_content += f"---\n\n"
        
        # Read all section files in order
        sections = cls.get_generated_sections(report_id)
        for section_info in sections:
            md_content += section_info["content"]
        
        # Post-process: clean up heading issues across the entire report
        md_content = cls._post_process_report(md_content, outline)
        
        # Save the full report
        full_path = cls._get_report_markdown_path(report_id)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        logger.info(t('report.fullReportAssembled', reportId=report_id))
        return md_content
    
    @classmethod
    def _post_process_report(cls, content: str, outline: ReportOutline) -> str:
        """
        Post-process the report content
        
        1. Remove duplicate headings
        2. Keep the report main heading (#) and section headings (##); remove other heading levels (###, ####, etc.)
        3. Clean up redundant blank lines and separator lines
        
        Args:
            content: The original report content
            outline: The report outline
            
        Returns:
            The processed content
        """
        import re
        
        lines = content.split('\n')
        processed_lines = []
        prev_was_heading = False
        
        # Collect all section titles from the outline
        section_titles = set()
        for section in outline.sections:
            section_titles.add(section.title)
        
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            
            # Check whether this is a heading line
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                
                # Check whether this is a duplicate heading (same content appearing within 5 consecutive lines)
                is_duplicate = False
                for j in range(max(0, len(processed_lines) - 5), len(processed_lines)):
                    prev_line = processed_lines[j].strip()
                    prev_match = re.match(r'^(#{1,6})\s+(.+)$', prev_line)
                    if prev_match:
                        prev_title = prev_match.group(2).strip()
                        if prev_title == title:
                            is_duplicate = True
                            break
                
                if is_duplicate:
                    # Skip the duplicate heading and any blank lines that follow
                    i += 1
                    while i < len(lines) and lines[i].strip() == '':
                        i += 1
                    continue
                
                # Heading level handling:
                # - # (level=1) Keep only the report main heading
                # - ## (level=2) Keep the section headings
                # - ### and below (level>=3) Convert to bold text
                
                if level == 1:
                    if title == outline.title:
                        # Keep the report main heading
                        processed_lines.append(line)
                        prev_was_heading = True
                    elif title in section_titles:
                        # Section heading mistakenly used #, correct it to ##
                        processed_lines.append(f"## {title}")
                        prev_was_heading = True
                    else:
                        # Other level-1 headings converted to bold
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                elif level == 2:
                    if title in section_titles or title == outline.title:
                        # Keep the section heading
                        processed_lines.append(line)
                        prev_was_heading = True
                    else:
                        # Non-section level-2 headings converted to bold
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                else:
                    # ### and lower-level headings converted to bold text
                    processed_lines.append(f"**{title}**")
                    processed_lines.append("")
                    prev_was_heading = False
                
                i += 1
                continue
            
            elif stripped == '---' and prev_was_heading:
                # Skip a separator line that immediately follows a heading
                i += 1
                continue
            
            elif stripped == '' and prev_was_heading:
                # Keep only one blank line after a heading
                if processed_lines and processed_lines[-1].strip() != '':
                    processed_lines.append(line)
                prev_was_heading = False
            
            else:
                processed_lines.append(line)
                prev_was_heading = False
            
            i += 1
        
        # Clean up consecutive blank lines (keep at most 2)
        result_lines = []
        empty_count = 0
        for line in processed_lines:
            if line.strip() == '':
                empty_count += 1
                if empty_count <= 2:
                    result_lines.append(line)
            else:
                empty_count = 0
                result_lines.append(line)
        
        return '\n'.join(result_lines)
    
    @classmethod
    def save_report(cls, report: Report) -> None:
        """Save the report metadata and the full report"""
        cls._ensure_report_folder(report.report_id)
        
        # Save the metadata JSON
        with open(cls._get_report_path(report.report_id), 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        
        # Save the outline
        if report.outline:
            cls.save_outline(report.report_id, report.outline)
        
        # Save the full Markdown report
        if report.markdown_content:
            with open(cls._get_report_markdown_path(report.report_id), 'w', encoding='utf-8') as f:
                f.write(report.markdown_content)
        
        logger.info(t('report.reportSaved', reportId=report.report_id))
    
    @classmethod
    def get_report(cls, report_id: str) -> Optional[Report]:
        """Get a report"""
        path = cls._get_report_path(report_id)
        
        if not os.path.exists(path):
            # Backward compatibility: check for files stored directly in the reports directory
            old_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
            if os.path.exists(old_path):
                path = old_path
            else:
                return None
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Rebuild the Report object
        outline = None
        if data.get('outline'):
            outline_data = data['outline']
            sections = []
            for s in outline_data.get('sections', []):
                sections.append(ReportSection(
                    title=s['title'],
                    content=s.get('content', '')
                ))
            outline = ReportOutline(
                title=outline_data['title'],
                summary=outline_data['summary'],
                sections=sections
            )
        
        # If markdown_content is empty, try to read from full_report.md
        markdown_content = data.get('markdown_content', '')
        if not markdown_content:
            full_report_path = cls._get_report_markdown_path(report_id)
            if os.path.exists(full_report_path):
                with open(full_report_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
        
        return Report(
            report_id=data['report_id'],
            simulation_id=data['simulation_id'],
            graph_id=data['graph_id'],
            simulation_requirement=data['simulation_requirement'],
            status=ReportStatus(data['status']),
            outline=outline,
            markdown_content=markdown_content,
            created_at=data.get('created_at', ''),
            completed_at=data.get('completed_at', ''),
            error=data.get('error')
        )
    
    @classmethod
    def get_report_by_simulation(cls, simulation_id: str) -> Optional[Report]:
        """Get a report by simulation ID"""
        cls._ensure_reports_dir()
        
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # New format: folder
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report and report.simulation_id == simulation_id:
                    return report
            # Backward compatibility: JSON file
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report and report.simulation_id == simulation_id:
                    return report
        
        return None
    
    @classmethod
    def list_reports(cls, simulation_id: Optional[str] = None, limit: int = 50) -> List[Report]:
        """List reports"""
        cls._ensure_reports_dir()
        
        reports = []
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # New format: folder
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
            # Backward compatibility: JSON file
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
        
        # Sort by creation time in descending order
        reports.sort(key=lambda r: r.created_at, reverse=True)
        
        return reports[:limit]
    
    @classmethod
    def delete_report(cls, report_id: str) -> bool:
        """Delete a report (the entire folder)"""
        import shutil
        
        folder_path = cls._get_report_folder(report_id)
        
        # New format: delete the entire folder
        if os.path.exists(folder_path) and os.path.isdir(folder_path):
            shutil.rmtree(folder_path)
            logger.info(t('report.reportFolderDeleted', reportId=report_id))
            return True
        
        # Backward compatibility: delete the individual file
        deleted = False
        old_json_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
        old_md_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.md")
        
        if os.path.exists(old_json_path):
            os.remove(old_json_path)
            deleted = True
        if os.path.exists(old_md_path):
            os.remove(old_md_path)
            deleted = True
        
        return deleted
