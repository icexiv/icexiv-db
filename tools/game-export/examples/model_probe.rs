//! Read-only, line-oriented SqPack probe used by scripts/pipeline/model_audit.py.
use icexiv_data::{
    excel::{Exd, Exh, Language, Value},
    mdl::Mdl,
    sgb::{DependencyKind, Sgb},
    sqpack::{SqPack, index::IndexKind, local::Local},
};
use serde_json::{Value as Json, json};
use std::{
    error::Error,
    io::{self, BufRead},
    path::PathBuf,
};

type Result<T> = std::result::Result<T, Box<dyn Error>>;

fn main() -> Result<()> {
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?
        .block_on(run())
}

async fn run() -> Result<()> {
    let root = PathBuf::from(std::env::args_os().nth(1).ok_or("expected sqpack root")?);
    let pack = SqPack::new(Local::new(&root).await?).with_max_read_bytes(Some(128 << 20));
    // All geometry routes in this audit are chara or bgcommon in repository ffxiv.
    // Enumerate chunks once rather than probing 256 absent chunks for every miss.
    let mut indices = Vec::new();
    for file in std::fs::read_dir(root.join("ffxiv"))? {
        let name = file?
            .file_name()
            .into_string()
            .map_err(|_| "invalid filename")?;
        if (name.starts_with("0400") || name.starts_with("0100")) && name.ends_with(".index2") {
            let path = format!("ffxiv/{name}");
            indices.push((
                path.clone(),
                pack.read_index(&path, IndexKind::Index2).await?,
            ));
        }
    }
    for prefix in ["ffxiv/0100", "ffxiv/0400"] {
        if !indices.iter().any(|(n, _)| n.starts_with(prefix)) {
            return Err("missing index2".into());
        }
    }
    for line in io::stdin().lock().lines() {
        let line = line?;
        if let Some(rest) = line.strip_prefix("sheet ") {
            let mut fields = rest.split_whitespace();
            let sheet = fields.next().ok_or("sheet name")?;
            let cols: Vec<usize> = fields
                .map(str::parse)
                .collect::<std::result::Result<_, _>>()?;
            let bytes = pack.read(&format!("exd/{sheet}.exh")).await?;
            let header = Exh::parse(&bytes)?;
            let lang = if header.languages().contains(&Language::ChineseSimplified) {
                Language::ChineseSimplified
            } else {
                Language::None
            };
            let mut rows = Vec::new();
            for path in header.page_paths(sheet, lang)? {
                let bytes = pack.read(&path).await?;
                for row in Exd::parse(&bytes, &header)?.rows() {
                    let mut values = vec![json!(row.id())];
                    for col in &cols {
                        values.push(match row.field(*col)? {
                            Value::UInt64(x) => json!(x),
                            Value::Int64(x) => json!(x),
                            Value::UInt32(x) => json!(x),
                            Value::Int32(x) => json!(x),
                            Value::UInt16(x) => json!(x),
                            Value::Int16(x) => json!(x),
                            Value::UInt8(x) => json!(x),
                            Value::Int8(x) => json!(x),
                            _ => return Err(format!("unexpected {sheet} column {col}").into()),
                        });
                    }
                    rows.push(values);
                }
            }
            println!("{}", json!(rows));
            continue;
        }
        let prefix = if line.starts_with("chara/") {
            "ffxiv/0400"
        } else if line.starts_with("bgcommon/") {
            "ffxiv/0100"
        } else {
            println!("{}", json!({"error":"outside probed categories"}));
            continue;
        };
        let mut result = Json::Null;
        for (name, index) in &indices {
            if !name.starts_with(prefix) {
                continue;
            }
            let Some(loc) = index.find_path(&line)? else {
                continue;
            };
            let dat = format!("{}.dat{}", name.trim_end_matches(".index2"), loc.dat);
            let bytes = pack.read_entry(&dat, loc.offset).await?;
            result = if line.ends_with(".mdl") {
                match Mdl::parse(&bytes) {
                    Ok(m) if m.mesh_count() > 0 => json!({"bytes":bytes.len()}),
                    Ok(_) => json!({"error":"no meshes"}),
                    Err(e) => json!({"error":e.to_string()}),
                }
            } else {
                match Sgb::parse(&bytes) {
                    Ok(s) => {
                        json!({"refs":s.dependencies().filter(|d|matches!(d.kind,DependencyKind::Model|DependencyKind::SharedGroup)).map(|d|String::from_utf8_lossy(d.path)).collect::<Vec<_>>()})
                    }
                    Err(e) => json!({"error":e.to_string()}),
                }
            };
            break;
        }
        println!("{result}");
    }
    Ok(())
}
