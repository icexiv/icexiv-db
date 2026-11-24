# icexiv-db

基于 Notist 的 FF14 静态资料站，属于 IceXIV 网站组。
物品记录与图标均从同一份国服游戏安装读取，浏览器消费 HTML、PNG 和精简搜索索引。

## 数据与页面链路

1. **游戏导出**：`tools/game-export` 调用 `icexiv-data` 读取 SqPack 中的 Item EXH/EXD，
   提取字段与文本，按 Icon ID 去重解码 TEX 并编码透明 PNG。
2. **数据准备**：`scripts/items.py prepare` 校验导出清单、schema、JSON 与图片哈希，
   生成 `content/.data/` 分片与准备凭据，以及 `static/generated/` 搜索索引及图标。
3. **静态生成**：Notist 启动 `scripts/items.py extension`。`before_compile` 在内存中生成物品与目录的
   `.md` 文档，调用 `modules/views.not` 读取分片生成正文，并把手册章节加入文档集合。扩展在同一进程内保存目录元数据，
   在 `before_template` 注入 `site.data.catalog`，Tera 模板生成页面外壳。
4. **浏览与搜索**：普通分页和详情不依赖 JavaScript；`static/catalog.js` 加载搜索索引，
   按名称或 ID 过滤并渲染分页结果。图片 URL 与静态目录一致。

首页和物品目录共用检索器，支持全部、装备、素材和解锁视图。收录规则为 ID 非零且名称非空，
不限可交易物品；每页 100 件。物品详情路径为 `items/{id}.html`。条目存在不代表游戏内可获得。
中文类型与浏览分组见[物品分类](docs/item-categories.md)。

装备检索额外使用 `sources/equipment.json`：物品品级、部位和职业来自国服 CSV 对照，
仅当 `items.json` 的 SHA-256 完全匹配时才载入；其他导出仍支持基本分类和装备等级检索。
更新时将同一批次的 `Item.csv`、`ClassJob.csv`、`ClassJobCategory.csv` 和
`EquipSlotCategory.csv` 放在同一目录，运行 `python3 scripts/equipment_snapshot.py CSV目录 inputs/game-export/items.json`，
再执行 `prepare`。普通构建不读取 CSV，也不联网。

字段映射绑定 `sources/item-schema.json` 中的客户端版本和 Item EXH SHA-256。
版本、结构或类型不匹配时导出失败，不猜测字段。没有配置或确认缺失的图标使用问号占位；
访问、解码或写入失败记录为错误，数据准备拒绝这类导出。

开发笔记：[游戏数据的判定口径](docs/game-data-rules.md)，涵盖时装、首次收录版本、解锁分类、部位与职业分组，以及这些信息能说明什么。

## 开发与构建

生成首次收录版本快照：`python3 scripts/release_snapshot.py 国服历史仓库路径 Garland的patches.json inputs/game-export/items.json`。构建和查询不需要联网。

需要 Nix Flakes。开发布局为相邻的 `icexiv-db/` 和 `icexiv-data/`，Rust 导出工具通过
Cargo path 依赖使用后者。开发环境提供 Rust、Notist、Python 3 和 Node.js。

```sh
nix develop

# 显式读取安装数据；输出目录必须不存在，父目录需存在。
cargo run --release --locked --manifest-path tools/game-export/Cargo.toml -- \
  sources/item-schema.json ~/Games/ffxiv inputs/game-export

# 只读取导出包，不访问游戏或网络。
python3 scripts/items.py prepare

# 构建到 notist-output/icexiv-db/；发布此目录内容。
notist build
python3 scripts/check_site.py
```

导出器读取安装根目录下的 `game/ffxivgame.ver` 与 `game/sqpack/`，导出前后复核版本。
导出期间保持安装数据不变；相同版本号不能证明所有容器属于同一个原子快照。
更换客户端版本时需要核验字段语义与 EXH，更新 schema，再使用新目录重新导出。
`--inspect` 可输出 EXH 的哈希、列类型、偏移和语言：

```sh
cargo run --locked --manifest-path tools/game-export/Cargo.toml -- --inspect ~/Games/ffxiv
```

Notist 需要具备 Tera 2、notc 的 `for` / `str` / 数据读取功能，以及足够的站点输入预算。
全量站点使用的输入请求额度为 1,000,000。与本地 Notist 工作区联调时显式覆盖输入，
不将本机路径写进依赖锁：

```sh
nix develop --no-write-lock-file --override-input notist /path/to/notist
```

### Nix 沙箱构建

沙箱不读取本机安装，不下载物品数据，也不隐式导出游戏文件。
`lib.<system>.mkSite` 接受显式提供的导出包路径，完成校验、准备、构建和链接检查。
导出包会进入 Nix store；注意磁盘空间和游戏资产的分发权限。

```sh
nix build --impure --expr '
  let project = builtins.getFlake (toString ./.);
  in project.lib.${builtins.currentSystem}.mkSite {
    gameExport = /absolute/path/to/game-export;
  }
'

# 单独构建 Notist；无默认站点包，以免隐藏游戏输入要求。
nix build .#notist
```

## 验证

```sh
python3 -m unittest discover -s tests -v
node --test tests/catalog.test.cjs
cargo test --locked --manifest-path tools/game-export/Cargo.toml

# 可选集成测试只使用合成 SqPack/EXH/EXD/TEX，不读取安装数据。
cargo build --locked --manifest-path tools/game-export/Cargo.toml
GAME_EXPORT_TEST_BIN="$PWD/tools/game-export/target/debug/icexiv-db-game-export" \
  NOTIST_TEST_BIN=/path/to/notist python3 -m unittest discover -s tests -v

nix flake check
nix fmt
```

## 文件与生成目录

- `tools/game-export/`：游戏数据导出工具，含文本投影与 PNG 编码。
- `sources/item-schema.json`：版本化 Item 字段映射及 EXH 哈希。
- `scripts/items.py`：导出包校验、分片、索引与 Notist 站点扩展。
- `modules/views.notc`：物品详情和目录正文。
- `templates/`：Tera 页面外壳、导航、页脚和搜索参数。
- `static/`：CSS、搜索脚本、占位图与生成的公开资产。
- `inputs/game-export/`：忽略的原始导出包；不由 prepare 清理。
- `content/.data/`：忽略的私有正文分片，不发布；`prepared.json` 在准备完成后记录导出清单摘要。
- `site.data.catalog`：扩展按已验证的导出生成的版本、导出身份、计数和搜索配置，不依赖数据文件。
- `static/generated/`：忽略的公开搜索索引与 PNG，路径含导出清单摘要。

`content/.data/` 与 `static/generated/` 由准备脚本独占并重建，不放手写文件。
导出清单与准备凭据不一致时构建失败，需重新执行 `prepare`。
`Notist.toml` 的 `base_url` 为 `/`；Pages 打包时将站内根路径转为相对路径。

## 发布

`main` 上的 GitHub Actions 从本仓库 Release `export-2026.10.06` 读取
`game-export.tar.gz`，用 `sources/game-export.sha256` 校验后生成全量站点。
更新数据时，从 `inputs/` 用 GNU tar 的 `--sort=name --mtime=@0 --owner=0
--group=0 --numeric-owner` 打包 `game-export/`，通过 `gzip -n -1` 压缩；
在新标签上传归档，并一起更新工作流里的标签和校验和。PR 使用离线样例。

- **Pages**：`https://icexiv.github.io/icexiv-db/`，站内链接相对当前页面，无备案和统计。
- **国内站**：`https://db.icexiv.top/`，含 ICP、公安备案和 Medama 访问统计。
  部署密钥由 `DEPLOY_SSH_KEY` 提供，`DEPLOY_KNOWN_HOSTS` 固定 SSH 主机公钥；
  服务端用 `restrict,command="/usr/bin/rrsync -wo /srv/db.icexiv.top/www"` 限定部署目录。

DNS 的 `db` A 记录指向国内源站。Caddyfile 顶层导入 `ops/db.caddy`，
Medama 注册 `db.icexiv.top` 后重启加载。只转发 ping 和同源 hit；
物品详情与分页按页面类型汇总，不传查询词、URL 参数或外站来源路径，尊重 DNT/GPC。
