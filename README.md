# icexiv-db

基于 Notist 的数据驱动 FF14 Wiki，属于 IceXIV 网站组。

仓库：<https://github.com/icexiv/icexiv-db>（原项目名 `xiv-db`）。

当前提供国服物品目录预览，尚未配置生产域名或部署上线。

页面正文已迁移到 notc：站点扩展为每个页面生成 `.not` 源，正文由 `modules/views.notc` 组织，模板只负责页面外壳、导航和目录页配置。模板使用 Tera 2（`.tera`），不再兼容 Handlebars 版 Notist。完整迁移依赖 Notist 工作区中尚未发布的 notc 循环、`str` 与站点请求预算修复，本地联调方式见下文。

## 物品目录

- 基于固定 commit 的 `Item.csv`，收录 ID 非零且名称非空的条目，不限可交易物品。
- 按名称或 ID 子串搜索，每页 100 件，搜索词和页码保存在 URL，支持浏览器前进与后退。
- 详情链接形如 `items/1.html`，描述和基本字段直接存在 HTML 中，不需要 JavaScript。
- Notist 站点扩展从 CSV 生成全部物品页与分页目录的 `.not` 源；每页把私有数据分片的 Path 与索引交给 `modules/views.notc`，由 notc 读取并构建正文。
- 模板不再查询 `site.data.items` 或分页实体数据；`data/catalog.json` 只保留版本、数量和搜索索引位置等页面外壳配置，正文数据位于隐藏的 `content/.data/`。
- 浏览器只为搜索加载精简索引。
- 目录、搜索和详情使用构建期导出的 PNG 图标；未提供图标资源时显示占位图。分类中文名和获取来源未收录。条目存在不代表当前可获得，未展示来源不代表无法获得。

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

Notist 发布下述改动后，也可以直接 `nix build`：Nix 根据固定 URL 与哈希获取 CSV，在沙箱中准备数据并构建，不需要先执行 fetch/prepare。正常进入 `nix develop` 不会下载游戏数据。

本次全量构建使用 Notist 本地工作区中的 Tera 2、notc 数据与循环、SSG 上下文复用和站点请求预算修复；这些改动尚未包含在当前锁定的远端版本中。`flake.lock` 已更新到最新的远端提交，但当前迁移还要求工作区中的 `for` 与 `str` 支持，以及 SSG 将默认的 16384 次输入请求预算提高到 1,000,000、提高站点数据缓存额度；否则 51k 页站点会在加载共享 notc 模块或缓存数据投影时触发预算错误。开发联调使用显式 override，不把本机路径写进项目依赖：

```sh
nix build --no-write-lock-file --override-input notist /home/azurice/Files/notist

# 或进入包含新版 Notist 的开发环境，再执行 prepare/build/serve。
nix develop --no-write-lock-file --override-input notist /home/azurice/Files/notist

# 已在本机构建新版 release 二进制时，也可直接运行。
/home/azurice/Files/notist/target/release/notist build
```

Notist 发布上述改动后更新输入锁定，再使用默认 `nix build` 验证。缺少 notc 循环或站点请求预算修复的 Notist 无法构建当前站点。

`sources/item.json` 是数据锁定清单，记录仓库、完整 commit、游戏版本、路径及 SHA-256。更新时先检查上游提交，再修改清单，重新 fetch/prepare 和验证；构建不会自动跟随 master。当前来源为 `master` 的传统三行表头格式，不兼容直接替换成 `exd-schema` 分支。

### 物品图标

`tools/icon-export` 是调用 `icexiv-data` 的离线 Rust 工具，按 Icon ID 去重，优先读取
`_hr1.tex`，仅在资源确认不存在时尝试普通纹理。PNG 保留透明度。读取或解码失败会记录
在 `manifest.json` 并返回非零退出码，`prepare --icons` 拒绝包含失败或缺项的导出。

开发目录布局为相邻的 `icexiv-db/` 与 `icexiv-data/`；工具的 Cargo path 依赖直接使用
相邻库中的纹理实现，不属于站点 Nix 沙箱构建的依赖。以下命令在 `icexiv-db` 开发环境中执行：

```sh
python3 scripts/items.py icons-request

# 必须先确认安装版本与 sources/item.json 的 gameVersion 一致。
# 版本参数是调用者对安装版本的声明，工具不会自动探测客户端版本。
# 输出目录的父目录需存在，输出目录本身必须不存在。
cargo run --release --locked --manifest-path tools/icon-export/Cargo.toml -- \
  inputs/icons-request.json /path/to/game/sqpack 2026.10.06.0000.0000 inputs/icons

python3 scripts/items.py prepare --icons inputs/icons
notist build
python3 scripts/check_site.py
```

导出期间保持安装数据不变。`prepare` 校验 CSV 哈希、游戏版本、每张 PNG 的哈希和尺寸，
并将图片复制进带版本摘要的 `static/generated/`；原始导出不受生成目录清理影响。
不带 `--icons` 的 `prepare` 和默认 `nix build` 使用占位图，不会读取安装目录。
资源映射和测试来源见 [图标资产](docs/icon-assets.md)。

## 开发环境

安装支持 Flakes 的 Nix，然后运行：

```sh
# Notist 改动发布前，使用本地工作区。
nix develop --no-write-lock-file --override-input notist /home/azurice/Files/notist
python3 scripts/items.py fetch
python3 scripts/items.py prepare
notist serve --address 127.0.0.1:8000
```

访问 <http://127.0.0.1:8000>，从首页进入物品目录。完成数据准备后，也可直接执行：

```sh
nix develop --no-write-lock-file --override-input notist /home/azurice/Files/notist \
  -c notist serve --address 127.0.0.1:8000
```

Notist 改动发布后去掉 `--no-write-lock-file` 与 `--override-input`。使用 direnv 时，在审核 `.envrc` 后运行 `direnv allow`。

环境通过 Crane `devShell` 提供 Rust nightly 2026-10-01、Cargo、rustfmt、
Clippy、rust-src、rust-analyzer，以及 Notist、Git、Python 3 和 Node.js。
`tools/icon-export` 使用此环境编译；站点数据准备脚本使用 Python 标准库。

## 构建与检查

Notist 改动发布前，将下面命令中的 `nix develop -c ...` 换成
`nix develop --no-write-lock-file --override-input notist /home/azurice/Files/notist -c ...`。

```sh
# 构建到 dist/icexiv-db/
nix develop -c notist build

# 检查内容
nix develop -c notist check content

# CSV 解析与数据校验测试
python3 -m unittest discover -s tests -v
node --test tests/catalog.test.cjs

# 图标导出工具的合成纹理测试
cargo test --locked --manifest-path tools/icon-export/Cargo.toml

# 可选的离线集成测试：导出工具与 Notist 二进制均需先构建。
# NOTIST_TEST_BIN 指向包含 notc for/str 支持的二进制。
cargo build --locked --manifest-path tools/icon-export/Cargo.toml
ICON_EXPORT_TEST_BIN="$PWD/tools/icon-export/target/debug/icexiv-db-icon-export" \
  NOTIST_TEST_BIN=/path/to/notist python3 -m unittest discover -s tests -v

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
- `content/`：手写页面源码；物品与目录页由站点扩展在内存中生成。`content/.data/` 是隐藏的只读分片输入，不发布。
- `modules/views.notc`：物品详情与目录分页的正文函数；读取构建期分片数据，构建标题、字段、表格和分页。
- `templates/`：Tera 2 页面外壳；include 共享页面上下文，正文通过 safe 输出。目录页的搜索配置由模板按页面路径输出，不包含实体数据。
- `static/`：直接发布的 CSS、搜索脚本与生成的搜索索引。
- `sources/item.json`：上游数据锁定清单。
- `scripts/items.py`：下载、校验、离线转换及 Notist prepare 扩展，仅使用 Python 标准库。
- `tools/icon-export/`：从 SqPack 批量导出物品图标和校验清单的 Rust 工具。
- `inputs/`、`data/`、`content/.data/`、`static/generated/`：忽略的输入与生成目录；`data/catalog.json`、`content/.data/` 与 `static/generated/` 由脚本独占并重建，不要手写内容。
- `flake.nix` / `flake.lock`：开发环境、站点构建与依赖锁定。

使用当前 Notist 的 `[[site]]`、`notist build` / `notist serve` 接口，
而不是旧版 `[ssg]` / `notist ssg` 接口。

模板名不带扩展名，例如 `{% include 'head' %}`。整站信息通过 site、当前页面通过 page 访问。生成页面的标题来自 notc 输出的第一个标题；物品字段、目录表格和静态分页都在 `modules/views.notc` 中组装。搜索表单和动态分页由 `static/catalog.js` 在浏览器中创建，静态页面不依赖它。

迁移前后的全量 release 构建性能及产物校验见 [Tera 2 迁移性能记录](docs/performance-2026-10-31.md)。

当前构建的阶段计时、CPU 采样和优化优先级见 [Tera 2 构建耗时剖析](docs/profile-2026-10-31.md)。

Registry 与共享上下文的四步实现、逐步收益和五轮原始值见 [分步优化记录](docs/registry-context-2026-10-31.md)。

Prepare 编码、目录摘要、语义 Registry 与环境查询的后续实测见 [Prepare 与语义环境优化记录](docs/prepare-environment-2026-10-31.md)。

模板正文迁移到 notc 的动机、数据流、Notist 侧修复和全量构建结果见 [notc 页面迁移记录](docs/notc-migration-2026-11-03.md)。

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
