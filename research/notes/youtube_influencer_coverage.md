# YouTube / Influencer Coverage of AI Networking, AI-HPC and Agentic Architecture (state as of 2 Oct 2026)

**Read this first - method limits.** YouTube was not directly readable in this research session (channel pages returned only header metadata; video pages returned HTTP 429; RSS feeds and x.com were blocked by robots.txt; direct network access to youtube.com was denied). Consequently:
- **View counts are almost entirely unavailable.** The only view counts recorded below come from a third-party ranking of AI Engineer World's Fair talks. No view count below was read from YouTube itself.
- Video titles and dates come from creators' own websites, podcast pages, GitHub companion repos, or search-result titles. Where a title came only from a search-result listing, it is marked **[title from search listing; channel, date and views not verified]**.
- Quotes were extracted through a page-summarising tool. They are reproduced as returned, but **each should be checked against the linked page before being published with attribution**.
- Items dated before April 2026 are marked **[BACKGROUND]**.

---

## Q1. For each creator: most recent / most viewed items on agentic AI, AI infrastructure, GPUs/HPC or networking

### Takeaway
Between April and October 2026 all four required creators published almost exclusively on the *software* layer of agents (coding agents, context, evals, skills, MCP); none of the verifiable items addresses cluster networking. The only creators found treating networking at all are networking-native channels (David Bombal, Packet Pushers), and they cover agentic NetOps and MCP for operations, not AI back-end fabrics.

### Cited Findings

**Andrej Karpathy**
- Fireside chat at Sequoia AI Ascent 2026 (talk given ~late April 2026; Karpathy posted highlights on X about a week later). His own X post opens: "The first theme I tried to push on is that LLMs are about a lot more than just speeding up what existed before (e.g. coding)", followed by "Three examples of new horizons", the first being "menugen" (post text is truncated in the search listing; full post not readable) — [Karpathy on X](https://x.com/karpathy/status/2049903821095354523?lang=en)
- A third-party write-up of the same talk (published 30 Apr 2026) reports the framing: Software 1.0 = humans write explicit code; 2.0 = neural networks trained with data; 3.0 = "humans program models through context". Reported claims: coding agents shifted around late 2025 from autocomplete to producing working code blocks; most AI apps are "temporary wrappers around model limitations"; AI automates what you can *verify* better than what you must *specify*. Reported quote: "The context window becomes the new programming surface." The write-up contains nothing on compute, GPUs or networking — [The AI Opportunities (Guillermo Flor)](https://www.theaiopportunities.com/p/sequoia-ai-ascent-2026-andrej-karpathy)
- Same write-up reports his distinction: "vibe coding" raises the floor for non-technical users; "agentic engineering" is professional-quality systems built with agents; "jagged intelligence" = capability unevenly spread across domains — [The AI Opportunities](https://www.theaiopportunities.com/p/sequoia-ai-ascent-2026-andrej-karpathy)
- **[BACKGROUND, Mar 2026]** No Priors podcast appearance, written up 20 Mar 2026. Reported quote: "The agent part is now taken for granted, not just a single session of coding or something like that. But now you can have multiple of them" (truncated in source) — [StartupHub.ai](https://www.startuphub.ai/ai-news/artificial-intelligence/2026/andrej-karpathy-on-ai-agents-more-than-just-code)
- A further secondary profile dated 16 Aug 2026 exists on the vibe-coding-to-agentic-engineering arc (not opened) — [StartupHub.ai](https://www.startuphub.ai/ai-news/ai-figures/2026/figure-andrej-karpathy-vibe-coding-agentic-engineering-2026-08-16)

**Andrew Ng (The Batch / DeepLearning.AI)**
- The Batch issue 373, 2 Oct 2026: "The Next Top Open Model, Google Voice Agents, DeepSeek Shrinks Caches"; Ng's letter concerns open-weight models and cybersecurity — [The Batch index](https://www.deeplearning.ai/the-batch/), [issue 373](https://www.deeplearning.ai/the-batch/issue-373)
- Issue 372, 25 Sep 2026: "Opus Stalks the Frontier, Jev Classifies Everything, Running Two Models in One Agent". Ng's letter: "Moving forward on early stage, 0-to-1 projects and mature projects requires very different tactics." Mature products must balance "latency, availability, consistency, reliability, maintainability, simplicity, and cost." He warns that "corporate policies that mandate a one-size-fits-all approach, like requiring certain types of testing before anything can be shipped, can be counterproductive." No data-centre, GPU or networking content in the issue — [issue 372](https://www.deeplearning.ai/the-batch/issue-372)
- Same issue, news item: Cognition's Devin Fusion runs a lead model (planning/review) alongside a cheaper sidekick model (execution) with separate contexts to preserve prompt caching; reported to match a frontier model's standalone score on a coding-agent index at 36% lower cost per task — [issue 372](https://www.deeplearning.ai/the-batch/issue-372)
- Issue 371, 18 Sep 2026: "Meta's Agent Security, The Navier-Stokes Controversy, Fraud on Claude" — [issue 371](https://www.deeplearning.ai/the-batch/issue-371)
- Issue 370, 11 Sep 2026: letter on AI engineering skills including shaping what gets built, not only implementing it — [issue 370](https://www.deeplearning.ai/the-batch/issue-370)
- Issue 369, 4 Sep 2026: Ng calls using coding agents "a key AI engineering skill"; three phases - planning ("writing a spec that captures requirements, technical design, and architecture"), execution ("with the right balance between agent autonomy and human oversight"), and deployment/monitoring (agents "watch logs, surface issues, and propose...improvements"). Quote: "most effective coding agent use is a complex, highly iterative process, and being able to intervene with high-skill judgement gives much better results." No infrastructure or networking content — [issue 369](https://www.deeplearning.ai/the-batch/issue-369)
- DeepLearning.AI catalogue (read 2 Oct 2026; individual course launch dates not shown): "Agentic AI" (Andrew Ng, 9h55m) [link](https://learn.deeplearning.ai/courses/agentic-ai); "MCP: Build Rich-Context AI Apps with Anthropic" (1h58m) [link](https://learn.deeplearning.ai/courses/mcp-build-rich-context-ai-apps-with-anthropic); "Claude Code: A Highly Agentic Coding Assistant" (2h) [link](https://learn.deeplearning.ai/courses/claude-code-a-highly-agentic-coding-assistant); "Build AI Apps with MCP Server: Working with Box Files" (36m) [link](https://learn.deeplearning.ai/courses/build-ai-apps-with-mcp-server-working-with-box-files); "Orchestrating Workflows for GenAI Applications" (Astronomer/Airflow, 1h48m) [link](https://learn.deeplearning.ai/courses/orchestrating-workflows-for-genai-applications). No course on GPU clusters, AI networking or HPC surfaced in the listing returned — [course catalogue](https://www.deeplearning.ai/courses/)

**Priyanka Vergadia ("The Cloud Girl")**
- Now Founder/CEO of The Cloud Girl (product and career storytelling consultancy); career path Akamai, Google, Microsoft, then independent; books *Visualizing Google Cloud* and *Visualizing Generative AI*; a tech-storytelling book is forthcoming — [SuperDataScience ep. 1019, 18 Aug 2026](https://superdatascience.com/1019)
- Podcast appearance, 18 Aug 2026, "Anyone Can Write Code Now, So What Gets You Hired?". Claims: firms buying AI tools rarely see returns because they neglect training; a 10-20-70 budget split (10% tools, 20% execution, 70% education); enterprise adoption follows a J-curve taking 6-8 months. Quotes: "AI is a habit. And habits don't form in days. They form in an extended period of time." and "Anybody can write code...What is unique about me? What do I bring to the table?" — [SuperDataScience 1019](https://superdatascience.com/1019)
- Recent YouTube video titles listed on her site (no dates or views shown): "How Huge AI Models Stay Fast and Efficient | Mixture of Experts Explained"; "How to Secure Enterprise AI Agents Before They Become a Problem"; "How to Read an AI Model: What All Those Numbers Actually Mean"; "Jev: The AI Model That's Breaking The Internet (Full Tutorial)". The last refers to a model that appears in The Batch of 25 Sep 2026, suggesting the video is from roughly September 2026 (inference on date) — [thecloudgirl.dev](https://thecloudgirl.dev/), channel [youtube.com/@pvergadia](https://www.youtube.com/@pvergadia)
- Blog posts, all **[BACKGROUND, pre-April 2026]**: "How NVIDIA GPUs Works Behind The Scene" (13 Jan 2026) [link](https://www.thecloudgirl.dev/how-nvidia-gpus-power-the-ai-revolution/); "Demystifying Evals: How to Test AI Agents Like a Pro" (12 Jan 2026) [link](https://www.thecloudgirl.dev/demystifying-evals-how-to-test-ai-agents-like-a-pro/); "Software 3.0: Intent Over Syntax" (11 Jan 2026) [link](https://www.thecloudgirl.dev/software-30-intent-over-syntax/); "The 5 AI Engineer Team Roles" (10 Jan 2026); "The Life of an AI Query: Inside ChatGPT, Gemini, & Claude" (17 Dec 2025). The blog index shows 62 posts in total; the newest shown is 17 Jan 2026 — [blog index](https://www.thecloudgirl.dev/blogs/)
- Her NVIDIA GPU explainer covers CPU vs GPU, CUDA (grids, thread blocks, warps), Tensor Cores, memory hierarchy and software stack - and stops at the single GPU. It contains no mention of NVLink, InfiniBand, Ethernet, RDMA or optics — [thecloudgirl.dev GPU post](https://www.thecloudgirl.dev/how-nvidia-gpus-power-the-ai-revolution/)
- Her sketchnote library's "Networking" category is classic cloud networking (VPC, DNS, load balancing, CDN) — [thecloudgirl.dev](https://thecloudgirl.dev/)
- Paid cohort: "Agentic AI Bootcamp for Builders & Leaders", Maven, 30 Nov 2026 - 3 Jan 2027, USD 1,999, 9 live sessions, 32 lessons, 17 projects; syllabus is RAG vs fine-tuning vs agents, multi-agent design, human-in-the-loop, evals, ROI and ethics policy. No infrastructure or networking module listed — [Maven](https://maven.com/pvergadia/ai-bootcamp-for-everyone)

**Ed Donner**
- Reports 900,000 enrolments across 194 countries on Udemy — [edwarddonner.com](https://edwarddonner.com/)
- Course posts on his site: "AI Coder: Vibe Coder to Agentic Engineer" (17 Feb 2026) **[BACKGROUND]**; "AI Builder with n8n - Create Agents and Voice Agents" (4 Jan 2026) **[BACKGROUND]**; "AI Engineering MLOps Track - Deploy AI to Production" (15 Sep 2025) **[BACKGROUND]**. No course post dated April-October 2026 was visible on the homepage — [edwarddonner.com](https://edwarddonner.com/)
- "AI Coder" is pitched as "the missing manual" for coding agents, explicitly borrowing Karpathy's line that they "feel like tools we got from Aliens that come with no manual". Three weeks; Claude Code primary, plus Copilot, Cursor, Codex, Antigravity, OpenCode, Amp. Concepts: Skills, MCP, Plugins, Hooks, Subagents, Sandboxes, Swarms, Orchestrators; also Ralph Loops, Gas Town, OpenClaw, Claude Agent SDK. Comes with a supplementary YouTube playlist for new features — [course page](https://edwarddonner.com/2026/02/17/ai-coder-vibe-coder-to-agentic-engineer/)
- Earlier Udemy titles still listed: "The Complete Agentic AI Engineering Course" [link](https://external-teksystems.udemy.com/course/the-complete-agentic-ai-engineering-course/) and "AI Engineer Agentic Track: The Complete Agent & MCP Course" [link](https://www2.ctgoodjobs.hk/Learning/1445557738/udemy/ai-engineer-agentic-track-the-complete-agent-mcp-course) **[BACKGROUND]**
- YouTube channel exists at [youtube.com/@edwarddonner](https://www.youtube.com/@edwarddonner); video list not readable.

**Additional creators (chosen for relevance to AI networking / infrastructure / agents)**

*IBM Technology (whiteboard/lightboard explainers)*
- Video titles surfaced under an IBM Technology search **[title from search listing; channel, date and views not verified]**: "A2A vs MCP: AI Agent Communication Explained" [link](https://www.youtube.com/watch?v=BMDFPOyezH4); "CLI vs MCP: How AI Agents Choose the Right Tool for the Job" [link](https://www.youtube.com/watch?v=g9JIUM0MHgQ); "MCP vs Skills: Which Is Right for Your AI Agent and LLMs?" [link](https://www.youtube.com/watch?v=goU9VIXA8II); "MCP vs ADK: How Modern AI Agents Connect and Work Together" [link](https://www.youtube.com/watch?v=BedAaB1RKgE); "Agentic AI Gets Real: Inside IBM Think 2026" [link](https://www.youtube.com/watch?v=NVKMp7JL7y0)
- IBM also maintains a written A2A explainer — [IBM Think](https://www.ibm.com/think/topics/agent2agent-protocol)

*David Bombal (networking audience)*
- "AI for Network Engineers: Cisco Cloud Control Demo", 4 Jun 2026, with DJ Sampath (SVP/GM AI Software and Platform, Cisco). Framing: one interface bringing "network, security, observability, and infrastructure context" together; the demo agent traces a fault to "a site-to-site VPN tunnel issue caused by missing OSPF route exchange" by calling specialised agents. Covers MCP servers, AgenticOps, agent observability, token-usage tracking and policy enforcement — [davidbombal.com](https://davidbombal.com/ai-for-network-engineers-cisco-cloud-control-demo/), video [VY0s4JUp-K8](https://www.youtube.com/watch?v=VY0s4JUp-K8) (views not readable)

*Packet Pushers (Heavy Networking - podcast with video)*
- HN838 "Meet Mr. Packets - Building Your Own Agentic AI Team Member", 21 Aug 2026, Hank Preston (Distinguished Architect, Cisco), recorded at Cisco Live 2026. About "the why and how of building a AI agent that would behave like a junior network engineer": choosing an LLM, MCP integration, connecting network tools, guardrails, cost control — [Packet Pushers](https://packetpushers.net/podcasts/heavy-networking/hn838-meet-mr-packets-building-your-own-agentic-ai-team-member/)
- HN832 "AI Agents Are Just Another Tool: How to Integrate With Your Network Automation Strategy" (sponsored; date not confirmed) — [Packet Pushers](https://packetpushers.net/podcasts/heavy-networking/hn832-ai-agents-are-just-another-tool-how-to-integrate-with-your-network-automation-strategy-sponsored/)

*NetworkChuck*
- "you need to try Paperclip RIGHT NOW!" - filmed early Sep 2026 (per companion repo). Frames agents as employees in an org chart: an open-source layer that "hires" Claude Code, Codex, Hermes and local models into an "AI IT department", with the user as "the board" approving decisions — [companion repo](https://github.com/theNetworkChuck/paperclip-guide), video [7RVf25Rg0Mc](https://youtu.be/7RVf25Rg0Mc) (views not readable)
- Also a companion repo for an "AI in the Terminal" video (Gemini CLI, Claude Code, Codex, opencode; date not confirmed) — [GitHub](https://github.com/theNetworkChuck/ai-in-the-terminal); and a paid academy course "Hermes Agent: Build Your Own Learning AI Worker" — [NetworkChuck Academy](https://academy.networkchuck.com/course/hermes)

*AI Engineer channel (World's Fair, 29 Jun - 2 Jul 2026, San Francisco)*
- Third-party ranking of 226 conference videos by YouTube views, measured 1 Aug 2026 — [Lawrence Wu](https://lawrencewu.net/posts/2026-07-09-aie-2026-youtube-popularity/). Infrastructure-relevant entries from that ranking:
  - "From fork() to Fleet: Designing an Agent Sandbox Cloud" (Abhishek Bhardwaj, OpenAI) - 71,943 views
  - "State of the Union: Why Local, Why Now" (NVIDIA, Osmantic, Roboflow, EXO Labs panel) - 23,947 views
  - "Why MCP and ChatGPT Apps Use Double Iframes" (Frédéric Barthelet, Alpic) - 7,882 views
  - "Agents Building Agents" (Alfonso Graziano, Nearform) - 4,245 views
  - "MCP Apps: Primitives, Discovery, and the Future of Software" (Pietro Zullo, Manufact) - 4,055 views
  - "GPU Cloud Deployment Without Leaving Your IDE" (Audry Hsu, RunPod) - 1,864 views
  - No talk on cluster networking, interconnect or optics appears among the entries returned.
- Conference site and schedule — [ai.engineer](https://ai.engineer/worldsfair/2026)

*NVIDIA (GTC / Hot Chips) and ServeTheHome - the vendor/trade source of what creators are not relaying*
- **[BACKGROUND, Mar 2026]** GTC 2026 analysis (20 Mar 2026): three-layer interconnect story - NVLink 6 at 260 TB/s inside a Vera Rubin rack letting 72 GPUs act as one system; Spectrum-6 Ethernet with co-packaged optics; ConnectX-9 SuperNICs for RoCE; BlueField-4 for KV-cache/context memory offload. Analyst's line: "NVIDIA is making it nearly impossible to separate networking from compute and memory." (analyst quote, not NVIDIA's) — [NAND Research](https://nand-research.com/nvidiagtc-2026-networking/2/)
- Hot Chips 2026 (article 25 Aug 2026): Spectrum-X multiplane architecture; NVIDIA-presented figures include scaling from 8,000 to 512,000 GPUs at 1.6 Tbps per GPU, "up to 14x higher NCCL performance" versus off-the-shelf Ethernet, 1.7x fewer scale-out switches than multi-tier designs, optics at about 10% of compute power in an AI factory, and CPO with "4x fewer lasers". These are vendor claims — [ServeTheHome](https://www.servethehome.com/nvidia-spectrum-x-ethernet-multiplane-network-architecture-at-hot-chips-2026/)

*Open Compute Project channel (standards-body video, low reach)*
- "OCP Defines New AI Scale Up Network Specification - ESUN (Ethernet for Scale Up Network)" [link](https://www.youtube.com/watch?v=nfGMqLUrMnw) and "Networking - ESUN workstream (2026-02-26)" [link](https://www.youtube.com/watch?v=WaULMmo_d3g) **[titles from search listing; BACKGROUND for the Feb 2026 item]**. Written explainers of ESUN / SUE / UALink come from vendors and trade press — [Synopsys](https://www.synopsys.com/articles/ethernet-standards-scale-up-ai.html), [SemiEngineering](https://semiengineering.com/multiple-ai-scale-up-options-emerge/)

### Inferences
- The April-October 2026 centre of gravity for every mass-audience creator checked is coding agents and "agentic engineering"; infrastructure appears only as sandboxes, runtimes and local inference.
- Networking creators have pivoted to "AI for network engineers" (agents operating networks), which is the inverse of "networks for AI" (fabrics that make GPU clusters work). The second topic has essentially no mass-audience explainer among the creators checked.

### Gaps
- View counts for all creators except the AI Engineer ranking: YouTube not readable.
- Karpathy's own blog (karpathy.bearblog.dev returned 403) and full X posts: not readable; his 2026 output is represented only through one truncated post and third-party summaries.
- Vergadia's LinkedIn posts and sketchnotes from April-October 2026: not retrievable; her blog index shows nothing newer than January 2026.
- Ed Donner's April-October 2026 releases: none confirmed.
- Fireship, Matthew Berman and NVIDIA Developer channel: no verifiable 2026 items retrieved; not covered.
- IBM Technology video dates, views and core claims: unverified.

---

## Q2. Recurring themes, terminology and mental models

### Takeaway
Each creator owns a small, repeatable vocabulary - and those vocabularies describe software and people, not hardware. That vocabulary can be extended downward into the network layer, which none of them has done.

### Cited Findings
- Karpathy: Software 1.0 / 2.0 / 3.0; "context window becomes the new programming surface"; vibe coding vs agentic engineering; "jagged intelligence"; verifiability as the predictor of where automation lands first — [The AI Opportunities](https://www.theaiopportunities.com/p/sequoia-ai-ascent-2026-andrej-karpathy)
- Karpathy's phrasing is reused by others: Ed Donner builds a course around the "tools from Aliens with no manual" line — [edwarddonner.com](https://edwarddonner.com/2026/02/17/ai-coder-vibe-coder-to-agentic-engineer/); Vergadia titled a post "Software 3.0: Intent Over Syntax" — [thecloudgirl.dev](https://www.thecloudgirl.dev/software-30-intent-over-syntax/)
- Ng: lifecycle framings in threes and fives (plan / execute / deploy-and-monitor; five competencies for steering agents); the autonomy-versus-oversight balance; 0-to-1 versus mature-project tactics; evals scaling from eyeballing a few examples to rigorous suites — [issue 369](https://www.deeplearning.ai/the-batch/issue-369), [issue 372](https://www.deeplearning.ai/the-batch/issue-372)
- Vergadia: "taste" and lived perspective as the differentiator once anyone can code; "AI is a habit"; 10-20-70 budget rule; visual storytelling as method — [SuperDataScience 1019](https://superdatascience.com/1019)
- Donner: a concrete tool taxonomy (Skills, MCP, Plugins, Hooks, Subagents, Sandboxes, Swarms, Orchestrators) and "be the boss" of agents — [edwarddonner.com](https://edwarddonner.com/2026/02/17/ai-coder-vibe-coder-to-agentic-engineer/)
- NetworkChuck: agents as staff in an org chart, user as "the board" — [paperclip-guide](https://github.com/theNetworkChuck/paperclip-guide)
- Networking channels: "junior network engineer" agent; AgenticOps; agent observability and token budgets — [Packet Pushers HN838](https://packetpushers.net/podcasts/heavy-networking/hn838-meet-mr-packets-building-your-own-agentic-ai-team-member/), [David Bombal](https://davidbombal.com/ai-for-network-engineers-cisco-cloud-control-demo/)
- IBM Technology: "X vs Y" pairings as the standard title form (A2A vs MCP, CLI vs MCP, MCP vs Skills, MCP vs ADK) — search listing, e.g. [BMDFPOyezH4](https://www.youtube.com/watch?v=BMDFPOyezH4) [unverified channel attribution]

### Inferences
- A human-org metaphor for agents (employee, junior engineer, boss, board) is the dominant mental model across at least three creators. Nobody found uses a *network* metaphor for agents (addressing, discovery, routing, congestion, trust boundaries), which a networking-literate author could own.
- "X vs Y" framing is proven for protocols; the same form has not been applied by these creators to InfiniBand vs Ethernet, scale-up vs scale-out, or pluggable vs co-packaged optics.

### Gaps
- Ng's four agentic design patterns (reflection, tool use, planning, multi-agent) were named in the brief but no 2026 source restating them was retrieved; not cited here.

---

## Q3. Formats and visual styles

### Takeaway
The durable formats are single-image visual explainers, short comparison whiteboards, and multi-week hands-on courses with a repo; long conference talks reach far fewer people unless they have a striking engineering story.

### Cited Findings
- Vergadia: sketchnote library organised by category, cheatsheet-style posts ("What is GraphRAG: Cheatsheet"), "life of a query" walk-throughs, two illustrated books, and a USD 1,999 live cohort — [thecloudgirl.dev](https://thecloudgirl.dev/), [blog index](https://www.thecloudgirl.dev/blogs/), [Maven](https://maven.com/pvergadia/ai-bootcamp-for-everyone)
- Ng: weekly letter plus news digest; short courses of roughly 30 minutes to 2 hours co-branded with a vendor, and one long flagship (9h55m) — [The Batch](https://www.deeplearning.ai/the-batch/), [catalogue](https://www.deeplearning.ai/courses/)
- Donner: three-week day-by-day courses with slides, GitHub templates and a companion YouTube playlist for fast-moving features — [edwarddonner.com](https://edwarddonner.com/2026/02/17/ai-coder-vibe-coder-to-agentic-engineer/)
- Karpathy: fireside talk followed by his own numbered-highlights post on X, then a wave of third-party summaries — [X post](https://x.com/karpathy/status/2049903821095354523?lang=en), [summary](https://www.theaiopportunities.com/p/sequoia-ai-ascent-2026-andrej-karpathy)
- NetworkChuck: hype-titled tutorial plus a versioned, step-tested GitHub companion guide — [paperclip-guide](https://github.com/theNetworkChuck/paperclip-guide)
- David Bombal: vendor-executive interview with live demo — [davidbombal.com](https://davidbombal.com/ai-for-network-engineers-cisco-cloud-control-demo/)
- AI Engineer talks: view counts range from about 72,000 for a systems-design story down to about 1,000-8,000 for most MCP and GPU talks (as of 1 Aug 2026) — [Lawrence Wu](https://lawrencewu.net/posts/2026-07-09-aie-2026-youtube-popularity/)

### Inferences
- For LinkedIn, the transferable formats are the single-image sketchnote, the "life of a ___" trace (for example, life of a gradient across the fabric; life of an MCP tool call across the network), and the two-column "X vs Y".

### Gaps
- No engagement data for LinkedIn posts or sketchnotes was obtainable.

---

## Q4. Gap analysis - AI networking topics barely or superficially covered (most important)

### Takeaway
Across everything retrievable, the mass-audience creators stop at the edge of the GPU or at the agent's API boundary. The network between GPUs, and the network behaviour of agent protocols, is covered almost only by vendors, standards bodies and trade press - dense material that nobody with a large audience has translated.

### Cited Findings (evidence of absence, each tied to a source)
- **Vergadia's GPU explainer ends at the single GPU**: no NVLink, InfiniBand, Ethernet, RDMA or optics — [thecloudgirl.dev](https://www.thecloudgirl.dev/how-nvidia-gpus-power-the-ai-revolution/). Her networking sketches are cloud networking (VPC, DNS, LB, CDN) — [thecloudgirl.dev](https://thecloudgirl.dev/)
- **Ng's recent letters and issues contain no data-centre, GPU or networking discussion** (issues 369 and 372 checked directly) — [369](https://www.deeplearning.ai/the-batch/issue-369), [372](https://www.deeplearning.ai/the-batch/issue-372). The course catalogue returned no AI-networking, cluster or HPC course — [catalogue](https://www.deeplearning.ai/courses/)
- **Karpathy's 2026 framing is about the context window as programming surface**; the summary of his Sequoia talk has no compute or networking content — [The AI Opportunities](https://www.theaiopportunities.com/p/sequoia-ai-ascent-2026-andrej-karpathy)
- **Donner's curriculum covers MCP as a developer tool** alongside skills, hooks, subagents and swarms; nothing on transport, latency, or infrastructure underneath — [edwarddonner.com](https://edwarddonner.com/2026/02/17/ai-coder-vibe-coder-to-agentic-engineer/)
- **AI Engineer World's Fair**: infrastructure talks are about agent sandboxes, local inference and GPU cloud developer experience; MCP talks are about app primitives and iframes; none of the listed entries concerns interconnect — [Lawrence Wu](https://lawrencewu.net/posts/2026-07-09-aie-2026-youtube-popularity/)
- **Networking creators cover agents-for-NetOps, not fabrics-for-AI**: Bombal's June 2026 video and Packet Pushers HN838 are both about MCP-connected agents troubleshooting networks — [David Bombal](https://davidbombal.com/ai-for-network-engineers-cisco-cloud-control-demo/), [Packet Pushers](https://packetpushers.net/podcasts/heavy-networking/hn838-meet-mr-packets-building-your-own-agentic-ai-team-member/). Both are Cisco-guest or sponsored formats.
- **Where the fabric content actually lives**: vendor keynotes and trade write-ups (NVLink 6, Spectrum-6 CPO, multiplane Spectrum-X) — [NAND Research](https://nand-research.com/nvidiagtc-2026-networking/2/), [ServeTheHome](https://www.servethehome.com/nvidia-spectrum-x-ethernet-multiplane-network-architecture-at-hot-chips-2026/); standards-body recordings (OCP ESUN) — [OCP video](https://www.youtube.com/watch?v=nfGMqLUrMnw); vendor explainers of ESUN / SUE / UALink — [Synopsys](https://www.synopsys.com/articles/ethernet-standards-scale-up-ai.html); vendor FAQ on InfiniBand vs Ethernet — [NVIDIA](https://perspectives.nvidia.com/networking/faq/i-keep-hearing-both-infiniband-and-ethernet-are-valid-for-ai-now-and-i-need-to-make-the-call-for-our-13283c/); trade analysis — [SDxCentral](https://www.sdxcentral.com/analysis/ai-shakes-up-the-ethernet-infiniband-battle/)

### Inferences - ranked gaps a LinkedIn author could fill
1. **Scale-up vs scale-out vs scale-across, explained visually.** No sketchnote-style explainer found from any covered creator. NVLink inside the rack, Ethernet/InfiniBand between racks, and the newer Ethernet scale-up efforts (ESUN, SUE, UALink) exist only in vendor and standards material. Highest-value gap.
2. **InfiniBand vs Ethernet (RoCE, Ultra Ethernet) as a neutral "X vs Y".** The comparison format is proven by IBM Technology for protocols, but the available InfiniBand/Ethernet explainers are vendor-authored and therefore partial.
3. **"What happens after the GPU" - continuing Vergadia's explainer.** Her post stops at one GPU; a natural sequel is "life of a gradient": all-reduce, NCCL, RDMA, why jitter and tail latency set job completion time. NVIDIA's own "up to 14x NCCL" figure shows the network is the lever, yet no educator unpacks why.
4. **Optics and power.** Co-packaged vs pluggable optics, lasers, and the claim that optics are about 10% of AI-factory compute power appear only in vendor/trade sources. No mass creator found explaining it.
5. **Topology literacy.** Multiplane, rails, fat-tree and fault behaviour (for example, keeping 90% of bandwidth on failure) are absent from educator content.
6. **Agent protocols as network traffic.** MCP and A2A are taught as developer abstractions. Not found: what they look like on the wire, session and streaming behaviour, discovery and identity, east-west traffic growth from multi-agent systems, where latency accumulates across chained tool calls, and what that means for enterprise network design and segmentation.
7. **Inference-era networking.** KV-cache / context-memory offload to DPUs (BlueField-4) and the networking impact of long-context agents appear in GTC coverage only. This directly connects Karpathy's "context window is the programming surface" to hardware - a bridge nobody has drawn.
8. **Agentic NetOps beyond the vendor demo.** Existing coverage is vendor-led. Missing: independent treatment of guardrails, blast radius, change approval, evaluation of network agents, and cost - applying Ng's eval and autonomy-vs-oversight framing to network operations.
9. **Agent sandboxes meet networking.** The most-viewed infrastructure talk at AI Engineer was on agent sandbox clouds; the networking side (egress control, isolation, per-agent identity) is an adjacent uncovered angle.
10. **Skills translation for network engineers.** Vergadia's "taste" and Ng's "AI engineering skills" pieces address developers; nothing found addresses what a network or HPC engineer's equivalent skill set is.

### Gaps
- This is an absence-of-evidence analysis limited by unreadable YouTube listings. A creator may have published a relevant video that did not surface; in particular IBM Technology, NVIDIA Developer, Fireship and Matthew Berman catalogues could not be enumerated. Treat "not covered" as "not found in retrievable sources", and spot-check on YouTube before asserting publicly that a named creator has never covered a topic.
- No evidence was obtained on whether Vergadia has published an InfiniBand/Ethernet or MCP/A2A sketchnote on LinkedIn in 2026.

---

## Q5. Quotable statements and data points (with attribution)

### Takeaway
There are usable quotes from Ng, Vergadia and Karpathy on agents and skills, and usable vendor data points on networking - which itself illustrates the gap: the people are quotable on software, only vendors are quotable on fabrics.

### Cited Findings
- Andrew Ng, 4 Sep 2026: using coding agents is "a key AI engineering skill"; "most effective coding agent use is a complex, highly iterative process, and being able to intervene with high-skill judgement gives much better results." — [The Batch 369](https://www.deeplearning.ai/the-batch/issue-369)
- Andrew Ng, 25 Sep 2026: "Moving forward on early stage, 0-to-1 projects and mature projects requires very different tactics."; mature products must balance "latency, availability, consistency, reliability, maintainability, simplicity, and cost." — [The Batch 372](https://www.deeplearning.ai/the-batch/issue-372)
- Andrej Karpathy, Sequoia Ascent 2026 (own post): "LLMs are about a lot more than just speeding up what existed before (e.g. coding)." — [X](https://x.com/karpathy/status/2049903821095354523?lang=en)
- Andrej Karpathy, as reported by a third party (verify against the recording before quoting): "The context window becomes the new programming surface." — [The AI Opportunities](https://www.theaiopportunities.com/p/sequoia-ai-ascent-2026-andrej-karpathy)
- Karpathy line as quoted by Ed Donner: coding agents "feel like tools we got from Aliens that come with no manual" — [edwarddonner.com](https://edwarddonner.com/2026/02/17/ai-coder-vibe-coder-to-agentic-engineer/)
- Priyanka Vergadia, 18 Aug 2026: "AI is a habit. And habits don't form in days. They form in an extended period of time."; the 10-20-70 budget rule; 6-8 month adoption J-curve — [SuperDataScience 1019](https://superdatascience.com/1019)
- Ed Donner: 900,000 enrolments across 194 countries — [edwarddonner.com](https://edwarddonner.com/)
- Cisco via David Bombal, 4 Jun 2026: agent root-caused "a site-to-site VPN tunnel issue caused by missing OSPF route exchange" — [davidbombal.com](https://davidbombal.com/ai-for-network-engineers-cisco-cloud-control-demo/)
- Hank Preston / Packet Pushers, 21 Aug 2026: an agent "that would behave like a junior network engineer" — [Packet Pushers](https://packetpushers.net/podcasts/heavy-networking/hn838-meet-mr-packets-building-your-own-agentic-ai-team-member/)
- NVIDIA (vendor claims, Hot Chips 2026): 8,000 to 512,000 GPUs at 1.6 Tbps per GPU; "up to 14x higher NCCL performance"; optics about 10% of AI-factory compute power; CPO "4x fewer lasers" — [ServeTheHome](https://www.servethehome.com/nvidia-spectrum-x-ethernet-multiplane-network-architecture-at-hot-chips-2026/)
- NVIDIA GTC 2026 **[BACKGROUND, Mar 2026]**: NVLink 6 at 260 TB/s per rack, 72 GPUs as one system; analyst comment "NVIDIA is making it nearly impossible to separate networking from compute and memory." — [NAND Research](https://nand-research.com/nvidiagtc-2026-networking/2/)
- AI Engineer World's Fair: top infrastructure talk at about 72,000 views versus roughly 4,000-8,000 for MCP talks, as of 1 Aug 2026 — [Lawrence Wu](https://lawrencewu.net/posts/2026-07-09-aie-2026-youtube-popularity/)

### Inferences
- A strong LinkedIn hook is the juxtaposition itself: Karpathy says the context window is the programming surface; NVIDIA says the network sets training performance; no popular educator connects the two.

### Gaps
- No direct, sourced quote from Karpathy, Ng, Vergadia or Donner about networking, InfiniBand, Ethernet, optics or HPC was found. Do not attribute any such view to them.
- No Jensen Huang quote was captured from a primary source.
- All quotes passed through a summarising tool; verify wording at the linked URL before publishing.
