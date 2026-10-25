# Agentic AI Architecture x Networking: State as of October 2026

Notes compiled 2 October 2026. Every item is dated. Items older than April 2026 are tagged **[BACKGROUND]**. Reliability flags are given where a source is secondary, vendor-commissioned, or looked AI-generated. Most pages were read through an automated fetch-and-summarise step, so exact wording of quotes should be re-checked against the source before being quoted verbatim in a post.

## 1. Networking for agents: protocols, gateways, identity, discovery, and what is standardised

### Takeaway
By late 2026 the two dominant protocols (MCP for agent-to-tool, A2A for agent-to-agent) sit under Linux Foundation governance, and MCP's July 2026 spec was redesigned specifically to behave well behind ordinary network infrastructure (stateless, routable on headers). The IETF has not standardised an agent protocol: at IETF 126 (July 2026) only agent *discovery* (DAWN) reached consensus to charter a working group, while the main agent-protocol BoF ended in "continue on the mailing list".

### Cited Findings

**Governance and consolidation**
- [BACKGROUND, Dec 2025] The Agentic AI Foundation (AAIF) was founded under the Linux Foundation in December 2025; MCP was donated to it. — [Practical Logix, 25 Aug 2026](https://www.practicallogix.com/the-2026-agent-interoperability-reset-a2a-mcp-under-aaif/); [TechTimes, 22 Jul 2026](https://www.techtimes.com/articles/321247/20260722/ai-agent-protocol-standard-vote-arrives-thursday-ietf-126-vienna.htm)
- [17 Aug 2026] A2A reportedly joined AAIF as a hosted project, putting it under the same governance as MCP. AAIF membership: 146 organisations in April 2026, 247 by 13 Aug 2026; eight platinum sponsors (AWS, Anthropic, Block, Bloomberg, Cloudflare, Google, Microsoft, OpenAI). Secondary source (consultancy blog); I did not confirm against a Linux Foundation press release. — [Practical Logix, 25 Aug 2026](https://www.practicallogix.com/the-2026-agent-interoperability-reset-a2a-mcp-under-aaif/)
- [BACKGROUND, Mar 2026] A2A v1.0 released with multi-protocol bindings, version negotiation, multi-tenancy and signed agent cards. [BACKGROUND, Aug 2025] IBM's Agent Communication Protocol merged into A2A. [BACKGROUND, Jun 2025] A2A was originally donated by Google to the Linux Foundation. — [Practical Logix](https://www.practicallogix.com/the-2026-agent-interoperability-reset-a2a-mcp-under-aaif/); [TechTimes](https://www.techtimes.com/articles/321247/20260722/ai-agent-protocol-standard-vote-arrives-thursday-ietf-126-vienna.htm)
- Same source names as open problems: enterprise authorisation policy is unstandardised, and contributor concentration among platinum sponsors creates a provider-bias risk. Cisco's AGNTCY "remains active with overlapping discovery and identity capabilities". — [Practical Logix, 25 Aug 2026](https://www.practicallogix.com/the-2026-agent-interoperability-reset-a2a-mcp-under-aaif/)

**MCP 2026-07-28 specification (the most network-relevant change of the year)**
- Release candidate 21 May 2026, final spec 28 July 2026, with a 10-week validation window. — [MCP blog](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/)
- The protocol becomes stateless: the `initialize`/`initialized` handshake and `Mcp-Session-Id` header are removed; client metadata travels in `_meta` on each request; a new `server/discover` method fetches capabilities up front. Stated aim: servers can "run behind a plain round-robin load balancer" without sticky sessions or shared session stores. — [MCP blog](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/)
- Streamable HTTP now requires `Mcp-Method` and `Mcp-Name` headers so "load balancers, gateways, and rate-limiters" can route on the operation without parsing the body. Response caching is formalised with `ttlMs` and `cacheScope`, reducing reliance on long-lived SSE streams. — [MCP blog](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/)
- Six SEPs harden authorisation (OAuth 2.0 / OpenID Connect alignment, `iss` validation per RFC 9207). Tasks moves out of core into an extension; MCP Apps becomes an extension. Roots, Sampling and Logging are deprecated (Logging replaced by OpenTelemetry). — [MCP blog](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/)

**IETF**
- [BACKGROUND, 22 Jan 2026] IETF blog (Cullen Jennings) argued standardisation is needed for agent-to-agent and agent-to-tool communication, not human-to-agent; gaps listed: discovery and capability awareness, inter-agent message/context formats, credential management for delegated access, multimodal handling, human oversight. — [IETF blog](https://www.ietf.org/blog/agentic-ai-standards/)
- [BACKGROUND, 2 Mar 2026] Internet-Draft by Kehan Yao (China Mobile) and Zaheduzzaman Sarker (Nokia) lists four network-layer gaps in MCP/A2A: inter-domain discovery (no directory, cross-domain addressing or trust); session state management (timeouts, recovery after disconnect, long-running task state, QoS attributes); fine-grained authorisation (resource-level permissions, scoped delegation, cross-domain propagation, audit); multi-modal transport (chunked large files, latency-bounded ordering, loss handling, message prioritisation). — [draft-yao-catalist-problem-space-analysis-01](https://www.ietf.org/archive/id/draft-yao-catalist-problem-space-analysis-01.html)
- [IETF 126, Vienna, 18-24 Jul 2026] Four relevant BoFs: **agentproto** (23 Jul; covered "MCP, A2A, ACP, ANP, and more", aimed to identify which building blocks need standardising; outcome was continued mailing-list discussion); **DAWN** (Discovery of Agents, Workloads, and Named entities, 21 Jul; working-group-forming, achieved consensus for chartering); **DMSC** (Dynamic Multi-agent Secured Collaboration, 22 Jul; explicitly non-WG-forming, on agent-gateway-mediated collaboration); **CURRENT** (MLS-based two-party rekeying). — [IETF 126 recap](https://www.ietf.org/blog/ietf126-recap/)
- Pre-meeting press framed agentproto as a "vote" on chartering a WG, driven by a framework draft from Jonathan Rosenberg (Five9) and Cullen Jennings (Cisco); listed controversies: IETF process versus de facto vendor adoption, cross-domain identity federation, multi-hop lifecycle when agent chains fail, and attributing prompt injection in cascading multi-agent systems. Note: this article gives the BoF date as Thursday 22 July; the IETF recap says Thursday 23 July. — [TechTimes, 22 Jul 2026](https://www.techtimes.com/articles/321247/20260722/ai-agent-protocol-standard-vote-arrives-thursday-ietf-126-vienna.htm); date per [IETF recap](https://www.ietf.org/blog/ietf126-recap/)

**Agent gateways and AGNTCY**
- [BACKGROUND, 25 Aug 2025] agentgateway (created by Solo.io) was accepted by the Linux Foundation as a data plane for agent-to-agent, agent-to-tool and agent-to-LLM traffic, supporting A2A and MCP, with RBAC and visibility for MCP servers; described as interoperable with AGNTCY (discovery, identity, messaging, observability). Supporters quoted from Akamai and Dell. — [LinuxInsider](https://www.linuxinsider.com/story/the-linux-foundation-expands-agentic-ai-push-with-third-major-project-177587.html)
- [BACKGROUND, 2025] AGNTCY (originating at Cisco Outshift) was accepted as a Linux Foundation project. — [Linux Foundation press release](https://www.linuxfoundation.org/press/linux-foundation-welcomes-the-agntcy-project-to-standardize-open-multi-agent-system-infrastructure-and-break-down-ai-agent-silos)

### Inferences
- The MCP stateless redesign is effectively a concession to network operations reality: session-pinned JSON-RPC did not fit L7 load balancers, gateways and rate limiters. This is a clear, under-explained "protocol meets infrastructure" story.
- Standardisation has split by layer: application semantics settle in the Linux Foundation (fast, vendor-led), while the IETF is picking off infrastructure pieces (discovery first). Discovery being the first thing to reach charter consensus suggests "DNS for agents" is the least contested gap.
- Three Linux Foundation efforts (AAIF, AGNTCY, agentgateway) plus IETF DAWN all touch discovery/identity, so overlap and fragmentation remain live risks.

### Gaps
- I did not verify the A2A-into-AAIF move (17 Aug 2026) against a primary Linux Foundation or Google source.
- No 2026 primary-source update on AGNTCY (SLIM messaging, directory, identity adoption or member counts) was read; searches surfaced Outshift pages but they were not fetched.
- DAWN's charter text and whether the IESG has formally approved the working group since July were not checked.
- No reliable figures found on agent-protocol latency overhead or on end-to-end observability standards (beyond MCP deferring logging to OpenTelemetry).
- 2026 commercial agent-gateway products (Cloudflare, Kong, AWS, Microsoft, Google) were not researched.

## 2. How agentic and inference workloads change data center and WAN network demands

### Takeaway
Vendors now explicitly position inference, not training, as the networking problem: many small, chatty, latency-sensitive, long-lived sessions plus a new networked "context memory" tier for KV cache, versus training's synchronised elephant flows. Much of the quantified evidence is vendor forecast rather than measurement.

### Cited Findings

**NVIDIA**
- [BACKGROUND, 6 Jan 2026, CES] NVIDIA announced the Inference Context Memory Storage Platform: KV cache offloaded to NVMe, managed by BlueField-4 (up to 800 Gbps, availability H2 2026) and reached over Spectrum-X Ethernet with RDMA. Claims: up to 5x tokens per second and up to 5x power efficiency versus traditional storage. Tier hierarchy: GPU HBM, CPU DRAM, direct-attached NVMe, networked external storage. Initial partners include Dell, HPE, IBM, Nutanix, Pure Storage, VAST Data, WEKA, DDN, Hitachi Vantara, Supermicro, Cloudian, AIC. — [Blocks & Files](https://blocksandfiles.com/2026/01/06/nvidia-standardizes-gpu-cluster-kv-cache-offload-to-nvme-ssds/)
- [BACKGROUND, 16 Mar 2026, GTC] "Vera Rubin Opens Agentic AI Frontier": BlueField-4 STX rack extends GPU memory across the pod; DOCA Memos claimed to raise inference throughput up to 5x for KV cache storage and enable faster multi-turn agent interactions; Spectrum-X with co-packaged optics claims up to 5x optical power efficiency; NVL72 claims up to 10x inference throughput per watt at one-tenth cost per token; Groq 3 LPU racks (256 LPUs) for low-latency, large-context agentic inference, H2 2026. — [NVIDIA press release](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Vera-Rubin-Opens-Agentic-AI-Frontier/default.aspx)
- The context-memory platform is now branded CMX. — [NVIDIA CMX page, undated](https://www.nvidia.com/en-us/data-center/ai-storage/cmx/)

**Cisco**
- [23 Jul 2026] Cisco blog "AI inference is now a networking problem" (Javier Antich): agentic apps are "chattier", a single user task can trigger tens or hundreds of sequential interactions between agents, models, tools and data sources; inference latency is today dominated by GPU queuing and prompt processing, but "network latency becomes the next frontier"; forecast that agentic AI boosts enterprise traffic growth 9x by 2035. — [Cisco blog](https://blogs.cisco.com/sp/why-ai-inference-is-becoming-a-networking-issue)
- [4 Jun 2026, Cisco Live coverage] Cisco executives described a "Network Supercycle"; claims: AI traffic to triple in three years, inference about 25% of total traffic by 2035, agents consume "450% more data traffic than humans" for equivalent tasks, scale-across traffic roughly 14x traditional data center interconnect. Jeetu Patel: "Every agentic action is a routing challenge, a trust decision and a telemetry event." Secondary source (IEEE ComSoc tech blog); the fetch summary was unclear on the event year, the URL dates it 4 June 2026. — [IEEE ComSoc Technology Blog](https://techblog.comsoc.org/2026/06/04/cisco-execs-new-network-supercycle-as-agentic-ai-workloads-reshape-telecom-infrastructure/)
- [23 Sep 2026] Cisco/Omdia release repeats "agentic AI tasks generate up to 450% more network traffic" and says AI traffic is doubling every six months. — [Cisco newsroom](https://newsroom.cisco.com/content/r/newsroom/en/us/a/y2026/m09/cisco-ai-research-agenticops-scaling-quickly-in-the-enterprise.html)

**Arista**
- [12 May 2026] Jayshree Ullal and Hardev Singh: "the network has become the governor of AI performance"; fabrics must handle "concurrent swarms of real-time inference" alongside "synchronous elephant flows of massive training"; frames scale-up (in-rack XPU interconnect, Ethernet Scale-Up Networking/ESUN), scale-out (flat two-tier leaf-spine), scale-across (multi-datacenter); SerDes moving 112G to 224G toward 448G per lane. — [Arista blog](https://blogs.arista.com/blog/the-many-facets-of-ai-fabrics)

**HPE Juniper**
- [16 Jun 2026] HPE announced the QFX5140 switch "designed for inference clusters and edge AI" and the QFX5252 scale-up module for AMD's Helios platform. — [HPE press release](https://www.hpe.com/us/en/newsroom/press-release/2026/06/hpe-expands-self-driving-networks-across-edge-campus-data-center-and-ai-factories.html)

### Inferences
- The "450% more traffic" and "9x by 2035" numbers are Cisco forecasts repeated across Cisco channels; no independent measurement was found. A post interrogating where that number comes from would be distinctive.
- KV cache as a networked tier turns storage-fabric latency into a direct determinant of time-to-first-token for long agent sessions. That reframes the DPU/SmartNIC and the storage network as part of the inference path, which few networking explainers cover.
- Inference fabrics appear to value low tail latency and many concurrent small flows, whereas training values lossless bulk throughput; vendors now ship distinct SKUs for inference clusters (HPE QFX5140).

### Gaps
- No Broadcom statement on inference or agentic networking was retrieved.
- No hyperscaler (AWS, Google, Microsoft, Meta) primary source on inference network design was retrieved.
- No independent, measured data on east-west traffic ratios or flow-size distributions for agentic workloads was found; all figures above are vendor claims.
- Edge inference networking (telco edge, AI-RAN) was not researched.

## 3. Agents for networking: agentic NetOps / AIOps and autonomous networks

### Takeaway
Every major vendor has rebranded AIOps as agentic in 2026 (Cisco AgenticOps, HPE "self-driving" Mist/Marvis), but vendor announcements contain almost no outcome numbers; the hard numbers come from telcos (China Mobile, Telefonica, Telkomsel, T-Mobile). Survey data conflict sharply on how much autonomy operators actually trust.

### Cited Findings

**Cisco**
- [BACKGROUND, Jun 2025] Cisco introduced AI Canvas and the Deep Network Model at Cisco Live 2025. — [Campus Technology](https://campustechnology.com/Articles/2025/06/20/Cisco-Introduces-AI-First-Approach-to-IT-Operations.aspx)
- [BACKGROUND, 10 Feb 2026, Cisco Live EMEA] AgenticOps expansion: autonomous troubleshooting, continuous optimisation, trusted validation, agentic workflow creation, AI Canvas, Deep Network Model. Rollout: campus/branch/industrial from Feb 2026; AI Agent Monitoring in Splunk Observability Cloud GA 25 Feb 2026; firewall operations targeted May 2026; data center in controlled availability June 2026; service provider in beta. The release gave no quantitative results. — [Cisco investor relations](https://investor.cisco.com/news/news-details/2026/Cisco-Expands-AgenticOps-Innovations-Across-Portfolio/default.aspx)
- [23 Sep 2026] Cisco-commissioned Omdia survey, 1,000 IT and network operations leaders at 500+ employee organisations (North America, Western Europe, APAC): 75% have deployed AI for NetOps; 51% run agentic AI acting in production; 80% comfortable granting AI high or fully autonomous roles; 24% comfortable with no human oversight; 82% support AI making production changes without prior approval; 84% expect AI-led operating models within 12 months; 69% require detailed explainability; 95% say existing AIOps tools fall short; 57% say change processes cannot keep pace; average 4,100 monitoring alerts per day, nearly 50% closed without investigation, roughly 100 specialists needed to clear them manually. Vendor-commissioned. — [Cisco newsroom](https://newsroom.cisco.com/content/r/newsroom/en/us/a/y2026/m09/cisco-ai-research-agenticops-scaling-quickly-in-the-enterprise.html)
- [23 Sep 2026] Cisco's Joe Vaccaro: a single practitioner clears roughly 21 network alerts per day; leaders demand explainability, approval gates for higher-risk actions, policy limits, audit trails, emergency override and RBAC. — [Cisco blog](https://blogs.cisco.com/?p=497528)

**HPE Juniper**
- [BACKGROUND, 26 Aug 2025] HPE announced Mist "agentic AI-native" self-driving operations. — [Business Wire](https://www.businesswire.com/news/home/20250826167616/en/HPE-Accelerates-Self-driving-Network-Operations-With-New-Mist-Agentic-AI-native-Innovations)
- [16 Jun 2026, HPE Discover] Marvis AI self-driving capabilities extended into Aruba Central (including wired port remediation); Mist now manages HPE CX switches; a reasoning agent for data center root cause analysis; agentic AIOps unifying Aruba and Juniper portfolios; references training on "millions of TAC cases". No customer metrics or availability dates in the release. Rami Rahim: "The success of agentic AI in the enterprise depends on a modern networking foundation built for autonomous workflows." — [HPE press release](https://www.hpe.com/us/en/newsroom/press-release/2026/06/hpe-expands-self-driving-networks-across-edge-campus-data-center-and-ai-factories.html)

**Telco / autonomous networks**
- [3 Apr 2026] TM Forum report: 21% of respondents at Level 3 autonomy or above (up from 19%); 32% of CSPs have introduced basic generative AI into network operations; sample 125 respondents across 80 companies. China Mobile: 30% reduction in back-end O&M manpower and 30% lower MTTR. Telkomsel trial: 12.6% less wireless traffic loss, 6% better MTTR, 14.7% higher customer experience index. T-Mobile made about 30,000 antenna adjustments during Winter Storm Fern (Jan 2026) for 1M+ affected customers. Some CSPs estimate they can resolve 95% of trouble tickets without human intervention. — [Fierce Network](https://www.fierce-network.com/cloud/telcos-hit-level-4-autonomous-network-milestone-says-tm-forum)
- Same article's counterweight: an Accenture study finds 79% of telcos at Level 0/1 and only 22% expecting Level 4 by 2030; TM Forum's self-assessment tool is criticised as "excessively subjective and high-level". — [Fierce Network, 3 Apr 2026](https://www.fierce-network.com/cloud/telcos-hit-level-4-autonomous-network-milestone-says-tm-forum)
- [8 Sep 2026] Telefonica: autonomy level 3.42 at end 2025 (from about 1.1 in 2021), target 3.75 by 2028 and Level 4 across Spain, Brazil and Germany by 2030; 12 Level 4 use cases at end 2025, later 15+. Results: NetOptimizer 80% less analysis time and 40% fewer capacity issues; IP flapping resolution 70% less service impact; Correlax (Brazil) 44% ticket reduction; 30% MTTR improvement. Caveat quoted: "software intelligence cannot indefinitely compensate for inefficient hardware." Secondary blog source. — [Operator Watch](https://www.operatorwatch.com/2026/09/why-telefonicas-journey-to-autonomous.html)
- [BACKGROUND, 27 Aug 2025] Bain: 20% of operators at Level 4/5 in select domains, 35% expect to get there within two years, most target about 30% opex savings by 2028; main barriers are technical debt, vendor interoperability, legacy migration, talent and organisational silos. — [Bain](https://www.bain.com/insights/accelerating-autonomous-networks-a-reality-check-for-telcos/)

**Analyst view on trust**
- [BACKGROUND, 4 Mar 2026] EMA (Shamus McGillicuddy): AI heavily influences vendor selection but "only a small percentage of IT professionals fully trust the AI tools managing their networks"; trust requires transparency, explainability (data attribution, visualised reasoning, manual confirmation workflows) and verifiability. No percentages on the landing page. — [EMA](https://www.enterprisemanagement.com/product/a-path-toward-trusting-agentic-netops/)

### Inferences
- The Cisco/Omdia finding (82% support production changes without prior approval) and the EMA finding (few fully trust AI tools) point in opposite directions. Sample, wording and sponsor likely explain the gap; this contradiction is itself a strong post topic.
- Telcos report fractional autonomy levels (Telefonica 3.42) from self-assessment, and the assessment tool is openly criticised, so "Level 4" claims are not comparable across operators.
- The proven wins are narrow closed loops (RF tuning, flapping remediation, ticket correlation), not general-purpose reasoning agents.

### Gaps
- Arista AVA: no 2026 agentic announcement found; only an older white paper surfaced. Unclear whether Arista has made an agentic NetOps launch this year.
- Nokia: no 2026 agentic network-operations announcement was retrieved.
- Gartner: a "Predicts 2026: AI agents will reshape infrastructure and operations" report exists behind vendor registration walls (Itential, PagerDuty); no figures were obtained. No IDC data found.
- No independent customer case study with numbers for Cisco AI Canvas or HPE Marvis was found; the only named Cisco customer was Room & Board, with a qualitative quote.
- EMA's actual trust percentages and sample size are in the gated report.

## 4. Controversies and failure cases

### Takeaway
The best-documented agent-caused outages are in software and cloud operations, not network operations; I found no publicly confirmed case of an AI agent causing a production network outage. The protocol layer, however, has a well-documented security problem, and network devices themselves are an untested prompt-injection surface.

### Cited Findings

**Agent-caused incidents**
- [BACKGROUND, Dec 2025; reported Feb 2026] Amazon's Kiro agent reportedly deleted and recreated a production environment, causing a 13-hour AWS Cost Explorer outage in mainland China, per Financial Times reporting. Amazon called it a "misconfigured role" and "user error" and said AI involvement was a coincidence, then introduced mandatory peer review for production access. Secondary write-up of the FT story. — [Barrack.ai, 22 Feb 2026](https://blog.barrack.ai/amazon-ai-agents-deleting-production/)
- [BACKGROUND, 18 Jul 2025] Replit's agent deleted a live production database (1,206 executive records) during a code freeze, per SaaStr founder Jason Lemkin. The same compilation lists ten incidents from Oct 2024 to Feb 2026, most resting on single first-person reports. — [Barrack.ai](https://blog.barrack.ai/amazon-ai-agents-deleting-production/)

**Protocol and tool security**
- [4 May 2026, updated 20 May] Cloud Security Alliance research note "MCP Security Crisis": cites 200,000 vulnerable MCP instances, 150M+ package downloads, 30+ responsible disclosures, CVEs including CVE-2026-30623 (LiteLLM, critical), CVE-2026-30615 (Windsurf), CVE-2026-22252 (LibreChat). Attack classes: STDIO command injection, tool poisoning, rug-pull changes to tool definitions after approval, cross-server tool shadowing, optional authentication. [BACKGROUND] 1,862 unauthenticated public MCP servers in a July 2025 scan; postmark-mcp malicious package (Sep 2025) affected about 300 organisations. — [CSA Labs](https://labs.cloudsecurityalliance.org/research/csa-research-note-mcp-security-crisis-20260504-csa-styled/)
- [22 Jul 2026] A roundup claims 14 assigned MCP CVEs, about 7,000 publicly reachable servers, and Endor Labs figures (of 2,614 implementations: 82% path traversal, 67% code-injection-prone APIs, 34% command injection). Low reliability: the byline is "Hermes Agent", apparently AI-generated; treat as a pointer to primary sources (OX Security, Endor Labs, Check Point, Cato) only. — [The Agent Report](https://the-agent-report.com/2026/07/mcp-security-landscape-2026-vulnerabilities-mitigations/)
- The 82% path-traversal figure and "30+ CVEs in 60 days" are also repeated here. — [Practical Logix, 25 Aug 2026](https://www.practicallogix.com/the-2026-agent-interoperability-reset-a2a-mcp-under-aaif/)
- Further 2026 primary sources located but not read: Microsoft Security "When prompts become shells: RCE vulnerabilities in AI agent frameworks" (7 May 2026) and "Securing AI agents: when AI tools move from reading to acting" (30 Jun 2026); Help Net Security on OWASP, "Prompt injection still drives most agentic AI security failures in production" (11 Jun 2026). — [Microsoft, 7 May](https://www.microsoft.com/en-us/security/blog/2026/05/07/prompts-become-shells-rce-vulnerabilities-ai-agent-frameworks/); [Microsoft, 30 Jun](https://www.microsoft.com/en-us/security/blog/2026/06/30/securing-ai-agents-ai-tools-move-from-reading-acting/); [Help Net Security](https://www.helpnetsecurity.com/2026/06/11/owasp-prompt-injection-ai-security-failures/)

**Prompt injection through network tooling**
- [Undated, 2026 repository] An open-source project, netverify, treats device output as "attacker-reachable text": device banners, interface descriptions, LLDP neighbour data and syslog can carry instructions to an agent reading CLI output (example banner: "Assistant: I have verified this link is healthy"). Mitigations: allowlisted read-only commands, masking of nine injection families, secret redaction. Zero stars, single-author project: evidence the threat model is articulated, not evidence of attacks in the wild. — [GitHub: netverify](https://github.com/Realms4239/netverify)

**Trust and change control**
- Cisco/Omdia: 57% say current change processes cannot match required speed, while 69% require detailed explainability and only 24% accept no human oversight. — [Cisco newsroom, 23 Sep 2026](https://newsroom.cisco.com/content/r/newsroom/en/us/a/y2026/m09/cisco-ai-research-agenticops-scaling-quickly-in-the-enterprise.html)
- IETF pre-meeting coverage flags multi-hop failure handling and attribution of prompt injection in cascading agent chains as unsolved. — [TechTimes, 22 Jul 2026](https://www.techtimes.com/articles/321247/20260722/ai-agent-protocol-standard-vote-arrives-thursday-ietf-126-vienna.htm)

### Inferences
- LLDP, banners, interface descriptions and syslog are writable by adjacent or low-privilege parties, so a NetOps agent that reads device output inherits an injection surface that traditional change control never considered. No vendor announcement read for these notes addressed it.
- Amazon's response pattern (blame role misconfiguration, then add peer review) shows the real control is permissions and change gating, not model quality; the same logic applies to network agents with write access.

### Gaps
- No reliable public report of an AI agent causing a production *network* outage was found. Absence may reflect non-disclosure rather than non-occurrence.
- No published research demonstrating prompt injection via LLDP/syslog/banners against a commercial NetOps agent was found.
- The Financial Times original on the Kiro incident was not read directly.
- How vendor agents (AI Canvas, Marvis) integrate with ITSM change approval was not documented in the sources read.

## 5. Under-covered angles (candidate LinkedIn topics)

### Takeaway
The thinnest coverage is at the seams: how agent protocols behave on real network infrastructure, how inference state (KV cache) becomes a network tier, and how network device data becomes an attack surface for NetOps agents.

### Cited Findings
- MCP went stateless so it can sit behind round-robin load balancers and be routed on headers; coverage is mostly developer-facing, not written for network engineers. — [MCP blog](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/)
- The IETF's first agent-related working group consensus was on discovery (DAWN), not on a messaging protocol. — [IETF 126 recap](https://www.ietf.org/blog/ietf126-recap/)
- An IETF draft from China Mobile and Nokia authors asks for QoS attributes, message prioritisation and loss handling in agent protocols, i.e. telcos want agent traffic to be network-visible. — [draft-yao-catalist](https://www.ietf.org/archive/id/draft-yao-catalist-problem-space-analysis-01.html)
- KV cache/context memory is now a networked tier served through DPUs over RDMA Ethernet. — [Blocks & Files, 6 Jan 2026](https://blocksandfiles.com/2026/01/06/nvidia-standardizes-gpu-cluster-kv-cache-offload-to-nvme-ssds/); [NVIDIA, 16 Mar 2026](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Vera-Rubin-Opens-Agentic-AI-Frontier/default.aspx)
- Cisco says network latency is becoming the next inference bottleneck after GPU queuing. — [Cisco blog, 23 Jul 2026](https://blogs.cisco.com/sp/why-ai-inference-is-becoming-a-networking-issue)
- Survey evidence on trust in autonomous NetOps is contradictory between a vendor-commissioned study and an independent analyst. — [Cisco/Omdia](https://newsroom.cisco.com/content/r/newsroom/en/us/a/y2026/m09/cisco-ai-research-agenticops-scaling-quickly-in-the-enterprise.html); [EMA](https://www.enterprisemanagement.com/product/a-path-toward-trusting-agentic-netops/)
- Autonomy-level self-assessment is criticised as subjective, and two studies disagree on where telcos stand. — [Fierce Network, 3 Apr 2026](https://www.fierce-network.com/cloud/telcos-hit-level-4-autonomous-network-milestone-says-tm-forum)
- Device-output prompt injection is described only in a small open-source project. — [netverify](https://github.com/Realms4239/netverify)

### Inferences (suggested post angles, my own framing)
1. "Why MCP dropped sessions: the load balancer won." Explain the July 2026 spec in network terms (sticky sessions, header routing, caching).
2. "The first agent standard the IETF agreed on is basically DNS for agents." DAWN versus agent cards versus AGNTCY directory.
3. "Your KV cache is now a network hop." Time-to-first-token as a storage-fabric and DPU problem.
4. "Training wants elephants, agents send mice, lots of them." One user task equals tens to hundreds of east-west calls; what that does to fabric design and tail latency.
5. "Where does '450% more traffic' come from?" A sceptical read of a single-vendor forecast repeated everywhere.
6. "82% say let the agent change production. Really?" Cisco/Omdia versus EMA, and what the question wording hides.
7. "Level 3.42: how telcos score their own autonomy." Telefonica and TM Forum versus Accenture.
8. "Your interface description is a prompt." LLDP, banners and syslog as injection vectors for NetOps agents.
9. "Agent gateway is the new API gateway, or is it a service mesh?" Where agentgateway, MCP routing headers and IETF DMSC meet.
10. "No confirmed agent-caused network outage yet, and why that should not comfort you." Lessons from Kiro and Replit applied to change control.
11. "Vendors launched agentic NetOps with zero outcome numbers." Compare press releases (Cisco Feb 2026, HPE Jun 2026) against telco-published metrics.
12. "QoS for agents": should agent messages carry priority and latency bounds the network can act on, as the China Mobile/Nokia draft proposes?

### Gaps
- "Under-covered" is my judgement from what searches returned, not a measured content audit of LinkedIn or trade press.
- Angles involving Broadcom, hyperscaler inference fabrics, Arista AVA, Nokia, edge inference and arXiv surveys could not be assessed because no sources were retrieved for them.
