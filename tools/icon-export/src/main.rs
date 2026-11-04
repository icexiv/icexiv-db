//! Offline, deduplicated PNG export for the site's pinned Item input.
use icexiv_data::{
    sqpack::{Error as PackError, PackSource, SqPack, local::Local},
    tex::Tex,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    error::Error,
    path::PathBuf,
};

type Result<T> = std::result::Result<T, Box<dyn Error>>;
const BUDGET: usize = 64 * 1024 * 1024;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Request {
    version: u32,
    game_version: String,
    csv_sha256: String,
    icon_ids: BTreeSet<u32>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Manifest {
    version: u32,
    game_version: String,
    csv_sha256: String,
    icons: BTreeMap<u32, Entry>,
}

#[derive(Serialize)]
#[serde(tag = "status", rename_all = "camelCase")]
enum Entry {
    Exported {
        resource: String,
        sha256: String,
        width: u16,
        height: u16,
    },
    Missing,
    Unconfigured,
    Failed {
        error: String,
    },
}

fn candidates(id: u32) -> [String; 2] {
    let group = id / 1000 * 1000;
    [
        format!("ui/icon/{group:06}/{id:06}_hr1.tex"),
        format!("ui/icon/{group:06}/{id:06}.tex"),
    ]
}

fn png_bytes(bytes: &[u8]) -> Result<(Vec<u8>, u16, u16)> {
    let texture = Tex::parse(bytes)?;
    let mip = texture.mip(0)?;
    let rgba = mip.decode_rgba8(BUDGET)?;
    let mut png = Vec::new();
    {
        let mut encoder =
            png::Encoder::new(&mut png, u32::from(mip.width()), u32::from(mip.height()));
        encoder.set_color(png::ColorType::Rgba);
        encoder.set_depth(png::BitDepth::Eight);
        let mut writer = encoder.write_header()?;
        writer.write_image_data(&rgba)?;
    }
    Ok((png, mip.width(), mip.height()))
}

async fn read_icon<S: PackSource>(
    pack: &SqPack<S>,
    id: u32,
) -> std::result::Result<Option<(String, Vec<u8>)>, PackError<S::Error>> {
    if id == 0 {
        return Ok(None);
    }
    for resource in candidates(id) {
        match pack.read(&resource).await {
            Ok(bytes) => return Ok(Some((resource, bytes))),
            Err(PackError::MissingResource(_)) => continue,
            Err(error) => return Err(error),
        }
    }
    Ok(None)
}

async fn run() -> Result<()> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    const USAGE: &str = "Usage: icon-export <request.json> <game/sqpack> <game-version> <new-output-directory>\nThe version is an explicit assertion about the supplied installation; it must match the CSV. Keep the installation stable while exporting.";
    if args.len() == 1 && args[0] == "--help" {
        println!("{USAGE}");
        return Ok(());
    }
    if args.len() != 4 {
        return Err(USAGE.into());
    }
    let request_bytes = std::fs::read(&args[0])?;
    let request: Request = serde_json::from_slice(&request_bytes)?;
    if request.version != 1 || args[2].to_str() != Some(&request.game_version) {
        return Err("Request version or asserted game version does not match".into());
    }
    if request.csv_sha256.len() != 64 || !request.csv_sha256.bytes().all(|c| c.is_ascii_hexdigit())
    {
        return Err("Invalid CSV SHA-256".into());
    }
    let source = Local::new(PathBuf::from(&args[1])).await?;
    let pack = SqPack::new(source)
        .with_max_read_bytes(Some(BUDGET))
        .with_index_cache(Some(BUDGET));
    let output = PathBuf::from(&args[3]);
    // Never overwrite an existing export or unrelated directory.
    std::fs::create_dir(&output)?;
    let mut icons = BTreeMap::new();
    let mut failed = 0;
    for id in request.icon_ids {
        let result: Result<Entry> = async {
            if id == 0 {
                return Ok(Entry::Unconfigured);
            }
            let Some((resource, bytes)) = read_icon(&pack, id).await? else {
                return Ok(Entry::Missing);
            };
            let (png, width, height) = png_bytes(&bytes)?;
            let sha256 = format!("{:x}", Sha256::digest(&png));
            std::fs::write(output.join(format!("{id}.png")), png)?;
            Ok(Entry::Exported {
                resource,
                sha256,
                width,
                height,
            })
        }
        .await;
        let entry = match result {
            Ok(entry) => entry,
            Err(error) => {
                failed += 1;
                Entry::Failed {
                    error: error.to_string(),
                }
            }
        };
        icons.insert(id, entry);
    }
    let manifest = Manifest {
        version: 1,
        game_version: request.game_version,
        csv_sha256: request.csv_sha256,
        icons,
    };
    std::fs::write(output.join("manifest.json"), serde_json::to_vec(&manifest)?)?;
    println!(
        "Recorded {} distinct icon IDs; {failed} failures",
        manifest.icons.len()
    );
    if failed != 0 {
        return Err("Export contains failures; inspect manifest.json".into());
    }
    Ok(())
}

fn main() -> Result<()> {
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?
        .block_on(run())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn icon_paths_use_thousand_groups_and_high_resolution_first() {
        assert_eq!(
            candidates(62101),
            ["ui/icon/062000/062101_hr1.tex", "ui/icon/062000/062101.tex"]
        );
        assert_eq!(candidates(999)[1], "ui/icon/000000/000999.tex");
        assert_eq!(candidates(1000)[1], "ui/icon/001000/001000.tex");
    }

    #[test]
    fn synthetic_bgra_exports_a_png_with_straight_alpha() {
        let mut tex = vec![0; 84];
        tex[..4].copy_from_slice(&0x00800000u32.to_le_bytes());
        tex[4..8].copy_from_slice(&0x1450u32.to_le_bytes());
        for offset in [8, 10, 12] {
            tex[offset..offset + 2].copy_from_slice(&1u16.to_le_bytes());
        }
        tex[14] = 1;
        tex[28..32].copy_from_slice(&80u32.to_le_bytes());
        tex[80..].copy_from_slice(&[10, 20, 30, 40]);
        let (png, width, height) = png_bytes(&tex).unwrap();
        assert_eq!((width, height), (1, 1));
        let mut reader = png::Decoder::new(png.as_slice()).read_info().unwrap();
        let mut pixels = vec![0; reader.output_buffer_size()];
        reader.next_frame(&mut pixels).unwrap();
        assert_eq!(pixels, [30, 20, 10, 40]);
    }
}
