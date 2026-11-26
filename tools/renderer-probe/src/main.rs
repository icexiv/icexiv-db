//! Batch local asset inspection; stdout is one JSON response per request line.
use icexiv_data::{
    imc::Imc,
    sqpack::{SqPack, index::IndexKind, local::Local},
};
use icexiv_renderer::{EquipmentModel, base_color_texture, diffuse_overlay, validate_material_with_diffuse};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    error::Error,
    fs,
    io::{self, BufRead},
    path::{Path, PathBuf},
};

type Result<T> = std::result::Result<T, Box<dyn Error>>;

fn object(root: &Path, sha: &str) -> Result<PathBuf> {
    if sha.len() != 64 || !sha.bytes().all(|c| c.is_ascii_hexdigit()) {
        return Err("invalid digest".into());
    }
    Ok(root.join(&sha[..2]).join(&sha[2..]))
}

fn inspect(path: &str, bytes: &[u8]) -> Result<Value> {
    Ok(match path.rsplit('.').next() {
        Some("mdl") => {
            match EquipmentModel::from_mdl(bytes) {
                Ok(model) => json!({"slots":model.material_names(),"triangles":model.triangle_count()}),
                Err(icexiv_renderer::ModelError::NoVisibleExtent) => json!({"noVisibleExtent":true}),
                Err(e) => return Err(e.into()),
            }
        }
        Some("mtrl") => json!({"texture":base_color_texture(bytes)?, "diffuse":diffuse_overlay(bytes)?}),
        Some("tex" | "pap" | "sklb") => json!({}),
        Some("imc") => {
            let imc = Imc::parse(bytes)?;
            let mut subsets = Vec::new();
            for sub in 0..=imc.variant_count() {
                let mut parts = serde_json::Map::new();
                for bit in imc.parts() {
                    parts.insert(bit.to_string(), json!(imc.entry(sub, bit)?.material_id));
                }
                subsets.push(parts);
            }
            json!({"subsets":subsets})
        }
        _ => return Err("unsupported extension".into()),
    })
}

async fn run() -> Result<()> {
    let mut args = std::env::args_os().skip(1).map(PathBuf::from);
    let root = args.next().ok_or("sqpack root required")?;
    let objects = args.next().ok_or("object directory required")?;
    let pack = SqPack::new(Local::new(&root).await?).with_max_read_bytes(Some(128 << 20));
    let mut indices = Vec::new();
    for file in fs::read_dir(root.join("ffxiv"))? {
        let file = file?.file_name().into_string().map_err(|_| "non UTF-8")?;
        if (file.starts_with("0100") || file.starts_with("0400")) && file.ends_with(".index2") {
            let path = format!("ffxiv/{file}");
            indices.push((
                path.clone(),
                pack.read_index(&path, IndexKind::Index2).await?,
            ));
        }
    }
    for line in io::stdin().lock().lines() {
        let line = line?;
        if let Some(args) = line.strip_prefix("paths ") {
            let (model, name, version): (String, String, Option<u16>) = serde_json::from_str(args)?;
            println!("{}", json!(icexiv_renderer::material_paths(&model, &name, version)));
            continue;
        }
        if let Some(pair) = line.strip_prefix("pair ") {
            let mut fields = pair.split_whitespace();
            let m = fields.next().ok_or("missing material")?;
            let t = fields.next().ok_or("missing texture")?;
            let d = fields.next().unwrap_or("-");
            let res = validate_material_with_diffuse(
                &fs::read(object(&objects, m)?)?,
                &if t == "-" { Vec::new() } else { fs::read(object(&objects, t)?)? },
                &if d == "-" { Vec::new() } else { fs::read(object(&objects, d)?)? },
                4096,
            );
            println!(
                "{}",
                match res {
                    Ok(()) => json!({"ok":true}),
                    Err(e) => json!({"error":e.to_string()}),
                }
            );
            continue;
        }
        let prefix = match line.split('/').next() {
            Some("chara") => "ffxiv/0400",
            Some("bgcommon") => "ffxiv/0100",
            _ => {
                println!("null");
                continue;
            }
        };
        let mut res = Value::Null;
        for (idx, table) in &indices {
            if !idx.starts_with(prefix) {
                continue;
            }
            let Some(loc) = table.find_path(&line)? else {
                continue;
            };
            let bytes = pack
                .read_entry(
                    &format!("{}.dat{}", idx.trim_end_matches(".index2"), loc.dat),
                    loc.offset,
                )
                .await?;
            res = match inspect(&line, &bytes) {
                Ok(mut v) => {
                    if !line.ends_with(".imc") {
                        let sha = format!("{:x}", Sha256::digest(&bytes));
                        let dst = object(&objects, &sha)?;
                        if !dst.exists() {
                            fs::create_dir_all(dst.parent().unwrap())?;
                            fs::write(dst, &bytes)?;
                        }
                        v["sha"] = json!(sha);
                    }
                    v
                }
                Err(e) => json!({"error":e.to_string()}),
            };
            break;
        }
        println!("{res}");
    }
    Ok(())
}
fn main() -> Result<()> {
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?
        .block_on(run())
}
