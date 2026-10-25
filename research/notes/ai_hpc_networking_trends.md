# AI and HPC Networking Trends (state as of 2 October 2026)

Reading notes for the writer:
- Window of interest is April-October 2026. Items dated before April 2026 are tagged **[BACKGROUND]**.
- Most facts were extracted from pages via an automated fetch-and-summarise step, so exact figures and quotes should be re-checked against the linked source before being published verbatim. Items I consider shaky are tagged **[VERIFY]**.
- Pages I could not open (HPCwire Cornelis article: 403; Nvidia Q2 FY27 call transcript: 429; an X post on Arista: blocked) are listed under Gaps.

## 1. Scale-out fabric: InfiniBand vs Ethernet, UEC, Spectrum-X/Quantum-X, Broadcom, Arista, Cisco, 800G/1.6T

### Takeaway
Ethernet has won the scale-out share argument (about two-thirds of AI back-end switch sales) but InfiniBand is not dying: its sales tripled in Q1 2026. The fresher story is that AI back-end switch spending overtook the entire front-end data center switch market in Q2 2026, with 800G dominant, 1.6T only sampling, and supply constraints expected to last one to two years or more.

### Cited Findings
Market data
- 3 Sep 2026 (Q2 2026 data): Dell'Oro reports AI back-end network switch sales surpassed front-end network switch sales for the first time, within three years of the back-end market emerging. 800 Gbps made up the vast majority of shipments and revenue; 1.6 Tbps is sampling with ramp expected H2 2026; supply constraints expected for at least 1-2 years. Ethernet AI back-end vendor ranking: Celestica 1st, NVIDIA 2nd, Arista 3rd (would rank closer if deferred revenue were included), Cisco gained the most share. Scale-out and scale-across dominated; scale-up Ethernet "emerging in H2 2026". Quote (Sameh Boujelbene): "AI back-end networks have grown at such a rapid pace that, within just three years of their emergence, spending surpassed that of the large, well-established front-end network market." — [Dell'Oro](https://www.delloro.com/news/ai-back-end-networks-switch-sales-surpass-front-end-networks-for-the-first-time-in-2q2026/)
- 3 Jun 2026 (Q1 2026 data): Ethernet switch sales in AI clusters doubled; Ethernet is about 66% of data center switch sales in AI clusters; InfiniBand switch sales tripled in Q1 2026 (InfiniBand held about 80% of the AI back-end market in 2023). Dell'Oro attributes much of the InfiniBand rebound to brownfield upgrades of the installed base. Dell'Oro projects about $80B of Ethernet switch sales over five years [VERIFY which segment this covers]. Tomahawk Ultra, Tomahawk 6, Edgecore AIS1600-64O, Aria Networks and Lambda are named in the piece. — [SDxCentral](https://www.sdxcentral.com/news/ethernet-dominates-ai-networking-as-switch-sales-double-but-infiniband-rebounds/); related Dell'Oro release: [Dell'Oro](https://www.delloro.com/news/ethernet-extends-lead-in-ai-scale-out-networks-despite-strong-infiniband-rebound/)
- [BACKGROUND] 20 Jan 2026: 650 Group forecasts for 2030: total AI/ML data center networking approaching or exceeding $200B a year; AI scale-out Ethernet over $100B; scale-up switching over $30B (NVLink $25B+, Ethernet scale-up $8B+, PCIe/UALink $3B+); scale-up optics $10B+; pluggable optics plus CPO could exceed 50% of annual switch revenue. — [650 Group](https://650group.com/blog/in-the-ai-era-ethernet-set-to-surge-in-scale-out-and-ramp-in-scale-up/)
- [BACKGROUND] Jan 2026: Ethernet was over two-thirds of AI cluster switch sales in Q3 2025; Spectrum-X grew 760.3% YoY to $1.46B in that quarter; Cisco projected over $3B AI revenue for fiscal 2026; Arista CEO Jayshree Ullal: "Ethernet is always the eventual winner and equalizer." — [Fierce Network](https://www.fierce-network.com/cloud/aristas-ullal-ethernet-eventual-winner-and-equalizer-ai-networking)

Vendors
- Broadcom, fiscal Q3 2026 call, 9 Sep 2026: AI networking revenue up over 2.5x YoY and expected to triple YoY in fiscal Q4; expected to grow as fast as XPUs over the next few years. Tomahawk 6 (102.4T, 200G SerDes) called the fastest ramp of any switch family. Tomahawk 7, described as the first 200 Tbps Ethernet switch, has taped out. Tomahawk Ultra (scale-up Ethernet) deployments begin in fiscal Q3 2026 and expand in fiscal 2027, in both XPU and GPU clusters, with adoption that "surprised us". Optical component capacity (EMLs, VCSELs, CW lasers) more than tripled YoY. — [Motley Fool transcript](https://www.fool.com/earnings/call-transcripts/2026/09/09/broadcom-avgo-q3-2026-earnings-call-transcript/)
- Arista, Q2 2026 call, 4 Aug 2026: revenue $3.0B (+37.7% YoY), first $3B quarter; FY2026 guide raised to $12.6B (about 40% growth); AI fabrics goal at least $3.5B for 2026 [VERIFY: the summary also mentions a $3.6B AI infrastructure target with $1.2B scale-across]; over 100 cumulative Etherlink AI customers versus 4-5 in 2024; $9.7B of multiyear purchase commitments. Ullal on supply: "The industry is going to have a 2-year problem. I don't think we get out of it as an industry until 2028." 1.6T platform (7060XE7 [VERIFY model name]) in trials H2 2026 with "real production still in 2027". On scale-up: "NVIDIA provides full vertical stack usually with NVLink...very little participation from Arista"; the opening is with non-NVIDIA accelerators (AMD, Google TPU). — [Motley Fool transcript](https://www.fool.com/earnings/call-transcripts/2026/08/11/arista-anet-q2-2026-earnings-call-transcript/)
- Cisco (20 Aug 2026 article; products announced Feb 2026 [BACKGROUND]): Silicon One G300 is 102.4 Tbps (512 lanes x 200G) for scale-out, expected to ship broadly before end of 2026; Silicon One P200 is 51.2 Tbps for scale-across, with 28.8T models in Q3 2026 and 51.2T before year end. Broadcom Tomahawk 6 and Nvidia Spectrum-6 are the other 102.4T ASICs. Boujelbene quote: "A company can spend billions on GPUs, but if the fabric cannot deliver predictable bandwidth and low latency, they did not buy an AI supercomputer; they bought an expensive collection of stranded chips." — [Data Center Knowledge](https://www.datacenterknowledge.com/networking/ai-data-center-networking-scaling-up-out-and-across-with-102-4t-ethernet)
- NVIDIA: Spectrum-X Ethernet Photonics (CPO switches, 200G SerDes) announced with Vera Rubin full production on 1 Jun 2026 and reported in full production on 15 Aug 2026 (details in section 3). — [HPCwire/NVIDIA release](https://www.hpcwire.com/off-the-wire/nvidia-vera-rubin-ramps-into-full-production-to-power-agentic-ai-factories-worldwide/); [StorageReview](https://www.storagereview.com/news/nvidia-spectrum-x-ethernet-photonics-enters-full-production-with-4x-fewer-lasers-and-a-five-vendor-cpo-supply-chain)
- [BACKGROUND] 26 Feb 2026: Nvidia networking revenue was $10.98B in the January 2026 quarter, up 263% YoY (CFO: "up more than 3.5x"), over $31B for the fiscal year, driven by NVLink, Spectrum-X and InfiniBand. — [CTech](https://www.calcalistech.com/ctechnews/article/bkyz5ttozg)
- AMD Helios (23 Jul 2026): scale-out uses Pensando Vulcano 800G AI NICs, three per GPU (2.4 Tbps per GPU), with UEC transport; front end uses Pensando Salina 400G DPU. Production now, volume ramp through H2 2026. Soni Jiandani (AMD): "At AI scale, networking is becoming as crucial as GPUs, CPUs, memory and storage." — [Fierce Network](https://www.fierce-network.com/cloud/amds-helios-bets-ai-networking-open-ethernet)

"Scale-across" as a third tier
- Vendors and analysts now routinely describe three planes: scale-up, scale-out, scale-across (between data centers). Cisco P200, Arista's $1.2B scale-across target [VERIFY] and Ciena's OCP 2026 demos all sit here. — [Data Center Knowledge](https://www.datacenterknowledge.com/networking/ai-data-center-networking-scaling-up-out-and-across-with-102-4t-ethernet); [Arista call](https://www.fool.com/earnings/call-transcripts/2026/08/11/arista-anet-q2-2026-earnings-call-transcript/); [Ciena](https://www.ciena.com/about/newsroom/press-releases/ciena-showcases-ai-ready-connectivity-expertise-for-scale-up-scale-out-and-scale-across-connectivity-at-ocp-global-summit-2026)
- 29 Sep 2026: Nvidia is adding a fourth term, "scale-in": bringing users, agents, storage and security controls into the AI factory via BlueField-4 (see section 4). — [SiliconANGLE](https://siliconangle.com/2026/09/29/nvidias-scale-in-play-controlling-agents-is-the-next-infrastructure-priority)

Ultra Ethernet (UEC)
- [BACKGROUND] UEC 1.0 released June 2025; 1.0.1 in September 2025. UET supports up to 1 million hosts; base packet carries 104 bytes of headers. 2026 priorities: Programmable Congestion Management, Congestion Signaling (CSIG), small-message performance (target 50% header reduction), In-Network Collectives. IEEE 802.3dj (200G/lane, 1.6T) targeted for completion late 2026; a 400G/lane project is being initiated. — [Network World, 7 Jan 2026](https://www.networkworld.com/article/4113364/ethernet-groups-keep-2026-focus-on-higher-bandwidth-ai-demands.html)
- A 1.0.2 specification PDF dated January 2026 exists and the UEC site lists 1.0.3 as current; consortium cites 90+ members. — [UEC spec PDF](https://ultraethernet.org/wp-content/uploads/sites/20/2026/01/UE-Specification-1.0.2-1.pdf); [UEC](https://ultraethernet.org/ultra-ethernet-specification-update/)
- [BACKGROUND] 16 Mar 2026 (OFC): Keysight and Broadcom showed what they called the first public UEC interoperability demo of Link Layer Retry and Credit-Based Flow Control at 800GE line rate on Tomahawk Ultra. — [Keysight](https://www.keysight.com/us/en/about/newsroom/news-releases/2026/0316_pr26-051-keysight-advances-ai-networking-with-ultra-ethernet-llr-and-cbfc-interoperability-demonstration-at-ofc-2026.html)
- UEC-capable NICs: AMD Pensando Pollara 400G and Vulcano 800G, Broadcom Thor Ultra 800G (announced 2025 [BACKGROUND]); Vulcano is in the shipping Helios rack. — [StorageReview](https://www.storagereview.com/news/broadcom-thor-ultra-uec-compliant-800g-ai-ethernet-nic-for-100k-xpu-scale-out); [Fierce Network](https://www.fierce-network.com/cloud/amds-helios-bets-ai-networking-open-ethernet)

### Inferences
- "InfiniBand vs Ethernet" as a binary is stale. Better framings with fresh data: (a) back-end has overtaken front-end; (b) InfiniBand tripled while losing share; (c) a white-box ODM (Celestica) leads Ethernet AI back-end revenue ahead of Nvidia, Arista and Cisco.
- 1.6T is slower than headlines suggest: sampling in H1, "ramp H2 2026" per Dell'Oro, but Arista says real production is 2027. 102.4T ASICs are mostly being used for more 800G ports.
- UEC appears to be arriving feature by feature (LLR, CBFC, packet spraying inside vendor products) rather than as a clean "UEC-compliant fabric" switch-over; I found no announcement of a named large production cluster running full UEC transport.
- Supply, not technology, is the binding constraint through 2027-2028 according to both Dell'Oro and Arista.

### Gaps
- Nvidia's networking revenue for fiscal Q2 2027 (reported 26 Aug 2026): transcript returned 429. Search result titles indicate total revenue about $96B and data center about $89B, but no networking figure was retrieved. Sources to check: [Nvidia IR](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-Second-Quarter-Fiscal-2027/default.aspx), [transcript](https://www.fool.com/earnings/call-transcripts/2026/08/31/nvidia-nvda-q2-2027-earnings-call-transcript/).
- No 2026-dated news found on Quantum-X InfiniBand photonics shipments or Broadcom Jericho 4 deployments.
- No UEC 1.1/2.0 release or formal compliance programme launch was found; no named production UEC deployment found.
- Cisco AI order figures for fiscal 2026 actuals not retrieved.

## 2. Scale-up networking inside the rack: NVLink / NVLink Fusion, UALink, ESUN / SUE, CXL

### Takeaway
Scale-up is the most active battleground of 2026: NVLink owns almost all of today's revenue, while the open side has split into UALink (2.0 spec out before 1.0 silicon ships) and Ethernet-based ESUN (1.0 released March 2026, 175+ companies) with Broadcom's Tomahawk Ultra already deploying. AMD's Helios is the first volume non-Nvidia rack with an open scale-up fabric.

### Cited Findings
- 7 Apr 2026: UALink Consortium released the 2.0 specification before any 1.0 silicon shipped. 2.0 adds a separate 200G data link/physical layer spec, in-network compute, a Manageability 1.0 spec (gRPC, YANG, SAI, Redfish) and a chiplet spec. 1.0 silicon: lab samples H2 2026, market in 2027. Consortium chair Kurtis Bowman conceded 1.0 and 2.0 will not be full competitors to Nvidia, with parity expected around 3.0. — [The Register](https://www.theregister.com/2026/04/07/ualink_2_specs/); [UALink PR](https://ualinkconsortium.org/wp-content/uploads/2026/04/UALink-2.0-Specification-PR_FINAL.pdf)
- [BACKGROUND] 10 Mar 2026: OCP released ESUN 1.0 (Ethernet for Scale-Up Networking): lossless Ethernet with link-level retry and congestion management, a 4-byte ESUN header replacing 28-48 byte IP/UDP stacks, and multi-hop scale-up topologies. Meta and Microsoft led it; 12 founders in Oct 2025 (AMD, Arista, Arm, Broadcom, Cisco, HPE Networking, Marvell, Meta, Microsoft, NVIDIA, OpenAI, Oracle); grew to over 175 companies in four months. — [OCP](https://www.opencompute.org/blog/the-ocp-esun-10-specification-has-been-released)
- 31 Aug 2026: The Next Platform (Timothy Prickett Morgan) argues "NVSwitch is the InfiniBand of scale-up": dominant now, likely displaced over time by standards. NVSwitch supports 72 accelerators, up to 576 across two tiers; UALink 1.0 scales to 1,024 accelerators in one tier with about 100 ns port-to-port hop target (InfiniBand is 100-120 ns per hop). Broadcom has left UALink to push ESUN/SUE-T. The author speculates the UALink and ESUN camps could converge. Nvidia holds roughly 95% of GPU revenue and about 75% of combined GPU/XPU revenue. — [The Next Platform](https://www.nextplatform.com/connect/2026/08/31/in-the-long-run-nvidia-nvswitch-is-the-infiniband-of-scale-up-ai-networks/5293474) [VERIFY: the revenue figures my extraction returned for this article were garbled and are omitted here]
- 23 Jul 2026: AMD Helios rack uses "UALink over Ethernet" (first generation) to connect 72 GPUs at 260 TB/s [VERIFY units and wording]. Commitments cited: OpenAI 6 GW, Meta 6 GW (custom GPU), Anthropic up to 2 GW of MI450-series (1 GW in H1 2027), Oracle 50,000 MI450 GPUs from Q3 2026, Microsoft Azure deployment. — [Fierce Network](https://www.fierce-network.com/cloud/amds-helios-bets-ai-networking-open-ethernet)
- 9 Sep 2026: Broadcom says Tomahawk Ultra scale-up Ethernet deployments started in fiscal Q3 2026 in both XPU and GPU clusters. — [Broadcom call](https://www.fool.com/earnings/call-transcripts/2026/09/09/broadcom-avgo-q3-2026-earnings-call-transcript/)
- 14-15 Sep 2026: Cornelis Networks raised about $205M and announced "Active Compute Fabric", moving from HPC scale-out (Omni-Path) into scale-up. It puts programmable compute (RISC-V cores) in NIC and switch to offload collective operations, KV cache acceleration and mixture-of-experts routing, aimed at inference. Supports UALink, ESUN, Ultra Ethernet and Omni-Path. CN5000 shipping; CN6000 (800G) sampling with wider availability Q4 2026. CEO Lisa Spelman cites GPU utilisation of roughly 42-54% and targets a 5-10 point gain. Qualcomm (Tony Pialis) collaborating on validation for rack-scale designs. — [Network World](https://www.networkworld.com/article/4221872/cornelis-lands-205m-to-make-ai-networks-compute-not-just-connect.html); [SDxCentral](https://www.sdxcentral.com/news/cornelis-targets-inference-accelerator-utilization-with-205m-expansion-into-scale-up/); [Converge Digest](https://convergedigest.com/cornelis-active-compute-fabric-scale-up-ai-networking/)
- NVLink Fusion partners listed in a spring 2026 brief: SiFive, AWS (Trainium4), Fujitsu, Qualcomm, Marvell, MediaTek, Astera Labs. UALink hardware "late 2026/early 2027". Scale-up switching forecast $20B by 2030 in this brief (650 Group says over $30B). — [AvidThink/NGI brief](https://cdn.asp.events/CLIENT_Kisaco_R_E0D4AD69_B740_B124_D2ADF5A777880773/sites/AI-Infra-Summit-2026/media/libraries/sponsor-editorial/9372-2026-ngi-data-center-networking-report-rev-a3-1-.pdf); [650 Group](https://650group.com/blog/in-the-ai-era-ethernet-set-to-surge-in-scale-out-and-ramp-in-scale-up/)
- [BACKGROUND] 25 Mar 2026: Dell'Oro after GTC 2026: NVLink expected to extend beyond the rack and eventually into optics; industry moving from 200G toward 400G SerDes on an "aggressive" timeline. — [Dell'Oro](https://www.delloro.com/from-scale-to-optimization-gtc-2026-signals-the-next-phase-of-ai-infrastructure/)
- [BACKGROUND] Upscale AI targeted late 2026 for a UALink switch (Dec 2025). — [HPCwire](https://www.hpcwire.com/2025/12/02/upscale-ai-eyes-late-2026-for-scale-up-ualink-switch/)
- CXL: positioned in 2026 as an inference memory tier rather than a GPU interconnect. CXL Consortium at FMS 2026 (4-6 Aug 2026) pitched memory pooling/sharing and "memory-tiering via KV Cache offloading" to "increase tokens-per-dollar"; 13 member vendors exhibiting (incl. Astera Labs, Marvell, Micron, Samsung, SK hynix). — [CXL Consortium](https://computeexpresslink.org/blog/increase-tokens-per-dollar-with-cxl-at-future-of-memory-and-storage-2026-4762/)
- OCP Global Summit 2026 networking track lists "ESUN 1.0, UALink-SAI, MetaRoCE, optical circuit switching, 102.4T liquid-cooled switching". — [OCP](https://www.opencompute.org/blog/explore-22-tracks-at-the-2026-ocp-global-summit)

### Inferences
- The open scale-up camp is fragmented three ways (UALink, ESUN/SUE-T, and "UALink over Ethernet" hybrids), and Nvidia sits inside ESUN while also licensing NVLink Fusion. That confusion is itself a good explainer topic.
- Ethernet scale-up silicon (Tomahawk Ultra) reached deployment before native UALink silicon, which is still at lab-sample stage. The "spec 2.0 before silicon 1.0" detail is a memorable hook.
- "In-network compute" is a converging idea across UALink 2.0, UEC In-Network Collectives and Cornelis: the network performing reductions, not only moving bytes.

### Gaps
- No verified 2026 shipment dates for UALink switches from Astera Labs, Marvell or Upscale AI were retrieved.
- No hard data on CXL deployment volumes in AI clusters; consortium material is promotional.
- HPCwire's Cornelis article (14 Sep 2026) could not be opened (403): [link](https://www.hpcwire.com/2026/09/14/cornelis-to-build-scale-up-interconnect-with-ualink/). Cornelis investor names not retrieved.
- Nothing 2026-specific found on NVLink 6 technical parameters or Kyber rack interconnect.

## 3. Optics: CPO, LPO, silicon photonics, startups, copper vs optical limits

### Takeaway
2026 is the year CPO moved from demo to production for scale-out switches (Nvidia Spectrum-X Photonics in full production August 2026; Coherent says its CPO scale-out ramp starts Q4 2026), while optics inside the rack for scale-up is still a 2027-2028 story. Copper's reach is collapsing with each speed step (about 1 m passive at 1.6T, under 1 m at 3.2T), which is the physical reason behind all of it.

### Cited Findings
- 15 Aug 2026: Nvidia Spectrum-X Ethernet Photonics reported in full production. Claims: 4x fewer lasers, 5x lower power, 10x higher mean time between incidents versus pluggable-based switches; 200G SerDes. Supply chain of five: TSMC (silicon photonics), SPIL (packaging/test), Lumentum (lasers), TFC Communication (laser module sub-assemblies), Foxconn (system assembly). Early adopters: CoreWeave, Lambda, Oracle Cloud, Microsoft Azure, IBM Cloud, Nebius. — [StorageReview](https://www.storagereview.com/news/nvidia-spectrum-x-ethernet-photonics-enters-full-production-with-4x-fewer-lasers-and-a-five-vendor-cpo-supply-chain)
- 1 Jun 2026: Nvidia's own release claims "5x better power efficiency, 5x longer AI uptime and 1.3x faster time to deployment" for CPO switches versus transceiver-based networks. — [HPCwire/NVIDIA](https://www.hpcwire.com/off-the-wire/nvidia-vera-rubin-ramps-into-full-production-to-power-agentic-ai-factories-worldwide/)
- 21 Sep 2026 (ECOC week): Coherent "PhotonLink" roadmap: CPO for scale-out ramps Q4 2026; CPO for scale-up H2 2027; near-package optics (NPO) H2 2027 with 1.2 pJ/bit demonstrated; chip-to-chip optics 2029-2030. Nvidia is the disclosed anchor CPO customer; over 10 customer engagements. Content about $15,000 per system for 100 Tb of I/O at 200G lanes. InP capacity doubled last year and will double again. TAM: $60B existing plus $30B integrated optics = $90B by 2030. — [Investing.com transcript](https://www.investing.com/news/transcripts/coherent-at-ecoc-2026-pushes-fullstack-optics-for-ai-data-centers-93CH-4909486)
- 20 Sep 2026: Marvell at ECOC 2026 (20-24 Sep, Málaga): first 2nm 400G/lane optical PAM4 demo; 2nm 1.6T ZR coherent and 1.6T coherent-lite O-band; 2nm 800G ZR/ZR+ with MACsec; a 102.4T CPO platform at 200G/lane; 38 demos; 3.2T named as the next target. — [Marvell](https://www.marvell.com/company/newsroom/marvell-industry-first-2nm-optical-technology-ai-data-center-infrastructure-ecoc-2026.html)
- 30 Sep 2026: CScale raised a $145M Series C ($188M total) to replace copper with optics inside AI racks (scale-up layer). Co-leads Atreides, Valor, Premji Invest; new strategic investors Nvidia and Intel Capital. Founded 2023; CEO Martin Lund (ex-Broadcom). Commercial chips targeted for 2028. — [Tech Insider](https://tech-insider.org/cscale-145-million-ai-optical-networking-nvidia-intel-2026) [VERIFY: single secondary source]
- 1 Oct 2026: Ciena's OCP 2026 line-up: Vesta 200 6.4T "CPX" optical engine scaling to 200T with "up to 70% power reduction"; Nitro 2004 linear redriver extending DAC copper reach to up to 4 m; liquid-cooled 12.8T XPO modules; RLS Hyper-Rail with "32x density improvement". — [Ciena](https://www.ciena.com/about/newsroom/press-releases/ciena-showcases-ai-ready-connectivity-expertise-for-scale-up-scale-out-and-scale-across-connectivity-at-ocp-global-summit-2026)
- Spring 2026 AvidThink brief, copper reach: 800G is 2-3 m passive DAC, 3-7 m active; 1.6T about 1 m passive, 2-3 m active; 3.2T under 1 m practical. Energy per bit: passive DAC 0.1-0.3 pJ/bit; active electrical cable 10-13; DSP pluggable optics 15-25; LPO 10-13; NPO 4-8 (target); CPO 5-6. Meta validated CPO over "1 million link-hours" with zero link flaps and about 65% power reduction versus pluggables; Broadcom TH6 CPO "70% reduction in optical interconnect power". LPO 800G modules shipped September 2025 and are projected in over one-third of 2026-2027 intra-data-center 800G deployments. Avicena microLED: under 1 pJ/bit, 10-20 m reach. 1.6T modules draw nearly double the power of 800G modules. — [AvidThink/NGI brief](https://cdn.asp.events/CLIENT_Kisaco_R_E0D4AD69_B740_B124_D2ADF5A777880773/sites/AI-Infra-Summit-2026/media/libraries/sponsor-editorial/9372-2026-ngi-data-center-networking-report-rev-a3-1-.pdf); [summary page](https://nextgeninfra.io/2026-dcnetwork/)
- Hot Interconnects 2026 (19-21 Aug) included Lightmatter (Nick Harris) on BiDi DWDM interconnect and a paper "Scaling Inference Prefill with High-Radix Photonic Interconnect". — [HOTI programme](https://hoti.org/2026/program.html)
- OCP 2026 Photonics track covers "XPO, NPO and CPO architectures" plus a Short Reach Optical Interconnect track. — [OCP](https://www.opencompute.org/blog/explore-22-tracks-at-the-2026-ocp-global-summit)
- Opinion headline: "All AI data center interconnects will be optical within 5 years". — [Semiconductor Engineering](https://semiengineering.com/all-ai-data-center-interconnects-will-be-optical-within-5-years/) (not opened; date unverified)

### Inferences
- The optics vocabulary has multiplied (CPO, NPO, LPO, XPO, CPX, coherent-lite, microLED). A plain-language "who sits where between the chip and the faceplate" explainer is missing in mainstream coverage.
- Copper is being defended as well as replaced: redrivers and active cables (Ciena's 4 m DAC claim) extend it, and passive copper remains 30-100x more energy-efficient per bit than any optic. "Copper where you can, optics where you must" still holds inside the rack until about 2027-2028.
- Lasers and InP capacity are a supply-chain story of their own (Coherent doubling twice, Broadcom tripling), tying optics to the broader "supply constrained until 2028" theme.
- Nvidia investing in a scale-up optics startup (CScale) while Coherent names Nvidia as anchor CPO customer suggests optical NVLink is on the roadmap; this is inference, consistent with Dell'Oro's GTC commentary.

### Gaps
- No 2026 deployment numbers found for Broadcom's CPO switches (Bailly/Davisson) or Quantum-X Photonics InfiniBand.
- Status of Ayar Labs, Lightmatter products and Marvell/Celestial AI in H2 2026 not retrieved.
- LPO at 1.6T: no dated 2026 milestone found.
- Vendor power/reliability claims (5x, 10x, 70%) are self-reported; no independent measurements found.

## 4. DPUs / SmartNICs and inference/agentic workloads

### Takeaway
The DPU has been repositioned from "cloud tenant isolation card" to the control and storage plane for agentic inference: Nvidia's BlueField-4 underpins a KV-cache/context-memory storage tier (STX/CMX, products due late 2026) and, as of late September 2026, a security story Nvidia calls "scale-in". AMD answers with Pensando Salina and Vulcano in Helios; I found little fresh Intel IPU news.

### Cited Findings
- 29 Sep 2026: Nvidia frames "scale-in" as a fourth dimension after scale-up/out/across: bringing users, agents, storage and compute into the AI factory with security controls enforced on BlueField-4, out-of-band from the workload. BlueField-4 combines a ConnectX-9 SuperNIC with a Grace CPU; DOCA is positioned as the "CUDA of DPUs"; OpenShell (v0.1.0) is an open-source agent runtime for permissions and sandboxing. Gilad Shainer: "agent is not just one inference call. There are many inference calls" and "You cannot count on an agent to contain itself." The article cites "7.2 terabits of secure traffic" versus 400G previously [VERIFY meaning]. Author (Dave Vellante) notes performance under load, lock-in and portability remain unproven. — [SiliconANGLE](https://siliconangle.com/2026/09/29/nvidias-scale-in-play-controlling-agents-is-the-next-infrastructure-priority)
- 1 Jun 2026: BlueField-4 in Vera Rubin provides multi-tenant isolation, zero-trust enforcement, runtime threat detection and encryption at up to 800 Gb/s (BlueField-4 "ASTRA"). — [HPCwire/NVIDIA](https://www.hpcwire.com/off-the-wire/nvidia-vera-rubin-ramps-into-full-production-to-power-agentic-ai-factories-worldwide/)
- [BACKGROUND] 16 Mar 2026 (GTC): BlueField-4 STX storage architecture for agentic inference. It moves KV cache to an accelerated storage tier reached by RDMA over Spectrum-X, bypassing the host CPU. Nvidia claims 5x token throughput, 4x power efficiency and 2x page ingestion versus CPU-based storage. CMX context memory storage is the first rack-scale STX implementation. Partners: DDN, Dell, HPE, IBM, NetApp, VAST Data; AIC, Supermicro, QCT; adopters CoreWeave, Lambda, Mistral AI, Oracle. Partner products expected late 2026. — [3DTested](https://www.3dtested.com/tech-industry/nvidia-launches-bluefield-4-stx-storage-architecture-for-agentic-ai) [VERIFY against Nvidia primary]; related [BACKGROUND, Jan 2026 CES] [VAST Data](https://www.vastdata.com/press-releases/vast-data-brings-context-memory-to-agentic-ai-bluefield-4)
- [BACKGROUND] 25 Mar 2026: Dell'Oro projects the SmartNIC/DPU market to grow at 30% CAGR over five years, with BlueField expanding into data movement between compute, storage and CPU domains. — [Dell'Oro](https://www.delloro.com/from-scale-to-optimization-gtc-2026-signals-the-next-phase-of-ai-infrastructure/)
- 23 Jul 2026: AMD Helios uses Pensando Salina (3rd-gen DPU, 400G) for front-end SDN, security and storage offload, and Vulcano (800G) AI NICs for scale-out. — [Fierce Network](https://www.fierce-network.com/cloud/amds-helios-bets-ai-networking-open-ethernet)
- Sep 2026: Cornelis targets KV cache acceleration and mixture-of-experts routing with compute inside NIC and switch. — [Network World](https://www.networkworld.com/article/4221872/cornelis-lands-205m-to-make-ai-networks-compute-not-just-connect.html)
- Aug 2026: CXL Consortium pitches KV-cache offload to CXL memory tiers. — [CXL Consortium](https://computeexpresslink.org/blog/increase-tokens-per-dollar-with-cxl-at-future-of-memory-and-storage-2026-4762/)

### Inferences
- Three different layers are now competing to hold the KV cache/context for long-running agents: DPU-fronted flash (Nvidia STX/CMX), CXL memory, and smart fabric (Cornelis). "Where does an agent's memory live?" links networking to something a general audience already cares about.
- Inference changes traffic shape: many small, latency-sensitive calls per agent rather than a few elephant flows. This is why small-message efficiency (ESUN's 4-byte header, UEC's header reduction work) keeps appearing.
- Late 2026 is when STX/CMX partner products are due, so SC26 is a natural moment to check which shipped.

### Gaps
- No 2026 news found on Intel IPU (E2100/E2200) in AI clusters; treat Intel's role as unknown rather than absent.
- No independent benchmarks of BlueField-4 STX claims, nor measured overhead of DPU-enforced agent security.
- Hyperscaler in-house DPUs (AWS Nitro, Google, Microsoft) in AI clusters not researched.

## 5. How networking limits AI cluster performance: concrete numbers

### Takeaway
The most quotable framing: networking is roughly 10% of AI infrastructure spend but is blamed for a large share of deployment pain and idle GPUs, with realised utilisation commonly cited at 30-55%. Most of these figures originate with vendors or vendor-sponsored briefs, so they should be attributed, not stated as fact.

### Cited Findings
- Spring 2026: interconnect is about 10% of AI infrastructure spend but accounts for roughly 80% of deployment challenges and idle GPU resources; training clusters typically run at 30-50% efficiency; racks at 150-300 kW; clusters beyond 100,000 XPUs. — [NextGenInfra/AvidThink](https://nextgeninfra.io/2026-dcnetwork/)
- Same brief: Model FLOPs Utilisation "35-40% in many deployments"; Meta's Llama 3 training saw "over 400 interruptions in just 54 days"; Alibaba found 43 of 107 jobs affected by congestion-related communication failures; AI infrastructure spending "$630 billion in 2026". — [AvidThink brief PDF](https://cdn.asp.events/CLIENT_Kisaco_R_E0D4AD69_B740_B124_D2ADF5A777880773/sites/AI-Infra-Summit-2026/media/libraries/sponsor-editorial/9372-2026-ngi-data-center-networking-report-rev-a3-1-.pdf) [VERIFY original studies]
- Sep 2026: Cornelis cites current GPU utilisation of about 42-54% and targets a 5-10 point gain. — [Network World](https://www.networkworld.com/article/4221872/cornelis-lands-205m-to-make-ai-networks-compute-not-just-connect.html). SDxCentral's write-up carries figures of $1.68B a year in wasted capacity and 500 GWh a year (about 48,000 US homes) from idling hardware, basis not stated. — [SDxCentral](https://www.sdxcentral.com/news/cornelis-targets-inference-accelerator-utilization-with-205m-expansion-into-scale-up/) [VERIFY]
- 4 Jun 2026: DriveNets CEO Ido Susan: "every percentage point of utilization translates into hundreds of millions of dollars"; the piece is opinion without data. — [DriveNets](https://drivenets.com/blog/the-most-expensive-idle-asset-in-the-world-right-now-is-a-gpu-waiting-on-the-network/)
- [BACKGROUND] 28 Aug 2025: Jensen Huang argued the right network lifts AI factory efficiency from about 65% to 85-90%, which "effectively makes networking free" against a $50B AI factory. — [SDxCentral](https://www.sdxcentral.com/news/nvidia-networking-is-booming-but-your-networks-cost-nothing/)
- Power: 1.6T modules use nearly double the power of 800G; DSP pluggables 15-25 pJ/bit vs CPO 5-6 pJ/bit. — [AvidThink brief PDF](https://cdn.asp.events/CLIENT_Kisaco_R_E0D4AD69_B740_B124_D2ADF5A777880773/sites/AI-Infra-Summit-2026/media/libraries/sponsor-editorial/9372-2026-ngi-data-center-networking-report-rev-a3-1-.pdf)
- Reliability: Nvidia claims 10x higher mean time between incidents (or "5x longer AI uptime") from removing pluggables. — [StorageReview](https://www.storagereview.com/news/nvidia-spectrum-x-ethernet-photonics-enters-full-production-with-4x-fewer-lasers-and-a-five-vendor-cpo-supply-chain); [HPCwire/NVIDIA](https://www.hpcwire.com/off-the-wire/nvidia-vera-rubin-ramps-into-full-production-to-power-agentic-ai-factories-worldwide/)
- Tail latency: UEC Link Layer Retry "enables local error recovery and reduces tail latency" (no figure given). — [Keysight](https://www.keysight.com/us/en/about/newsroom/news-releases/2026/0316_pr26-051-keysight-advances-ai-networking-with-ultra-ethernet-llr-and-cbfc-interoperability-demonstration-at-ofc-2026.html)
- Bandwidth per accelerator: AMD Helios gives each GPU 3 x 800G = 2.4 Tbps of scale-out. — [Fierce Network](https://www.fierce-network.com/cloud/amds-helios-bets-ai-networking-open-ethernet)
- Time synchronisation is now treated as an AI-cluster issue: OCP Time Appliances track lists "clock-aligned telemetry", PTP and NIC timing recovery; the NGI brief cites nanosecond clock sync as a utilisation lever. — [OCP](https://www.opencompute.org/blog/explore-22-tracks-at-the-2026-ocp-global-summit); [NextGenInfra](https://nextgeninfra.io/2026-dcnetwork/)

### Inferences
- "10% of the cost, most of the idle time" plus Huang's "networking is free" gives a simple economic argument: a few points of utilisation on a multi-billion-dollar cluster outweigh the whole network bill.
- Link flaps and optics failures (reliability) are as large a part of the story as congestion; with hundreds of thousands of optical links, one flap can stall a synchronous training job. This is under-explained relative to throughput.
- Utilisation figures differ by definition (MFU vs GPU-busy vs "efficiency"), so 30-50%, 35-40% and 42-54% are not directly comparable.

### Gaps
- No independent, 2026-dated measurement of job completion time or tail latency (e.g. p99 with numbers) comparing InfiniBand, Spectrum-X and UEC fabrics was found.
- No authoritative 2026 figure for networking's share of AI factory capex beyond the "about 10%" in a sponsored brief; analysts' paid reports may hold it.
- The Meta and Alibaba statistics are second-hand via the brief; original papers not checked.

## 6. Saturated vs under-covered topics

### Takeaway
This is my assessment from what dominated search results versus what appeared only in specialist sources; it is judgement, not measured coverage volume.

### Cited Findings
Heavily covered (many near-identical articles surfaced)
- "Ethernet is beating InfiniBand" share narrative. — [SDxCentral](https://www.sdxcentral.com/news/ethernet-dominates-ai-networking-as-switch-sales-double-but-infiniband-rebounds/); [Fierce Network](https://www.fierce-network.com/cloud/aristas-ullal-ethernet-eventual-winner-and-equalizer-ai-networking); [Lightwave](https://www.lightwaveonline.com/home/article/55315256/ethernet-maintains-a-lead-over-infiniband-in-the-ai-race)
- "UALink vs NVLink" explainers and CPO market forecasts/stock pieces. — [The Register](https://www.theregister.com/2026/04/07/ualink_2_specs/); [GlobeNewswire CPO report](https://www.globenewswire.com/news-release/2026/08/17/3346232/0/en/co-packaged-optics-in-the-ai-data-center-10-year-market-forecast-and-strategic-analysis-evaluating-silicon-photonics-switch-asics-and-strategies-of-nvidia-broadcom-intel-and-marvel.html)
- Vendor earnings and "AI networking revenue" figures (Broadcom, Arista, Nvidia). — [Broadcom call](https://www.fool.com/earnings/call-transcripts/2026/09/09/broadcom-avgo-q3-2026-earnings-call-transcript/); [Arista call](https://www.fool.com/earnings/call-transcripts/2026/08/11/arista-anet-q2-2026-earnings-call-transcript/)

Appeared only in specialist or single sources
- Back-end overtaking front-end switching (one Dell'Oro release, 3 Sep 2026). — [Dell'Oro](https://www.delloro.com/news/ai-back-end-networks-switch-sales-surpass-front-end-networks-for-the-first-time-in-2q2026/)
- InfiniBand tripling via brownfield upgrades. — [SDxCentral](https://www.sdxcentral.com/news/ethernet-dominates-ai-networking-as-switch-sales-double-but-infiniband-rebounds/)
- Celestica leading Ethernet AI back-end revenue. — [Dell'Oro](https://www.delloro.com/news/ai-back-end-networks-switch-sales-surpass-front-end-networks-for-the-first-time-in-2q2026/)
- ESUN versus UALink versus SUE-T relationship, and Broadcom leaving UALink. — [The Next Platform](https://www.nextplatform.com/connect/2026/08/31/in-the-long-run-nvidia-nvswitch-is-the-infiniband-of-scale-up-ai-networks/5293474); [OCP](https://www.opencompute.org/blog/the-ocp-esun-10-specification-has-been-released)
- "Scale-in" and DPU-enforced agent security (one analyst piece, 29 Sep 2026). — [SiliconANGLE](https://siliconangle.com/2026/09/29/nvidias-scale-in-play-controlling-agents-is-the-next-infrastructure-priority)
- In-network compute/collectives. — [The Register](https://www.theregister.com/2026/04/07/ualink_2_specs/); [Network World](https://www.networkworld.com/article/4113364/ethernet-groups-keep-2026-focus-on-higher-bandwidth-ai-demands.html); [Network World on Cornelis](https://www.networkworld.com/article/4221872/cornelis-lands-205m-to-make-ai-networks-compute-not-just-connect.html)
- Copper reach numbers per speed and pJ/bit comparisons. — [AvidThink brief PDF](https://cdn.asp.events/CLIENT_Kisaco_R_E0D4AD69_B740_B124_D2ADF5A777880773/sites/AI-Infra-Summit-2026/media/libraries/sponsor-editorial/9372-2026-ngi-data-center-networking-report-rev-a3-1-.pdf)
- Time synchronisation and telemetry in AI clusters. — [OCP](https://www.opencompute.org/blog/explore-22-tracks-at-the-2026-ocp-global-summit)
- Supply constraints lasting to 2028. — [Arista call](https://www.fool.com/earnings/call-transcripts/2026/08/11/arista-anet-q2-2026-earnings-call-transcript/)

### Inferences
Candidate post angles that are timely and less crowded:
1. "The back-end just overtook the front-end": what a back-end network is and why it outgrew a decades-old market in three years.
2. "Scale-up, scale-out, scale-across, and now scale-in": a four-term glossary in plain language.
3. "UALink published version 2.0 before version 1.0 chips exist": the standards race against NVLink, and why Ethernet (ESUN, Tomahawk Ultra) got to deployment first.
4. "Why your GPU is idle half the time": 10% of spend vs most of the idle time; attribute numbers carefully.
5. "Copper's shrinking leash": 3 m, 1 m, under 1 m, and what CPO/NPO/LPO each mean.
6. "Where does an AI agent's memory live?": KV cache on DPU-fronted flash vs CXL vs smart fabric.
7. "The network that computes": in-network collectives in UALink 2.0, UEC and Cornelis.
8. "InfiniBand tripled while losing": nuance on a story usually told as a knockout.
9. "The supply chain behind a co-packaged switch": five vendors, lasers and InP as bottleneck.
10. "The biggest Ethernet AI switch vendor is a contract manufacturer": Celestica and white boxes.
11. "One flapping link can stall a training run": reliability, not speed, as the CPO argument.
- Poorly explained for general readers: the difference between scale-up and scale-out; why lossless matters; what a DPU is; optics acronyms; utilisation metric definitions.

### Gaps
- No quantitative measure of coverage volume was made; "saturated" is a qualitative judgement from search results.
- LinkedIn-specific engagement on these topics was not researched.

## 7. Upcoming and recent events as timely hooks

### Takeaway
The strongest near-term hooks are OCP Global Summit (mid-October 2026, San Jose) and SC26 (15-20 November 2026, Chicago); ECOC, Hot Interconnects and AI Infra Summit have just passed and supply fresh material.

### Cited Findings
- OCP Global Summit 2026: San Jose, 12-15 Oct 2026 per OCP's blog (Ciena's release says 13-15 Oct; the earlier day is likely co-located workshops). 22 tracks; Networking track covers ESUN 1.0, UALink-SAI, MetaRoCE, optical circuit switching, 102.4T liquid-cooled switching; Photonics track covers XPO/NPO/CPO; also Short Reach Optical Interconnect, Time Appliances, and AI Clusters (800G/1.6T). — [OCP](https://www.opencompute.org/blog/explore-22-tracks-at-the-2026-ocp-global-summit); [Ciena](https://www.ciena.com/about/newsroom/press-releases/ciena-showcases-ai-ready-connectivity-expertise-for-scale-up-scale-out-and-scale-across-connectivity-at-ocp-global-summit-2026)
- SC26: 15-20 Nov 2026, McCormick Place, Chicago. — [Choose Chicago](https://www.choosechicago.com/meetings/sc26/); [SC26 site](https://sc26.supercomputing.org/2026/07/ready-set-sprints/)
- Hot Interconnects 2026 (past): 19-21 Aug 2026, virtual. Keynotes: Omar Baldonado (Meta) "Lessons from networking Meta's gigawatt-scale AI fleet"; Gilad Shainer (NVIDIA) "Networking Innovations for Gigascale AI Systems"; Bilal Riaz (Ciena) on open AI interconnects. Papers include "Breaking Through the Network Wall: Petabit-Class Switching for Single-Hop MoE Training". Sponsor talks from Lightmatter, Broadcom (Mohan Kalkunte), Cisco (Will Eatherton). Panel on scale-up/out/across at the edge. — [HOTI programme](https://hoti.org/2026/program.html)
- ECOC 2026 (past): 20-24 Sep 2026, Málaga. — [Marvell](https://www.marvell.com/company/newsroom/marvell-industry-first-2nm-optical-technology-ai-data-center-infrastructure-ecoc-2026.html)
- AI Infra Summit 2026 (past): Cornelis/Qualcomm keynote on 15 Sep 2026. — [Converge Digest](https://convergedigest.com/cornelis-active-compute-fabric-scale-up-ai-networking/)
- Product milestones due in Q4 2026 that can be checked at those events: 1.6T ramp (Dell'Oro), Cisco G300 broad shipment, Cornelis CN6000 availability, Coherent CPO scale-out ramp, BlueField-4 STX partner systems, UALink 1.0 lab samples, IEEE 802.3dj completion, Vera Rubin shipments ("fall 2026"). — [Dell'Oro](https://www.delloro.com/news/ai-back-end-networks-switch-sales-surpass-front-end-networks-for-the-first-time-in-2q2026/); [Data Center Knowledge](https://www.datacenterknowledge.com/networking/ai-data-center-networking-scaling-up-out-and-across-with-102-4t-ethernet); [Converge Digest](https://convergedigest.com/cornelis-active-compute-fabric-scale-up-ai-networking/); [Coherent](https://www.investing.com/news/transcripts/coherent-at-ecoc-2026-pushes-fullstack-optics-for-ai-data-centers-93CH-4909486); [3DTested](https://www.3dtested.com/tech-industry/nvidia-launches-bluefield-4-stx-storage-architecture-for-agentic-ai); [The Register](https://www.theregister.com/2026/04/07/ualink_2_specs/); [Network World](https://www.networkworld.com/article/4113364/ethernet-groups-keep-2026-focus-on-higher-bandwidth-ai-demands.html); [StorageReview](https://www.storagereview.com/news/nvidia-spectrum-x-ethernet-photonics-enters-full-production-with-4x-fewer-lasers-and-a-five-vendor-cpo-supply-chain)

### Inferences
- A "what to watch at OCP" post in the first half of October and a "did 2026's promises ship?" scorecard around SC26 are natural formats.
- Meta's Hot Interconnects keynote on a gigawatt-scale fleet is a likely source of operator-side numbers, more credible than vendor claims, if a recording is available.

### Gaps
- No dates found for an autumn 2026 NVIDIA GTC (e.g. GTC DC/Europe); GTC 2026 in March is background. Not confirmed either way.
- SC26 networking-specific programme (SCinet capacity, TOP500 interconnect share) not yet published or not retrieved.
- UEC Member Summit 2026 exists on the UEC events page but its date was not retrieved: [UEC](https://ultraethernet.org/event/ultra-ethernet-consortium-member-summit-2026/).
