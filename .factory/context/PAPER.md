# CodeCanvas: Visual Scratchpads for Architectural Reasoning

**Ainesh Chatterjee &nbsp;&nbsp; Navya Khurana &nbsp;&nbsp; Eric Wang**

*University of Maryland, College Park*

## Abstract

Large language models achieve remarkable success at local code editing yet struggle with repository-scale architectural reasoning. Current approaches use symbolic graphs or disjoint snippets without the global, manipulable representation developers naturally form. We introduce Code Maps as Working Memory, a multimodal approach treating repository structure as a visual canvas for agent reasoning. Our system combines three innovations: (1) semantic-structural codemaps via UMAP projection and Leiden clustering, (2) integration with MemGPT-style memory blocks for persistent architectural understanding, and (3) visual scratchpads enabling reasoning through rendered maps with overlays. We evaluate against text-only and graph baselines on architectural violation detection and TerminalBench tasks. We hypothesize visual working memory enables direct architectural reasoning, with agents identifying violations by observing long edges crossing cluster boundaries. This work bridges visual reasoning, memory architectures, and code understanding to address limitations in current LLM-based software tools.

## 1. Introduction

Large language models have significantly improved code generation and editing, with recent models like Claude Haiku 4.5 achieving 73.3% accuracy on SWE-bench Verified [8] at a fraction of the cost of larger models. However, these impressive local editing capabilities mask a persistent challenge: when tasked with understanding or modifying repository-scale architecture, even state-of-the-art models struggle to maintain a coherent global view of the codebase.

Human developers approach new codebases by forming a mental map of the system—routing logic in one region, the database layer in another, with problematic couplings visualized as tangled connections. This spatial-semantic representation serves as persistent working memory, continuously updated during exploration.

Current approaches to repository-level understanding fall into two categories, neither of which captures this essential aspect of human reasoning. Graph-augmented systems like RepoGraph [13] and LocAgent [18] build sophisticated dependency graphs and expose them through symbolic queries, achieving state-of-the-art results on benchmarks. However, the graph remains hidden machinery—the model can query it but cannot "see" or manipulate it as a coherent whole. Meanwhile, recent work on visual scratchpads [5, 12, 24] has shown that forcing models to externalize reasoning through diagrams improves performance by 12.7% on mathematical tasks, yet none of these systems target code architecture.

**Our Approach.** We propose Code Maps as Working Memory, a multimodal system that gives LLM agents a persistent, visual representation of repository architecture that they can both perceive and actively manipulate. Our key insight is that by combining three existing threads—repository graphs, visual scratchpads, and explicit memory architectures—we can create a new interaction pattern for code understanding.

Specifically, we construct a codemap by: (1) parsing a repository into a dependency graph using Tree-sitter, (2) embedding code entities and projecting them to 2D using UMAP, (3) identifying semantic clusters via Leiden community detection, and (4) rendering this as a 1024×1024 PNG with visual encodings (size for centrality, color for clusters, edges for dependencies). This map becomes the centerpiece of a MemGPT-style [6, 14] memory architecture where agents maintain synchronized textual notes about their understanding of the architecture, query the underlying graph symbolically, and crucially, re-render the map with overlays to highlight suspected problems or planned changes.

**Contributions.** Our work makes three primary contributions:

1. **A visual working memory for code:** We in-
   troduce a system that treats repository structure as a visual canvas for agent reasoning, bridging symbolic and perceptual representations.

2. **Integration with memory architectures:** We show how to incorporate visual artifacts into MemGPT-style memory blocks, creating a multimodal memory system where text and images reinforce each other.

3. **Architecture-centric evaluation:** We propose evaluation tasks focused on architectural violations and cross-layer dependencies—phenomena that visual maps make salient—complementing existing patch-oriented benchmarks.

We hypothesize that agents with visual working memory will identify problems more directly by visually detecting long edges crossing cluster boundaries, providing clearer explanations grounded in spatial metaphors that align with how human developers naturally reason about code architecture.

## 2. Related Work

Our work builds on three distinct research threads: repository-scale code understanding, visual reasoning with scratchpads, and memory architectures for agents. We position our contribution at the intersection of these areas.

### 2.1. Graph-Augmented Code Understanding and Visualization

Recent advances in repository-level understanding have focused on augmenting LLMs with graph structures. Systems like RepoGraph [13] (k-hop ego-graphs), LocAgent [18] (graph-guided agents), CGM [19] (graph-integrated attention), GraphCoder [22] and GRACE [21] (hybrid retrieval), and RPG [9] (planning graphs) demonstrate consistent improvements but treat graphs as hidden symbolic backends. The software engineering community has long used visual representations like CodeCity [23] (3D metaphors) and Dependency Structure Matrices [3] for manual inspection, while GraphRAG [15] applies clustering to knowledge graphs. Our departure is making repository structure a persistent visual artifact that models can perceive and manipulate directly, bridging symbolic and perceptual representations.

### 2.2. Visual Scratchpads and Diagrammatic Reasoning

A parallel thread of research has demonstrated the power of visual externalization for reasoning. Whiteboard-of-Thought [12] shows that having models generate and consult diagrams improves multi-step reasoning, while Visual Sketchpad [5] provides explicit drawing tools that achieve 12.7% improvement on math tasks and 8.6% on vision tasks. Latent Sketchpad [24] takes a different approach, training models to produce visual latents alongside text, demonstrating comparable or superior performance across multiple MLLMs including Gemma3 and Qwen2.5-VL. The success of these methods on mathematical and spatial reasoning tasks strongly suggests that visual externalization could benefit code understanding. However, none of these systems target software architecture. Recent benchmarks like MIRA [26] explicitly test scenarios where intermediate visuals are necessary, showing strong gains when models generate and use images mid-reasoning. We adapt these insights to code, using repository structure as the "diagram" that models iteratively render and reason over.

### 2.3. Memory Architectures for Agents

MemGPT [14] introduced hierarchical memory with self-editing tools, treating memory management as an explicit capability rather than an implicit feature. Letta [6] operationalizes this with "memory blocks"—labeled, always-visible working zones that agents control through natural language. These blocks (task state, working notes, archival facts) provide structure for long-running interactions.

Evaluations like LoCoMo [10] expose the limits of current long-horizon memory, while systems like MemInsight [16] and HiAgent [25] explore multi-level indexing and agent-managed chunking. Reflexion [17] and its successors show that inference-time reflection with episodic memory improves multi-step decision-making.

Our contribution is adding a first-class visual memory block—the codemap image with synchronized textual notes—to this architecture. This creates a multimodal working memory where visual and textual representations reinforce each other, anchored in a consistent spatial representation of the codebase.

Our work bridges three previously disconnected areas: repository graphs, visual scratchpads, and explicit memory architectures. Table 1 summarizes how we combine persistent visual working memory with graph structures and multimodal memory blocks, positioning repository understanding to benefit from visual externalization proven effective in other reasoning domains.
**Table 1.** Comparison with representative approaches

| Approach | Graph | Visual | Memory |
|----------|-------|--------|--------|
| RepoGraph [13] | Symbolic | – | Traces |
| Visual Sketchpad [5] | – | Dynamic | Transient |
| MemGPT [14] | – | – | Hierarchical |
| Ours | Both | Persistent | Multimodal |

## 3. Approach

### 3.1. Problem Formulation

Given a code repository $R$ consisting of source files $\{f_1, f_2, ..., f_n\}$, we aim to enable agents to perform architectural reasoning tasks that require global understanding. Specifically, we focus on violation detection (identifying dependencies that violate architectural layers), impact analysis (predicting affected modules), and refactoring planning (suggesting improvements based on coupling patterns). Unlike local tasks, these require understanding relationships across the entire codebase—precisely where current LLMs struggle despite strong performance on patch-oriented benchmarks.

### 3.2. Codemap Construction

**Graph Extraction.** We parse the repository using Tree-sitter to build a directed graph $G = (V, E)$ where:

- **Vertices $V$:** Files, classes, and top-level functions
- **Edges $E$:** Three types—import (module dependencies), call (function invocations), and contain (structural nesting)

This lightweight schema balances expressiveness with visual clarity, avoiding the complexity of full program dependence graphs while capturing essential architectural relationships.

**Semantic Embedding.** For each vertex $v \in V$, we compute an embedding $e_v \in \mathbb{R}^d$ using a pretrained code encoder (CodeBERT [4] or similar). To maintain tractable input lengths, we use:

$$e_v = \text{Encode}(\text{signature}(v) \oplus \text{docstring}(v) \oplus \text{context}(v))$$

where $\text{context}(v)$ includes the first 10 lines of implementation and immediate structural context.

**Spatial Projection.** We project embeddings to 2D coordinates using UMAP [11] with parameters tuned for stability:

$$x_v = \text{UMAP}(e_v; n = 15, d = 0.1, s = 42)$$

where $n$ is n_neighbors, $d$ is min_dist, and $s$ is the random seed. The fixed seed ensures deterministic layouts across runs, critical for agents to develop consistent spatial mental models.

**Community Detection.** We apply Leiden clustering [20] on $G$ to identify semantic modules:

$$C = \text{Leiden}(G, \gamma = 1.0)$$

where $\gamma$ controls granularity. These communities typically correspond to architectural layers (e.g., controllers, models, utilities).

**Visual Encoding.** We render a 1024×1024 PNG using the following scheme:

- **Position:** UMAP coordinates $x_v$
- **Size:** $\propto \log(1 + \text{degree}(v))$ to emphasize hubs
- **Color:** Categorical palette by cluster $C(v)$
- **Edges:** Bezier curves with opacity $\alpha = \exp(-d_{ij}/\bar{d})$ where $d_{ij}$ is Euclidean distance

This encoding is designed to prioritize architectural salience: cluster boundaries are intended to reveal layer separation, long edges to highlight potential violations, and node size to emphasize critical components.

### 3.3. Memory Architecture

Following MemGPT [14] and Letta [6], we structure agent memory hierarchically:

**Core Memory (Always in Context).**

1. **Task Block:** Current objective (1-3 sentences)
2. **Map Notes:** Bulleted observations about the codemap
   ```
   - Cluster C1 (blue): HTTP handlers
   - Cluster C2 (green): Database models
   - Long edge: api/routes.py -> db/models.py
     (potential violation)
   ```
3. **Structural Facts:** Stable architectural insights
   ```
   - Three-layer architecture: API/Business/Data
   - Central hub: services/auth.py (degree=47)
   ```

**Archival Memory (External Storage).**

- Graph database with full $G = (V, E)$ and embeddings
- Episode log of past analyses for this repository
- Rendered map cache with different views/overlays
### 3.4. Agent Tools and Interaction

We provide four tools that agents invoke through function calling: (1) **graph_query** for symbolic graph operations (k-hop neighbors, inter-cluster edges), (2) **render_map** for visualization with overlays and zoom, (3) **update_notes** to append observations to working memory, and (4) **summarize_state** to condense notes into structural facts.

### 3.5. Agent Configurations

We evaluate three agent configurations to isolate the impact of visual working memory:

**Text-Only Agent.** Has access to standard file operations (`ls`, `cat`, `grep`) but no graph or visual tools, inferring architecture from reading files sequentially.

**Graph Agent.** Extends Text-Only with `graph_query` for symbolic graph operations, enabling efficient dependency navigation but lacking global visual context.

**Codemap Agent.** Has the full toolkit including `render_map`, enabling it to see architecture, form spatial hypotheses ("violations appear as long edges"), and verify them visually. We guide this agent through natural language instructions that leverage existing visual understanding capabilities: "When analyzing architecture, first render the full map and identify clusters. Look for long edges crossing cluster boundaries—these often indicate violations."

## 4. Experiments

### 4.1. Experimental Setup

**Model Selection.** We use Claude Haiku 4.5 [1] as our base model, chosen for its balance of cost, speed, and multimodal capabilities. With 73.3% accuracy on SWE-bench Verified, it provides strong performance while remaining practical for the iterative interactions our approach requires.

**Datasets and Tasks.** We plan to evaluate on two complementary task sets:

1. **Architectural Violation Detection:** Using three open-source Python repositories (FastAPI, Django, Flask) with documented architectural intentions. We will inject known violations such as views directly querying databases and measure detection accuracy.

![Figure 1](figure1_placeholder.png)

**Figure 1.** Illustrative system architecture showing the flow from repository parsing through visual rendering to agent reasoning. The codemap serves as persistent visual working memory that agents repeatedly consult and annotate. *(Placeholder diagram adapted from CodeGraph [2]; will be replaced with our own system architecture in the final version)*

2. **Terminal-Bench Subset:** Seven tasks from Terminal-Bench [7] spanning multiple difficulty levels, from debugging data pipelines to reverse engineering binaries, providing diverse evaluation of architectural understanding capabilities.

**Metrics.** We will measure detection accuracy (precision/recall for violations), explanation quality (human evaluation), tool efficiency (calls and tokens), and task success rate on Terminal-Bench.

### 4.2. Expected Results

We hypothesize that visual working memory will enable more effective architectural reasoning compared to text-only and graph-based approaches. Specifically, we expect the Codemap agent to excel at violation detection by visually identifying problematic dependencies as long edges crossing cluster boundaries, providing immediate focus that reduces search space. The visual representation should also lead to clearer explanations grounded in spatial metaphors that are easier for humans to verify.
![Figure 2](figure2_placeholder.png)

**Figure 2.** Sample codemap visualization showing graph reasoning with code. Clusters represent architectural layers, node size indicates centrality. *(Placeholder from CodeGraph [2]; will be replaced with our actual codemap visualizations in final version)*

**Tool Usage Patterns.** We expect the Codemap agent to show a characteristic progression: initial map rendering for overview, focused graph queries based on visual observations, targeted re-rendering with overlays, and summarization into structural facts. This should result in fewer but more targeted tool calls compared to exhaustive text-based exploration.

### 4.3. Limitations and Future Work

**Scalability.** Our current approach is designed to handle repositories up to 10K files effectively. Larger codebases require hierarchical visualization or sampling strategies.

**Visual Complexity.** Dense graphs can overwhelm the visual channel. Future work should explore progressive disclosure and level-of-detail techniques.

**Evaluation Scope.** Our current evaluation focuses on Python repositories. Extending to multi-language codebases and cross-language dependencies remains future work.

## References

[1] Anthropic. Claude haiku 4.5: Fast, affordable, and multimodal. https://www.anthropic.com/news/claude-haiku-4-5, 2025.

[2] Qiaolong Cai, Zhaowei Wang, Shizhe Diao, James Kwok, and Yangqiu Song. Codegraph: Enhancing graph reasoning of llms with code. *arXiv preprint arXiv:2408.13863*, 2024.

[3] Steven D. Eppinger and Tyson R. Browning. *Design Structure Matrix Methods and Applications*. MIT Press, 2012.

[4] Zhangyin Feng, Daya Guo, Duyu Tang, Nan Duan, Xiaocheng Feng, Ming Gong, Linjun Shou, Bing Qin, Ting Liu, Daxin Jiang, and Ming Zhou. Codebert: A pre-trained model for programming and natural languages. *arXiv preprint arXiv:2002.08155*, 2020.

[5] Yushi Hu, Weijia Shi, Xingyu Fu, Dan Roth, Mari Ostendorf, Luke Zettlemoyer, Noah A. Smith, and Ranjay Krishna. Visual sketchpad: Sketching as a visual chain of thought for multimodal language models. In *Advances in Neural Information Processing Systems (NeurIPS)*, 2024.

[6] Letta Inc. Letta: Advanced memory management for ai agents. https://docs.letta.com/, 2024.

[7] Laude Institute. Terminal-bench: Evaluating terminal-based ai agents. https://www.tbench.ai/, 2024.

[8] Carlos E. Jimenez, John Yang, Alexander Wettig, Shunyu Yao, Kexin Pei, Ofir Press, and Karthik Narasimhan. Swe-bench: Can language models resolve real-world github issues? https://www.swebench.com/, 2024.

[9] Haowei Lin, Zhiyuan Liu, Kaiyi Zhang, Hao Zhang, Zhaohan Wang, Hengrui Yang, Qi Chen, Yufan Li, Jie Wang, Lingyu Zhang, Bo Tang, Yujiu Yang, et al. Rpg: A repository planning graph for unified and scalable codebase generation. *arXiv preprint arXiv:2509.16198*, 2025.

[10] Adyasha Maharana, Dong-Ho Lee, Sergey Tulyakov, Mohit Bansal, Francesco Barbieri, and Yuwei Fang. Evaluating very long-term conversational memory of llm agents. *arXiv preprint arXiv:2402.17753*, 2024. ACL 2024.

[11] Leland McInnes, John Healy, and James Melville. Umap: Uniform manifold approximation and projection for dimension reduction. *arXiv preprint arXiv:1802.03426*, 2018.

[12] Sachit Menon, Richard Zemel, and Carl Vondrick. Whiteboard-of-thought: Thinking step-by-step across modalities. *arXiv preprint arXiv:2406.14562*, 2024. EMNLP 2024.

[13] Siru Ouyang, Zilin Wang, Zhihan Zhang, Mengzhao Jia, and Meng Yan. Repograph: Enhancing ai software engineering with repository-level code graph. *arXiv preprint arXiv:2410.14684*, 2024.

[14] Charles Packer, Vivian Fang, Shishir G. Patil, Kevin Lin, Sarah Wooders, and Joseph E. Gonzalez. Memgpt: Towards llms as operating systems. *arXiv preprint arXiv:2310.08560*, 2024.

[15] Microsoft Research. Graphrag: Graph-based retrieval augmented generation. *arXiv preprint arXiv:2404.16130*, 2024.

[16] Rana Salama, Hamed Zamani, et al. Meminsight: Autonomous memory augmentation for llm agents. *arXiv preprint arXiv:2503.21760*, 2024.

[17] Noah Shinn, Federico Cassano, Edward Berman, Ashwin Gopinath, Karthik Narasimhan, and Shunyu Yao.
Reflexion: Language agents with verbal reinforcement learning. *arXiv preprint arXiv:2303.11366*, 2024.

[18] Zifan Song, Yesheng Ma, Zeyu Zhang, Yu Kang, Hong Mei, and Mark Gerstein. Locagent: Graph-guided llm agents for code localization. In *Proceedings of the 63rd Annual Meeting of the Association for Computational Linguistics (ACL)*, 2025.

[19] Hongyuan Tao, Ying Zhang, Zhenhao Tang, Hongen Peng, Xukun Zhu, Bingchang Liu, Yingguang Yang, Ziyin Zhang, Zhaogui Xu, Haipeng Zhang, Linchao Zhu, Rui Wang, Hang Yu, Jianguo Li, and Peng Di. Code graph model: Integrating repository structure into model attention. *arXiv preprint arXiv:2505.16901*, 2025.

[20] V. A. Traag, L. Waltman, and N. J. van Eck. From louvain to leiden: guaranteeing well-connected communities. *Scientific Reports*, 9(1):5233, 2019.

[21] Xingliang Wang, Baoyi Wang, Chen Zhi, Junxiao Han, Xinkui Zhao, Jianwei Yin, and Shuiguang Deng. Grace: Graph-guided repository-aware code completion through hierarchical code fusion. *arXiv preprint arXiv:2509.05980*, 2024.

[22] Yanlin Wang, Lianghong Guo, Ensheng Shi, Wanjun Zhong, Hongyu Zhang, Jiachi Chen, and Zibin Zheng. Graphcoder: Enhancing repository-level code completion via code context graph-based retrieval and language model. *arXiv preprint arXiv:2406.07003*, 2024.

[23] Richard Wettel. Codecity: Software systems as cities. https://wettel.github.io/codecity.html, 2011.

[24] Huanyu Zhang, Wenshan Wu, Qi Zhang, Jinfeng Bai, Tao Wang, Weize Chen, et al. Latent sketchpad: Sketching visual thoughts to elicit multimodal reasoning in mllms. *arXiv preprint arXiv:2510.24514*, 2024.

[25] Yangqiaoyu Zhou, Yile Wang, Jing Xu, Chenhui Xie, Qi Liu, and Enhong Chen. Hiagent: Hierarchical working memory management for solving long-horizon agent tasks. *arXiv preprint arXiv:2408.09559*, 2024. ACL 2025.

[26] Yiyang Zhou, Chenhang Cui, Rafael Rafailov, Xilin Wu, Chelsea Finn, et al. Mira: A benchmark for visual chain-of-thought. *arXiv preprint arXiv:2511.02779*, 2025.
