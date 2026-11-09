use crate::{BUDGET, Result, text};
use icexiv_data::{
    excel::{Exd, Exh, Language, Row, Value, Variant},
    sqpack::{PackSource, SqPack, local::Local},
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
};

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Schema {
    pub version: u32,
    pub game_version: String,
    pub language: String,
    pub exh_sha256: String,
    pub fields: BTreeMap<String, Field>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Field {
    pub column: usize,
    pub kind: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Source {
    kind: &'static str,
    game_version: String,
    language: String,
    schema_sha256: String,
    resources: BTreeMap<String, String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Item {
    pub id: u32,
    name: String,
    description: String,
    pub icon: u32,
    category: u32,
    search_category: u32,
    equip_level: u32,
    rarity: u32,
    stack_size: u32,
    unique: bool,
    untradable: bool,
    hq: bool,
}

pub fn version(installation: &Path) -> Result<String> {
    let value = std::fs::read_to_string(installation.join("game/ffxivgame.ver"))?;
    let value = value.trim();
    if value.is_empty() || !value.bytes().all(|c| c.is_ascii_digit() || c == b'.') {
        return Err("Invalid game/ffxivgame.ver".into());
    }
    Ok(value.to_owned())
}

pub async fn inspect(installation: PathBuf) -> Result<()> {
    let version = version(&installation)?;
    let pack = SqPack::new(Local::new(installation.join("game/sqpack")).await?)
        .with_max_read_bytes(Some(BUDGET));
    let bytes = pack.read("exd/item.exh").await?;
    let header = Exh::parse(&bytes)?;
    let columns = header.columns().iter().enumerate().map(|(index, column)|
        serde_json::json!({"column": index, "kind": format!("{:?}", column.data_type), "offset": column.offset})
    ).collect::<Vec<_>>();
    println!(
        "{}",
        serde_json::to_string_pretty(&serde_json::json!({
            "gameVersion": version, "exhSha256": format!("{:x}", Sha256::digest(&bytes)),
            "variant": format!("{:?}",header.variant()), "rowCount": header.row_count(),
            "languages": format!("{:?}",header.languages()), "columns": columns,
        }))?
    );
    Ok(())
}

const FIELDS: [&str; 11] = [
    "name",
    "description",
    "icon",
    "category",
    "searchCategory",
    "equipLevel",
    "rarity",
    "stackSize",
    "unique",
    "untradable",
    "hq",
];

fn validate(header: &Exh, schema: &Schema, bytes: &[u8]) -> Result<()> {
    if schema.exh_sha256 != format!("{:x}", Sha256::digest(bytes)) {
        return Err("Item EXH SHA-256 differs from the reviewed schema".into());
    }
    if schema.language != "chs" || header.variant() != Variant::Default {
        return Err("Schema requires an ordinary ChineseSimplified Item sheet".into());
    }
    if schema.fields.len() != FIELDS.len() {
        return Err("Wrong schema field set".into());
    }
    for name in FIELDS {
        let field = schema
            .fields
            .get(name)
            .ok_or_else(|| format!("Missing schema field {name}"))?;
        let column = header
            .columns()
            .get(field.column)
            .ok_or("Schema column out of bounds")?;
        if field.kind != format!("{:?}", column.data_type) {
            return Err(format!("Schema type mismatch for {name}").into());
        }
    }
    Ok(())
}

fn field<'a>(row: Row<'a, '_>, schema: &Schema, name: &str) -> Result<Value<'a>> {
    Ok(row.field(schema.fields.get(name).ok_or("Missing field")?.column)?)
}

fn number(row: Row<'_, '_>, schema: &Schema, name: &str) -> Result<u32> {
    Ok(match field(row, schema, name)? {
        Value::UInt8(value) => u32::from(value),
        Value::UInt16(value) => u32::from(value),
        Value::UInt32(value) => value,
        _ => return Err(format!("Expected unsigned integer for {name}").into()),
    })
}

fn boolean(row: Row<'_, '_>, schema: &Schema, name: &str) -> Result<bool> {
    match field(row, schema, name)? {
        Value::Bool(value) => Ok(value),
        _ => Err(format!("Expected boolean for {name}").into()),
    }
}

fn string(
    row: Row<'_, '_>,
    schema: &Schema,
    name: &str,
    macros: &mut BTreeMap<u8, usize>,
) -> Result<String> {
    match field(row, schema, name)? {
        Value::String(bytes) => text::plain(bytes, macros),
        _ => Err(format!("Expected string for {name}").into()),
    }
}

pub async fn read_items<S: PackSource>(
    pack: &SqPack<S>,
    schema: &Schema,
    schema_bytes: &[u8],
) -> Result<(Vec<Item>, Source, BTreeMap<u8, usize>)>
where
    S::Error: std::error::Error + 'static,
{
    let bytes = pack.read("exd/item.exh").await?;
    let header = Exh::parse(&bytes)?;
    validate(&header, schema, &bytes)?;
    let mut resources = BTreeMap::from([(
        "exd/item.exh".to_owned(),
        format!("{:x}", Sha256::digest(&bytes)),
    )]);
    let mut items = BTreeMap::new();
    let mut seen = std::collections::BTreeSet::new();
    let mut macros = BTreeMap::new();
    for (page_info, path) in header
        .pages()
        .iter()
        .zip(header.page_paths("item", Language::ChineseSimplified)?)
    {
        let bytes = pack.read(&path).await?;
        resources.insert(path.clone(), format!("{:x}", Sha256::digest(&bytes)));
        let page = Exd::parse(&bytes, &header)?;
        for row in page.rows() {
            if !page_info.contains(row.id()) || !seen.insert(row.id()) {
                return Err(format!("Duplicate or out-of-range row {} in {path}", row.id()).into());
            }
            if row.id() == 0 {
                continue;
            }
            let decoded: Result<Option<Item>> = (|| {
                let name = string(row, schema, "name", &mut macros)?;
                if name.trim().is_empty() {
                    return Ok(None);
                }
                Ok(Some(Item {
                    id: row.id(),
                    name,
                    description: string(row, schema, "description", &mut macros)?,
                    icon: number(row, schema, "icon")?,
                    category: number(row, schema, "category")?,
                    search_category: number(row, schema, "searchCategory")?,
                    equip_level: number(row, schema, "equipLevel")?,
                    rarity: number(row, schema, "rarity")?,
                    stack_size: number(row, schema, "stackSize")?,
                    unique: boolean(row, schema, "unique")?,
                    untradable: boolean(row, schema, "untradable")?,
                    hq: boolean(row, schema, "hq")?,
                }))
            })();
            if let Some(item) =
                decoded.map_err(|error| format!("{path} row {}: {error}", row.id()))?
            {
                items.insert(item.id, item);
            }
        }
    }
    if seen.len() != header.row_count() as usize {
        return Err("Item EXH row count disagrees with the complete page set".into());
    }
    if items.is_empty() {
        return Err("No named Item rows found".into());
    }
    Ok((
        items.into_values().collect(),
        Source {
            kind: "game",
            game_version: schema.game_version.clone(),
            language: schema.language.clone(),
            schema_sha256: format!("{:x}", Sha256::digest(schema_bytes)),
            resources,
        },
        macros,
    ))
}
