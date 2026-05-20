# Spike S1: Prototype Memory Layer for Backtesting Comparison

## 1. Executive Summary
This spike prototyped an alternative memory layer for MiroFish, inspired by Andrej Karpathy's LLM-Wiki approach. The goal was to create a simpler, more predictable memory system that can be used for A/B testing and backtesting against the current Zep-based Knowledge Graph system.

## 2. Technical Mapping (Current System)
The current MiroFish memory system relies on **Zep Knowledge Graph**:
- **Construction:** `GraphBuilderService` extracts entities and relationships from text.
- **Ingestion:** `ZepGraphMemoryUpdater` batch-updates Zep with agent activities.
- **Retrieval:** `ZepToolsService` performs complex graph searches (InsightForge, PanoramaSearch).
- **Pros:** High structure, captures complex relationships.
- **Cons:** High token cost, variable retrieval consistency, complex maintenance.

## 3. Experimental Architecture
The prototype implements a **Dual-Layer Flat Memory**:

### A. Core Memory (Working Set)
- **Concept:** A fixed block of high-value information.
- **Content:** Agent Persona, Bio, Current Objectives, and Key Global Facts.
- **Injection:** Always prepended to the retrieved context in the prompt.
- **Token Budget:** ~500 tokens.

### B. Archival Memory (Long-term)
- **Concept:** A vector-based repository of raw text "episodes".
- **Retrieval:** Top-K semantic search (Cosine Similarity).
- **Fallback:** Keyword-based scoring if embedding services are unavailable.
- **Storage:** Local JSON storage per simulation (`backend/data/simulations/{id}/experimental_memory.json`).
- **Optimization:** Added an `add_memories` batching method to process multiple episodes concurrently, preventing I/O bottlenecks during high-volume simulation cycles.

## 4. Implementation Details
- **Flag:** `USE_EXPERIMENTAL_MEMORY=true` (Environment variable).
- **Service:** `ExperimentalMemoryService` handles storage and retrieval.
- **Interception:** `ZepToolsService` and `ZepGraphMemoryUpdater` are modified to divert calls to the experimental service when the flag is enabled.

## 5. Initial Metrics for Evaluation
The following metrics have been defined for comparing Baseline vs Experimental:

1.  **Consistency:** Does the agent contradict past actions/statements? (0 to 1).
2.  **Evidence Usage:** Ratio of cited/used retrieved fragments in the final response.
3.  **Stability:** Token consumption growth over time (tokens/round).
4.  **Prediction Quality:** Proximity of agent decisions to historical ground truth (for backtesting).

## 6. How to Run Comparison
1.  **Run Baseline:** Set `USE_EXPERIMENTAL_MEMORY=false` and run a simulation/report.
2.  **Run Experimental:** Set `USE_EXPERIMENTAL_MEMORY=true` and run the same simulation/report.
3.  **Compare Output:** Check `backend/data/simulations/{id}/experimental_memory.json` vs Zep dashboard.

## 7. Next Steps
- Implement a more robust local vector store (FAISS/Chroma).
- Refine the "Core Memory" update logic (summarization of key events).
- Integration with UI to show Core Memory status.
