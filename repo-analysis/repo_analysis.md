# Repository Analysis: OpenClaw & ZeroClaw
**Date:** 2026-04-07
**Analyst:** ClawBro Research Subagent

---

## Clone Status

| Repository | Requested URL | Outcome |
|---|---|---|
| openclawai | `https://github.com/anthropics/openclawai` | **Not found (404).** This repo does not exist under the `anthropics` org. The actual OpenClaw project lives at `https://github.com/openclaw/openclaw` (310k+ stars). Cloning `openclaw/openclaw` was initiated but the repo is very large and the clone did not complete within the session window. Architecture analysis is based on the official docs at `docs.openclaw.ai` and the public GitHub page. |
| zeroclaw | `https://github.com/zeroclaw-labs/zeroclaw` | **Cloned successfully** to `outputs/repo-analysis/zeroclaw/`. Full source read. |

---

## Part 1: OpenClaw (`openclaw/openclaw`)

*Source: docs.openclaw.ai, github.com/openclaw/openclaw, public README, package.json. No local clone available — all architecture facts below come from official documentation and public source inspection.*

### Background

OpenClaw (originally "Clawdbot", released Nov 2025, renamed to OpenClaw Jan 2026) is a TypeScript/Node.js personal AI assistant platform created by Austrian developer Peter Steinberger. As of April 2026 it has 310,000+ GitHub stars, 58,000+ forks, and 1,200+ contributors. The creator has since joined OpenAI; development continues as an open-source project under MIT license.

### Overall Architecture

OpenClaw uses a **centralized Gateway pattern**. A single long-lived Gateway process owns all messaging surfaces and exposes a typed WebSocket API on `ws://127.0.0.1:18789`. Everything else — CLI, web UI, macOS/iOS/Android node apps — connects to this WebSocket as a client.

```
Messaging Channels (WhatsApp, Telegram, Slack, Discord, Signal, Matrix, ...)
        |
        v
  Gateway Daemon  <---  WebSocket API  --->  CLI / Web UI / Mobile Nodes
        |
        v
  Pi Agent Runtime (tool streaming, block streaming, RPC mode)
        |
        v
  Model Providers (OpenAI, Anthropic, Gemini, Ollama, ...)
```

**Data flow:**
1. A message arrives on a channel (e.g., Telegram DM).
2. Gateway authenticates the sender (pairing/allowlist check).
3. Gateway routes the message to the Pi agent runtime.
4. Agent runs a tool-call loop: receives model response, executes tools, feeds results back.
5. Response is delivered back through the originating channel.

### Key Design Patterns

1. **Single Gateway / Control Plane**: One daemon per host manages all channels, sessions, and tools. Clients and device nodes connect via WebSocket with shared-secret auth. This gives a unified event bus: agent execution, chat, presence, and health events all flow through the same pipe.

2. **Plugin / Registration Pattern**: Three-layer extensibility:
   - *Tools* — typed functions (`exec`, `browser`, `web_search`, `canvas`, `cron`, etc.).
   - *Skills* — markdown files (`SKILL.md` with YAML frontmatter) injected into the system prompt.
   - *Plugins* — npm packages that call `api.registerProvider()`, `api.registerTool()`, `api.registerChannel()` during activation. Discovery follows a precedence chain: config paths → workspace extensions → global extensions → bundled plugins.

3. **Three-Mode Access Control**: DM policy is `pairing` (unknown senders get a time-limited code), `allowlist` (explicit approval), or `open`. Tool access uses allow/deny lists and shorthand groups (`group:fs`, `group:web`) with per-agent profiles (`full`, `coding`, `messaging`, `minimal`).

4. **Request-Response + Streaming Duality**: The agent runtime supports both synchronous (single-response) and streaming (block/chunk) modes over the same WebSocket channel, enabling responsive UIs without polling.

5. **Device-as-Node**: macOS/iOS/Android apps connect with `role: node` declaring explicit capabilities. This lets the agent invoke camera, location, system commands, and screen recording on paired devices.

6. **Monorepo**: `apps/` (Android, iOS, macOS), `extensions/` (per-channel integrations), `packages/` (shared libs), `src/` (gateway, agents, tools, media), `skills/`, `ui/`. Build tooling: pnpm, TypeScript, oxlint, vitest for unit/e2e tests.

### Technologies and Dependencies

- **Runtime**: Node.js 24+ (or 22.16+), TypeScript, pnpm
- **Channel libs**: Baileys (WhatsApp), grammY (Telegram), discord.js, Bolt (Slack)
- **UI**: React-based web dashboard; native Swift (iOS/macOS) and Kotlin (Android)
- **Model providers**: 40+ providers: OpenAI, Anthropic, Gemini, Mistral, Groq, Ollama, vLLM, Perplexity, Runway, Deepgram, ElevenLabs, and more
- **Infrastructure**: Axum-equivalent gateway via Node HTTP, Docker sandbox option, Tailscale/SSH for remote access
- **Testing**: vitest (unit + integration), Docker-based e2e tests

### What Makes It Powerful

- **Breadth of channel support**: 24+ messaging platforms out of the box. Users interact where they already live.
- **Plugin ecosystem**: `ClawHub` skills registry + npm plugin format makes OpenClaw extensible without forking.
- **Device integration**: Phones and desktops become tool-capable nodes the agent can leverage.
- **Skills-as-markdown**: SKILL.md files are user-editable plain text, making skill authoring accessible without code.
- **Media generation coverage**: Image, music, video, TTS, realtime transcription all have tool abstractions.

### What It Does Less Well

- **Resource footprint**: Node.js runtime means >1 GB RAM in practice and slow cold starts (>500s on low-end hardware per ZeroClaw's benchmark). Not viable on constrained embedded hardware.
- **Complexity**: The monorepo with Android/iOS apps, 24+ channel extensions, and a WS control plane is operationally heavy. Onboarding involves multiple moving parts.
- **Single-user design**: The security model explicitly states "one trusted operator boundary per gateway." Multi-user or multi-tenant use requires separate gateway instances and OS-level isolation.

---

## Part 2: ZeroClaw (`zeroclaw-labs/zeroclaw`)

*Source: Full local clone at `outputs/repo-analysis/zeroclaw/`. All architecture facts are directly read from source code.*

### Background

ZeroClaw (v0.6.8, Rust edition 2024) is a Rust-first autonomous agent runtime built by students from Harvard, MIT, and the Sundai.Club community. It explicitly markets itself as a direct alternative to OpenClaw: "99% less memory than OpenClaw, 98% cheaper than a Mac mini." Released early 2026, MIT/Apache-2.0 dual license.

### Overall Architecture

ZeroClaw is a **trait-driven, single-binary** agent runtime. All major subsystems are expressed as Rust traits; concrete implementations register in factory modules. The binary embeds the web dashboard (via `rust-embed`) so there are no separate deployments.

```
CLI (clap) --> Commands --> Config (TOML)
                               |
                    +----------+----------+
                    |          |          |
               Agent Loop   Gateway    Daemon
               (loop_.rs)   (axum)   (channels + cron + hands)
                    |          |
             Provider (trait) Channel (trait)
                    |
             Tool (trait) x 70+
                    |
             Memory (trait) [sqlite / markdown / lucid / qdrant]
                    |
          Observer (trait) [prometheus / opentelemetry]
```

**Data flow (interactive mode):**
1. Message arrives on a channel (Telegram, Discord, etc.) or CLI stdin.
2. Channel validates sender (pairing guard, allowlist).
3. `process_message` in `agent/loop_.rs` routes to the agent.
4. `Agent::turn_streamed` starts a tool-call loop: calls provider, streams `TurnEvent` chunks (text, thinking, tool calls, tool results) via `tokio::sync::mpsc`.
5. Response is sent back through the originating channel with optional E-stop/budget enforcement.

**Key entry points (all directly read from source):**
- `src/main.rs` — CLI parsing (clap), command dispatch
- `src/agent/loop_.rs` — `process_message`, `run` (main agentic loop)
- `src/agent/agent.rs` — `Agent` struct, `AgentBuilder`, `TurnEvent` enum
- `src/gateway/mod.rs` — axum HTTP/WS server
- `src/channels/traits.rs` — `Channel`, `ChannelMessage`, `SendMessage`
- `src/providers/traits.rs` — `Provider`, `ChatMessage`, `ChatResponse`, `ToolCall`
- `src/tools/traits.rs` — `Tool`, `ToolSpec`
- `src/memory/mod.rs` — `Memory` trait, backend selection
- `src/security/mod.rs` — `SecurityPolicy`, `PairingGuard`, `SecretStore`, sandbox backends

### Key Design Patterns

1. **Trait-Driven Extension Model**: Every major axis (Provider, Channel, Tool, Memory, Observer, RuntimeAdapter, Peripheral) is a Rust trait. Adding a new tool means implementing `Tool` in a new submodule, registering in `all_tools_with_runtime`. This is enforced — the compiler won't link unregistered implementations.

2. **Streaming Event Bus via mpsc**: `TurnEvent` enum (`Chunk`, `Thinking`, `ToolCall`, `ToolResult`) is streamed through `tokio::sync::mpsc::Sender<TurnEvent>`. Channels consume this stream and can render or relay events in real time. This is notably cleaner than OpenClaw's WebSocket event model because it's typed at the Rust level.

3. **Context Compressor**: `agent/context_compressor.rs` monitors context window usage (configurable ratio trigger, default 50%) and automatically compresses older history via an LLM summarization pass, protecting first N and last N messages. Configurable per agent.

4. **History Pruner + Smart Truncation**: `history.rs` implements token-aware trimming; tool results are truncated head+tail with byte-accurate char boundaries, preserving JSON envelopes. History is persisted to SQLite per session.

5. **SOP Engine (Standard Operating Procedures)**: `src/sop/` implements an event-driven workflow system. SOPs are YAML/TOML manifests with typed triggers (`Mqtt`, `Webhook`, `Cron`, `Peripheral`) and execution modes (`Auto`, `Supervised`, `StepByStep`, `Deterministic`, `PriorityBased`). Steps can require human approval checkpoints. This is a first-class feature, not an afterthought.

6. **SkillForge (Auto-Discovery)**: `src/skillforge/` implements a Scout → Evaluate → Integrate pipeline. It automatically scans GitHub and ClawHub, scores candidates, and generates ZeroClaw-compatible skill manifests for qualifying repos. Configurable min_score threshold (default 0.7), scan interval (default 24 hours).

7. **Multi-level Security (Defense in Depth)**:
   - `PairingGuard` — device pairing with constant-time token comparison
   - `SecurityPolicy` — autonomy levels: `ReadOnly`, `Supervised`, `Full`
   - `PromptGuard` + `LeakDetector` — injected prompt defense, sensitive key regex detection
   - `WorkspaceBoundary` — path traversal blocking, forbidden paths enforcement
   - Pluggable sandbox backends: Docker, Firejail, Bubblewrap, Landlock (Linux), Seatbelt (macOS)
   - `EstopManager` — levels `KillAll`, `NetworkKill`, `DomainBlock`, `ToolFreeze`
   - `AuditLogger` — security events logged for forensic review
   - `SecretStore` — ChaCha20-Poly1305 AEAD encrypted credential storage

8. **Personality System**: `src/agent/personality.rs` loads workspace markdown files (`SOUL.md`, `IDENTITY.md`, `USER.md`, `AGENTS.md`, `TOOLS.md`, `HEARTBEAT.md`, `BOOTSTRAP.md`, `MEMORY.md`) and injects them into the system prompt pipeline.

9. **Thinking Level Control**: `src/agent/thinking.rs` provides 6-level reasoning control (`Off`, `Minimal`, `Low`, `Medium`, `High`, `Max`) settable via `/think:high` inline directive or config. Parsed before each turn.

10. **Tool Filtering with MCP Deferred Loading**: `filter_tool_specs_for_turn` applies group-based filtering (`always` vs `dynamic` groups with keyword triggers). MCP tools are activated on demand via `tool_search` and stored in `ActivatedToolSet` — avoiding the cost of sending all MCP specs every turn.

11. **Hands (Multi-agent Swarms)**: `src/hands/` implements autonomous agent swarms scheduled to run and grow smarter over time. Separate from the SOP engine, focused on parallel agent orchestration.

### Technologies and Dependencies (from Cargo.toml, directly read)

- **Language**: Rust edition 2024, MSRV 1.87
- **Async runtime**: tokio (rt-multi-thread, full feature set), tokio-util, tokio-stream
- **HTTP/WS**: axum 0.8, hyper 1, tower, tower-http, tokio-tungstenite
- **CLI**: clap 4.5 (derive), clap_complete
- **Config**: toml 1.0, schemars 1.2 (JSON Schema export), shellexpand
- **Serialization**: serde + serde_json (minimal features)
- **Memory/Storage**: rusqlite 0.37 (bundled), chrono, chrono-tz, cron scheduler
- **Observability**: tracing + tracing-subscriber, prometheus (optional), opentelemetry-otlp (optional)
- **Security/Crypto**: chacha20poly1305, hmac + sha2, ring (JWT), rand, landlock (Linux, optional)
- **UI**: rust-embed (embeds compiled React/Vite dist into binary), ratatui + crossterm (TUI onboarding)
- **Channels**: matrix-sdk (optional, E2EE), lettre (email), async-imap, rumqttc (MQTT), nostr-sdk (optional), wa-rs (WhatsApp native, optional)
- **Hardware**: nusb (USB enumeration), rppal (Raspberry Pi GPIO), probe-rs (STM32), tokio-serial, aardvark-sys (I2C/SPI/GPIO)
- **Plugins**: extism (WASM plugin runtime, optional)
- **Browser**: fantoccini (optional, native browser automation)
- **Media**: image (jpeg/png), base64, pdf-extract (RAG, optional)
- **Binary size profile**: `opt-level = "z"`, fat LTO, `codegen-units = 1`, `strip = true`, `panic = "abort"` → ~8.8 MB release binary

### What Makes It Powerful

- **Extreme resource efficiency**: <5 MB RAM at runtime on release builds, <10ms startup on edge hardware. Runs on a $10 ESP32 class board. This is the project's defining differentiator.
- **Type-safe extensibility**: Trait system means extensions are checked at compile time. No runtime registration bugs, no duck-typing failures.
- **First-class hardware support**: Direct GPIO, I2C/SPI, STM32, Arduino, Raspberry Pi integration. No other assistant platform in this class has this.
- **SOP engine**: Event-driven workflow automation with MQTT/webhook/cron triggers and human-in-the-loop checkpoints. Enables reliable, auditable automation.
- **Defense-in-depth security**: Multiple independent layers (crypto secret store, prompt guard, workspace boundary, OS sandbox, audit log, E-stop). Security is structural, not advisory.
- **Single binary deployment**: No Node.js, no Python, no Docker required. `./install.sh` → one binary with embedded web UI.
- **Provider agnosticism**: TOML config + trait-based providers. No lock-in; swap providers at runtime including mid-conversation model switching (`model_switch` tool).

### What It Does Less Well (vs OpenClaw)

- **Channel breadth**: ZeroClaw has many channels (Telegram, Discord, Slack, WhatsApp, Matrix, Signal, Email, IRC, Nostr, MQTT, etc.) but the OpenClaw ecosystem with its npm plugin format has a wider range of community-contributed integrations.
- **Compilation cost**: The Rust build is slow (minutes) and memory-intensive during compile. OpenClaw's Node.js starts faster for development iteration.
- **Media generation**: ZeroClaw's `image_gen.rs` tool exists but the full music/video/TTS pipeline is less complete than OpenClaw's dedicated media-generation subsystem.
- **Mobile native apps**: ZeroClaw has no iOS/Android companion app. OpenClaw's mobile nodes unlock on-device capabilities (camera, location, screen recording).
- **Plugin ecosystem maturity**: ClawHub/open-skills exist but are smaller than OpenClaw's npm-native ecosystem with 1,200+ contributors.

---

## Part 3: Synthesis for ClawBro

ClawBro is our custom AI assistant targeting resource-constrained environments, personal use, and simplicity. Here is what to borrow and what to avoid.

### 3 Best Ideas to Borrow

**1. ZeroClaw's Trait-Driven Architecture**

ZeroClaw's `Provider`, `Channel`, `Tool`, `Memory`, and `Observer` traits are a clean, compile-time-enforced extension model. For ClawBro, define the same core traits early — even if the first implementation is simple. This gives us:
- Swap providers without changing the agent core.
- Add channels (Telegram first, then others) by implementing `Channel`.
- Add tools without touching the agent loop.
- Compiler enforces the contract; no runtime surprises.

The `TurnEvent` enum streamed over mpsc is also worth copying directly: it makes the streaming agent loop decoupled from how responses are displayed or relayed.

**2. OpenClaw's Skills-as-Markdown Pattern**

Both projects converged on a SKILL.md format. The simplest version: a directory with a `SKILL.md` file containing YAML frontmatter (name, description, version, tools, requires) and freeform instruction text. Skills are loaded from a workspace directory, validated, and injected into the system prompt. This is:
- Zero-code extensibility for non-programmers.
- Composable: skills can declare tool allowlists and environment requirements.
- Compatible with both ecosystems (ClawHub + open-skills) for community sharing.

ClawBro should implement skill loading from `~/.clawbro/skills/` before writing any built-in "personality" logic.

**3. ZeroClaw's Context Compression + History Trimming**

The `context_compressor.rs` approach (trigger at 50% context fill, protect first N and last N messages, LLM summarization pass for middle) is proven and practical. Combined with `truncate_tool_result` (head 2/3 + tail 1/3 with ellipsis) this keeps ClawBro working on models with small context windows without crashing or silently dropping data. For resource-constrained targets, context management is not optional — borrow this exact algorithm.

---

### 3 Things to Do Differently

**1. Skip the Gateway / WebSocket Control Plane (at first)**

Both projects center on a persistent daemon with a WebSocket API. This is the right architecture at scale, but it adds significant complexity: you need the daemon, clients that speak the protocol, session management, auth, and reconnection logic. For ClawBro's initial version, use a simpler model:
- Single process, single invocation.
- `clawbro agent -m "..."` for one-shot or `clawbro agent` for interactive.
- Add the gateway later as a dedicated `clawbro daemon` command when channel support warrants it.

This keeps the initial codebase small enough for one developer to hold in their head, and avoids the operational complexity of keeping a daemon running.

**2. Use TOML Config + One Memory Backend (SQLite) from Day 1**

ZeroClaw offers SQLite, Markdown, Lucid, Qdrant, and None backends. OpenClaw has its own configurable memory system. For ClawBro, start with SQLite only. It is:
- Embedded (no server).
- Fast.
- Persistent.
- Queryable.
- Works on every target platform including Raspberry Pi.

Do not abstract memory into a trait until there is a proven need for a second backend. Premature abstraction here costs weeks of work for zero user benefit in the early phase.

**3. Prefer Explicit Autonomy Over Autonomous Features (No SkillForge/Hands at Start)**

ZeroClaw's SkillForge (auto-discover/auto-integrate skills from GitHub) and Hands (autonomous agent swarms) are impressive but operationally risky and complex to reason about. They require network access, scoring heuristics, and human-in-the-loop checkpoints that are hard to get right. For ClawBro, keep autonomy explicit:
- The user chooses which skills to install.
- There are no background swarms without explicit invocation.
- Automation (cron, webhooks) is an opt-in feature, not the default runtime mode.

This makes ClawBro's behavior predictable, debuggable, and trustworthy for resource-constrained and privacy-sensitive deployments — exactly the niche ZeroClaw benchmarks show is underserved.

---

## Appendix: Key File Paths (ZeroClaw, Local Clone)

These files were directly read and contain the architecture described above:

- `/outputs/repo-analysis/zeroclaw/src/main.rs` — CLI entry, all module declarations
- `/outputs/repo-analysis/zeroclaw/src/agent/agent.rs` — Agent struct, AgentBuilder, TurnEvent
- `/outputs/repo-analysis/zeroclaw/src/agent/loop_.rs` — process_message, run, filter_tool_specs_for_turn
- `/outputs/repo-analysis/zeroclaw/src/agent/context_compressor.rs` — ContextCompressionConfig
- `/outputs/repo-analysis/zeroclaw/src/agent/history.rs` — truncate_tool_result, history trimming
- `/outputs/repo-analysis/zeroclaw/src/agent/thinking.rs` — ThinkingLevel, ThinkingConfig
- `/outputs/repo-analysis/zeroclaw/src/agent/personality.rs` — PersonalityProfile, SOUL.md loading
- `/outputs/repo-analysis/zeroclaw/src/agent/dispatcher.rs` — XmlToolDispatcher, NativeToolDispatcher
- `/outputs/repo-analysis/zeroclaw/src/channels/traits.rs` — Channel, ChannelMessage, SendMessage
- `/outputs/repo-analysis/zeroclaw/src/providers/traits.rs` — Provider, ChatMessage, ToolCall, ChatResponse
- `/outputs/repo-analysis/zeroclaw/src/tools/mod.rs` — full tool registry (70+ tools listed)
- `/outputs/repo-analysis/zeroclaw/src/memory/mod.rs` — Memory backends, backend selection
- `/outputs/repo-analysis/zeroclaw/src/security/mod.rs` — all security subsystem modules
- `/outputs/repo-analysis/zeroclaw/src/sop/types.rs` — SopTrigger, SopExecutionMode, SopPriority
- `/outputs/repo-analysis/zeroclaw/src/sop/mod.rs` — SopEngine, SopAuditLogger
- `/outputs/repo-analysis/zeroclaw/src/skillforge/mod.rs` — SkillForgeConfig, Scout/Evaluate/Integrate pipeline
- `/outputs/repo-analysis/zeroclaw/src/skills/mod.rs` — Skill, SkillTool, ClawHub integration
- `/outputs/repo-analysis/zeroclaw/src/gateway/mod.rs` — axum gateway, MAX_BODY_SIZE, request limits
- `/outputs/repo-analysis/zeroclaw/Cargo.toml` — full dependency list, feature flags, build profiles
- `/outputs/repo-analysis/zeroclaw/AGENTS.md` — repository map, risk tiers, anti-patterns
- `/outputs/repo-analysis/zeroclaw/README.md` — full feature list, benchmark comparison table

---

*OpenClaw analysis is based on official docs and public GitHub inspection only (no local clone). ZeroClaw analysis is based on direct source reading of the cloned repository.*
