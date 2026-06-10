"""数据导入导出模块：支持 CSV 和 Excel 格式，支持 RulesConfig"""

import os
import pandas as pd
from typing import Optional, Dict, Any, Tuple
from .config import ALL_FIELDS, REQUIRED_FIELDS, FIELD_CN_MAPPING, CN_FIELD_MAPPING
from .rules_config import RulesConfig, DEFAULT_CONFIG


def _detect_encoding(file_path: str) -> str:
    """检测文件编码"""
    encodings = ["utf-8-sig", "utf-8", "gbk", "gb18030"]
    for encoding in encodings:
        try:
            with open(file_path, "r", encoding=encoding) as f:
                f.read(10000)
            return encoding
        except UnicodeDecodeError:
            continue
    return "utf-8"


def _normalize_columns(df: pd.DataFrame, config: RulesConfig = DEFAULT_CONFIG) -> pd.DataFrame:
    """将中文列名转换为英文字段名"""
    cn_mapping = config.cn_field_mapping
    field_names = config.all_fields
    rename_map = {}
    for col in df.columns:
        col_stripped = str(col).strip()
        if col_stripped in cn_mapping:
            rename_map[col] = cn_mapping[col_stripped]
        elif col_stripped in field_names:
            rename_map[col] = col_stripped
    return df.rename(columns=rename_map)


def _add_missing_columns(df: pd.DataFrame, config: RulesConfig = DEFAULT_CONFIG) -> pd.DataFrame:
    """添加缺失的可选字段列"""
    for field in config.all_fields:
        if field not in df.columns:
            df[field] = None
    return df


def _clean_string_fields(df: pd.DataFrame) -> pd.DataFrame:
    """清理字符串字段的空白字符"""
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].apply(
                lambda x: x.strip() if isinstance(x, str) else x
            )
    return df


def import_roster(
    file_path: str,
    sheet_name: Optional[str] = None,
    rules_config: Optional[RulesConfig] = None
) -> pd.DataFrame:
    """
    导入花名册文件

    Args:
        file_path: 文件路径，支持 .csv, .xlsx, .xls
        sheet_name: Excel 工作表名，仅对 Excel 文件有效
        rules_config: 规则配置对象

    Returns:
        标准化后的 DataFrame
    """
    config = rules_config if rules_config else DEFAULT_CONFIG

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".csv":
        encoding = _detect_encoding(file_path)
        df = pd.read_csv(file_path, encoding=encoding, dtype=str, keep_default_na=False)
    elif ext in [".xlsx", ".xls"]:
        df = pd.read_excel(file_path, sheet_name=sheet_name if sheet_name else 0, dtype=str, keep_default_na=False)
    else:
        raise ValueError(f"不支持的文件格式: {ext}，请使用 CSV 或 Excel 文件")

    df = _normalize_columns(df, config)
    df = _add_missing_columns(df, config)
    df = _clean_string_fields(df)

    if "row_id" not in df.columns:
        df.insert(0, "row_id", range(2, len(df) + 2))

    return df


def _apply_column_rename(df: pd.DataFrame, config: RulesConfig = DEFAULT_CONFIG) -> pd.DataFrame:
    """应用列名转换（英文 -> 中文）"""
    df_display = df.copy()
    rename_map = {}
    cn_mapping = config.field_cn_mapping
    for col in df_display.columns:
        if col in cn_mapping:
            rename_map[col] = cn_mapping[col]
    return df_display.rename(columns=rename_map)


def export_to_excel(
    output_path: str,
    data_frames: Dict[str, pd.DataFrame],
    rules_config: Optional[RulesConfig] = None
) -> None:
    """
    导出数据到 Excel 文件（支持多工作表）

    Args:
        output_path: 输出文件路径
        data_frames: 字典，key 为工作表名，value 为 DataFrame
        rules_config: 规则配置（用于列名映射）
    """
    config = rules_config if rules_config else DEFAULT_CONFIG

    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, df in data_frames.items():
            safe_sheet_name = sheet_name[:31]
            df_display = _apply_column_rename(df, config)
            df_display.to_excel(writer, sheet_name=safe_sheet_name, index=False)


def export_to_csv(
    output_path: str,
    df: pd.DataFrame,
    encoding: str = "utf-8-sig",
    rules_config: Optional[RulesConfig] = None
) -> None:
    """
    导出数据到 CSV 文件

    Args:
        output_path: 输出文件路径
        df: 要导出的 DataFrame
        encoding: 文件编码，默认 utf-8-sig (Excel 友好)
        rules_config: 规则配置（用于列名映射）
    """
    config = rules_config if rules_config else DEFAULT_CONFIG

    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    df_display = _apply_column_rename(df, config)
    df_display.to_csv(output_path, index=False, encoding=encoding)


def get_file_info(file_path: str) -> Dict[str, Any]:
    """获取文件基本信息"""
    stat = os.stat(file_path)
    ext = os.path.splitext(file_path)[1].lower()
    return {
        "file_name": os.path.basename(file_path),
        "file_path": os.path.abspath(file_path),
        "file_size": stat.st_size,
        "file_format": ext.lstrip(".").upper(),
        "modified_time": stat.st_mtime,
    }
