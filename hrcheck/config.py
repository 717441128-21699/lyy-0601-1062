"""核心配置：字段定义、错误等级、校验规则"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


class ErrorLevel(str, Enum):
    """错误等级"""
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class ErrorCode(str, Enum):
    """错误代码"""
    DUPLICATE_EMP_ID = "DUPLICATE_EMP_ID"
    EMPTY_FIELD = "EMPTY_FIELD"
    INVALID_DATE = "INVALID_DATE"
    FUTURE_DATE = "FUTURE_DATE"
    DEPARTMENT_NOT_FOUND = "DEPARTMENT_NOT_FOUND"
    SUPERVISOR_CYCLE = "SUPERVISOR_CYCLE"
    SUPERVISOR_NOT_FOUND = "SUPERVISOR_NOT_FOUND"
    EMPLOYMENT_STATUS_CONFLICT = "EMPLOYMENT_STATUS_CONFLICT"
    INVALID_EMPLOYMENT_TYPE = "INVALID_EMPLOYMENT_TYPE"
    INVALID_NAME_FORMAT = "INVALID_NAME_FORMAT"


@dataclass
class ValidationIssue:
    """校验问题"""
    error_code: ErrorCode
    error_level: ErrorLevel
    emp_id: Optional[str]
    field_name: Optional[str]
    message: str
    row_index: Optional[int] = None
    suggestion: Optional[str] = None
    actual_value: Any = None


REQUIRED_FIELDS = [
    "emp_id",
    "name",
    "department",
    "position",
    "hire_date",
    "employment_type",
    "supervisor_id",
]

OPTIONAL_FIELDS = [
    "status",
    "resign_date",
    "phone",
    "email",
    "id_card",
    "gender",
    "birthday",
    "education",
]

ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

FIELD_CN_MAPPING = {
    "emp_id": "工号",
    "name": "姓名",
    "department": "部门",
    "position": "岗位",
    "hire_date": "入职日期",
    "employment_type": "用工类型",
    "supervisor_id": "直属上级工号",
    "status": "在职状态",
    "resign_date": "离职日期",
    "phone": "电话",
    "email": "邮箱",
    "id_card": "身份证号",
    "gender": "性别",
    "birthday": "生日",
    "education": "学历",
}

CN_FIELD_MAPPING = {v: k for k, v in FIELD_CN_MAPPING.items()}

VALID_EMPLOYMENT_TYPES = [
    "正式",
    "试用期",
    "实习",
    "外包",
    "派遣",
    "兼职",
    "劳务",
]

VALID_STATUS = [
    "在职",
    "离职",
    "停薪留职",
    "退休",
]

VALID_DEPARTMENTS = [
    "总经办",
    "人力资源部",
    "财务部",
    "行政部",
    "技术部",
    "产品部",
    "设计部",
    "市场部",
    "销售部",
    "运营部",
    "客户服务部",
    "研发中心",
    "测试部",
    "质量管理部",
    "采购部",
    "仓储部",
    "生产部",
    "法务部",
    "审计部",
    "战略发展部",
]

DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y年%m月%d日",
    "%Y.%m.%d",
    "%Y%m%d",
    "%Y-%m",
    "%Y/%m",
]

ERROR_LEVEL_CONFIG = {
    ErrorCode.DUPLICATE_EMP_ID: ErrorLevel.CRITICAL,
    ErrorCode.EMPTY_FIELD: ErrorLevel.ERROR,
    ErrorCode.INVALID_DATE: ErrorLevel.ERROR,
    ErrorCode.FUTURE_DATE: ErrorLevel.WARNING,
    ErrorCode.DEPARTMENT_NOT_FOUND: ErrorLevel.ERROR,
    ErrorCode.SUPERVISOR_CYCLE: ErrorLevel.CRITICAL,
    ErrorCode.SUPERVISOR_NOT_FOUND: ErrorLevel.WARNING,
    ErrorCode.EMPLOYMENT_STATUS_CONFLICT: ErrorLevel.ERROR,
    ErrorCode.INVALID_EMPLOYMENT_TYPE: ErrorLevel.ERROR,
    ErrorCode.INVALID_NAME_FORMAT: ErrorLevel.WARNING,
}

ERROR_MESSAGE_TEMPLATES = {
    ErrorCode.DUPLICATE_EMP_ID: "工号 [{}] 重复出现 {} 次",
    ErrorCode.EMPTY_FIELD: "字段 [{}] 为空",
    ErrorCode.INVALID_DATE: "字段 [{}] 日期格式无效: {}",
    ErrorCode.FUTURE_DATE: "字段 [{}] 日期在未来: {}",
    ErrorCode.DEPARTMENT_NOT_FOUND: "部门 [{}] 不在有效部门列表中",
    ErrorCode.SUPERVISOR_CYCLE: "上下级关系存在循环引用: {}",
    ErrorCode.SUPERVISOR_NOT_FOUND: "直属上级工号 [{}] 不存在",
    ErrorCode.EMPLOYMENT_STATUS_CONFLICT: "在职状态与入职/离职日期冲突: {}",
    ErrorCode.INVALID_EMPLOYMENT_TYPE: "用工类型 [{}] 不在有效值列表中",
    ErrorCode.INVALID_NAME_FORMAT: "姓名 [{}] 格式异常",
}

SUGGESTION_TEMPLATES = {
    ErrorCode.DUPLICATE_EMP_ID: "请检查并删除重复的工号记录，或更正工号",
    ErrorCode.EMPTY_FIELD: "请补充 {} 字段信息",
    ErrorCode.INVALID_DATE: "请将 {} 调整为正确的日期格式 (YYYY-MM-DD)",
    ErrorCode.FUTURE_DATE: "请确认 {} 是否正确，该日期在当前日期之后",
    ErrorCode.DEPARTMENT_NOT_FOUND: "请选择有效部门或更新部门配置列表",
    ErrorCode.SUPERVISOR_CYCLE: "请检查并修正上下级关系，打破循环引用",
    ErrorCode.SUPERVISOR_NOT_FOUND: "请确认上级工号是否正确，或先录入上级信息",
    ErrorCode.EMPLOYMENT_STATUS_CONFLICT: "请检查在职状态与入职/离职日期的一致性",
    ErrorCode.INVALID_EMPLOYMENT_TYPE: "请从 {} 中选择有效的用工类型",
    ErrorCode.INVALID_NAME_FORMAT: "请确认姓名是否正确，应包含有效字符",
}

DIFF_CHANGE_TYPES = [
    "新增",
    "离职",
    "调岗",
    "改名",
    "部门变更",
    "上级变更",
    "用工类型变更",
    "其他修改",
]


@dataclass
class DiffRecord:
    """差异记录"""
    emp_id: str
    change_type: str
    field_name: Optional[str] = None
    old_value: Any = None
    new_value: Any = None
    description: str = ""


@dataclass
class DepartmentSummary:
    """部门汇总"""
    department: str
    last_month_count: int
    current_count: int
    new_count: int
    resign_count: int
    transfer_in: int
    transfer_out: int
    net_change: int
