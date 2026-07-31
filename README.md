# Disney Vault · 迪士尼影视作品数据库

一个无需构建工具、可直接运行的纯前端影视资料库，覆盖迪士尼动画、皮克斯、漫威、星球大战、二十世纪影业、真人电影与自然纪录片。完整离线目录由 Wikipedia 分类与 Wikidata 结构化资料生成，并与人工整理的中文代表作数据合并。

## 运行

推荐在项目目录启动一个本地静态服务器：

```bash
python3 -m http.server 8000
```

然后访问 <http://localhost:8000>。

也可以直接双击 `index.html` 打开。项目通过 `data/movies.js` 离线镜像支持 `file://` 场景；浏览器通常会阻止页面在 `file://` 下通过 `fetch` 读取 JSON，因此推荐使用本地服务器获得完整的数据请求流程。

## 数据降级策略

`app.js` 会依次：

1. 分页请求 Disney API 的角色关联影视作品；
2. 若请求失败或返回量不足，请求 Disney Movies API；
3. 若仍失败或数据不足，读取 `data/movies.json`；
4. 在直接打开页面、浏览器不允许读取本地 JSON 时，使用内容相同的 `data/movies.js` 离线镜像。

远程数据会与本地精选条目合并去重，因此中文片名、厂牌和详情信息在 API 可用时也能保留。

## 功能

- 中文与英文片名即时模糊搜索
- 七大厂牌筛选
- 年份升序 / 降序
- 首页精选海报排序，可切换年份升序 / 降序
- 每页 24 张卡片，避免大量 DOM 节点造成卡顿
- 影片详情弹窗（导演、主演/配音、评分、片长与简介）
- 明确的加载、数据源降级与空结果状态
- 桌面、平板及 375px 手机宽度响应式布局

详情页保留中英文片名；导演、演员与配音信息使用英文展示，影片简介采用英文原文在上、中文翻译在下的固定双语结构。条目会根据已有年份、厂牌、片长、导演、演职员和简介显示资料完整度。

### 后续数据迭代建议

1. 补全编剧、角色名与演员/配音的对应关系，而不只保存姓名列表。
2. 补全类型、制片国家/地区、原始语言、首映日期和准确片长。
3. 增加 IMDb、Wikidata、Wikipedia 等稳定外部标识，便于去重和持续更新。
4. 将评分明确标注来源和更新时间，避免不同平台评分混用。
5. 增加人物详情页和作品关联，让导演、演员、角色可以反向浏览其作品。

### 数据质量规则

- 全库保留所有 3,534 条影片记录；疑似重复或错配的条目进入资料复核状态，不以删除影片的方式处理。
- 百科简介若实际指向演员、虚构角色、动物物种、电视系列或乐园设施，不作为电影简介展示。
- “某作品是迪士尼目录中的电影”一类模板句不计入简介；详情页会明确标记来源待复核。
- 已确认误连到非电影百科页面的记录仍保留影片条目，但隐藏错误简介并标记为待复核，直到获得可靠的电影页面或稳定外部 ID。

## 部署到 GitHub Pages

1. 将本目录提交并推送到 GitHub 仓库。
2. 打开仓库的 **Settings → Pages**。
3. 在 **Build and deployment** 中选择 **Deploy from a branch**。
4. 选择要发布的分支（通常是 `main`）及根目录 `/ (root)`，保存。
5. 等待 GitHub Pages 给出公开网址。

本项目只使用相对路径，无需修改即可部署在仓库子路径下。第三方 API 若因 CORS、限流或网络不可用而失败，站点会自动使用本地数据。

## 项目结构

```text
.
├── index.html
├── style.css
├── app.js
├── data
│   ├── movies.json
│   └── movies.js
└── README.md
```

`data/movies.js` 是为满足直接打开 `index.html` 的离线兼容镜像；权威本地兜底文件仍为 `data/movies.json`。

## 更新百科片库

需要联网，并要求系统安装 `curl`：

```bash
python3 scripts/sync_wikimedia.py
```

脚本从 Wikipedia 的迪士尼旗下主要电影分类获取影片列表，并通过 Wikipedia/Wikidata 补充中文标题、首映年份、简介、页面图片、导演和来源链接。生成结果会同时写入 `data/movies.json` 与供 `file://` 使用的 `data/movies.js`。Wikidata 结构化数据采用 CC0；Wikipedia 摘要与图片的具体许可请以相应来源页面为准。

如需为没有中文百科标签的长尾影片补齐中文名，运行 `python3 scripts/enrich_chinese_titles.py`。脚本优先采用 Wikidata 中文标签，其余条目使用机器辅助译名，并通过 `title_cn_source` 字段明确标记，不将其冒充为官方译名。

运行 `python3 scripts/enrich_movie_details.py` 可通过 Wikidata 的导演、演员及配音属性补齐双语演职人员，并生成 `summary_cn` / `summary_en` 双语简介。中文机器译文缓存于 `data/chinese_summaries.json`，人员标签缓存于 `data/people_labels.json`。

首页精选作品的海报预览图片来自 [The Movie Database (TMDB)](https://www.themoviedb.org/)。本项目不受 TMDB 认可或认证。
