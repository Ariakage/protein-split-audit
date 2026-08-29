// SPDX-License-Identifier: CC-BY-4.0
#import "@preview/elegant-paper:0.1.0": *

// References to sections appear as bare numbers so the hand-written bilingual
// wrappers ("第 X 节" / "Section X") are not duplicated by the localized
// heading supplement ("小节" / "Section").
#show heading: set heading(supplement: none)

#set document(
  title: "ProteinSplitAudit: A Protocol-Driven Workflow for Auditable Similarity-Aware Evaluation of Protein Classifiers (ProteinSplitAudit：面向蛋白质分类器相似性感知评估的协议驱动可审计工作流)",
  description: "Methods/software paper describing an auditable, hash-linked workflow for similarity-aware evaluation of protein classifiers, with a bounded Escherichia coli K-12 pilot of 442 reviewed enzymes.",
  author: ("Aria Chen",),
  date: datetime(year: 2026, month: 8, day: 29),
  keywords: ("protein classification", "sequence similarity", "data leakage", "audit trail", "reproducible evaluation"),
)

#show: elegant-paper.with(
  title: (
    title: "ProteinSplitAudit：面向蛋白质分类器相似性感知评估的协议驱动可审计工作流 (ProteinSplitAudit: A Protocol-Driven Workflow for Auditable Similarity-Aware Evaluation of Protein Classifiers)",
    authors: (
      (
        name: [陈佳杰 (Aria Chen)#footnote[本名 Jiajie Chen。Legal name: Jiajie Chen. ORCID: #link("https://orcid.org/0009-0001-6214-219X")[0009-0001-6214-219X]。]],
        institution: "杭州市第十一中学 (Hangzhou No.11 High School)",
        email: [#link("mailto:ariakage233@gmail.com")[ariakage233\@gmail.com]],
        note: [通讯作者 (Corresponding Author)],
      ),
    ),
    date: "2026年8月29日 (August 29, 2026)",
    abstract: [
蛋白质序列相似性会让分类器的评估结果显得比实际更可靠。随机划分可能把近缘蛋白同时分到训练集和测试集；即使采用相似性感知划分，如果聚类参数、图构建规则、划分身份或模型选择过程没有留下记录，泄漏仍然难以审查。ProteinSplitAudit 是一个开源 Python 工作流，用可检查且由哈希相连的产物保存这条证据链。流程覆盖来源抓取、候选过滤、完全相同序列的冲突处理、确定性队列选择、MMseqs2 搜索、相似性连通分量、分组划分、边界审计、冻结基线评估、受控测试集访问、精确重放与仅聚合发布。本文说明其设计，并报告一个边界明确的案例：442 条经审阅的_大肠杆菌_ K-12 酶蛋白，分属 5 个 EC 二级类别。三个分组划分均未出现分量跨界；在冻结的 MMseqs2 判定条件下，也没有发现达到对应阈值的测试集到训练集违规对。21 个预先规定的"随机划分减聚类划分"Macro-F1 区间全部包含零。因此，本文只作有限结论：该工作流可以让数据划分与评估决定接受审查，但这个单一物种的小型研究不能给出通用模型排名，也不能估计随机划分的一般影响。项目另有完全离线的合成数据命令，可在不公开蛋白质记录、不重新打开冻结测试集的情况下运行主要软件路径。

#v(0.6em)
#align(center)[#strong[Abstract]]

Sequence similarity can make a protein classifier look more reliable than it is. A random split may place close relatives in both Train and Test, and a nominally similarity-aware split can still fail when clustering parameters, graph rules, split identities, or model-selection steps stay outside the record. ProteinSplitAudit is an open-source Python workflow that keeps this lineage in reviewable, hash-linked artifacts. It covers source capture, candidate filtering, exact-sequence conflict handling, deterministic cohort selection, MMseqs2 search, connected similarity components, grouped splits, boundary audits, frozen baseline evaluation, controlled Test access, exact replay, and aggregate-only publication. We describe the design and report a bounded case study of 442 reviewed _Escherichia coli_ K-12 enzymes across five EC level-2 classes. The three grouped splits contain no component crossings and no matching-threshold Test-to-Train violations under the frozen MMseqs2 predicate. All 21 prespecified intervals for the Macro-F1 difference between Random and clustered splits include zero. The conclusion is deliberately narrow: the workflow makes data separation and evaluation decisions inspectable, but this small single-organism study does not establish a universal model ranking or measure the general effect of random splitting. An offline synthetic command exercises the main software path without publishing protein records or reopening the frozen Test set.
    ],
    keywords: (
      "蛋白质分类 (Protein Classification)",
      "序列相似性 (Sequence Similarity)",
      "数据泄漏 (Data Leakage)",
      "审计轨迹 (Audit Trail)",
      "可复现评估 (Reproducible Evaluation)",
    ),
  ),
  enable-outline: true,
)

= 引言 (Introduction) <sec:introduction>

== 研究背景与意义 (Background and Significance) <sec:introduction:background>

蛋白质分类研究通常把序列集合分成训练集 (Train)、验证集 (Validation) 和测试集 (Test)，最后报告测试集指标。这个常见流程留下了一个直接的问题：测试序列和参与拟合的蛋白质到底有多相似？如果同源蛋白或近重复序列跨过划分边界，模型可能只是在恢复家族关系，而没有解决原先设定的泛化问题。

Protein classification studies usually divide a sequence collection into Train, Validation, and Test sets and report Test metrics at the end. This common routine leaves one direct question open: how similar are the Test sequences to the proteins that took part in fitting? If homologs or near-duplicates cross a split boundary, the model may only be recovering family relationships instead of solving the generalization problem it was set.

这个问题在酶分类任务中表现得格外具体。EC 编号 (Enzyme Commission number)#footnote[EC 编号按催化反应类型分四级，例如 2.7.1.1。本文的标签取前两级，例如 2.7 指转移酶中转移含磷基团的类别。EC numbers have four levels organized by catalytic reaction type, for example 2.7.1.1. Labels in this paper use the first two levels; 2.7 denotes transferases transferring phosphorus-containing groups.] 按催化反应层级组织，同源酶往往共享前两级编号。一旦近缘序列同时出现在训练与测试两侧，分类器学到的可能是家族内的保守模式，而不是跨家族的判别能力。论文里报告的测试分数因此会偏高，读者却很难从成品的指标表判断偏高多少。

The problem is especially concrete in enzyme classification. EC numbers are organized by catalytic reaction level, and homologous enzymes often share their first two levels. Once close relatives appear on both sides of a split, a classifier may learn conserved within-family patterns rather than cross-family discrimination. Reported Test scores are therefore inflated, and readers can rarely tell by how much from a finished metric table.

== 相关工作 (Related Work) <sec:introduction:related>

同源性感知划分已有成熟研究。GraphPart 在保留带标签样本的同时构建同源性隔离的划分 @teufel2023graphpart。SpanSeq 将基于相似性的划分用于蛋白质、基因和基因组 @ferrerflorensa2024spanseq。DataSAIL 把生物医学数据的低泄漏划分写成带约束的分配问题 @joeres2025datasail。以 CD-HIT 为代表的序列聚类工具常被用来降低训练集冗余 @fu2012cdhit；ProteinSplitAudit 改用连通分量作为不可分割的分配单元，并把判定条件写进可审查的记录。

Similarity-aware splitting has a mature literature. GraphPart builds homology-isolated splits while preserving labeled samples @teufel2023graphpart. SpanSeq applies similarity-based splits to proteins, genes, and genomes @ferrerflorensa2024spanseq. DataSAIL casts low-leakage splitting of biomedical data as a constrained assignment problem @joeres2025datasail. Sequence clustering tools such as CD-HIT are often used to reduce training-set redundancy @fu2012cdhit; ProteinSplitAudit instead uses connected components as indivisible allocation units and writes the decision predicate into a reviewable record.

ProteinSplitAudit 不再提出一种通用划分算法。它处理的是划分前后那段常被省略的工程记录：使用了哪一份来源数据，候选行如何通过过滤，一条相似性边代表什么，连通分量 (connected component) 是否跨界，测试集访问在何时得到授权，以及重放是否生成相同的产物。这些记录决定了一个"相似性感知"声明能否被第三方审查。

ProteinSplitAudit does not propose yet another general partitioning algorithm. It handles the engineering record that is often omitted before and after a split: which source release was used, how candidate rows passed filtering, what a similarity edge means, whether a connected component crosses a boundary, when Test access was authorized, and whether replay produces identical artifacts. This record decides whether a "similarity-aware" claim can be reviewed by a third party.

== 版本化开发与本文结构 (Versioned Development and Paper Organization) <sec:introduction:structure>

软件按照一系列冻结协议开发。每个版本增加一层功能，但不改写先前证据。v0.2.0 固定队列和划分；v0.3.0 与 v0.4.0 分别固定经典方法和 ESM-2 的验证集基线；v0.5.0 在带证明的双会话闸门下首次打开测试集；v0.6.0 不再执行推理，只对冻结结果开展预先规定的聚合分析。

The software was developed under a series of frozen protocols. Each version adds one layer of functionality without rewriting earlier evidence. v0.2.0 froze the cohort and splits; v0.3.0 and v0.4.0 froze Validation baselines for the classical methods and for ESM-2 respectively; v0.5.0 opened the Test set for the first time under an attested two-session gate; v0.6.0 runs no inference and only performs prespecified aggregate analyses of the frozen results.

本文第 @sec:design 节给出设计目标与证据模型，第 @sec:workflow 节描述工作流各阶段，第 @sec:results 节报告_大肠杆菌_ K-12 pilot 的固定结果，第 @sec:reproducibility 节说明复现途径，第 @sec:discussion 节讨论贡献边界与局限，第 @sec:conclusion 节作结。

Section @sec:design states the design goals and evidence model, Section @sec:workflow describes the workflow stages, Section @sec:results reports the fixed results of the _E. coli_ K-12 pilot, Section @sec:reproducibility explains the reproduction path, Section @sec:discussion discusses the boundary of the claims and the limitations, and Section @sec:conclusion concludes.

= 设计目标与证据模型 (Design Goals and Evidence Model) <sec:design>

ProteinSplitAudit 把数据划分视为一条处理链的输出，而不是一个孤立的 CSV 文件。每个确定性阶段在运行前检查父产物。内容哈希绑定来源字节、规范化表格、配置、队列成员、划分分配、模型身份与公开聚合结果。时间戳和运行环境细节放在单独的运行 provenance 中，因而两次等价运行仍可生成逐字节相同的科学内容。

ProteinSplitAudit treats a data split as the output of a processing chain rather than an isolated CSV file. Every deterministic stage checks its parent artifacts before running. Content hashes bind source bytes, normalized tables, configurations, cohort membership, split assignments, model identities, and public aggregate results. Timestamps and runtime details live in separate run provenance, so two equivalent runs still produce byte-identical scientific content.

实现遵循四条规则。The implementation follows four rules.

+ *拒绝含糊输入 (Refuse ambiguous input)。* 候选构建只接受一个完整的四级 EC 注释、标准氨基酸字符和规定长度。完全相同的序列若对应不同 EC 二级标签，则整组拒绝。Candidate construction accepts only one complete four-level EC annotation, standard amino-acid characters, and the prescribed length range; an exact-sequence group with conflicting EC level-2 labels is rejected as a whole.
+ *明确相似性的含义 (Make similarity semantics explicit)。* MMseqs2 @steinegger2017mmseqs2 在冻结参数下提供观测到的序列对。对阈值 $t$，每个序列一致性不低于 $t$ 的合格序列对形成一条无向边。用于分组分配的最小单元是连通分量，不是代表序列聚类。MMseqs2 @steinegger2017mmseqs2 supplies the observed sequence pairs under frozen parameters. For a threshold $t$, every eligible pair with sequence identity at least $t$ forms an undirected edge; the smallest unit for grouped allocation is the connected component, not a representative-sequence cluster.
+ *拟合信息只来自训练集 (Keep fitting information inside Train)。* 缩放器、类别权重、分类器以及最近同源方法的目标数据库都只使用训练集。验证集用于协议冻结前的开发。完整预测身份封存以后，程序才载入测试标签。Scalers, class weights, classifiers, and the target database of the nearest-homolog method all use Train only; Validation served protocol development before freezing, and Test labels are loaded into memory only after the full prediction identity has been sealed.
+ *只公开足以审查的材料 (Publish the minimum useful evidence)。* 发布物包含 manifest、哈希、计数、聚合指标和通过隐私检查的图。序列、accession、embedding、拟合模型、逐行预测、缓存、访问 ledger 与本地路径不进入版本控制。Releases contain manifests, hashes, counts, aggregate metrics, and figures that pass privacy checks; sequences, accessions, embeddings, fitted models, per-row predictions, caches, access ledgers, and local paths never enter version control.

这些规则不能证明两条蛋白质在生物学上相互独立。MMseqs2 是启发式搜索，没有报告边只说明在指定判定条件下未观察到边。软件保留这个条件，不把它扩写成更强的结论。

These rules cannot prove that two proteins are biologically independent. MMseqs2 is a heuristic search; an unreported edge only means that no edge was observed under the stated predicate. The software keeps this condition and does not inflate it into a stronger conclusion.

= 工作流 (Workflow) <sec:workflow>

@fig:workflow 给出工作流全貌：十二个确定性阶段按顺序连接，每个阶段的输入哈希都写进 manifest，测试标签只在闸门授权之后才与预测连接。

@fig:workflow gives the full picture: twelve deterministic stages connected in order, with the input hash of every stage written into manifests, and Test labels joined to predictions only after the gate authorizes it.

#figure(
  image("images/workflow.svg", width: 98%),
  caption: [ProteinSplitAudit 工作流概览 (Workflow overview)。SHA-256 哈希相连的 manifest 与 attestation 绑定每个阶段；测试集闸门 (Test gate) 之后才允许连接测试标签。SHA-256 hash-linked manifests and attestations bind every stage; Test labels may be joined to predictions only after the Test gate.],
) <fig:workflow>

== 来源下载与候选构建 (Source Download and Candidate Construction) <sec:workflow:source>

Pilot 使用 UniProtKB/Swiss-Prot `2026_02` 版 @uniprot2025。查询选择 taxonomy ID 83333#footnote[83333 是 _Escherichia coli_ K-12 参考株在 UniProt 分类体系中的编号。83333 is the identifier of the _Escherichia coli_ K-12 reference strain in the UniProt taxonomy.] 中经审阅 (reviewed)、非片段 (non-fragment) 且带 EC 注释的酶条目。下载程序跟随 UniProt 分页，将 TSV 合并为规范化内容，只对瞬时错误进行有限重试，并保存响应头白名单。Manifest 记录人类可读查询、规范请求、UniProt 发布信息、页数与记录数、软件状态、lockfile 哈希和规范化内容哈希。

The pilot uses UniProtKB/Swiss-Prot release `2026_02` @uniprot2025. The query selects reviewed, non-fragment enzyme entries with EC annotations from taxonomy ID 83333. The downloader follows UniProt pagination, merges TSV pages into normalized content, retries only transient errors a bounded number of times, and stores a response-header allowlist. The manifest records the human-readable query, the canonical request, UniProt release information, page and record counts, software state, the lockfile hash, and the normalized-content hash.

候选构建先去除序列两端空白并转成大写，只接受 20 种标准氨基酸和 50 至 1000 个残基的长度。EC 字段必须只有一个由四级整数组成的注释，前两级作为目标标签。对于序列和目标标签都相同的记录，字典序最小的 accession 是规范记录，其余 accession 写入别名审计。若目标标签不同，整组完全相同序列从候选集中删除，注释分歧保留在单独的审计材料中。

Candidate construction trims flanking whitespace from sequences and uppercases them, accepting only the 20 standard amino acids and lengths from 50 to 1000 residues. The EC field must contain exactly one annotation of four integer levels, whose first two levels form the target label. For records sharing both sequence and target label, the lexicographically smallest accession is the canonical record and the others are written to an alias audit. If target labels conflict, the whole exact-sequence group is removed from the candidate set, and the annotation disagreement is kept in separate audit material.

== 队列选择与相似性分量 (Cohort Selection and Similarity Components) <sec:workflow:cohort>

队列规则在模型结果产生前写定。合格类别至少有 40 条候选序列和 10 个 Cluster30 发现组。流程必须选择恰好 5 个类别，每类上限 250 条，随机种子为 42。若不足 5 类，命令直接失败，不会自动退回较小的研究设计。

Cohort rules were written down before any model result existed. An eligible class has at least 40 candidate sequences and 10 Cluster30 discovery groups. The pipeline must select exactly 5 classes, cap each at 250 sequences, and use random seed 42; if fewer than 5 classes qualify, the command fails outright instead of falling back to a smaller study design.

MMseqs2 `18-8cc5c` 使用下列冻结设置：最低覆盖率 0.80、覆盖模式 0、E-value 0.001、敏感度 7.5、比对模式 3、8 个线程。序列对输出先规范化，再用于构图。每个分量的标识符来自成员精确序列哈希的排序结果，因此输入次序和代表序列的选择不会改变分量身份。

MMseqs2 `18-8cc5c` runs with the following frozen settings: minimum coverage 0.80, coverage mode 0, E-value 0.001, sensitivity 7.5, alignment mode 3, and 8 threads. Pair output is normalized before graph construction. Each component identifier is derived from the sorted exact-sequence hashes of its members, so input order and the choice of representative sequence cannot change component identity.

流程在 70%、50% 与 30% 一致性阈值构图。三个划分必须嵌套：较严格阈值下的每个分量，都完整属于下一个较宽松阈值的某个分量。分配器以完整分量为单位，同时保证每个类别都出现在训练、验证和测试分区中，并满足冻结的比例容差。相同类别计数的随机划分作为对照。

Graphs are built at the 70%, 50%, and 30% identity thresholds. The three splits must nest: every component at the stricter threshold lies entirely inside one component at the next looser threshold. The allocator moves whole components and guarantees that every class appears in the Train, Validation, and Test partitions within frozen ratio tolerances. A random split with identical class counts serves as the control.

== 边界审计 (Boundary Audit) <sec:workflow:audit>

构建与审计是两个独立步骤。每个划分都把测试序列作为 query，在只含训练序列的数据库中按冻结的 MMseqs2 设置搜索。审计报告观测命中，以及达到 30%、50% 和 70% 一致性的数量。如果某个分量跨过对应的分组划分边界，或审计发现达到对应阈值的测试集到训练集序列对，划分即失败。因此，零违规表示在这套判定条件下没有观测到违规对，不表示两个分区没有演化关系。

Construction and audit are two separate steps. For every split, Test sequences are used as queries against a database containing only Train sequences, under the frozen MMseqs2 settings. The audit reports observed hits and the counts reaching 30%, 50%, and 70% identity. A split fails if a component crosses the corresponding grouped-split boundary or if the audit finds a Test-to-Train pair reaching the matching threshold. Zero violations therefore mean that no violating pair was observed under this predicate, not that the two partitions share no evolutionary relationship.

== 基线方法与测试集闸门 (Baselines and the Test-Set Gate) <sec:workflow:gate>

评估矩阵含 7 个固定方法：多数类；序列长度、氨基酸组成 (amino-acid composition) 和完整 3-mer 相对频率配合逻辑回归；最近训练同源序列；冻结的 ESM-2 35M 和 150M 表征配合线性 probe @lin2023esm2。逻辑回归由 scikit-learn @pedregosa2011scikit 实现，类别权重和参数固定。长度、氨基酸组成与 ESM 表征使用仅在训练集拟合的缩放器。3-mer 词表包含按固定顺序排列的全部 8000 个组合，不使用缩放器。ESM-2 表征是最后一层残基 token 的均值，不包括特殊 token，模型权重不参与训练。

The evaluation matrix contains 7 fixed methods: majority class; sequence length, amino-acid composition, and full 3-mer relative frequencies each paired with logistic regression; the nearest Train homolog; and frozen ESM-2 35M and 150M representations paired with linear probes @lin2023esm2. Logistic regression comes from scikit-learn @pedregosa2011scikit with fixed class weights and parameters. Length, composition, and ESM features use scalers fitted on Train only; the 3-mer vocabulary lists all 8000 combinations in fixed order without a scaler. ESM-2 representations are the mean over last-layer residue tokens, excluding special tokens, and the model weights are not trained.

真实测试路径要求一份机器可读 attestation。它绑定干净的 generation commit、依赖锁、输入、方法矩阵、两个允许的会话名和维护者永久审批链接。预测完成后，程序才把测试标签载入内存。会话一旦消费，即使运行失败也不能恢复额度。重放逐字节比较确定性产物；不一致会阻止发布，后续修复必须先经过前瞻性的协议修订。失败的旧尝试仍留在审计记录中。

The real Test path requires a machine-readable attestation binding a clean generation commit, the dependency lock, inputs, the method matrix, the two permitted session names, and the maintainer's permanent approval link. Test labels are loaded into memory only after predictions are complete. Once a session is consumed, its quota cannot be restored even if the run fails. Replay compares deterministic artifacts byte by byte; a mismatch blocks publication, and any later fix must first pass a forward-looking protocol revision. Failed earlier attempts remain in the audit record.

= 结果 (Results) <sec:results>

== 边界明确的 Pilot 队列 (The Bounded Pilot Cohort) <sec:results:cohort>

来源查询返回 2632 条记录。候选过滤与精确去重后保留 1182 条；冻结队列有 442 条蛋白质。@tbl:cohort 给出固定计数。EC 2.7 是最大类别，只看准确率会受类别分布影响，因此评估同时报告 balanced accuracy 和 Macro-F1#footnote[Macro-F1 是各类别 F1 分数的未加权平均，可以减轻类别不平衡对总体分数的影响。Macro-F1 is the unweighted mean of per-class F1 scores; it reduces the influence of class imbalance on the overall score.]。

The source query returned 2632 records. Candidate filtering and exact deduplication retained 1182; the frozen cohort contains 442 proteins. @tbl:cohort gives the frozen counts. EC 2.7 is the largest class, so accuracy alone would be shaped by the class distribution; the evaluation therefore reports balanced accuracy and Macro-F1 together.

#figure(
  table(
    columns: (1.5fr, 1fr, 1fr, 1fr, 1fr, 1fr),
    align: (left, center, center, center, center, center),
    table.header([阶段或类别 (Stage or Class)], [总数 (All)], [2.7], [3.1], [1.1], [2.1 / 4.1]),
    [下载来源 (Downloaded source)], [2632], [], [], [], [],
    [合格候选 (Accepted candidates)], [1182], [], [], [], [],
    [冻结队列 (Frozen cohort)], [442], [192], [85], [59], [57 / 49],
    [训练 / 验证 / 测试 (Train / Val. / Test)], [308 / 68 / 66], [], [], [], [],
  ),
  caption: [Pilot 固定计数 (Frozen pilot counts)。评估标签顺序为 2.7、3.1、1.1、2.1、4.1。The evaluation label order is 2.7, 3.1, 1.1, 2.1, 4.1.],
) <tbl:cohort>

队列在 70%、50% 与 30% 阈值下分别形成 437、427 与 398 个严格分量。三个聚类感知划分均没有分量跨界，也没有达到对应阈值的测试集到训练集违规对。随机划分审计发现 4 个一致性不低于 30% 的序列对，其中 2 个不低于 50%，没有序列对达到 70%。这个随机对照本身的高一致性泄漏已经很少，不适合用来估计随机划分通常会把性能夸大多少。

The cohort forms 437, 427, and 398 strict components at the 70%, 50%, and 30% thresholds respectively. None of the three cluster-aware splits contains a component crossing, and none contains a Test-to-Train pair reaching the matching threshold. The random-split audit found 4 pairs with identity at least 30%, of which 2 reach at least 50%, and none reaches 70%. This random control already shows very little high-identity leakage and is not suitable for estimating how much random splitting usually inflates performance.

== 测试集评估与不确定性 (Test Evaluation and Uncertainty) <sec:results:evaluation>

@tbl:macro-f1 和 @fig:macro-f1 汇总测试集 Macro-F1。ESM-2 线性 probe 在这个 pilot 中的点估计最高，但测试集小且类别不均衡，不能据此给出通用排名。每个划分只有 66 条测试蛋白质，各类别支持数为 29、13、9、8 和 7。

@tbl:macro-f1 and @fig:macro-f1 summarize Test Macro-F1. The ESM-2 linear probes have the highest point estimates in this pilot, but the Test set is small and class-imbalanced, so no universal ranking can be drawn from them. Each split has only 66 Test proteins, with per-class supports of 29, 13, 9, 8, and 7.

#figure(
  table(
    columns: (1.7fr, 0.8fr, 0.8fr, 0.8fr, 0.8fr),
    align: (left, center, center, center, center),
    table.header([方法 (Method)], [Random], [C70], [C50], [C30]),
    [多数类 (Majority)], [0.122], [0.122], [0.122], [0.122],
    [长度逻辑回归 (Length logistic)], [0.171], [0.142], [0.148], [0.189],
    [AAC 逻辑回归 (AAC logistic)], [0.236], [0.343], [0.349], [0.246],
    [3-mer 逻辑回归 (3-mer logistic)], [0.358], [0.418], [0.389], [0.389],
    [最近同源 (Nearest homolog)], [0.369], [0.462], [0.543], [0.307],
    [ESM-2 35M], [0.797], [0.735], [0.860], [0.713],
    [ESM-2 150M], [0.784], [0.807], [0.844], [0.780],
  ),
  caption: [冻结的测试集 Macro-F1 点估计 (Frozen Test Macro-F1 point estimates)。C70、C50、C30 表示三个聚类感知划分。C70, C50, and C30 denote the three cluster-aware splits.],
) <tbl:macro-f1>

#figure(
  image("../../results/released/v0.6.0/figures/macro_f1_by_split.pdf", width: 94%),
  caption: [各方法与划分的测试集 Macro-F1 (Test Macro-F1 by method and split)。图来自不可变的 v0.6.0 聚合发布物。Figure taken from the immutable v0.6.0 aggregate release.],
) <fig:macro-f1>

不确定性计算以冻结的 Cluster30 发现分量为抽样单位，使用种子 2026 进行 2000 次百分位 bootstrap#footnote[以完整分量为重抽样单位，同一分量内的近缘序列不会被拆到重抽样的两侧。Using whole components as the resampling unit keeps close relatives within a component from being separated across resampled sides.]。21 个预先规定的"随机划分减聚类划分"Macro-F1 区间全部包含零。@fig:gaps 给出这些差值。现有证据没有显示更严格的聚类会单调降低模型分数，也没有显示某一种划分普遍更好。

Uncertainty calculations use the frozen Cluster30 discovery components as the sampling unit and run 2000 percentile bootstrap iterations with seed 2026. All 21 prespecified Random-minus-cluster Macro-F1 intervals include zero; @fig:gaps shows these differences. The available evidence shows neither that stricter clustering monotonically lowers model scores nor that any one split is uniformly better.

#figure(
  image("../../results/released/v0.6.0/figures/generalization_gap.pdf", width: 94%),
  caption: [随机划分减聚类划分的 Macro-F1 差值及冻结的分量 bootstrap 区间 (Random minus clustered Macro-F1 differences with frozen component-bootstrap intervals)。所有区间均包含零。All intervals include zero.],
) <fig:gaps>

== 重放与协议修订记录 (Replay and Protocol Revision Records) <sec:results:replay>

早期重放发现会话身份进入产物身份的缺陷。该问题只用合成 fixture 修复，没有重新打开测试集。修复后，两次获批的替代测试会话在 430 个确定性产物上完全一致。v0.6 的测试后分析也精确重放了全部 11 个确定性文件。这些检查说明软件和指定环境可以重放，但不会扩大 pilot 的生物学适用范围。

An early replay uncovered a defect in which session identity leaked into artifact identity. The problem was fixed using synthetic fixtures only, without reopening the Test set. After the fix, the two approved substitute Test sessions agreed on all 430 deterministic artifacts. The v0.6 post-test analysis also replayed all 11 deterministic files exactly. These checks show that the software and the specified environment can be replayed; they do not widen the biological scope of the pilot.

= 可复现性与公开验证 (Reproducibility and Public Verification) <sec:reproducibility>

ProteinSplitAudit 面向 Python 3.12，并检查纳入版本控制的 `uv.lock`。自动测试覆盖配置验证、使用 mock HTTP transport 的下载分页与重试、候选过滤、确定性 Parquet 与 FASTA、连通分量、划分隔离、模型协议、授权闸门、重放身份、公开内容白名单和 wheel 安装。默认 CI 不连接 UniProt，也不执行真实 MMseqs2 或 ESM-2 作业。

ProteinSplitAudit targets Python 3.12 and checks the version-controlled `uv.lock`. Automated tests cover configuration validation, download pagination and retries with a mock HTTP transport, candidate filtering, deterministic Parquet and FASTA outputs, connected components, split isolation, model protocols, the authorization gate, replay identity, the public-content allowlist, and wheel installation. The default CI never connects to UniProt and runs no real MMseqs2 or ESM-2 jobs.

@sec:appendix:demo 中的命令无需受控蛋白质数据，可公开检查软件主路径。该命令生成 90 条合成蛋白质样记录和 45 个成对分量，构建 Random 与 Cluster30 划分，提取氨基酸组成，拟合只使用训练集的逻辑回归，并写出 3 个聚合文件。在新目录中重复运行可得到逐字节相同的内容。这个 demo 检查软件行为，其指标不是科学结果。

The command in @sec:appendix:demo needs no controlled protein data and lets anyone inspect the main software path in public. It generates 90 synthetic protein-like records and 45 paired components, builds Random and Cluster30 splits, extracts amino-acid composition, fits a logistic regression on Train only, and writes 3 aggregate files. Repeated runs in a fresh directory yield byte-identical content. The demo checks software behavior; its metrics are not scientific results.

本文报告的全部评估数字来自该仓库不可变的 v0.6.0 发布产物 @proteinsplitaudit。软件运行需求汇总于 @tbl:requirements。

All evaluation numbers reported here come from the immutable v0.6.0 release artifacts of the repository @proteinsplitaudit. Runtime requirements are summarized in @tbl:requirements.

#figure(
  table(
    columns: (1fr, 2.2fr),
    align: (left, left),
    table.header([项目 (Item)], [说明 (Detail)]),
    [软件包 (Package)], [`protein-split-audit`，命令行入口 `psaudit`],
    [Python], [3.12（`>=3.12,<3.13`）],
    [依赖管理 (Dependency manager)], [`uv`，依赖锁定于纳入版本控制的 `uv.lock`],
    [外部工具 (External tools)], [MMseqs2 `18-8cc5c`（pilot 相似性搜索；合成演示不需要）],
    [预训练权重 (Pretrained weights)], [ESM-2 35M / 150M（基线方法；合成演示不需要）],
    [许可证 (Licenses)], [软件 Apache-2.0；原创文档 CC BY 4.0],
  ),
  caption: [软件需求 (Software requirements)。离线合成演示不连接网络，也不需要 MMseqs2 或 ESM-2 权重。The offline synthetic demo needs no network access and neither MMseqs2 nor ESM-2 weights.],
) <tbl:requirements>

== 数据可用性 (Data Availability) <sec:reproducibility:data>

软件与全部公开产物发布于 #link("https://github.com/ariakage/protein-split-audit")[github.com/ariakage/protein-split-audit] @proteinsplitaudit：软件代码采用 Apache-2.0 许可证，项目原创文档采用 CC BY 4.0。UniProt 衍生序列数据遵循上游条款，仓库不再分发；蛋白质序列、accession、embedding、拟合模型与逐行预测不进入版本控制。公开材料只包含计数、哈希、聚合指标和通过隐私检查的图，读者可用 @sec:appendix:demo 的合成命令检查软件主路径。本文评估数字来自仓库内不可变的 v0.6.0 发布产物。

The software and all public artifacts are published at #link("https://github.com/ariakage/protein-split-audit")[github.com/ariakage/protein-split-audit] @proteinsplitaudit: code under the Apache-2.0 license and original project documentation under CC BY 4.0. UniProt-derived sequence data remain under the upstream terms and are not redistributed; protein sequences, accessions, embeddings, fitted models, and per-row predictions do not enter version control. Public material contains only counts, hashes, aggregate metrics, and privacy-checked figures, and readers can exercise the main software path with the synthetic command in @sec:appendix:demo. The evaluation numbers in this paper come from the immutable v0.6.0 release artifacts in the repository.

== 数字核验与稿件冻结 (Number Verification and Manuscript Freeze) <sec:reproducibility:verification>

正文中的全部数字已用独立脚本 `scripts/verify_manuscript_numbers.py` 逐项对照 `results/released` 与 `data/manifests` 的冻结产物完成核验，共 47 项对照全部一致；核验记录保存于 `docs/attestations/manuscript-number-verification.json`，其中同时登记了三个稿件源文件的 SHA-256，用于识别本冻结稿件。@sec:appendix:demo 的离线合成演示经实测生成 90 条合成记录与 45 个分量，写出 3 个聚合文件，与正文描述一致。

Every number in the text has been checked item by item against the frozen artifacts in `results/released` and `data/manifests` by the standalone script `scripts/verify_manuscript_numbers.py`; all 47 checks agree. The verification record at `docs/attestations/manuscript-number-verification.json` also registers the SHA-256 of the three manuscript source files, which identifies this frozen manuscript. The synthetic demo was run in practice and produced 90 synthetic records and 45 components across 3 aggregate files, matching the text.

= 讨论 (Discussion) <sec:discussion>

== 贡献边界 (Boundary of the Claims) <sec:discussion:claims>

本文的贡献是一个审查方法，不是一个新算法，也不是一个基准结论。工作流把相似性感知评估中常被口头带过的决定变成可以逐条核对的产物：来源字节、候选规则、图语义、划分验证、仅训练集拟合、测试集授权、重放与公开过滤由同一条哈希链相连。_大肠杆菌_ K-12 pilot 说明这条链可以完整运行并被第三方复现，包括对重放失败的处理。

The contribution of this paper is a method of review, not a new algorithm and not a benchmark conclusion. The workflow turns decisions that are usually talked over in similarity-aware evaluation into artifacts that can be checked one by one: source bytes, candidate rules, graph semantics, split validation, Train-only fitting, Test authorization, replay, and public filtering are joined by one hash chain. The _E. coli_ K-12 pilot shows that this chain can run end to end and be reproduced by a third party, including the handling of failed replays.

21 个区间全部包含零这一结果不能被读成"随机划分没有问题"。这个随机对照观测到的高一致性泄漏本来就少，统计功效也受 66 条测试序列的限制。它只能说明：在这套冻结条件下，聚类划分相对随机划分的性能差异没有被观测到。

The fact that all 21 intervals include zero must not be read as "random splitting is fine". The random control already shows little high-identity leakage, and statistical power is limited by 66 Test sequences. It only shows that, under these frozen conditions, no performance difference between clustered and random splits was observed.

== 局限性 (Limitations) <sec:discussion:limitations>

本研究只覆盖一个物种、一版 UniProt、5 个较粗的 EC 类别、一个队列随机种子和每个划分 66 条测试蛋白质。类别不平衡使一些子组低于预先规定的支持数或隐私阈值。被抑制的子组表示证据不足，不表示效应为零。

This study covers one organism, one UniProt release, five coarse EC classes, one cohort random seed, and 66 Test proteins per split. Class imbalance pushes some subgroups below the prespecified support or privacy thresholds; a suppressed subgroup means insufficient evidence, not a zero effect.

冻结的 MMseqs2 搜索只实现一种可操作的相似性定义，无法排除启发式搜索遗漏的关系，也无法审计队列之外的蛋白质。ESM-2 在本项目外完成预训练，pilot 蛋白、其近缘蛋白是否进入预训练语料仍不清楚 @hermann2024pretraining。下游划分干净，不能据此声称模型与预训练数据独立。

The frozen MMseqs2 search implements only one operational definition of similarity; it cannot exclude relationships that the heuristic search misses, and it cannot audit proteins outside the cohort. ESM-2 was pretrained outside this project, and whether the pilot proteins or their close relatives entered the pretraining corpus remains unknown @hermann2024pretraining. Clean downstream splits do not justify a claim that the models are independent of pretraining data.

评估只包含两个 ESM-2 checkpoint、一种 pooling、一种线性 probe、5 个简单经典基线和一个种子。尚无外部物种或独立抽样队列检验相同结论。投稿前要求的一次干净检出独立复现已由主要实现者之外的审查人完成并公开记录（GitHub Issue #7）；投稿版本的永久归档与 DOI（`10.5281/zenodo.22164608`）也已建立。

The evaluation contains only two ESM-2 checkpoints, one pooling scheme, one linear probe, five simple classical baselines, and one seed. No external organism or independently sampled cohort has tested the same conclusions. The independent reproduction from a clean checkout required before submission has been completed by a reviewer other than the main implementer and publicly recorded (GitHub issue #7); permanent archival and a DOI for the submission version (`10.5281/zenodo.22164608`) are also in place.

= 结论 (Conclusion) <sec:conclusion>

ProteinSplitAudit 把相似性感知蛋白质评估中的决定留给审阅者检查。来源抓取、候选规则、图语义、划分验证、仅训练集拟合、测试集授权、重放和公开聚合过滤由一条证据链相连。_大肠杆菌_ K-12 pilot 说明这条链可以运行并复现，也保留了重放失败的处理记录。它的规模有限。本文能支持的是一套检查评估 lineage 的软件方法，而不是通用 benchmark 结论。

ProteinSplitAudit leaves the decisions in similarity-aware protein evaluation open for reviewers to inspect. Source capture, candidate rules, graph semantics, split validation, Train-only fitting, Test authorization, replay, and public aggregate filtering are joined into one evidence chain. The _E. coli_ K-12 pilot shows that the chain can be executed and reproduced, including the handling of failed replay identities. Its scale is limited. The defensible result is a software method for inspecting evaluation lineage, not a universal benchmark conclusion, and the pilot is not offered as a representative enzyme benchmark.

= 声明 (Declarations) <sec:declarations>

*作者与通讯 (Author and Correspondence)。* 陈佳杰 (Aria Chen，亦署名 Jiajie Chen)，杭州市第十一中学 (Hangzhou No.11 High School)，中国浙江省杭州市拱墅区八丈井东路150号 (No. 150 Bazhangjing East Road, Gongshu District, Hangzhou, Zhejiang, China)。电子邮箱：#link("mailto:ariakage233@gmail.com")[ariakage233\@gmail.com]。ORCID：#link("https://orcid.org/0009-0001-6214-219X")[0009-0001-6214-219X]。Author and correspondence: Chen Jiajie (Aria Chen, also published as Jiajie Chen), Hangzhou No.11 High School, No. 150 Bazhangjing East Road, Gongshu District, Hangzhou, Zhejiang, China. Email: #link("mailto:ariakage233@gmail.com")[ariakage233\@gmail.com]. ORCID: #link("https://orcid.org/0009-0001-6214-219X")[0009-0001-6214-219X].

*经费 (Funding)。* 本研究未获得科研经费资助。项目在“智极松 Minicamp2026”黑客松期间得到了部分完善，获 AI+生命科学赛道冠军，奖励为面值 500 元的京东 E 卡；该奖励是竞赛奖品，不构成科研资助。This work received no research funding; the project was partially refined during the Zhijisong Minicamp2026 hackathon, where it won the AI+Life Science track (prize: a 500-CNY JD.com E-card, a competition award rather than research funding).

*利益冲突 (Competing Interests)。* 作者声明没有利益冲突。The author declares no competing interests.

*作者贡献 (Author Contributions)。* 陈佳杰为本文唯一作者，按 CRediT 分类承担全部工作：概念化 (Conceptualization)、方法学 (Methodology)、软件 (Software)、验证 (Validation)、形式分析 (Formal analysis)、初稿写作 (Writing, original draft)、审阅与编辑 (Writing, review & editing)、可视化 (Visualization)、项目管理 (Project administration)。AI 工具的参与范围与约束见下文使用说明。Chen Jiajie (Aria Chen, legal name Jiajie Chen) is the sole author of this paper and performed all work under the CRediT taxonomy: Conceptualization, Methodology, Software, Validation, Formal analysis, Writing (original draft), Writing (review & editing), Visualization, and Project administration. The scope and constraints of AI-tool involvement are described in the AI-use disclosure below.

*伦理声明 (Ethics Statement)。* 本研究是仅使用公开数据库的计算研究，不涉及人体或动物实验，也不开展湿实验。This is a computational study using public databases only; it involves no human or animal subjects and no wet-lab experiments.

*AI 使用说明 (AI-Use Disclosure)。* OpenAI Codex 参与了软件开发、测试、仓库检查和论文起草。维护者确定科研范围，批准冻结协议与访问闸门，并控制 commit 和 release。静态分析、离线测试、哈希、精确重放和人工审阅用于检查生成内容。任何 AI 系统都未获准代替维护者批准协议、冒充维护者、增加测试集访问次数，或在没有明确授权时发布版本。作者须按照目标期刊政策复核这段说明。OpenAI Codex took part in software development, testing, repository checks, and paper drafting. The maintainer sets the research scope, approves frozen protocols and access gates, and controls commits and releases. Static analysis, offline tests, hashes, exact replay, and human review are used to check generated content. No AI system was ever authorized to approve protocols on the maintainer's behalf, impersonate the maintainer, add Test-set accesses, or release versions without explicit authorization. The author will review this statement against the target venue's policy.

= 致谢 (Acknowledgements) <sec:acknowledgements>

本工作建立在若干公开项目之上：UniProt 提供经审阅的蛋白质注释 @uniprot2025，MMseqs2 提供序列搜索 @steinegger2017mmseqs2，ESM-2 提供蛋白质语言模型权重 @lin2023esm2，scikit-learn 提供经典模型实现 @pedregosa2011scikit，Typst 与 elegant-paper 模板承担排版。感谢这些项目的维护者。稿件中所有数字来自仓库已冻结的发布产物，任何未被发布材料支持的表述均未写入正文。

This work builds on several public projects: UniProt supplies reviewed protein annotation @uniprot2025, MMseqs2 supplies sequence search @steinegger2017mmseqs2, ESM-2 supplies protein language model weights @lin2023esm2, scikit-learn supplies classical model implementations @pedregosa2011scikit, and Typst with the elegant-paper template handles typesetting. We thank the maintainers of these projects. Every number in the manuscript comes from the frozen release artifacts of the repository, and no statement unsupported by published material was written into the text.

= 附录 (Appendix) <sec:appendix>

== A.1 离线合成演示命令 (Offline Synthetic Demo Command) <sec:appendix:demo>

下面的命令无需受控蛋白质数据，也不连接网络，可公开检查软件主路径：

The command below needs no controlled protein data and no network access, and lets anyone inspect the main software path in public:

```
uv run --locked psaudit demo run --output-dir results/runs/methods-demo
```

重复运行产生逐字节相同的产物。该命令验证软件行为，其指标不构成科学结果。

Repeated runs produce byte-identical artifacts. The command verifies software behavior; its metrics are not scientific results.

== A.2 投稿前清单的处理记录 (Pre-Submission Checklist Record) <sec:appendix:checklist>

原清单共六项，六项均已完成并留有证据。

The original checklist had six items; all six are completed with evidence on record.

One: 选定目标平台。以 arXiv 预印本（分类 q-bio.QM，许可 CC BY 4.0）作为首发平台；期刊投稿在公开历史满足要求后另行决定（JOSS 要求公开历史不少于六个月）。The initial venue is an arXiv preprint (category q-bio.QM, license CC BY 4.0); journal submission will be decided once the public development history is long enough (JOSS requires at least six months).

Two: AI 使用说明复核。作者已按 arXiv 政策复核第 @sec:declarations 节的披露：AI 参与须披露、AI 不能署名作者、生成内容须经人工审阅，本稿披露满足这三条。The author reviewed the disclosure in Section @sec:declarations against arXiv policy: AI assistance is disclosed, no AI system is listed as an author, and generated content was reviewed by a human.

Three: 数字核验与稿件源哈希。全部数字已用 `scripts/verify_manuscript_numbers.py` 逐项对照冻结发布产物核验（47 项对照一致），记录写入 `docs/attestations/manuscript-number-verification.json`，其中登记三个稿件源文件的 SHA-256。All reported numbers were verified against the frozen release artifacts (47 matching checks); the record at `docs/attestations/manuscript-number-verification.json` registers the SHA-256 of the three manuscript source files.

Four: 外部数据集预注册。决定暂不预注册：本研究的公开范围明确限定为单一物种示范，外部物种评估属于未来工作。Decision: no preregistration at this time; the public scope is bounded to the single-species demonstration, and external datasets remain future work.

Five: 独立复现。已由主要实现者之外的审查人（GitHub 用户 urntt）从标签 v0.7.0 的干净检出完成，公开记录为 GitHub Issue #7：复核提交 `50b6ce08`，`uv.lock` 哈希与发布锁文件一致，837 项测试通过，两次 demo 运行逐字节一致，三个产物哈希与已归档容器运行逐字节一致，并附同提交 CI 运行链接与无偏差声明。Five: independent reproduction. Completed from a clean checkout of tag v0.7.0 by a reviewer other than the main implementer (GitHub user urntt); the public record is GitHub issue #7: reviewed commit `50b6ce08`, `uv.lock` hash matching the released lockfile, 837 passing tests, two byte-identical demo runs, three artifact hashes byte-identical to the archived container run, plus the CI run link for the same commit and a statement that no warnings, deviations, or failures occurred.

Six: 永久归档。软件 v0.7.0 已向 Zenodo 存档（记录 22164608，DOI `10.5281/zenodo.22164608`，2026-08-29 发布），存档源码绑定 GitHub 标签 v0.7.0，许可 Apache-2.0。Software v0.7.0 has been archived on Zenodo (record 22164608, DOI `10.5281/zenodo.22164608`, published 2026-08-29); the archived source is bound to GitHub tag v0.7.0 under Apache-2.0.

#bibliography("references.bib", title: "参考文献 (References)", style: "gb-7714-2015-author-date")
