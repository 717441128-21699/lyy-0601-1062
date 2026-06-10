"""外置规则配置加载模块：支持 JSON 格式配置文件统一管理校验规则"""

import os
import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from copy import deepcopy

from .config import (
    REQUIRED_FIELDS, OPTIONAL_FIELDS, ALL_FIELDS,
    VALID_DEPARTMENTS, VALID_EMPLOYMENT_TYPES, VALID_STATUS,
    ERROR_LEVEL_CONFIG, ErrorCode, ErrorLevel,
    FIELD_CN_MAPPING, DATE_FORMATS,
)


@dataclass
class RulesConfig:
    """校验规则配置对象"""

    required_fields: List[str] = field(default_factory=lambda: list(REQUIRED_FIELDS))
    optional_fields: List[str] = field(default_factory=lambda: list(OPTIONAL_FIELDS))
    valid_departments: List[str] = field(default_factory=lambda: list(VALID_DEPARTMENTS))
    valid_employment_types: List[str] = field(default_factory=lambda: list(VALID_EMPLOYMENT_TYPES))
    valid_statuses: List[str] = field(default_factory=lambda: list(VALID_STATUS))
    date_formats: List[str] = field(default_factory=lambda: list(DATE_FORMATS))
    error_levels: Dict[str, str] = field(default_factory=dict)
    field_cn_mapping: Dict[str, str] = field(default_factory=dict)
    status_rules: Dict[str, Any] = field(default_factory=lambda: {
        "active_statuses": ["在职"],
        "resigned_statuses": ["离职", "退休"],
        "require_resign_date_for_resigned": True,
        "forbid_resign_date_for_active": True,
    })
    custom: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.error_levels:
            self.error_levels = {k.value: v.value for k, v in ERROR_LEVEL_CONFIG.items()}
        if not self.field_cn_mapping:
            self.field_cn_mapping = dict(FIELD_CN_MAPPING)

    @property
    def all_fields(self) -> List[str]:
        return self.required_fields + self.optional_fields

    @property
    def cn_field_mapping(self) -> Dict[str, str]:
        return {v: k for k, v in self.field_cn_mapping.items()}

    def get_error_level(self, code: ErrorCode) -> ErrorLevel:
        """获取错误代码对应的错误等级"""
        level_str = self.error_levels.get(code.value, ERROR_LEVEL_CONFIG.get(code, ErrorLevel.ERROR).value)
        try:
            return ErrorLevel(level_str)
        except (ValueError, KeyError):
            return ErrorLevel.ERROR

    def get_field_cn(self, field: str) -> str:
        """获取字段中文名"""
        return self.field_cn_mapping.get(field, field)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


DEFAULT_CONFIG = RulesConfig()


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """深度合并两个字典，override 覆盖 base"""
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_rules_config(config_path: Optional[str] = None) -> RulesConfig:
    """
    加载规则配置文件

    Args:
        config_path: 配置文件路径（JSON 格式），None 则返回默认配置

    Returns:
        RulesConfig 配置对象
    """
    if not config_path:
        return RulesConfig()

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"规则配置文件不存在: {config_path}")

    ext = os.path.splitext(config_path)[1].lower()
    if ext != ".json":
        raise ValueError(f"规则配置文件必须是 JSON 格式，当前为: {ext}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            user_config = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"规则配置文件 JSON 格式错误: {e}")

    default_dict = DEFAULT_CONFIG.to_dict()
    merged_dict = _deep_merge(default_dict, user_config)

    clean_dict = {k: v for k, v in merged_dict.items() if not k.startswith("_")}

    try:
        config = RulesConfig(**clean_dict)
    except TypeError as e:
        raise ValueError(f"规则配置文件包含未知字段: {e}")

    return config


def save_rules_config(config: RulesConfig, output_path: str) -> None:
    """
    保存规则配置到 JSON 文件

    Args:
        config: 配置对象
        output_path: 输出文件路径
    """
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, ensure_ascii=False, indent=2)


def generate_template_config(output_path: str) -> None:
    """
    生成模板配置文件，包含注释说明（用 JSON 的 _comment 字段）

    Args:
        output_path: 输出文件路径
    """
    template = {
        "_comment": "HR 花名册校验规则配置模板 - 按需修改后使用 check/fix/report 的 -r 参数指定此文件",
        "required_fields": REQUIRED_FIELDS,
        "_required_fields_comment": "必填字段列表，空值将报 ERROR",
        "optional_fields": OPTIONAL_FIELDS,
        "_optional_fields_comment": "可选字段列表，不校验空值",
        "valid_departments": VALID_DEPARTMENTS,
        "_valid_departments_comment": "有效部门列表，不在此列表将报错",
        "valid_employment_types": VALID_EMPLOYMENT_TYPES,
        "_valid_employment_types_comment": "有效用工类型列表",
        "valid_statuses": VALID_STATUS,
        "_valid_statuses_comment": "有效在职状态列表",
        "date_formats": DATE_FORMATS,
        "_date_formats_comment": "支持的日期格式列表（按顺序尝试解析）",
        "error_levels": {k.value: v.value for k, v in ERROR_LEVEL_CONFIG.items()},
        "_error_levels_comment": "错误等级调整：CRITICAL/ERROR/WARNING/INFO，可降级或升级特定错误",
        "field_cn_mapping": FIELD_CN_MAPPING,
        "_field_cn_mapping_comment": "字段中英文映射，用于识别中文列名和导出报表",
        "status_rules": {
            "active_statuses": ["在职"],
            "resigned_statuses": ["离职", "退休"],
            "require_resign_date_for_resigned": True,
            "forbid_resign_date_for_active": True,
        },
        "_status_rules_comment": "在职状态业务规则：哪些算在职/离职，离职日期的要求",
        "custom": {},
        "_custom_comment": "自定义扩展配置，可用于脚本扩展",
    }

    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(template, f, ensure_ascii=False, indent=2)
