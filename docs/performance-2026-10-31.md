# XIV DB：Handlebars → Tera 2 迁移与性能对照

日期：2026-10-31。

## 结论

迁移 6 个页面/局部模板到 `.tera`，保留全部静态详情、目录分页和浏览器搜索功能，不修改 CSV 解析或生成文档的 prepare 扩展。

在本机完整 release 构建中，五轮耗时中位数由 **6.489 s → 6.026 s，减少 7.14%**，约 **1.077 倍**速度；峰值 RSS 中位数由 **2.502 GiB → 2.360 GiB，减少 145.11 MiB / 5.66%**。这是整站构建的温缓存测量，不是模板引擎的独立微基准，也不是冷启动、增量构建或内存分配剖析。

## 对照条件

- CPU：AMD Ryzen 9 9950X3D2 16-Core Processor，32 逻辑 CPU。
- 系统：Linux 7.2.12 x86_64，glibc 2.44。
- 当前工具链：rustc 1.97.1；两边均使用本地 release 二进制。Handlebars 二进制在重新编译 Tera 版之前保存。
- 基线是已经优化过的 Handlebars 版本：整站上下文复用、发布路径冲突检查优化、`{{> head page}}` 等显式 partial 上下文。不拿早先未优化的平方级实现作为对照。
- 新版是 Tera 2.4.0，使用普通 include、显式变量及动态下标查询；普通字段自动转义，只有已渲染的 page.html 使用 safe。
- 两边使用同一份站点快照、CSV、Python 脚本、静态资源、Notist.toml 和输出路径，只切换二进制与模板。没有下载数据，没有裁剪物品数量。
- 每边先完整预热一次，再各测五轮；轮内顺序交替为 H/T、T/H、H/T、T/H、H/T。没有并发执行构建或编译。
- 计时范围：`notist build` 进程启动至退出，含 Python prepare 扩展、内容处理、模板渲染及文件发布；不含首次编译、CSV 下载、单独的数据 prepare、HTML 解析或链接校验。
- 文件系统缓存已热，不做 fsync，不据此推断冷盘性能。
- 峰值 RSS 取 Linux `wait4` 的 `ru_maxrss`，单位 KiB，是命令及后代的高水位口径，不是进程树同时驻留内存总和。CPU 时间为该口径下 user + system。
- 测量工具在第五轮前遇到 120 s 总超时；已完成的四轮保存，第五轮重新执行。被中止的构建未计入结果。

## 输入与产物验证

- 上游 commit：`2c6741cffe3cfe70f093c54c463791364e515d8d`。
- 客户端版本：`2026.10.06.0000.0000`。
- Item.csv SHA-256：`abb68a057f68e4d9d37eae76d31354555d30f76a88554d0d1c04315598c7268f`。
- 两边均为 **51,225 详情 + 513 目录 + 1 首页 = 51,739 张 HTML**，输出路径集合一致。
- 两边均运行 scripts/check_site.py：全部详情与目录数量正确，所有本地 HTML href/src 均指向存在的目标；详情仍不依赖 JavaScript。
- 对全部 HTML 使用 Python HTMLParser 解码实体、排序属性并忽略纯空白文本节点后，元素、属性、非空文本 token 序列的 SHA-256 全部一致。
- 非 HTML 文件（含搜索索引、CSS、JS）逐字节一致。
- HTML **不是逐字节相同**：总量从 112,544,774 增至 113,167,656 bytes，增加 622,882 bytes / 0.553%。模板引擎的空白处理等序列化差异没有通过压缩或特殊裁剪掩盖。
- Python 数据测试 9 项全部通过；迁移后的实际项目目录另外执行完整构建和全站链接检查。

## 汇总

| 指标 | Handlebars | Tera 2 | 变化 |
| --- | ---: | ---: | ---: |
| 完整构建耗时中位数 | 6.489080 s | 6.025502 s | −7.14% |
| 最短耗时 | 6.479656 s | 6.001507 s | |
| 最长耗时 | 6.562216 s | 6.079082 s | |
| CPU 时间中位数 | 6.447912 s | 5.996464 s | −7.00% |
| 峰值 RSS 中位数 | 2,623,492 KiB | 2,474,896 KiB | −5.66% |
| HTML 总字节 | 112,544,774 | 113,167,656 | +0.553% |

## 各轮原始值

| 轮次 | H 耗时 s | T 耗时 s | H RSS KiB | T RSS KiB |
| --- | ---: | ---: | ---: | ---: |
| 1 | 6.489080 | 6.025502 | 2,623,460 | 2,473,800 |
| 2 | 6.559271 | 6.032320 | 2,623,804 | 2,475,148 |
| 3 | 6.483276 | 6.079082 | 2,623,988 | 2,475,052 |
| 4 | 6.479656 | 6.001507 | 2,623,352 | 2,474,896 |
| 5 | 6.562216 | 6.002627 | 2,623,492 | 2,474,252 |

不计入统计的预热：H 6.215148 s / 2,623,620 KiB；T 6.066515 s / 2,476,472 KiB。

## 复现与记录

本次本地原始记录与站点快照位于 `/tmp/opencode/xiv-db-tera-comparison/`：

- benchmark.py：计时、模板切换、完整产物对比脚本；已存在 results.json 时跳过已完成轮次，重新测量需另建结果目录。
- results.json：包含每轮 wall/user/system/RSS、二进制哈希和验证结果。
- handlebars-inventory.json、tera-inventory.json：全量文件清单及原始/归一化哈希。
- notist-handlebars、notist-tera：本次对照的两个二进制。
- templates-handlebars/、templates-tera/：原始与迁移后的模板快照。
- site/：脱离 Git、direnv 和原输出目录的可重建站点快照。

临时目录不是永久归档；关键结果、条件和原始轮次已保存在本文中。

二进制 SHA-256：

```text
Handlebars afe6a72b6a097638d40f48d81c1a6f54372ef188d9eb14a80199fdbba85e60e0
Tera 2     879c608419e5c0b7169982195a2ada771c0627b40cd494b4e7c480143632954d
```

当前项目的验证命令：

```sh
# 先在 Notist 工作区编译新版。
cargo build -p notist-cli --release --manifest-path /home/azurice/Files/notist/Cargo.toml

# 在 xiv-db 根目录运行；CSV 和 prepare 数据已就绪。
python3 -m unittest discover -s tests -v
/home/azurice/Files/notist/target/release/notist build
python3 scripts/check_site.py
```

flake.lock 仍固定远端旧版 Notist，此次未更改依赖锁，也未重跑 Nix 沙箱构建。必须使用新版二进制或本地 input override；Notist 迁移发布后再更新锁。Nix 的 Git 源码快照不会包含未跟踪文件，新 `.tera` 模板需纳入 Git 后再做 Nix 验证。本次没有更改用户暂存区。

## 如何解读

Tera 2 在这个已经优化过的真实站点上带来稳定但有限的整站收益，没有数量级加速。完整构建还包含 Python 扩展、文档处理和文件发布，不能把这里的 7.14% 当作纯模板执行差异，也不能据此声称瓶颈已经被精确定位。内存仍约 2.36 GiB，不代表已经实现流式或增量构建。
