# Local research MCP

The user wants another AI agent to run and reuse this local research workbench as a tool, with README instructions and a less generic web port.

## Design

Add an independent Python MCP adapter using the official SDK already present in the backend dependency tree. It talks HTTP to the one running Flask backend; it never imports the application or starts a second simulation owner. The browser and MCP share projects, graphs, jobs, and reports. HTTP is available at `http://127.0.0.1:4318/mcp`; stdio is available for clients that launch their own adapter. The web interface moves to port 4317 with strict port binding.

Use named, typed tools for the existing document → ontology → graph → preparation → simulation → report workflow, evidence search, and interaction. Sources are supplied as text/Markdown content; PDFs can still be uploaded in the browser and continued through MCP. Do not add arbitrary filesystem or shell access. Validate IDs as single safe path segments, bound pagination and round inputs, propagate backend failures as MCP errors, and never automatically retry mutations. Require a stable upload ID so an interrupted document submission can reuse backend upload recovery.

Graph building, preparation, simulation, and reporting return immediately with existing IDs for polling. Ontology generation and interviews are synchronous existing API operations; allow a configurable 900-second backend timeout and document the matching client timeout. Return backend envelopes intact to preserve recovery metadata. Include workflow guidance in server instructions and an MCP resource.

## Operation

`npm run dev` starts MCP with the current services. `npm run dev:agent` starts backend, graph service when configured, and MCP without a browser. `npm run mcp` starts only HTTP MCP; a direct Python command runs stdio with clean stdout. Environment settings control frontend/MCP ports and backend URL. MCP binds only to loopback, matching the existing single-user application. A remote agent can use an SSH tunnel; this is not a public authenticated hosting design.

## Verification

Test real tool schemas and calls through MCP, HTTP error handling, source multipart encoding and upload IDs, recovery argument mapping, and invalid inputs. Exercise stdio and Streamable HTTP with official SDK clients without inference. Run existing backend/frontend suites and a frontend production build. Test source creation against the real Flask upload route with only the AI ontology generation stubbed, preserving project persistence and retry behavior.
