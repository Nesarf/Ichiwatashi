# MAP — Ichiwatashi 的工程地图

像素画工具：测量、构造、判断。它不生成图，它提供画布与尺子。

## 顶层目录

```
ichiwatashi/
  builder.py       画布与全部构造动词（rect / disc / line / trap / cone / shade / outline /
                   mirror / crop / stamp / flip / mask / unit / 历史）
  layers.py        图层包装：一次一张画布，按声明顺序合成
  cli.py           唯一入口，把脚本翻译成对画布的操作
  judge.py         判据：一张图是手绘 sprite 还是渲染帧，量化指标在这里
  calibration.py   参考带：分位数与「离带有多远」，只给位置不做判定
  profile.py       把判据结果折算成「离哪一代更近」，不给结论
  palette.py       采色与噪声合并
  perceptual.py    感知层面的换算（按用途）
  keys.py          颜色键的解析与规范化
  scope.py         读取范围的界定
  audit.py         构建时的提示：脚本自相矛盾的地方
  panel.py         九色面板绘制
  figures.py       数据图（判据报告用的图形）
  font.py          字模
  frames.py        动图帧合成
  window.py        窗口渲染
  terminal.py      终端渲染
  portable.py      可携带的产物
  pixelate.py      把插画压成像素稿（众数采样 / 减色 / 取样策略 / 头部加权 / 轮廓）
  library.py       零件目录的清点
  assets/          font5x7.txt
corpus/            语料政策与事实清单（POLICY / SAMPLES / AESTHETICS / REFERENCES / manifest）
test/              12 个测试文件，357 条
tools/             开发期工具（calibrate、corpus、probe_* 一组探针）
.github/workflows/ 发布与 CI
```

## 模块职责

`builder.py` 是核心，也是唯一直接写格子的地方。所有写入集中在 `_write`：遮罩、越界裁剪、单位吸附都在那一条路上生效。这一条不是设计洁癖 —— 遮罩若只在 `put` 上生效，`blit` 就会漏，而漏的方式在简单用例里看不出来。

`cli.py` 把脚本（JSON）翻译成动词序列。可撤销的步骤进历史，`mask` 与 `unit` 这类条件不进 —— 它们描述的是作画条件，不是画。

`judge.py` 与 `calibration.py` 分工明确：前者量，后者比对参考带。`profile.py` 只回答「离哪一代更近」，且在两代都为零距离时拒绝区分。

`pixelate.py` 是唯一读外部图片的模块，产出的是**稿子**而非成品：它的输出适合交给 `grid` 继续改。

## 数据流

```
形状脚本（JSON）或 一张插画
  -> cli.plan_steps 校验 -> apply_plan 逐条执行
  -> Canvas / Layers（格子）
  -> 输出：PNG · 网格 JSON（可编辑、可回读）· 判据报告 · 数据图 · 动图帧
```

## 入口与命令

```
ichiwatashi build sprite.json --out sprite.png [--preview 1] [--hide layer] [--no-hints]
ichiwatashi grid sprite.json --out sprite-grid.json
ichiwatashi judge IMAGE [--generation th155]         # 量，不判
ichiwatashi profile IMAGE --generation th123         # 定位，不下结论
ichiwatashi pixelate IMAGE --out out.png --width 320 --colours 0 --sample contrast
ichiwatashi library DIR                              # 零件目录清点
ichiwatashi panel / frames / window / ...
```

## 测试与验证

`test/` 12 个文件，`python -m unittest discover -s test -t .`（357 条通过、1 条跳过）。按能力分组：构造（`test_mirror`、`test_part`、`test_layers`、`test_regions`、`test_mask`、`test_unit`）、判断（`test_profile`、`test_ichiwatashi`）、输出与提示（`test_audit`、`test_library`、`test_pixelate`）。

新增守卫一律先证明能失败：关掉遮罩检查会让十四条里八条红；把 `flip` 的 `stamp` 换成 `blit`，恰好那条指名失败的测试红。

## 边界

不判定画得好不好，只报可核对的矛盾；不区分两代都为零距离的图；不发明超出源图的像素。`--edges` 目前在命令行上被拒绝，实现留在库里。

## 发布

`pyproject.toml` 定义包；tag 触发 `.github/workflows/release.yml`，Trusted Publishing 到 PyPI，GitHub release 带发布记录。sdist 发布前解包并自跑测试。
