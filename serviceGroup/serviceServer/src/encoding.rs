//! 文本编码探测与解码 (修旧 read_file_content 的替换字符污染 bug)。
//!
//! 旧版 `raw_data.decode(encoding, errors='replace')` 永不失败:
//! 用户选 UTF-8 读 GBK 文件 -> 替换字符污染 -> 保存时原内容永久丢失。
//! 本实现: BOM 嗅探 + strict decode 候选 (utf-8 优先, 次 gbk), 杜绝静默替换。

use crate::error::AppError;
use encoding_rs::{GBK, UTF_16BE, UTF_16LE, UTF_8};

#[derive(Debug, Clone, PartialEq)]
pub struct Decoded {
    pub content: String,
    pub encoding: &'static str,
    /// true = 走了 latin-1 兜底 (errors ignore 等价), 内容可能损坏。
    pub used_fallback: bool,
}

const UTF8_BOM: &[u8] = &[0xEF, 0xBB, 0xBF];
const UTF16LE_BOM: &[u8] = &[0xFF, 0xFE];
const UTF16BE_BOM: &[u8] = &[0xFE, 0xFF];

/// 探测 + 解码字节流。优先级: BOM > strict utf-8 > strict gbk > latin-1 兜底。
pub fn decode(bytes: &[u8]) -> Decoded {
    if bytes.starts_with(UTF8_BOM) {
        return decode_strict(&UTF_8, &bytes[3..], "utf-8-sig");
    }
    if bytes.starts_with(UTF16LE_BOM) {
        return decode_strict(&UTF_16LE, &bytes[2..], "utf-16-le");
    }
    if bytes.starts_with(UTF16BE_BOM) {
        return decode_strict(&UTF_16BE, &bytes[2..], "utf-16-be");
    }
    if let Ok(s) = std::str::from_utf8(bytes) {
        return Decoded {
            content: s.into(),
            encoding: "utf-8",
            used_fallback: false,
        };
    }
    let gbk = decode_strict(&GBK, bytes, "gbk");
    if !gbk.used_fallback {
        return gbk;
    }
    fallback_latin1(bytes)
}

fn decode_strict(enc: &'static encoding_rs::Encoding, bytes: &[u8], name: &'static str) -> Decoded {
    let (cow, had_errors) = enc.decode_without_bom_handling(bytes);
    Decoded {
        content: cow.into_owned(),
        encoding: name,
        used_fallback: had_errors,
    }
}

fn fallback_latin1(bytes: &[u8]) -> Decoded {
    Decoded {
        content: bytes.iter().map(|&b| b as char).collect(),
        encoding: "latin-1",
        used_fallback: true,
    }
}

/// 按指定编码把内容编码为字节 (保存用)。strict: 含无法表示的字符则报错,
/// 不静默替换 (与 decode 对称, 杜绝写回污染)。
pub fn encode(content: &str, encoding: &str) -> Result<Vec<u8>, AppError> {
    match encoding {
        "utf-8" => Ok(content.as_bytes().to_vec()),
        "utf-8-sig" => {
            let mut v = vec![0xEF, 0xBB, 0xBF];
            v.extend_from_slice(content.as_bytes());
            Ok(v)
        }
        "gbk" => encode_raw(&GBK, content),
        "utf-16-le" => {
            let mut v = vec![0xFF, 0xFE];
            v.extend(encode_raw(&UTF_16LE, content)?);
            Ok(v)
        }
        "utf-16-be" => {
            let mut v = vec![0xFE, 0xFF];
            v.extend(encode_raw(&UTF_16BE, content)?);
            Ok(v)
        }
        other => Err(AppError::UnknownEncoding(other.into())),
    }
}

fn encode_raw(enc: &'static encoding_rs::Encoding, content: &str) -> Result<Vec<u8>, AppError> {
    let (cow, _, had_errors) = enc.encode(content);
    if had_errors {
        Err(AppError::Encode("内容含目标编码无法表示的字符".into()))
    } else {
        Ok(cow.into_owned())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    #[rstest]
    fn test_decode_ascii_utf8() {
        let d = decode(b"hello world");
        assert_eq!(d.encoding, "utf-8");
    }

    #[rstest]
    fn test_decode_utf8_chinese_strict() {
        let d = decode("中文".as_bytes());
        assert_eq!(d.encoding, "utf-8");
        assert!(!d.used_fallback);
        assert_eq!(d.content, "中文");
    }

    /// GBK 中文 (无 BOM): strict gbk 命中, 无替换 — 修旧 bug 的核心保证。
    #[rstest]
    fn test_decode_gbk_chinese_strict_no_replacement() {
        let d = decode(&[0xD6, 0xD0, 0xCE, 0xC4]); // "中文" GBK
        assert_eq!(d.encoding, "gbk");
        assert!(!d.used_fallback, "合法 GBK 不应走 fallback, 杜绝替换字符");
        assert_eq!(d.content, "中文");
    }

    #[rstest]
    fn test_decode_utf8_bom_sig() {
        let mut bytes = vec![0xEF, 0xBB, 0xBF];
        bytes.extend_from_slice("中文".as_bytes());
        let d = decode(&bytes);
        assert_eq!(d.encoding, "utf-8-sig");
        assert_eq!(d.content, "中文");
    }

    #[rstest]
    fn test_decode_utf16le_bom() {
        let mut bytes = vec![0xFF, 0xFE];
        bytes.extend_from_slice(&[0x41, 0x00, 0x42, 0x00]); // "AB" UTF-16LE
        let d = decode(&bytes);
        assert_eq!(d.encoding, "utf-16-le");
        assert_eq!(d.content, "AB");
    }

    #[rstest]
    fn test_fallback_latin1_maps_bytes_one_to_one() {
        let d = fallback_latin1(&[0x41, 0x42, 0xC3]);
        assert_eq!(d.encoding, "latin-1");
        assert!(d.used_fallback);
        assert_eq!(d.content.chars().count(), 3);
    }

    /// encode(中文, gbk) -> GBK 字节, 与 decode 往返一致。
    #[rstest]
    fn test_encode_gbk_roundtrips_chinese() {
        let bytes = encode("中文", "gbk").unwrap();
        assert_eq!(bytes, vec![0xD6, 0xD0, 0xCE, 0xC4]);
        let d = decode(&bytes);
        assert_eq!(d.content, "中文");
        assert_eq!(d.encoding, "gbk");
    }

    /// encode utf-8-sig 带 BOM。
    #[rstest]
    fn test_encode_utf8_sig_prepends_bom() {
        let bytes = encode("AB", "utf-8-sig").unwrap();
        assert_eq!(bytes, vec![0xEF, 0xBB, 0xBF, b'A', b'B']);
    }

    /// 含 GBK 无法表示的字符 (emoji) -> 报错, 不静默替换。
    #[rstest]
    fn test_encode_gbk_unencodable_emoji_errors() {
        let err = encode("😀", "gbk");
        assert!(err.is_err(), "GBK 无法表示 emoji 必须报错非静默");
    }

    /// 未知编码名 -> 报错。
    #[rstest]
    fn test_encode_unknown_encoding_errors() {
        let err = encode("x", "klingon");
        assert!(err.is_err());
    }
}
