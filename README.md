# icexiv-db

基于 Notist 的数据驱动 FF14 Wiki，属于 IceXIV 网站组。

仓库：<https://github.com/icexiv/icexiv-db>（原项目名 `xiv-db`）。

当前提供国服物品目录预览，尚未配置生产域名或部署上线。

模板已迁移到 Tera 2（`.tera`），需要支持 Tera 2 的 Notist；不再兼容 Handlebars 版 Notist。当前远端依赖锁尚未包含此迁移，下面的 Nix 命令需在更新锁定后使用；本地联调方式见下文。

## 物品目录

- 基于固定 commit 的 `Item.csv`，收录 ID 非零且名称非空的条目，不限可交易物品。
- 按名称或 ID 子串搜索，每页 100 件，搜索词和页码保存在 URL，支持浏览器前进与后退。
- 详情链接形如 `items/1.html`，描述和基本字段直接存在 HTML 中，不需要 JavaScript。
- Notist 站点扩展从 CSV 生成全部物品页与分页目录；浏览器只为搜索加载精简索引。
- 分页模板数据只保存 id/path/name/category 摘要；完整物品描述和属性保留在 site.data.items，详情 HTML 不受影响。
- 当前未接入图标图片、分类中文名和获取来源。条目存在不代表当前可获得，未展示来源不代表无法获得。

关闭 JavaScript 或搜索索引加载失败时，仍可浏览全部分页目录和物品详情。这里也是 Notist 数据驱动 SSG 的实践评估：构建性能问题应在 Notist 侧定位，而不是改成浏览器加载详情来绕过。

## 数据准备与构建

```sh
# 下载 sources/item.json 固定的 CSV，并校验 SHA-256；仅这一步需要网络。
nix develop -c python3 scripts/items.py fetch

# 从已下载输入生成版本元数据与搜索索引，不访问网络。
nix develop -c python3 scripts/items.py prepare

# 构建到 dist/icexiv-db/
nix develop -c notist build
```

或者直接 `nix build`：Nix 根据固定 URL 与哈希获取 CSV，在沙箱中准备数据并构建，不需要先执行 fetch/prepare。正常进入 `nix develop` 不会下载游戏数据。

本次全量构建使用 Notist 本地工作区中的 Tera 2 引擎及 SSG 优化；这些改动尚未包含在当前锁定的远端版本中，默认 flake.lock 仍固定旧版。开发联调使用显式 override，不把本机路径写进项目依赖：

```sh
nix build --no-write-lock-file --override-input notist /home/azurice/Files/notist

# 或进入包含新版 Notist 的开发环境，再执行 prepare/build/serve。
nix develop --no-write-lock-file --override-input notist /home/azurice/Files/notist

# 已在本机构建新版 release 二进制时，也可直接运行。
/home/azurice/Files/notist/target/release/notist build
```

Notist 迁移发布后更新输入锁定，再使用默认 `nix build` 验证。旧版 Notist 无法渲染 `.tera` 模板，不可用于本项目的当前模板。

`sources/item.json` 是数据锁定清单，记录仓库、完整 commit、游戏版本、路径及 SHA-256。更新时先检查上游提交，再修改清单，重新 fetch/prepare 和验证；构建不会自动跟随 master。当前来源为 `master` 的传统三行表头格式，不兼容直接替换成 `exd-schema` 分支。

## 开发环境

安装支持 Flakes 的 Nix，然后运行：

```sh
nix develop
python3 scripts/items.py fetch
python3 scripts/items.py prepare
notist serve --address 127.0.0.1:8000
```

访问 <http://127.0.0.1:8000>，从首页进入物品目录。完成数据准备后，也可直接执行：

```sh
nix develop -c notist serve --address 127.0.0.1:8000
```

使用 direnv 时，在审核 `.envrc` 后运行 `direnv allow`。

环境通过 Crane `devShell` 提供 Rust nightly 2026-10-01、Cargo、rustfmt、
Clippy、rust-src、rust-analyzer，以及 Notist、Git 和 Python 3。
目前未创建 Rust crate，后续数据工具可直接使用此环境开发。

## 构建与检查

```sh
# 构建到 dist/icexiv-db/
nix develop -c notist build

# 检查内容
nix develop -c notist check content

# CSV 解析与数据校验测试
python3 -m unittest discover -s tests -v

# 构建后验证全量详情、分页数量与所有本地 HTML 链接
python3 scripts/check_site.py

# Nix 沙箱内构建；result/ 是静态站点根目录
nix build

# 构建检查及 Nix 格式化
nix flake check
nix fmt
```

## 目录

- `Notist.toml`：项目与 Site target 配置。
- `content/`：Notist / Markdown 页面源码。
- `templates/`：Tera 2 页面模板；include 共享页面上下文，普通字段自动转义，已渲染正文通过 safe 输出。
- `static/`：直接发布的 CSS 等资源。
- `sources/item.json`：上游数据锁定清单。
- `scripts/items.py`：下载、校验、离线转换及 Notist prepare 扩展，仅使用 Python 标准库。
- `inputs/`、`data/`、`static/generated/`：忽略的输入与生成目录；`static/generated/` 由脚本独占并重建，不要手写内容。
- `flake.nix` / `flake.lock`：开发环境、站点构建与依赖锁定。

使用当前 Notist 的 `[[site]]`、`notist build` / `notist serve` 接口，
而不是旧版 `[ssg]` / `notist ssg` 接口。

模板名不带扩展名，例如 `{% include 'head' %}`。整站信息通过 site、当前页面通过 page 访问；详情使用 `site.data.items[page.attrs.item_id]` 查询，目录使用 `site.data.catalog.pages[page.attrs.catalog_page]` 查询，不再依赖 Handlebars 的 lookup、@root 或隐式上下文切换。

迁移前后的全量 release 构建性能及产物校验见 [Tera 2 迁移性能记录](docs/performance-2026-10-31.md)。

当前构建的阶段计时、CPU 采样和优化优先级见 [Tera 2 构建耗时剖析](docs/profile-2026-10-31.md)。

Registry 与共享上下文的四步实现、逐步收益和五轮原始值见 [分步优化记录](docs/registry-context-2026-10-31.md)。

Prepare 编码、目录摘要、语义 Registry 与环境查询的后续实测见 [Prepare 与语义环境优化记录](docs/prepare-environment-2026-10-31.md)。

## 依赖与发布

Notist 来自 `github:AzurIce/notist`；Nixpkgs、Crane、rust-overlay 和 flake-utils
共享 Notist 的依赖锁定，避免重复的依赖图。不依赖相邻目录中的 Notist 源码。

更新 Notist 及其上游锁定依赖后，应重新执行构建检查：

```sh
nix flake update notist
nix flake check
```

`base_url` 暂设为 `/`。确定正式域名后再修改 `Notist.toml`，部署时发布
`dist/icexiv-db/` 的内容，或使用 `nix build` 的产物。
