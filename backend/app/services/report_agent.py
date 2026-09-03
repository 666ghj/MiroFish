"""
Report Agent.

Generates the simulation report in a ReACT loop over the Zep graph.

What it does:
1. Writes the report from the simulation requirement and the graph
2. Plans an outline first, then generates one section at a time
3. Runs a multi-turn ReACT think-act-observe loop per section
4. Answers follow-up questions, calling the retrieval tools as needed
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

logger = get_logger('sosim.report_agent')


class ReportLogger:
    """
    Structured action log for one report run.

    Writes agent_log.jsonl into the report folder, one JSON object per line,
    each carrying a timestamp, an action type and the full detail of the step.
    """

    def __init__(self, report_id: str):
        """Open the structured log for one report.

        Args:
            report_id: Report ID, which fixes the log file path
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'agent_log.jsonl'
        )
        self.start_time = datetime.now()
        self._ensure_log_file()
    
    def _ensure_log_file(self):
        """Create the log file's directory if it does not exist yet."""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)

    def _get_elapsed_time(self) -> float:
        """Return the seconds elapsed since the run started."""
        return (datetime.now() - self.start_time).total_seconds()
    
    def log(
        self, 
        action: str, 
        stage: str,
        details: Dict[str, Any],
        section_title: str = None,
        section_index: int = None
    ):
        """Append one entry to the structured log.

        Args:
            action: Action type, such as 'start', 'tool_call',
                'llm_response' or 'section_complete'
            stage: Current stage, such as 'planning', 'generating' or
                'completed'
            details: The full detail of the step, never truncated
            section_title: Title of the section being worked on
            section_index: Index of the section being worked on
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
        
        # Append one JSON object per line.
        with open(self.log_file_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    
    def log_start(self, simulation_id: str, graph_id: str, simulation_requirement: str):
        """Log that the report run started."""
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
        """Log that outline planning started."""
        self.log(
            action="planning_start",
            stage="planning",
            details={"message": t('report.planningStart')}
        )
    
    def log_planning_context(self, context: Dict[str, Any]):
        """Log the graph context the outline was planned from."""
        self.log(
            action="planning_context",
            stage="planning",
            details={
                "message": t('report.fetchSimContext'),
                "context": context
            }
        )
    
    def log_planning_complete(self, outline_dict: Dict[str, Any]):
        """Log the finished outline."""
        self.log(
            action="planning_complete",
            stage="planning",
            details={
                "message": t('report.planningComplete'),
                "outline": outline_dict
            }
        )
    
    def log_section_start(self, section_title: str, section_index: int):
        """Log that a section started generating."""
        self.log(
            action="section_start",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={"message": t('report.sectionStart', title=section_title)}
        )
    
    def log_react_thought(self, section_title: str, section_index: int, iteration: int, thought: str):
        """Log one ReACT thought."""
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
        """Log a tool call."""
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
        """Log a tool result in full, without truncation."""
        self.log(
            action="tool_result",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "result": result,
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
        """Log an LLM response in full, without truncation."""
        self.log(
            action="llm_response",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "response": response,
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
        """Log a section's generated body; the section itself is not done yet."""
        self.log(
            action="section_content",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": content,
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
        """Log that a section is complete.

        The frontend watches for this entry to decide that a section has
        finished and to pick up its full content.
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
        """Log that the report run finished."""
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
        """Log an error."""
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
    Console log for one report run.

    Mirrors the console-style log lines, INFO and above, into console_log.txt
    in the report folder. Unlike agent_log.jsonl this is plain text.
    """

    def __init__(self, report_id: str):
        """Open the console log for one report.

        Args:
            report_id: Report ID, which fixes the log file path
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'console_log.txt'
        )
        self._ensure_log_file()
        self._file_handler = None
        self._setup_file_handler()
    
    def _ensure_log_file(self):
        """Create the log file's directory if it does not exist yet."""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)

    def _setup_file_handler(self):
        """Attach a file handler so console output is captured on disk too."""
        import logging

        self._file_handler = logging.FileHandler(
            self.log_file_path,
            mode='a',
            encoding='utf-8'
        )
        self._file_handler.setLevel(logging.INFO)
        
        # The same terse format the console uses.
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        self._file_handler.setFormatter(formatter)
        
        # These names must stay in step with the get_logger() calls in this
        # module and in zep_tools; a mismatch leaves console_log.txt empty.
        loggers_to_attach = [
            'sosim.report_agent',
            'sosim.zep_tools',
        ]

        for logger_name in loggers_to_attach:
            target_logger = logging.getLogger(logger_name)
            if self._file_handler not in target_logger.handlers:
                target_logger.addHandler(self._file_handler)
    
    def close(self):
        """Detach the file handler from the loggers and close it."""
        import logging

        if self._file_handler:
            loggers_to_detach = [
                'sosim.report_agent',
                'sosim.zep_tools',
            ]
            
            for logger_name in loggers_to_detach:
                target_logger = logging.getLogger(logger_name)
                if self._file_handler in target_logger.handlers:
                    target_logger.removeHandler(self._file_handler)
            
            self._file_handler.close()
            self._file_handler = None
    
    def __del__(self):
        """Close the file handler when the logger is garbage collected."""
        self.close()


class ReportStatus(str, Enum):
    """Lifecycle state of a report."""
    PENDING = "pending"
    PLANNING = "planning"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ReportSection:
    """One section of a report."""
    title: str
    content: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content
        }

    def to_markdown(self, level: int = 2) -> str:
        """Render the section as Markdown."""
        md = f"{'#' * level} {self.title}\n\n"
        if self.content:
            md += f"{self.content}\n\n"
        return md


@dataclass
class ReportOutline:
    """A report's title, summary and section list."""
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
        """Render the whole outline as Markdown."""
        md = f"# {self.title}\n\n"
        md += f"> {self.summary}\n\n"
        for section in self.sections:
            md += section.to_markdown()
        return md


@dataclass
class Report:
    """A report and everything persisted about the run that produced it."""
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
# Prompt templates
# ═══════════════════════════════════════════════════════════════

# -- Tool descriptions --

TOOL_DESC_INSIGHT_FORGE = """\
[Deep insight retrieval - the strongest tool available]
This is the deep-analysis retrieval function. It will:
1. Break your question down into several sub-questions
2. Search the simulation graph along several dimensions
3. Combine semantic search, entity analysis and relation-chain tracing
4. Return the broadest and deepest material available

[When to use it]
- You need to analyse a topic in depth
- You need several angles on the same event
- You need rich material to support a report section

[What you get back]
- Verbatim related facts you can quote
- Insight into the core entities
- Relation-chain analysis"""

TOOL_DESC_PANORAMA_SEARCH = """\
[Broad search - the full picture]
Use this to see the whole of the simulation result, especially how an event
evolved. It will:
1. Read every relevant node and relation
2. Separate the facts that still hold from the historical and expired ones
3. Show you how opinion moved over the course of the run

[When to use it]
- You need the complete arc of an event
- You need to compare how sentiment differed between stages
- You need a full picture of the entities and relations

[What you get back]
- Currently valid facts, the latest simulation output
- Historical and expired facts, the evolution record
- Every entity involved"""

TOOL_DESC_QUICK_SEARCH = """\
[Simple search - a fast lookup]
A lightweight retrieval tool for a direct, single-point question.

[When to use it]
- You need to look one specific thing up quickly
- You need to check a single fact
- The retrieval is simple

[What you get back]
- The facts most relevant to the query"""

TOOL_DESC_INTERVIEW_AGENTS = """\
[Deep interview - the real agents, on both platforms]
Calls the OASIS interview API and puts your questions to the agents that are
still running in the simulation. These are the agents' own answers, not an LLM
impersonating them. Both Twitter and Reddit are interviewed by default, so you
get the broader range of views.

How it works:
1. Reads the agent profiles to see who is in the simulation
2. Picks the agents most relevant to your topic, such as students, journalists
   or officials
3. Generates the interview questions
4. Calls /api/simulation/interview/batch on both platforms
5. Combines the answers into a multi-perspective analysis

[When to use it]
- You need to know how different roles see the event: what do students think?
  what do journalists think? what is the official line?
- You need to collect several positions on the same question
- You need the simulated agents' own answers, from the OASIS environment
- You want the report to carry a real interview transcript

[What you get back]
- Who was interviewed
- Each agent's answers on Twitter and on Reddit
- Key quotes you can use verbatim
- An interview summary comparing the views

[Important] The OASIS simulation environment must still be running."""

# -- Outline planning prompt --

PLAN_SYSTEM_PROMPT = """\
You write future-prediction reports, and you have a god's-eye view of the simulated world: you can see what every agent in it did, said and responded to.

[The idea]
We built a simulated world and injected a specific simulation requirement into it as a variable. How that world then evolved is our prediction of what may happen. You are not looking at experiment data; you are looking at a rehearsal of the future.

[Your task]
Write a future-prediction report answering:
1. Under the conditions we set, what happened next?
2. How did each kind of agent, and each group, react and act?
3. What future trends and risks does the simulation surface?

[What the report is]
- A prediction report grounded in the simulation: "if this, then what?"
- Focused on the outcome: how the event moved, how groups reacted, what emerged, what could go wrong
- Built on the premise that what the simulated agents said and did predicts how real people would behave
- Not an analysis of the present-day real world
- Not a general survey of public opinion

[Section count]
- At least 2 sections, at most 5
- No sub-sections; write each section as one complete body of text
- Keep it tight and focused on the core prediction findings
- Design the section structure yourself, around what the simulation showed

Return the outline as JSON:
{
    "title": "Report title",
    "summary": "One sentence capturing the core prediction finding",
    "sections": [
        {
            "title": "Section title",
            "description": "What the section covers"
        }
    ]
}

The sections array must hold at least 2 and at most 5 entries."""

PLAN_USER_PROMPT_TEMPLATE = """\
[The scenario]
The variable injected into the simulated world, the simulation requirement: {simulation_requirement}

[Scale of the simulated world]
- Entities taking part: {total_nodes}
- Relations between them: {total_edges}
- Entity type distribution: {entity_types}
- Active agents: {total_entities}

[A sample of the future facts the simulation predicted]
{related_facts_json}

Take the god's-eye view of this rehearsal:
1. Under the conditions we set, what state did the future settle into?
2. How did each group of agents react and act?
3. What future trends does the simulation surface?

Design the section structure that best fits what the prediction showed.

A reminder: at least 2 sections, at most 5, kept tight and focused on the core prediction findings."""

# -- Section generation prompt --

SECTION_SYSTEM_PROMPT_TEMPLATE = """\
You write future-prediction reports, and you are writing one section of one.

Report title: {report_title}
Report summary: {report_summary}
Prediction scenario, the simulation requirement: {simulation_requirement}

The section to write: {section_title}

═══════════════════════════════════════════════════════════════
[The idea]
═══════════════════════════════════════════════════════════════

The simulated world is a rehearsal of the future. We injected a specific
condition into it, the simulation requirement, and how the agents then behaved
and interacted is our prediction of how people would behave.

Your task:
- Show what happened next under the condition we set
- Predict how each group of agents reacted and acted
- Surface the future trends, risks and opportunities worth attention

❌ Do not write an analysis of the present-day real world
✅ Focus on what the future looks like: the simulation result is the prediction

═══════════════════════════════════════════════════════════════
[The rules that matter most]
═══════════════════════════════════════════════════════════════

1. [Call the tools and observe the simulated world]
   - You are watching a rehearsal of the future from a god's-eye view
   - Everything you write must come from events and agent behaviour inside the
     simulated world
   - Do not write the report from your own knowledge
   - Call the tools at least 3 times per section, at most 5, to observe the
     simulated world that stands in for the future

2. [Quote the agents verbatim]
   - What an agent said and did is the prediction of how people will behave
   - Show those predictions as block quotes, for example:
     > "One group would say: ..."
   - These quotes are the core evidence of the prediction

3. [Language consistency: translate quoted material]
   - Tool results may come back phrased differently from the report language
   - The whole report must be written in the language the user asked for
   - Translate quoted material into the report language before writing it in
   - Translate faithfully, and keep the result natural to read
   - This applies to the body and to block quotes alike

4. [Report the prediction faithfully]
   - The report must reflect what the simulated world actually produced
   - Do not add information the simulation does not contain
   - Where the material is thin, say so

5. [Do not invent data]
   - ❌ Do not invent usernames, quotes, statistics or engagement numbers
   - ❌ Do not include <tool_result> blocks in your reply; only the system
     supplies tool results
   - ✅ Only cite entities, quotes and figures that appear in the tool results
   - Where the tool results say nothing, say so rather than making it up

═══════════════════════════════════════════════════════════════
[⚠️ Formatting rules, and they matter]
═══════════════════════════════════════════════════════════════

[One section is the smallest unit of the report]
- Each section is the report's smallest block
- ❌ Do not use any Markdown heading inside a section: #, ##, ###, #### and so on
- ❌ Do not open the body with the section title
- ✅ The system adds the section title; write the body only
- ✅ Organise the body with **bold**, paragraph breaks, quotes and lists,
  never with headings

[Correct]
```
This section looks at how the story spread. Analysing the simulation data
closely, we found ...

**The first spike**

Twitter was where the story broke, and it carried the first wave:

> "Twitter accounted for 68% of the first-day volume ..."

**The amplification phase**

Reddit then pushed the story further:

- Strong visual impact
- High emotional resonance
```

[Wrong]
```
## Executive summary       <- wrong: no headings
### 1. The first spike     <- wrong: no ### sub-sections
#### 1.1 Detailed analysis <- wrong: no #### breakdown

This section looks at ...
```

═══════════════════════════════════════════════════════════════
[Retrieval tools available] (call 3 to 5 times per section)
═══════════════════════════════════════════════════════════════

{tools_description}

[Which tool to reach for; mix them, do not lean on one]
- insight_forge: deep insight; decomposes the question and retrieves facts and
  relations along several dimensions
- panorama_search: the full picture, the timeline and how the event evolved
- quick_search: check one specific point fast
- interview_agents: interview the simulated agents for first-person views and
  real reactions from different roles

═══════════════════════════════════════════════════════════════
[The loop]
═══════════════════════════════════════════════════════════════

Each reply does exactly one of these two things, never both:

Option A - call a tool:
Write your thinking, then call one tool in this format:
<tool_call>
{{"name": "tool name", "parameters": {{"parameter name": "value"}}}}
</tool_call>
The system runs the tool and hands you the result. You neither need to nor may
write the tool result yourself.

Option B - write the final content:
Once the tools have given you enough, write the section body starting with
"Final Answer:".

⚠️ Strictly forbidden:
- A reply containing both a tool call and a Final Answer
- Writing your own tool result, the Observation; the system injects those
- More than one tool call per reply

═══════════════════════════════════════════════════════════════
[What the section body must do]
═══════════════════════════════════════════════════════════════

1. Build the content on the simulation data the tools returned
2. Quote generously, so the simulation shows through
3. Use Markdown, but no headings:
   - Mark emphasis with **bold** instead of a sub-heading
   - Organise points as lists, with - or 1. 2. 3.
   - Separate paragraphs with a blank line
   - ❌ Never use #, ##, ### or #### heading syntax
4. [Quote formatting: a quote is its own paragraph]
   A quote stands alone, with a blank line before and after it, never inline:

   ✅ Correct:
   ```
   The university's response was seen as saying very little.

   > "The university's playbook looks rigid and slow against how fast social media moves."

   That reading matches the wider frustration.
   ```

   ❌ Wrong:
   ```
   The university's response was seen as saying very little. > "The university's playbook ..." That reading matches ...
   ```
5. Keep the section coherent with the sections around it
6. [Do not repeat] Read the completed sections below carefully and do not
   restate what they already cover
7. [Once more] Add no headings; use **bold** where you would have used one"""

SECTION_USER_PROMPT_TEMPLATE = """\
Sections already written; read them and avoid repeating them:
{previous_content}

═══════════════════════════════════════════════════════════════
[Your task] Write the section: {section_title}
═══════════════════════════════════════════════════════════════

[Reminders]
1. Read the completed sections above and do not repeat their content
2. Call a tool for simulation data before you start writing
3. Mix the tools; do not lean on one
4. The content must come from the retrieval results, not from your own knowledge

[⚠️ Formatting]
- ❌ No headings at all: not #, ##, ### or ####
- ❌ Do not open with "{section_title}"
- ✅ The system adds the section title
- ✅ Write the body directly, using **bold** where you would have used a sub-heading

Begin:
1. Think about what this section needs
2. Call a tool to get the simulation data
3. Once you have enough, write Final Answer: followed by the body, with no headings"""

# -- ReACT loop messages --

REACT_OBSERVATION_TEMPLATE = """\
Observation (retrieval result):

═══ Tool {tool_name} returned ═══
{result}

═══════════════════════════════════════════════════════════════
Tools called {tool_calls_count}/{max_tool_calls} (used: {used_tools_str}){unused_hint}
- If that is enough: write the section body starting with "Final Answer:", quoting the material above
- If you need more: call one more tool
═══════════════════════════════════════════════════════════════"""

REACT_INSUFFICIENT_TOOLS_MSG = (
    "[Note] You have called {tool_calls_count} tool(s); at least "
    "{min_tool_calls} are required. Call another tool for more simulation "
    "data before writing the Final Answer.{unused_hint}"
)

REACT_INSUFFICIENT_TOOLS_MSG_ALT = (
    "You have called {tool_calls_count} tool(s); at least {min_tool_calls} "
    "are required. Call a tool for simulation data.{unused_hint}"
)

REACT_TOOL_LIMIT_MSG = (
    "The tool call limit has been reached ({tool_calls_count}/{max_tool_calls}); "
    'no further tool calls are possible. Write the section body now, starting '
    'with "Final Answer:", from what you already have.'
)

REACT_UNUSED_TOOLS_HINT = "\n💡 Not used yet: {unused_list}. A different tool may give you another angle."

REACT_FORCE_FINAL_MSG = "The tool call limit has been reached. Write Final Answer: followed by the section body."

# -- Chat prompt --

CHAT_SYSTEM_PROMPT_TEMPLATE = """\
You are a concise assistant answering questions about a simulation prediction.

[Background]
Prediction conditions: {simulation_requirement}

[The analysis report already generated]
{report_content}

[Rules]
1. Answer from the report above wherever you can
2. Answer the question directly; skip the long deliberation
3. Call a tool for more data only when the report cannot answer the question
4. Keep the answer short, clear and ordered

[Tools available] (only when needed, at most one or two calls)
{tools_description}

[Tool call format]
<tool_call>
{{"name": "tool name", "parameters": {{"parameter name": "value"}}}}
</tool_call>

[Style]
- Short and direct, not an essay
- Quote key material with the > block quote format
- Lead with the conclusion, then explain it"""

CHAT_OBSERVATION_SUFFIX = "\n\nAnswer the question concisely."


# ═══════════════════════════════════════════════════════════════
# The ReportAgent itself
# ═══════════════════════════════════════════════════════════════


class ReportAgent:
    """
    Generates a simulation report in a ReACT loop.

    ReACT, reasoning plus acting, runs in three phases:
    1. Planning: read the simulation requirement and plan the outline
    2. Generating: write one section at a time, calling the retrieval tools
       as many times as each section needs
    3. Reflecting: check the result for completeness and accuracy
    """

    # Tool calls allowed per section
    MAX_TOOL_CALLS_PER_SECTION = 5

    # Reflection rounds allowed
    MAX_REFLECTION_ROUNDS = 3

    # Tool calls allowed per chat turn
    MAX_TOOL_CALLS_PER_CHAT = 2
    
    def __init__(
        self, 
        graph_id: str,
        simulation_id: str,
        simulation_requirement: str,
        llm_client: Optional[LLMClient] = None,
        zep_tools: Optional[ZepToolsService] = None
    ):
        """Create the agent for one simulation.

        Args:
            graph_id: Graph ID
            simulation_id: Simulation ID
            simulation_requirement: The simulation requirement
            llm_client: LLM client; one is created when omitted
            zep_tools: Zep tool service; one is created when omitted
        """
        self.graph_id = graph_id
        self.simulation_id = simulation_id
        self.simulation_requirement = simulation_requirement
        
        self.llm = llm_client or LLMClient()
        self.zep_tools = zep_tools or ZepToolsService()
        
        # Tool definitions
        self.tools = self._define_tools()
        
        # Both loggers are opened in generate_report.
        self.report_logger: Optional[ReportLogger] = None
        self.console_logger: Optional[ReportConsoleLogger] = None
        
        logger.info(t('report.agentInitDone', graphId=graph_id, simulationId=simulation_id))
    
    def _define_tools(self) -> Dict[str, Dict[str, Any]]:
        """Define the tools the agent may call."""
        return {
            "insight_forge": {
                "name": "insight_forge",
                "description": TOOL_DESC_INSIGHT_FORGE,
                "parameters": {
                    "query": "The question or topic to analyse in depth",
                    "report_context": "Context for the current section, which sharpens the generated sub-questions"
                }
            },
            "panorama_search": {
                "name": "panorama_search",
                "description": TOOL_DESC_PANORAMA_SEARCH,
                "parameters": {
                    "query": "Search query, used to rank the results",
                    "include_expired": "Whether to include historical and expired content; defaults to True"
                }
            },
            "quick_search": {
                "name": "quick_search",
                "description": TOOL_DESC_QUICK_SEARCH,
                "parameters": {
                    "query": "Search query",
                    "limit": "How many results to return; defaults to 10"
                }
            },
            "interview_agents": {
                "name": "interview_agents",
                "description": TOOL_DESC_INTERVIEW_AGENTS,
                "parameters": {
                    "interview_topic": "What the interview should find out, for example \"how students see the dormitory formaldehyde incident\"",
                    "max_agents": "How many agents to interview; defaults to 5, maximum 10"
                }
            }
        }
    
    def _execute_tool(self, tool_name: str, parameters: Dict[str, Any], report_context: str = "") -> str:
        """Run one tool call.

        Args:
            tool_name: Tool to run
            parameters: Parameters the model supplied
            report_context: Report context, passed on to InsightForge

        Returns:
            The tool result, rendered as text
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
                # Broad search: the full picture
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
                # Simple search: a fast lookup
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
                # Deep interview: the OASIS API, on both platforms
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
            
            # ========== Legacy tool names, redirected to the current tools ==========
            
            elif tool_name == "search_graph":
                # Redirect to quick_search.
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
                # Redirect to insight_forge, which is strictly stronger.
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
                return (
                    f"Unknown tool: {tool_name}. Use one of: insight_forge, "
                    "panorama_search, quick_search, interview_agents"
                )
                
        except Exception as e:
            logger.error(t('report.toolExecFailed', toolName=tool_name, error=str(e)))
            return f"Failed to run {tool_name}: {str(e)}"
    
    # Checked when a bare JSON object is parsed as a fallback tool call.
    VALID_TOOL_NAMES = {"insight_forge", "panorama_search", "quick_search", "interview_agents"}

    def _parse_tool_calls(self, response: str) -> List[Dict[str, Any]]:
        """Parse the tool calls out of an LLM response.

        Two formats are accepted, in this order:
        1. <tool_call>{"name": "tool_name", "parameters": {...}}</tool_call>
        2. A bare JSON object, when the whole response or its last line is one
        """
        tool_calls = []

        # Format 1: the XML-style block, which is what the prompt asks for.
        xml_pattern = r'<tool_call>\s*(\{.*?\})\s*</tool_call>'
        for match in re.finditer(xml_pattern, response, re.DOTALL):
            try:
                call_data = json.loads(match.group(1))
                tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        if tool_calls:
            return tool_calls

        # Format 2: a bare JSON object with no <tool_call> wrapper. Only tried
        # when format 1 matched nothing, so JSON quoted in the body is not
        # mistaken for a call.
        stripped = response.strip()
        if stripped.startswith('{') and stripped.endswith('}'):
            try:
                call_data = json.loads(stripped)
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
                    return tool_calls
            except json.JSONDecodeError:
                pass

        # The response may be reasoning followed by bare JSON; take the last object.
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
        """Return whether a parsed JSON object is a valid tool call."""
        # Both {"name", "parameters"} and {"tool", "params"} are accepted.
        tool_name = data.get("name") or data.get("tool")
        if tool_name and tool_name in self.VALID_TOOL_NAMES:
            # Normalise onto name / parameters.
            if "tool" in data:
                data["name"] = data.pop("tool")
            if "params" in data and "parameters" not in data:
                data["parameters"] = data.pop("params")
            return True
        return False
    
    def _get_tools_description(self) -> str:
        """Render the tool definitions for the system prompt."""
        desc_parts = ["Tools available:"]
        for name, tool in self.tools.items():
            params_desc = ", ".join([f"{k}: {v}" for k, v in tool["parameters"].items()])
            desc_parts.append(f"- {name}: {tool['description']}")
            if params_desc:
                desc_parts.append(f"  Parameters: {params_desc}")
        return "\n".join(desc_parts)

    @staticmethod
    def _strip_fake_tool_results(response: str) -> str:
        """Strip any <tool_result> blocks the LLM fabricated in its response.

        When the LLM generates a <tool_call> block and then continues to generate
        a <tool_result> block in the same response, we must strip the fake result
        before appending to message history. The real tool result will be injected
        separately by the system.
        """
        tag_pattern = re.compile(r'</?tool_result\b[^>]*>', flags=re.IGNORECASE)
        parts = []
        cursor = 0
        depth = 0

        for match in tag_pattern.finditer(response):
            if depth == 0:
                parts.append(response[cursor:match.start()])

            if match.group(0).lstrip().startswith('</'):
                depth = max(0, depth - 1)
            else:
                depth += 1
            cursor = match.end()

        if depth == 0:
            parts.append(response[cursor:])

        cleaned = ''.join(parts)
        # Treat a malformed opening tag without a closing `>` as unsafe too.
        cleaned = re.sub(r'<tool_result\b.*$', '', cleaned, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        return cleaned.strip()

    def plan_outline(
        self, 
        progress_callback: Optional[Callable] = None
    ) -> ReportOutline:
        """Plan the report outline.

        Reads the simulation requirement and asks the LLM for the section
        structure the report should have.

        Args:
            progress_callback: Progress callback

        Returns:
            ReportOutline: The planned outline
        """
        logger.info(t('report.startPlanningOutline'))
        
        if progress_callback:
            progress_callback("planning", 0, t('progress.analyzingRequirements'))
        
        # The outline is planned from the graph context.
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
            
            # Read the sections out of the response.
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
            # Fall back to a three-section outline.
            return ReportOutline(
                title="Future Prediction Report",
                summary="Future trends and risks predicted by the simulation",
                sections=[
                    ReportSection(title="Scenario and Core Findings"),
                    ReportSection(title="Predicted Group Behaviour"),
                    ReportSection(title="Outlook and Risks")
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
        """Generate one section in a ReACT loop.

        The loop is:
        1. Thought: work out what the section needs
        2. Action: call a tool to get it
        3. Observation: read what came back
        4. Repeat until the material is enough or the call budget runs out
        5. Final Answer: write the section body

        Args:
            section: The section to write
            outline: The full outline
            previous_sections: Sections already written, for coherence
            progress_callback: Progress callback
            section_index: Section index, recorded in the log

        Returns:
            The section body, as Markdown
        """
        logger.info(t('report.reactGenerateSection', title=section.title))
        
        # Log the start of the section.
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

        # Each completed section is carried into the prompt, capped at 4000
        # characters so the context does not grow without bound.
        if previous_sections:
            previous_parts = []
            for sec in previous_sections:
                truncated = sec[:4000] + "..." if len(sec) > 4000 else sec
                previous_parts.append(truncated)
            previous_content = "\n\n---\n\n".join(previous_parts)
        else:
            previous_content = "(This is the first section.)"
        
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
        max_iterations = 5  # iterations allowed
        min_tool_calls = 3  # tool calls required before a Final Answer
        conflict_retries = 0  # consecutive replies mixing a tool call and Final Answer
        used_tools = set()  # tools called so far
        all_tools = {"insight_forge", "panorama_search", "quick_search", "interview_agents"}

        # Passed to InsightForge so its sub-questions stay on topic.
        report_context = f"Section title: {section.title}\nSimulation requirement: {self.simulation_requirement}"
        
        for iteration in range(max_iterations):
            if progress_callback:
                progress_callback(
                    "generating", 
                    int((iteration / max_iterations) * 100),
                    t('progress.deepSearchAndWrite', current=tool_calls_count, max=self.MAX_TOOL_CALLS_PER_SECTION)
                )
            
            # Ask the model what to do next.
            response = self.llm.chat(
                messages=messages,
                temperature=0.5,
                max_tokens=4096
            )

            # The API can return None on an error or on empty content.
            if response is None:
                logger.warning(t('report.sectionIterNone', title=section.title, iteration=iteration + 1))
                if iteration < max_iterations - 1:
                    messages.append({"role": "assistant", "content": "(Empty response)"})
                    messages.append({"role": "user", "content": "Continue writing the section."})
                    continue
                # Still empty on the last iteration; fall through to the forced ending.
                break

            logger.debug(f"LLM response: {response[:200]}...")

            # Parse once and reuse the result.
            tool_calls = self._parse_tool_calls(response)
            has_tool_calls = bool(tool_calls)
            has_final_answer = "Final Answer:" in response

            # -- Conflict: the reply holds a tool call and a Final Answer --
            if has_tool_calls and has_final_answer:
                conflict_retries += 1
                logger.warning(
                    t('report.sectionConflict', title=section.title, iteration=iteration+1, conflictCount=conflict_retries)
                )

                if conflict_retries <= 2:
                    # Twice over: discard the reply and ask for a clean one.
                    cleaned_response = ReportAgent._strip_fake_tool_results(response)
                    messages.append({"role": "assistant", "content": cleaned_response})
                    messages.append({
                        "role": "user",
                        "content": (
                            "[Format error] Your reply contained both a tool call and a Final Answer, which is not allowed.\n"
                            "Each reply does exactly one of these:\n"
                            "- Call one tool: emit a single <tool_call> block and no Final Answer\n"
                            "- Write the final content: start with 'Final Answer:' and emit no <tool_call>\n"
                            "Reply again, doing only one of them."
                        ),
                    })
                    continue
                else:
                    # Third time: truncate to the first tool call and run it.
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

            # Log the response.
            if self.report_logger:
                self.report_logger.log_llm_response(
                    section_title=section.title,
                    section_index=section_index,
                    response=response,
                    iteration=iteration + 1,
                    has_tool_calls=has_tool_calls,
                    has_final_answer=has_final_answer
                )

            # -- Case 1: the reply is a Final Answer --
            if has_final_answer:
                cleaned_response = ReportAgent._strip_fake_tool_results(response)
                # Too few tool calls; refuse and ask for another.
                if tool_calls_count < min_tool_calls:
                    messages.append({"role": "assistant", "content": cleaned_response})
                    unused_tools = all_tools - used_tools
                    unused_hint = f" Not used yet: {', '.join(unused_tools)}." if unused_tools else ""
                    messages.append({
                        "role": "user",
                        "content": REACT_INSUFFICIENT_TOOLS_MSG.format(
                            tool_calls_count=tool_calls_count,
                            min_tool_calls=min_tool_calls,
                            unused_hint=unused_hint,
                        ),
                    })
                    continue

                # The section is done.
                final_answer = cleaned_response.split("Final Answer:")[-1].strip()
                logger.info(t('report.sectionGenDone', title=section.title, count=tool_calls_count))

                if self.report_logger:
                    self.report_logger.log_section_content(
                        section_title=section.title,
                        section_index=section_index,
                        content=final_answer,
                        tool_calls_count=tool_calls_count
                    )
                return final_answer

            # -- Case 2: the reply calls a tool --
            if has_tool_calls:
                # Budget exhausted; say so and ask for the Final Answer.
                if tool_calls_count >= self.MAX_TOOL_CALLS_PER_SECTION:
                    cleaned_response = ReportAgent._strip_fake_tool_results(response)
                    messages.append({"role": "assistant", "content": cleaned_response})
                    messages.append({
                        "role": "user",
                        "content": REACT_TOOL_LIMIT_MSG.format(
                            tool_calls_count=tool_calls_count,
                            max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        ),
                    })
                    continue

                # Only the first tool call is run.
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

                # Nudge the model towards a tool it has not tried.
                unused_tools = all_tools - used_tools
                unused_hint = ""
                if unused_tools and tool_calls_count < self.MAX_TOOL_CALLS_PER_SECTION:
                    unused_hint = REACT_UNUSED_TOOLS_HINT.format(unused_list=", ".join(unused_tools))

                cleaned_response = ReportAgent._strip_fake_tool_results(response)
                messages.append({"role": "assistant", "content": cleaned_response})
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

            # -- Case 3: neither a tool call nor a Final Answer --
            cleaned_response = ReportAgent._strip_fake_tool_results(response)
            messages.append({"role": "assistant", "content": cleaned_response})

            if tool_calls_count < min_tool_calls:
                # Too few tool calls; nudge towards an unused tool.
                unused_tools = all_tools - used_tools
                unused_hint = f" Not used yet: {', '.join(unused_tools)}." if unused_tools else ""

                messages.append({
                    "role": "user",
                    "content": REACT_INSUFFICIENT_TOOLS_MSG_ALT.format(
                        tool_calls_count=tool_calls_count,
                        min_tool_calls=min_tool_calls,
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # Enough tools were called and the model wrote content without the
            # "Final Answer:" prefix. Take it as the answer rather than looping.
            logger.info(t('report.sectionNoPrefix', title=section.title, count=tool_calls_count))
            final_answer = cleaned_response

            if self.report_logger:
                self.report_logger.log_section_content(
                    section_title=section.title,
                    section_index=section_index,
                    content=final_answer,
                    tool_calls_count=tool_calls_count
                )
            return final_answer
        
        # Out of iterations; force the model to write the section.
        logger.warning(t('report.sectionMaxIter', title=section.title))
        messages.append({"role": "user", "content": REACT_FORCE_FINAL_MSG})
        
        response = self.llm.chat(
            messages=messages,
            temperature=0.5,
            max_tokens=4096
        )

        # The forced call can come back empty too.
        if response is None:
            logger.error(t('report.sectionForceFailed', title=section.title))
            final_answer = t('report.sectionGenFailedContent')
        elif "Final Answer:" in response:
            final_answer = response.split("Final Answer:")[-1].strip()
        else:
            final_answer = response
        
        # Log the finished body.
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
        """Generate the whole report, writing each section out as it lands.

        A section is saved as soon as it is finished, so the frontend does not
        have to wait for the whole report. The layout is:
        reports/{report_id}/
            meta.json       - report metadata
            outline.json    - report outline
            progress.json   - generation progress
            section_01.md   - first section
            section_02.md   - second section
            ...
            full_report.md  - the assembled report

        Args:
            progress_callback: Progress callback (stage, progress, message)
            report_id: Report ID; one is minted when omitted

        Returns:
            Report: The finished report
        """
        import uuid

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
        
        # Titles of the sections finished so far, reported as progress.
        completed_section_titles = []
        
        try:
            # Create the report folder and persist the initial state.
            ReportManager._ensure_report_folder(report_id)
            
            # Structured log: agent_log.jsonl
            self.report_logger = ReportLogger(report_id)
            self.report_logger.log_start(
                simulation_id=self.simulation_id,
                graph_id=self.graph_id,
                simulation_requirement=self.simulation_requirement
            )
            
            # Console log: console_log.txt
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
            
            # Log the start of planning.
            self.report_logger.log_planning_start()
            
            if progress_callback:
                progress_callback("planning", 0, t('progress.startPlanningOutline'))
            
            outline = self.plan_outline(
                progress_callback=lambda stage, prog, msg: 
                    progress_callback(stage, prog // 5, msg) if progress_callback else None
            )
            report.outline = outline
            
            # Log the finished outline.
            self.report_logger.log_planning_complete(outline.to_dict())
            
            # Persist the outline.
            ReportManager.save_outline(report_id, outline)
            ReportManager.update_progress(
                report_id, "planning", 15, t('progress.outlineDone', count=len(outline.sections)),
                completed_sections=[]
            )
            ReportManager.save_report(report)
            
            logger.info(t('report.outlineSavedToFile', reportId=report_id))
            
            # Phase 2: generate and save one section at a time
            report.status = ReportStatus.GENERATING
            
            total_sections = len(outline.sections)
            generated_sections = []  # carried into the next section as context
            
            for i, section in enumerate(outline.sections):
                section_num = i + 1
                base_progress = 20 + int((i / total_sections) * 70)
                
                # Report progress.
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
                
                # Generate the section body.
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

                # Persist the section.
                ReportManager.save_section(report_id, section_num, section)
                completed_section_titles.append(section.title)

                # Log the finished section.
                full_section_content = f"## {section.title}\n\n{section_content}"

                if self.report_logger:
                    self.report_logger.log_section_full_complete(
                        section_title=section.title,
                        section_index=section_num,
                        full_content=full_section_content.strip()
                    )

                logger.info(t('report.sectionSaved', reportId=report_id, sectionNum=f"{section_num:02d}"))
                
                # Report progress.
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
            
            # ReportManager stitches the saved sections together.
            report.markdown_content = ReportManager.assemble_full_report(report_id, outline)
            report.status = ReportStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()
            
            # Total wall-clock time for the run.
            total_time_seconds = (datetime.now() - start_time).total_seconds()
            
            # Log that the run finished.
            if self.report_logger:
                self.report_logger.log_report_complete(
                    total_sections=total_sections,
                    total_time_seconds=total_time_seconds
                )
            
            # Persist the finished report.
            ReportManager.save_report(report)
            ReportManager.update_progress(
                report_id, "completed", 100, t('progress.reportComplete'),
                completed_sections=completed_section_titles
            )
            
            if progress_callback:
                progress_callback("completed", 100, t('progress.reportComplete'))
            
            logger.info(t('report.reportGenDone', reportId=report_id))
            
            # Close the console log.
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None
            
            return report
            
        except Exception as e:
            logger.error(t('report.reportGenFailed', error=str(e)))
            report.status = ReportStatus.FAILED
            report.error = str(e)
            
            # Log the failure.
            if self.report_logger:
                self.report_logger.log_error(str(e), "failed")
            
            # Persist the failed state.
            try:
                ReportManager.save_report(report)
                ReportManager.update_progress(
                    report_id, "failed", -1, t('progress.reportFailed', error=str(e)),
                    completed_sections=completed_section_titles
                )
            except Exception:
                pass  # A failure to persist the failure must not mask it.
            
            # Close the console log.
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None
            
            return report
    
    def chat(
        self, 
        message: str,
        chat_history: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Answer a follow-up question about the report.

        The agent may call the retrieval tools while answering.

        Args:
            message: The user's message
            chat_history: Earlier turns of the conversation

        Returns:
            {
                "response": the agent's reply,
                "tool_calls": the tools it called,
                "sources": the queries behind those calls
            }
        """
        logger.info(t('report.agentChat', message=message[:50]))
        
        chat_history = chat_history or []
        
        # The generated report is the primary source for the answer.
        report_content = ""
        try:
            report = ReportManager.get_report_by_simulation(self.simulation_id)
            if report and report.markdown_content:
                # Cap the report so the context stays manageable.
                report_content = report.markdown_content[:15000]
                if len(report.markdown_content) > 15000:
                    report_content += "\n\n... [report truncated] ..."
        except Exception as e:
            logger.warning(t('report.fetchReportFailed', error=e))
        
        system_prompt = CHAT_SYSTEM_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            report_content=report_content if report_content else "(No report yet)",
            tools_description=self._get_tools_description(),
        )
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}"

        # Build the message list.
        messages = [{"role": "system", "content": system_prompt}]
        
        # Carry the last few turns across.
        for h in chat_history[-10:]:
            messages.append(h)
        
        # Then the new question.
        messages.append({
            "role": "user", 
            "content": message
        })
        
        # A shortened ReACT loop.
        tool_calls_made = []
        max_iterations = 2
        
        for iteration in range(max_iterations):
            response = self.llm.chat(
                messages=messages,
                temperature=0.5
            )
            
            # Parse any tool call out of the reply.
            tool_calls = self._parse_tool_calls(response)
            
            if not tool_calls:
                # No tool call, so the reply is the answer.
                clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', response, flags=re.DOTALL)
                clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)
                clean_response = ReportAgent._strip_fake_tool_results(clean_response)
                
                return {
                    "response": clean_response.strip(),
                    "tool_calls": tool_calls_made,
                    "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
                }
            
            # Run the tool calls, within the per-chat budget.
            tool_results = []
            for call in tool_calls[:1]:  # one tool call per turn
                if len(tool_calls_made) >= self.MAX_TOOL_CALLS_PER_CHAT:
                    break
                result = self._execute_tool(call["name"], call.get("parameters", {}))
                tool_results.append({
                    "tool": call["name"],
                    "result": result[:1500]  # capped so the context stays small
                })
                tool_calls_made.append(call)
            
            # Feed the results back as an observation.
            cleaned_response = ReportAgent._strip_fake_tool_results(response)
            messages.append({"role": "assistant", "content": cleaned_response})
            observation = "\n".join([f"[{r['tool']} result]\n{r['result']}" for r in tool_results])
            messages.append({
                "role": "user",
                "content": observation + CHAT_OBSERVATION_SUFFIX
            })
        
        # Out of iterations; ask for the final answer.
        final_response = self.llm.chat(
            messages=messages,
            temperature=0.5
        )
        
        # Strip any tool-call syntax out of the reply.
        clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', final_response, flags=re.DOTALL)
        clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)
        clean_response = ReportAgent._strip_fake_tool_results(clean_response)
        
        return {
            "response": clean_response.strip(),
            "tool_calls": tool_calls_made,
            "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
        }


class ReportManager:
    """
    Persists reports and reads them back.

    One folder per report, with sections written out as they land:
    reports/
      {report_id}/
        meta.json          - report metadata and status
        outline.json       - report outline
        progress.json      - generation progress
        section_01.md      - first section
        section_02.md      - second section
        ...
        full_report.md     - the assembled report
    """

    # Where reports live on disk
    REPORTS_DIR = os.path.join(Config.UPLOAD_FOLDER, 'reports')
    
    @classmethod
    def _ensure_reports_dir(cls):
        """Create the reports directory if it does not exist yet."""
        os.makedirs(cls.REPORTS_DIR, exist_ok=True)
    
    @classmethod
    def _get_report_folder(cls, report_id: str) -> str:
        """Return the folder holding one report."""
        return os.path.join(cls.REPORTS_DIR, report_id)
    
    @classmethod
    def _ensure_report_folder(cls, report_id: str) -> str:
        """Create one report's folder if needed, and return its path."""
        folder = cls._get_report_folder(report_id)
        os.makedirs(folder, exist_ok=True)
        return folder
    
    @classmethod
    def _get_report_path(cls, report_id: str) -> str:
        """Return the path of a report's metadata file."""
        return os.path.join(cls._get_report_folder(report_id), "meta.json")
    
    @classmethod
    def _get_report_markdown_path(cls, report_id: str) -> str:
        """Return the path of a report's assembled Markdown file."""
        return os.path.join(cls._get_report_folder(report_id), "full_report.md")
    
    @classmethod
    def _get_outline_path(cls, report_id: str) -> str:
        """Return the path of a report's outline file."""
        return os.path.join(cls._get_report_folder(report_id), "outline.json")
    
    @classmethod
    def _get_progress_path(cls, report_id: str) -> str:
        """Return the path of a report's progress file."""
        return os.path.join(cls._get_report_folder(report_id), "progress.json")
    
    @classmethod
    def _get_section_path(cls, report_id: str, section_index: int) -> str:
        """Return the path of one section's Markdown file."""
        return os.path.join(cls._get_report_folder(report_id), f"section_{section_index:02d}.md")
    
    @classmethod
    def _get_agent_log_path(cls, report_id: str) -> str:
        """Return the path of a report's structured agent log."""
        return os.path.join(cls._get_report_folder(report_id), "agent_log.jsonl")
    
    @classmethod
    def _get_console_log_path(cls, report_id: str) -> str:
        """Return the path of a report's console log."""
        return os.path.join(cls._get_report_folder(report_id), "console_log.txt")
    
    @classmethod
    def get_console_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """Read a report's console log.

        This is the console output of the run, INFO and above, as opposed to
        the structured entries in agent_log.jsonl.

        Args:
            report_id: Report ID
            from_line: Line to start at, so callers can poll incrementally

        Returns:
            {
                "logs": the log lines,
                "total_lines": how many lines the file holds,
                "from_line": the line the read started at,
                "has_more": whether more lines remain
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
                    # Keep the line verbatim, minus its line ending.
                    logs.append(line.rstrip('\n\r'))
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # the file was read to the end
        }
    
    @classmethod
    def get_console_log_stream(cls, report_id: str) -> List[str]:
        """Read a report's console log in one go.

        Args:
            report_id: Report ID

        Returns:
            Every line of the log
        """
        result = cls.get_console_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def get_agent_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """Read a report's structured agent log.

        Args:
            report_id: Report ID
            from_line: Line to start at, so callers can poll incrementally

        Returns:
            {
                "logs": the decoded log entries,
                "total_lines": how many lines the file holds,
                "from_line": the line the read started at,
                "has_more": whether more lines remain
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
                        # Skip a line that is not valid JSON.
                        continue
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # the file was read to the end
        }
    
    @classmethod
    def get_agent_log_stream(cls, report_id: str) -> List[Dict[str, Any]]:
        """Read a report's structured agent log in one go.

        Args:
            report_id: Report ID

        Returns:
            Every entry in the log
        """
        result = cls.get_agent_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def save_outline(cls, report_id: str, outline: ReportOutline) -> None:
        """Persist a report's outline, as soon as planning finishes."""
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
        """Persist one section as soon as it has been generated.

        Args:
            report_id: Report ID
            section_index: Section index, starting at 1
            section: The section to write

        Returns:
            The path the section was written to
        """
        cls._ensure_report_folder(report_id)

        # Strip a heading the model may have repeated from the title.
        cleaned_content = cls._clean_section_content(section.content, section.title)
        md_content = f"## {section.title}\n\n"
        if cleaned_content:
            md_content += f"{cleaned_content}\n\n"

        # Write the file.
        file_suffix = f"section_{section_index:02d}.md"
        file_path = os.path.join(cls._get_report_folder(report_id), file_suffix)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        logger.info(t('report.sectionFileSaved', reportId=report_id, fileSuffix=file_suffix))
        return file_path
    
    @classmethod
    def _clean_section_content(cls, content: str, section_title: str) -> str:
        """Clean up one section's body.

        1. Drop a leading Markdown heading that repeats the section title
        2. Turn every remaining heading into bold text

        Args:
            content: The generated body
            section_title: The section title the system adds separately

        Returns:
            The cleaned body
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
            
            # Is this a Markdown heading?
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title_text = heading_match.group(2).strip()
                
                # Within the first few lines, a heading repeating the title goes.
                if i < 5:
                    if title_text == section_title or title_text.replace(' ', '') == section_title.replace(' ', ''):
                        skip_next_empty = True
                        continue
                
                # The system supplies the section title, so no heading of any
                # level belongs in the body; render them as bold instead.
                cleaned_lines.append(f"**{title_text}**")
                cleaned_lines.append("")
                continue
            
            # Drop the blank line that followed a dropped heading.
            if skip_next_empty and stripped == '':
                skip_next_empty = False
                continue
            
            skip_next_empty = False
            cleaned_lines.append(line)
        
        # Trim leading blank lines.
        while cleaned_lines and cleaned_lines[0].strip() == '':
            cleaned_lines.pop(0)
        
        # Trim a leading horizontal rule.
        while cleaned_lines and cleaned_lines[0].strip() in ['---', '***', '___']:
            cleaned_lines.pop(0)
            # And the blank lines that followed it.
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
        """Write the run's current progress to progress.json.

        The frontend polls that file for live progress.
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
        """Read a report's progress, or None when it has none yet."""
        path = cls._get_progress_path(report_id)
        
        if not os.path.exists(path):
            return None
        
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @classmethod
    def get_generated_sections(cls, report_id: str) -> List[Dict[str, Any]]:
        """Return every section file saved for a report so far."""
        folder = cls._get_report_folder(report_id)
        
        if not os.path.exists(folder):
            return []
        
        sections = []
        for filename in sorted(os.listdir(folder)):
            if filename.startswith('section_') and filename.endswith('.md'):
                file_path = os.path.join(folder, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # The index is encoded in the filename.
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
        """Assemble full_report.md from the saved sections and clean it up."""
        folder = cls._get_report_folder(report_id)
        
        # Report header
        md_content = f"# {outline.title}\n\n"
        md_content += f"> {outline.summary}\n\n"
        md_content += f"---\n\n"
        
        # Sections, in order.
        sections = cls.get_generated_sections(report_id)
        for section_info in sections:
            md_content += section_info["content"]
        
        # Post-process the heading structure across the whole report.
        md_content = cls._post_process_report(md_content, outline)
        
        # Persist the assembled report.
        full_path = cls._get_report_markdown_path(report_id)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        logger.info(t('report.fullReportAssembled', reportId=report_id))
        return md_content
    
    @classmethod
    def _post_process_report(cls, content: str, outline: ReportOutline) -> str:
        """Normalise the heading structure of an assembled report.

        1. Drop duplicated headings
        2. Keep the report title (#) and the section titles (##), and turn
           every other heading into bold text
        3. Collapse surplus blank lines and horizontal rules

        Args:
            content: The assembled report
            outline: The report outline

        Returns:
            The normalised report
        """
        import re
        
        lines = content.split('\n')
        processed_lines = []
        prev_was_heading = False
        
        # The section titles the outline declared.
        section_titles = set()
        for section in outline.sections:
            section_titles.add(section.title)
        
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            
            # Is this a heading?
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                
                # A heading repeated within the last few lines is a duplicate.
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
                    # Drop the duplicate and the blank lines after it.
                    i += 1
                    while i < len(lines) and lines[i].strip() == '':
                        i += 1
                    continue
                
                # Heading levels:
                # - # keeps only the report title
                # - ## keeps the section titles
                # - ### and below become bold text
                
                if level == 1:
                    if title == outline.title:
                        # Keep the report title.
                        processed_lines.append(line)
                        prev_was_heading = True
                    elif title in section_titles:
                        # A section title written as # is corrected to ##.
                        processed_lines.append(f"## {title}")
                        prev_was_heading = True
                    else:
                        # Any other level-1 heading becomes bold.
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                elif level == 2:
                    if title in section_titles or title == outline.title:
                        # Keep the section title.
                        processed_lines.append(line)
                        prev_was_heading = True
                    else:
                        # A level-2 heading that is not a section becomes bold.
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                else:
                    # ### and below become bold text.
                    processed_lines.append(f"**{title}**")
                    processed_lines.append("")
                    prev_was_heading = False
                
                i += 1
                continue
            
            elif stripped == '---' and prev_was_heading:
                # Drop a horizontal rule sitting right under a heading.
                i += 1
                continue
            
            elif stripped == '' and prev_was_heading:
                # Keep at most one blank line after a heading.
                if processed_lines and processed_lines[-1].strip() != '':
                    processed_lines.append(line)
                prev_was_heading = False
            
            else:
                processed_lines.append(line)
                prev_was_heading = False
            
            i += 1
        
        # Collapse runs of blank lines to at most two.
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
        """Persist a report's metadata, outline and assembled Markdown."""
        cls._ensure_report_folder(report.report_id)
        
        # Metadata
        with open(cls._get_report_path(report.report_id), 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        
        # Outline
        if report.outline:
            cls.save_outline(report.report_id, report.outline)
        
        # Assembled Markdown
        if report.markdown_content:
            with open(cls._get_report_markdown_path(report.report_id), 'w', encoding='utf-8') as f:
                f.write(report.markdown_content)
        
        logger.info(t('report.reportSaved', reportId=report.report_id))
    
    @classmethod
    def get_report(cls, report_id: str) -> Optional[Report]:
        """Read one report back, or None when it does not exist."""
        path = cls._get_report_path(report_id)
        
        if not os.path.exists(path):
            # Older reports were single JSON files under reports/.
            old_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
            if os.path.exists(old_path):
                path = old_path
            else:
                return None
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Rebuild the Report object.
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
        
        # An empty markdown_content can still be recovered from disk.
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
        """Return the report generated for one simulation, if there is one."""
        cls._ensure_reports_dir()
        
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # Current format: one folder per report.
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report and report.simulation_id == simulation_id:
                    return report
            # Legacy format: a single JSON file.
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report and report.simulation_id == simulation_id:
                    return report
        
        return None
    
    @classmethod
    def list_reports(cls, simulation_id: Optional[str] = None, limit: int = 50) -> List[Report]:
        """List reports, newest first, optionally for one simulation."""
        cls._ensure_reports_dir()
        
        reports = []
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # Current format: one folder per report.
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
            # Legacy format: a single JSON file.
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
        
        # Newest first.
        reports.sort(key=lambda r: r.created_at, reverse=True)
        
        return reports[:limit]
    
    @classmethod
    def delete_report(cls, report_id: str) -> bool:
        """Delete a report and everything saved with it."""
        import shutil
        
        folder_path = cls._get_report_folder(report_id)
        
        # Current format: remove the whole folder.
        if os.path.exists(folder_path) and os.path.isdir(folder_path):
            shutil.rmtree(folder_path)
            logger.info(t('report.reportFolderDeleted', reportId=report_id))
            return True
        
        # Legacy format: remove the individual files.
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
