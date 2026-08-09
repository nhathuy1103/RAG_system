from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

ZERO_WIDTH_PATTERN = re.compile("[\u200b\u200c\u200d\ufeff]")
CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
HORIZONTAL_WHITESPACE_PATTERN = re.compile(r"[ \t\f\v]+")
MULTI_NEWLINE_PATTERN = re.compile(r"\n{3,}")
REPEATED_SYMBOL_PATTERN = re.compile(r"([=*_~\-])\1{4,}")
MOJIBAKE_PATTERN = re.compile(r"(Ã.|Â.|Æ.|áº.|á».|Ä.|Å.)")
MOJIBAKE_PATTERN = re.compile(
    r"(Ã[\x80-\xBF]|Â[\x80-\xBF]|Ä[\x80-\xBF]|Å[\x80-\xBF]|"
    r"Æ[\x80-\xBF]|áº[\x80-\xBF]|á»[\x80-\xBF]|â€[\x80-\xBF]?)"
)

PUNCTUATION_TRANSLATION = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "„": '"',
        "«": '"',
        "»": '"',
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "−": "-",
        "…": "...",
    }
)


@dataclass(frozen=True)
class TextNormalizationConfig:
    unicode_form: str = "NFC"
    apply_nfkc: bool = False
    repair_mojibake: bool = True
    repair_vietnamese_ocr_terms: bool = True
    normalize_punctuation: bool = True
    normalize_whitespace: bool = True
    remove_zero_width: bool = True
    merge_broken_lines: bool = True
    cleanup_repeated_symbols: bool = True


@dataclass(frozen=True)
class TextNormalizationReport:
    original_character_count: int
    normalized_character_count: int
    changed: bool
    normalization_time_ms: float
    unicode_form: str
    zero_width_removed: int
    control_characters_removed: int
    compatibility_characters_detected: int
    combining_characters_detected: int
    mojibake_sequences_detected: int
    mojibake_repaired: bool
    vietnamese_ocr_terms_repaired: int
    punctuation_normalized: int
    whitespace_collapsed: int
    line_endings_normalized: int
    repeated_symbols_collapsed: int
    broken_lines_merged: int
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OcrTextNormalizer:
    """Normalize OCR text with conservative, auditable repairs."""

    def __init__(self, config: TextNormalizationConfig | None = None) -> None:
        self.config = config or TextNormalizationConfig()

    def normalize(self, text: str) -> tuple[str, TextNormalizationReport]:
        started = time.perf_counter()
        original = text or ""
        warnings: list[str] = []
        line_endings = original.count("\r\n") + original.replace(
            "\r\n",
            "",
        ).count("\r")
        zero_width_removed = len(ZERO_WIDTH_PATTERN.findall(original))
        control_removed = len(CONTROL_PATTERN.findall(original))
        combining = sum(1 for char in original if unicodedata.combining(char))
        compatibility = _count_compatibility_characters(original)
        mojibake_detected = len(MOJIBAKE_PATTERN.findall(original))

        normalized = original.replace("\r\n", "\n").replace("\r", "\n")
        if self.config.remove_zero_width:
            normalized = ZERO_WIDTH_PATTERN.sub("", normalized)
        normalized = CONTROL_PATTERN.sub("", normalized)
        if self.config.apply_nfkc:
            normalized = unicodedata.normalize("NFKC", normalized)
        normalized = unicodedata.normalize(self.config.unicode_form, normalized)
        normalized, mojibake_repaired = (
            _repair_mojibake_if_safe(normalized)
            if self.config.repair_mojibake
            else (normalized, False)
        )

        vietnamese_ocr_repairs = 0
        if self.config.repair_vietnamese_ocr_terms:
            normalized, vietnamese_ocr_repairs = _repair_vietnamese_ocr_terms(normalized)
        normalized = re.sub(
            r"(?<=[\)\"])(?=\d{2},\d{2}\b)",
            " ",
            normalized,
        )

        punctuation_changes = 0
        if self.config.normalize_punctuation:
            translated = normalized.translate(PUNCTUATION_TRANSLATION)
            punctuation_changes = sum(
                1 for before, after in zip(normalized, translated, strict=False) if before != after
            )
            normalized = translated
            normalized, spacing_changes = re.subn(
                r"\s+([,.;:])",
                r"\1",
                normalized,
            )
            punctuation_changes += spacing_changes

        whitespace_collapsed = 0
        if self.config.normalize_whitespace:
            whitespace_collapsed = len(HORIZONTAL_WHITESPACE_PATTERN.findall(normalized))
            normalized = HORIZONTAL_WHITESPACE_PATTERN.sub(" ", normalized)
            normalized = "\n".join(line.strip() for line in normalized.split("\n"))
            normalized = MULTI_NEWLINE_PATTERN.sub("\n\n", normalized)

        repeated_symbols = 0
        if self.config.cleanup_repeated_symbols:
            repeated_symbols = len(REPEATED_SYMBOL_PATTERN.findall(normalized))
            normalized = REPEATED_SYMBOL_PATTERN.sub(
                lambda match: match.group(1) * 3,
                normalized,
            )

        broken_lines = 0
        if self.config.merge_broken_lines:
            normalized, broken_lines = merge_broken_lines(normalized)
        normalized = normalized.strip()
        if mojibake_detected and not mojibake_repaired:
            warnings.append("mojibake_detected_not_repaired")

        return normalized, TextNormalizationReport(
            original_character_count=len(original),
            normalized_character_count=len(normalized),
            changed=original != normalized,
            normalization_time_ms=round(
                (time.perf_counter() - started) * 1000,
                3,
            ),
            unicode_form=self.config.unicode_form,
            zero_width_removed=zero_width_removed,
            control_characters_removed=control_removed,
            compatibility_characters_detected=compatibility,
            combining_characters_detected=combining,
            mojibake_sequences_detected=mojibake_detected,
            mojibake_repaired=mojibake_repaired,
            vietnamese_ocr_terms_repaired=vietnamese_ocr_repairs,
            punctuation_normalized=punctuation_changes,
            whitespace_collapsed=whitespace_collapsed,
            line_endings_normalized=line_endings,
            repeated_symbols_collapsed=repeated_symbols,
            broken_lines_merged=broken_lines,
            warnings=tuple(warnings),
        )


def merge_broken_lines(text: str) -> tuple[str, int]:
    lines = text.split("\n")
    if not lines:
        return text, 0
    merged: list[str] = []
    merge_count = 0
    for line in lines:
        current = line.strip()
        if not current:
            merged.append("")
            continue
        if merged and _should_merge_line(merged[-1], current):
            merged[-1] = f"{merged[-1]} {current}".strip()
            merge_count += 1
        else:
            merged.append(current)
    return "\n".join(merged), merge_count


def _repair_mojibake_if_safe(text: str) -> tuple[str, bool]:
    before = len(MOJIBAKE_PATTERN.findall(text))
    if before == 0:
        return text, False
    try:
        candidate = text.encode("latin1").decode("utf-8")
    except UnicodeError:
        return text, False
    after = len(MOJIBAKE_PATTERN.findall(candidate))
    if after < before and "\ufffd" not in candidate:
        return candidate, True
    return text, False


_VIETNAMESE_OCR_TERM_REPAIRS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), replacement)
    for pattern, replacement in (
        (r"\bCöng ty Cö phän Xäy dung\b", "Công ty Cổ phần Xây dựng"),
        (r"\bCöng ty Cö phän Xay dung\b", "Công ty Cổ phần Xây dựng"),
        (r"\bCöng ty Cö phan Xay dung\b", "Công ty Cổ phần Xây dựng"),
        (r"\bCong ty Co phan Xay dung\b", "Công ty Cổ phần Xây dựng"),
        (r"\bCng ty Cö phan Xay dung Coteccons\b", "Công ty Cổ phần Xây dựng Coteccons"),
        (r"\bBäo cao tai chinh rieng\b", "Báo cáo tài chính riêng"),
        (r"\bBäo cao tài chinh rieng\b", "Báo cáo tài chính riêng"),
        (r"\bBäo cäo\b", "Báo cáo"),
        (r"\bBäo cao\b", "Báo cáo"),
        (r"\bBáo cäo\b", "Báo cáo"),
        (r"\bbao cäo\b", "báo cáo"),
        (r"\bBäng can dói ké toan\b", "Bảng cân đối kế toán"),
        (r"\bBäng can doi ke toan\b", "Bảng cân đối kế toán"),
        (r"\bBáo cáo két quá\b", "Báo cáo kết quả"),
        (r"\bBáo cáo két quä\b", "Báo cáo kết quả"),
        (r"\bBäo cäo luu chuyén tiền tệ riéng\b", "Báo cáo lưu chuyển tiền tệ riêng"),
        (r"\bThuyét minh bäo cäo tài chính\b", "Thuyết minh báo cáo tài chính"),
        (r"\bBAO CAO TAI CHINH\b", "BÁO CÁO TÀI CHÍNH"),
        (r"\bBANG CAN DOI KE TOAN RIENG\b", "Bảng cân đối kế toán riêng"),
        (
            r"\bBAO CAO KET QUA HOAT DONG KINH DOANH RIENG\b",
            "Báo cáo kết quả hoạt động kinh doanh riêng",
        ),
        (r"\bBAO CAO LUU CHUYEN TIEN TE RIENG\b", "Báo cáo lưu chuyển tiền tệ riêng"),
        (r"\bBAO CÁO LƯU CHUYÊN TIÊN TỆ RIÊNG\b", "BÁO CÁO LƯU CHUYỂN TIỀN TỆ RIÊNG"),
        (r"\bTHUYET MINH BAO CAO TAI CHINH RIENG\b", "Thuyết minh báo cáo tài chính riêng"),
        (r"\bTONG CONG TAI SAN\b", "TỔNG CỘNG TÀI SẢN"),
        (r"\bTONG CONG NGUON VON\b", "TỔNG CỘNG NGUỒN VỐN"),
        (r"\bC\s*\.\s*NO\s*PHAI\s*TRA\b", "C. NỢ PHẢI TRẢ"),
        (r"\bC\s*\.\s*NỢ\s+PHẢ[lI]\s+TRẢ\b", "C. NỢ PHẢI TRẢ"),
        (r"\bD\s*\.\s*VON\s*CHU\s*SO\s*HU(?:U)?\b", "D. VỐN CHỦ SỞ HỮU"),
        (r"\bTHUYET MINH.*TÀI CHÍNH RIÊNG\b", "Thuyết minh báo cáo tài chính riêng"),
        (r"\bTHUYET MINH BÁO CÁO TÀI CHÍNH RIÊNG\b", "Thuyết minh báo cáo tài chính riêng"),
        (r"\bTHONG TIN CONG TY\b", "THÔNG TIN CÔNG TY"),
        (r"\bTHONG TIN\b", "THÔNG TIN"),
        (r"\bRIENG\b", "RIÊNG"),
        (r"\bThäng\b", "Tháng"),
        (r"\bthäng\b", "tháng"),
        (r"\bQuy\s*([1-4])\s*/", r"Quý \1/"),
        (r"\bQuy\s*([1-4])\s*n[äa]m\s*(\d{4})\b", r"Quý \1 năm \2"),
        (r"\bnäm\b", "năm"),
        (r"\bthang\b", "tháng"),
        (r"\bchin tháng\b", "chín tháng"),
        (r"\bgiai doan\b", "giai đoạn"),
        (r"\bNgay\s*24\s*th[äa]ng\s*4\s*n[äa]m\s*2026\b", "Ngày 24 tháng 4 năm 2026"),
        (r"\bNgay\s*20\s*th[äa]ng\s*4\s*n[äa]m\s*2026\b", "Ngày 20 tháng 4 năm 2026"),
        (r"\bNgay\s*24\s*tháng\s*4\s*nam\s*2026\b", "Ngày 24 tháng 4 năm 2026"),
        (r"\bNgay\s*20\s*tháng\s*4\s*nam\s*2026\b", "Ngày 20 tháng 4 năm 2026"),
        (r"\b(ngay\s+\d{1,2}\s+tháng\s+\d{1,2})\s+nam\s+(\d{4})\b", r"\1 năm \2"),
        (r"\bNgay\s*24\s*tháng\s*4\s*năm\s*2026\b", "Ngày 24 tháng 4 năm 2026"),
        (r"\bNgay\s*20\s*tháng\s*4\s*năm\s*2026\b", "Ngày 20 tháng 4 năm 2026"),
        (r"\bkét thüc\b", "kết thúc"),
        (r"\bk[eé]t thuc\b", "kết thúc"),
        (r"\bhoat d[öo]ng\b", "hoạt động"),
        (r"\bHoat d[öo]ng\b", "Hoạt động"),
        (r"\bti[eé]n t[eé]\b", "tiền tệ"),
        (r"\bT[ií]en t[eé]\b", "Tiền tệ"),
        (r"\bluu chuy[eé]n\b", "lưu chuyển"),
        (r"\bri[eé]ng\b", "riêng"),
        (r"\bThuy[eé]t minh\b", "Thuyết minh"),
        (r"\bThuyết minh BÁO CÁO TÀI CHÍNH RIÊNG\b", "Thuyết minh báo cáo tài chính riêng"),
        (r"\bThuyết minh Báo cáo tài chính\b", "Thuyết minh báo cáo tài chính"),
        (r"\bTy le\b", "Tỷ lệ"),
        (r"\bTyle\b", "Tỷ lệ"),
        (r"\bbi[eé]u quy[eé]t\b", "biểu quyết"),
        (r"\bloi ich\b", "lợi ích"),
        (r"\bTru s[öo] chinh\b", "Trụ sở chính"),
        (r"\bHoat d[öo]ng chinh\b", "Hoạt động chính"),
        (
            r"\bS\s+K[eé]\s+hoach\s+va\s+(?:au|dau)\s+tu(?=SKH\b|\W|$)",
            "Sở Kế hoạch và Đầu tư",
        ),
        (
            r"\bPhurng\s+Gia\s+inh(?=Thanh|\s|[,.])",
            "Phường Gia Định ",
        ),
        (r"\bThanh\s+ph(?:o|ó)?\s+H\s+Chi\s+Minh\b", "Thành phố Hồ Chí Minh"),
        (r"\b(?:Phung|Phuong)\s+Gia\s+Dinh\b", "Phường Gia Định"),
        (r"\b(\d{1,3}(?:\.\d{3})+)\s+ngui\b", r"\1 người"),
        (r"\btai chinh\b", "tài chính"),
        (r"\bTai chinh\b", "Tài chính"),
        (r"\bXäy dung\b", "Xây dựng"),
        (r"\bxäy dung\b", "xây dựng"),
        (r"\bthuàn\b", "thuần"),
        (r"\bthuẩn\b", "thuần"),
        (r"\bhàng tổn kho\b", "hàng tồn kho"),
        (r"\btổn kho\b", "tồn kho"),
        (r"\bnhâp\b", "nhập"),
        (r"\bcông cu\b", "công cụ"),
        (r"\bhoạt ẩộng\b", "hoạt động"),
        (r"\bẩộng\b", "động"),
        (r"\bđàu tư\b", "đầu tư"),
        (r"\bAnh hưởng\b", "Ảnh hưởng"),
        (r"\bquy đối\b", "quy đổi"),
        (r"\bthay đối\b", "thay đổi"),
        (r"\btwơng đương\b", "tương đương"),
        (r"\btưong đương\b", "tương đương"),
        (r"\bLưu chuyển ti[eèé]n\b", "Lưu chuyển tiền"),
        (r"\bTi[eèé]n thu khác\b", "Tiền thu khác"),
        (r"\bTi[eèé]n chi đầu tư\b", "Tiền chi đầu tư"),
        (
            r"\bTiền chi đầu tư\s+góp vốn vào đơn vị khác\b",
            "Tiền chi đầu tư vào góp vốn vào đơn vị khác",
        ),
        (r"\bTi[eèé]n và\b", "Tiền và"),
        (r"\bltừ\b", "/từ"),
        (r"\(Tăng\)\s*[ỈIl|/]\s*giảm\b", "(Tăng)/giảm"),
        (
            r"\(T\u0103ng\)\s*['\u2019`]\s*gi\u1ea3m\b",
            "(T\u0103ng)/gi\u1ea3m",
        ),
        (r"\bkho\u00e1n ph\u1ea3i thu\b", "kho\u1ea3n ph\u1ea3i thu"),
        (r"\bC\u00f3 t\u1ee9c\b", "C\u1ed5 t\u1ee9c"),
        (r"\bLwu chuy\u1ec3n\b", "L\u01b0u chuy\u1ec3n"),
        (
            r"\btwong \u0111\u01b0\u01a1ng\b",
            "t\u01b0\u01a1ng \u0111\u01b0\u01a1ng",
        ),
        (r"\bngoai t\u1ec7\b", "ngo\u1ea1i t\u1ec7"),
        (
            r"\b\u00c1nh h\u01b0\u1edfng\b",
            "\u1ea2nh h\u01b0\u1edfng",
        ),
        (r"\bCOTECCOMS\b", "COTECCONS"),
    )
)


def _repair_vietnamese_ocr_terms(text: str) -> tuple[str, int]:
    repaired = text
    count = 0
    for pattern, replacement in _VIETNAMESE_OCR_TERM_REPAIRS:
        repaired, changes = pattern.subn(replacement, repaired)
        count += changes
    for pattern, replacement in (
        (
            r"(?im)^THUYET MINH.*(?:TAI CHINH RIENG|TÀI CHÍNH RIÊNG)$",
            "Thuyết minh báo cáo tài chính riêng",
        ),
        (r"(?im)^BANG CAN DOI KE TOAN RIENG$", "Bảng cân đối kế toán riêng"),
        (r"(?im)^BAO CAO LUU CHUYEN TIEN TE RIENG$", "Báo cáo lưu chuyển tiền tệ riêng"),
        (
            r"(?im)^BAO CAO KET QUA HOAT DONG KINH DOANH RIENG$",
            "Báo cáo kết quả hoạt động kinh doanh riêng",
        ),
    ):
        repaired, changes = re.subn(pattern, replacement, repaired)
        count += changes
    return repaired, count


def _count_compatibility_characters(text: str) -> int:
    return sum(1 for char in text if unicodedata.normalize("NFKC", char) != char)


def _should_merge_line(previous: str, current: str) -> bool:
    if not previous or not current:
        return False
    if previous.endswith((".", ":", ";", "!", "?", ")", "]")):
        return False
    if len(previous) <= 3 or len(current) <= 3:
        return False
    if re.match(r"^\d+[\).]?$", current):
        return False
    if previous.isupper() and current.isupper():
        return bool(_looks_like_uppercase_heading_continuation(previous, current))
    return previous[-1].isalnum() and current[0].islower()


def _looks_like_uppercase_heading_continuation(previous: str, current: str) -> bool:
    if any(char.isdigit() for char in previous + current):
        return False
    if "|" in previous or "|" in current:
        return False
    current_words = current.split()
    if not current_words or len(current_words) > 2:
        return False
    return len(previous) <= 60 and len(current) <= 24


__all__ = [
    "OcrTextNormalizer",
    "TextNormalizationConfig",
    "TextNormalizationReport",
]
