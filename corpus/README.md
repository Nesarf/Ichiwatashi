# corpus — 测量事实，不是样本

**一行一条 `manifest.jsonl`。** 规则见 `POLICY.md`（准入三门与来源世代）。

## 为什么这样组织

**测量是贵的那部分，样本是可复现的。** 而这里还有第二个理由，是本仓库特有的：

**同一个像素画指标在不同来源上的含义不同。** 已经实测到的例子 —— TH123 的
`outline_variation` 中位数是 0.726，TH155 是 0.003，**而两代都是正确作品**。
当时没人知道那 120 张只来自一款游戏，于是 TH155 那一代每一张都被报警。
**所以来源不是备注，是判据的一部分。**

## `manifest.jsonl` 每条记录的字段

| 字段 | 含义 |
|---|---|
| `sha256` | **身份。** 路径在机器之间会变，内容不变 |
| `path_hint` | 上次见到的位置 —— 提示，绝不是身份 |
| `source_id` | 指向 `sources.jsonl`，**没有它这条记录不完整** |
| `generation` | `th105/th123` · `th155` · `ugoira` · `other_acg` · `synthetic` |
| `derived` | **`false` 才能进参照表。** `true` 时必有 `derived_from` |
| `derived_from` | 源样本的 sha256 |
| `eligibility` | `adopted` · `pending`（只有一项正面证据）· `rejected` |
| `reject_reason` | `eligibility == rejected` 时必填，取自 `POLICY.md` 门 1 的列表 |
| `lossless` | 是否为未经重编码的索引色/无损 PNG |
| `format` | `png` · `gif` · `apng` · `8bpp-indexed` … |
| `size`, `width`, `height` | 基本尺寸 |
| `palette_size`, `pixel_scale`, `bbox_fill` | 与来源无关或敏感度已知的指标 |
| `outline_variation`, `outline_predictability`, `outline_colours` | **必须与 `generation` 一起读** |
| `metrics_schema` | 指标集版本 —— 跨版本比数值前先看这个 |
| `first_seen`, `last_seen`, `times_seen` | 让重复抓取**可比**，而不是替换掉前一次 |

## `sources.jsonl` 每条记录的字段

| 字段 | 含义 |
|---|---|
| `source_id` | 短 id，被 manifest 引用 |
| `url` | 出处 |
| `kind` | `game-rip` · `artist-gallery` · `doujin-scan` · `paper` · `reference` |
| `work` | 作品名（ACG 出处） |
| `author` | 画师/社团，若有署名 |
| `generation` | 该来源属于哪一档 |
| `fetched` | 抓取时间 |
| `via` | **`proxy-10090`**（本机直连多站不可达，见下） |
| `licence_stance` | 我们的态度：`quoted-for-measurement` · `public-domain` · `unknown-do-not-redistribute` |
| `notes` | 任何准入判断的依据，写在这里 |

## 网络

**本机出口经 mihomo 代理，HTTP 端口 `10090`。** 直连对多数目标站不可达，实测：

| 站点 | 直连 | 代理 |
|---|---|---|
| pixiv.net | ERR | **200** |
| danbooru | ERR | **200** |
| e-hentai | ERR | **200** |
| scholar.google | ERR | **200** |
| google | ERR | **200** |
| arxiv / github / safebooru | 200 | 200 |

**所以抓取一律带 `-x http://127.0.0.1:10090`**，并把 `via` 记进 `sources.jsonl`。

## 样本在哪

**不在仓库里。** 当前：`E:\DaShaoHuo\downloads\ichiwatashi-corpus\`，
按 `corpus/README.md` 的 schema 用 `path_hint` 关联。

`POLICY.md` 门 3 管的就是这件事：**任何我合成或改过的样本一律 `derived: true`，
并且永进参照表** —— 否则「真手绘的分布」里会混进我自己的产物，而那是循环论证。
