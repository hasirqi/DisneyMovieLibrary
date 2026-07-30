# Disney Vault · 迪士尼影视作品数据库

一个无需构建工具、可直接运行的纯前端影视资料库，覆盖迪士尼动画、皮克斯、漫威、星球大战、二十世纪影业、真人电影与自然纪录片。

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
- 每页 24 张卡片，避免大量 DOM 节点造成卡顿
- 影片详情弹窗（导演、主演/配音、评分、片长与简介）
- 明确的加载、数据源降级与空结果状态
- 桌面、平板及 375px 手机宽度响应式布局

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
