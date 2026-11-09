//! Conservative SeString-to-text projection, without evaluating game expressions.
use crate::Result;
use std::collections::BTreeMap;

fn integer(bytes: &[u8], position: &mut usize) -> Result<usize> {
    let tag = *bytes.get(*position).ok_or("Truncated SeString length")?;
    *position += 1;
    if (1..0xd0).contains(&tag) {
        return Ok(usize::from(tag - 1));
    }
    if tag < 0xf0 || tag == 0xff {
        return Err("Invalid SeString integer tag".into());
    }
    let flags = tag + 1;
    let mut value = 0u32;
    for (mask, shift) in [(8, 24), (4, 16), (2, 8), (1, 0)] {
        if flags & mask != 0 {
            let byte = *bytes.get(*position).ok_or("Truncated SeString integer")?;
            *position += 1;
            value |= u32::from(byte) << shift;
        }
    }
    Ok(usize::try_from(value)?)
}

pub fn plain(bytes: &[u8], unknown: &mut BTreeMap<u8, usize>) -> Result<String> {
    let mut out = String::new();
    let mut position = 0;
    while position < bytes.len() {
        if bytes[position] != 2 {
            let end = bytes[position..]
                .iter()
                .position(|byte| *byte == 2)
                .map_or(bytes.len(), |end| position + end);
            let text = std::str::from_utf8(&bytes[position..end])?;
            if text
                .chars()
                .any(|c| c.is_control() && !matches!(c, '\n' | '\r' | '\t'))
            {
                return Err("Unexpected control character outside SeString payload".into());
            }
            out.push_str(text);
            position = end;
            continue;
        }
        let kind = *bytes
            .get(position + 1)
            .ok_or("Truncated SeString payload")?;
        position += 2;
        let length = integer(bytes, &mut position)?;
        let end = position
            .checked_add(length)
            .ok_or("SeString length overflow")?;
        if bytes.get(end) != Some(&3) {
            return Err("Truncated or unterminated SeString payload".into());
        }
        if kind == 0x10 && length == 0 {
            out.push('\n');
        } else {
            // Preserve the existence of unevaluated content instead of silently dropping it.
            out.push('\u{fffc}');
            *unknown.entry(kind).or_default() += 1;
        }
        position = end + 1;
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn text_newlines_and_unknown_payloads_are_distinguished() {
        let mut counts = BTreeMap::new();
        assert_eq!(
            plain(b"A\x02\x10\x01\x03B\x02\x48\x02x\x03", &mut counts).unwrap(),
            "A\nB\u{fffc}"
        );
        assert_eq!(counts.get(&0x48), Some(&1));
    }
    #[test]
    fn malformed_text_is_rejected() {
        for bytes in [
            b"\xff".as_slice(),
            b"\x02",
            b"\x02\x10\x01",
            b"\x02\x10\xff\x03",
            b"\x03",
        ] {
            assert!(plain(bytes, &mut BTreeMap::new()).is_err());
        }
    }
    #[test]
    fn multi_byte_length_is_checked_without_allocating_its_declared_size() {
        let mut pos = 0;
        assert_eq!(integer(&[0xf1, 0x12], &mut pos).unwrap(), 0x1200);
        assert!(plain(&[2, 0x48, 0xfe, 255, 255, 255, 255], &mut BTreeMap::new()).is_err());
    }
}
