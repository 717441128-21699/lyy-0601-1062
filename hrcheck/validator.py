"""核心校验模块：实现所有数据校验规则"""

import pandas as pd
from datetime import datetime, date
from typing import List, Optional, Tuple
from collections import defaultdict
from .config import (
    ValidationIssue, ErrorCode, ErrorLevel,
    REQUIRED_FIELDS, VALID_DEPARTMENTS, VALID_EMPLOYMENT_TYPES, VALID_STATUS,
    DATE_FORMATS, ERROR_LEVEL_CONFIG, ERROR_MESSAGE_TEMPLATES, SUGGESTION_TEMPLATES,
    FIELD_CN_MAPPING,
)


def _parse_date(value: str) -> Optional[datetime]:
    """尝试用多种格式解析日期"""
    if not value or pd.isna(value) or str(value).strip() == "":
        return None
    value = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _is_empty(value) -> bool:
    """判断值是否为空"""
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, str) and value.lower() in ["nan", "none", "null", "nat"]:
        return True
    return False


def check_duplicate_emp_ids(df: pd.DataFrame) -> List[ValidationIssue]:
    """检查重复工号"""
    issues = []
    valid_emp_ids = df[~df["emp_id"].apply(_is_empty)]["emp_id"]
    dup_counts = valid_emp_ids.value_counts()
    duplicates = dup_counts[dup_counts > 1]

    for emp_id, count in duplicates.items():
        dup_rows = df[df["emp_id"] == emp_id]
        for _, row in dup_rows.iterrows():
            issues.append(ValidationIssue(
                error_code=ErrorCode.DUPLICATE_EMP_ID,
                error_level=ERROR_LEVEL_CONFIG[ErrorCode.DUPLICATE_EMP_ID],
                emp_id=emp_id,
                field_name="emp_id",
                message=ERROR_MESSAGE_TEMPLATES[ErrorCode.DUPLICATE_EMP_ID].format(emp_id, count),
                row_index=int(row.get("row_id", 0)) if "row_id" in df.columns else None,
                suggestion=SUGGESTION_TEMPLATES[ErrorCode.DUPLICATE_EMP_ID],
                actual_value=emp_id,
            ))
    return issues


def check_empty_required_fields(df: pd.DataFrame) -> List[ValidationIssue]:
    """检查必填字段为空"""
    issues = []
    for _, row in df.iterrows():
        emp_id = row.get("emp_id")
        row_idx = int(row.get("row_id", 0)) if "row_id" in df.columns else None
        for field in REQUIRED_FIELDS:
            value = row.get(field)
            if _is_empty(value):
                field_cn = FIELD_CN_MAPPING.get(field, field)
                issues.append(ValidationIssue(
                    error_code=ErrorCode.EMPTY_FIELD,
                    error_level=ERROR_LEVEL_CONFIG[ErrorCode.EMPTY_FIELD],
                    emp_id=emp_id if not _is_empty(emp_id) else None,
                    field_name=field,
                    message=ERROR_MESSAGE_TEMPLATES[ErrorCode.EMPTY_FIELD].format(field_cn),
                    row_index=row_idx,
                    suggestion=SUGGESTION_TEMPLATES[ErrorCode.EMPTY_FIELD].format(field_cn),
                    actual_value=value,
                ))
    return issues


def check_date_fields(df: pd.DataFrame) -> List[ValidationIssue]:
    """检查日期字段格式和有效性"""
    issues = []
    today = date.today()

    for _, row in df.iterrows():
        emp_id = row.get("emp_id")
        row_idx = int(row.get("row_id", 0)) if "row_id" in df.columns else None

        for date_field in ["hire_date", "resign_date", "birthday"]:
            value = row.get(date_field)
            if _is_empty(value):
                continue
            parsed = _parse_date(value)
            if parsed is None:
                field_cn = FIELD_CN_MAPPING.get(date_field, date_field)
                issues.append(ValidationIssue(
                    error_code=ErrorCode.INVALID_DATE,
                    error_level=ERROR_LEVEL_CONFIG[ErrorCode.INVALID_DATE],
                    emp_id=emp_id if not _is_empty(emp_id) else None,
                    field_name=date_field,
                    message=ERROR_MESSAGE_TEMPLATES[ErrorCode.INVALID_DATE].format(field_cn, value),
                    row_index=row_idx,
                    suggestion=SUGGESTION_TEMPLATES[ErrorCode.INVALID_DATE].format(field_cn),
                    actual_value=value,
                ))
            else:
                d = parsed.date()
                if d > today:
                    field_cn = FIELD_CN_MAPPING.get(date_field, date_field)
                    issues.append(ValidationIssue(
                        error_code=ErrorCode.FUTURE_DATE,
                        error_level=ERROR_LEVEL_CONFIG[ErrorCode.FUTURE_DATE],
                        emp_id=emp_id if not _is_empty(emp_id) else None,
                        field_name=date_field,
                        message=ERROR_MESSAGE_TEMPLATES[ErrorCode.FUTURE_DATE].format(field_cn, d),
                        row_index=row_idx,
                        suggestion=SUGGESTION_TEMPLATES[ErrorCode.FUTURE_DATE].format(field_cn),
                        actual_value=str(d),
                    ))
    return issues


def check_departments(df: pd.DataFrame, valid_departments: Optional[List[str]] = None) -> List[ValidationIssue]:
    """检查部门有效性"""
    issues = []
    depts = valid_departments if valid_departments else VALID_DEPARTMENTS

    for _, row in df.iterrows():
        value = row.get("department")
        if _is_empty(value):
            continue
        if value not in depts:
            emp_id = row.get("emp_id")
            row_idx = int(row.get("row_id", 0)) if "row_id" in df.columns else None
            issues.append(ValidationIssue(
                error_code=ErrorCode.DEPARTMENT_NOT_FOUND,
                error_level=ERROR_LEVEL_CONFIG[ErrorCode.DEPARTMENT_NOT_FOUND],
                emp_id=emp_id if not _is_empty(emp_id) else None,
                field_name="department",
                message=ERROR_MESSAGE_TEMPLATES[ErrorCode.DEPARTMENT_NOT_FOUND].format(value),
                row_index=row_idx,
                suggestion=SUGGESTION_TEMPLATES[ErrorCode.DEPARTMENT_NOT_FOUND],
                actual_value=value,
            ))
    return issues


def check_employment_types(df: pd.DataFrame) -> List[ValidationIssue]:
    """检查用工类型有效性"""
    issues = []
    for _, row in df.iterrows():
        value = row.get("employment_type")
        if _is_empty(value):
            continue
        if value not in VALID_EMPLOYMENT_TYPES:
            emp_id = row.get("emp_id")
            row_idx = int(row.get("row_id", 0)) if "row_id" in df.columns else None
            issues.append(ValidationIssue(
                error_code=ErrorCode.INVALID_EMPLOYMENT_TYPE,
                error_level=ERROR_LEVEL_CONFIG[ErrorCode.INVALID_EMPLOYMENT_TYPE],
                emp_id=emp_id if not _is_empty(emp_id) else None,
                field_name="employment_type",
                message=ERROR_MESSAGE_TEMPLATES[ErrorCode.INVALID_EMPLOYMENT_TYPE].format(value),
                row_index=row_idx,
                suggestion=SUGGESTION_TEMPLATES[ErrorCode.INVALID_EMPLOYMENT_TYPE].format(
                    "、".join(VALID_EMPLOYMENT_TYPES)
                ),
                actual_value=value,
            ))
    return issues


def _detect_cycles(supervisor_map: dict) -> List[List[str]]:
    """检测有向图中的循环"""
    cycles = []
    visited = set()
    path = []
    path_set = set()

    def dfs(node: str):
        if node in path_set:
            cycle_start = path.index(node)
            cycles.append(path[cycle_start:] + [node])
            return
        if node in visited:
            return
        visited.add(node)
        path.append(node)
        path_set.add(node)
        if node in supervisor_map and supervisor_map[node]:
            dfs(supervisor_map[node])
        path.pop()
        path_set.discard(node)

    for node in supervisor_map:
        dfs(node)
    return cycles


def check_supervisor_relations(df: pd.DataFrame) -> List[ValidationIssue]:
    """检查上下级关系：上级不存在、循环引用"""
    issues = []
    valid_ids = set(df[~df["emp_id"].apply(_is_empty)]["emp_id"].tolist())

    supervisor_map = {}
    for _, row in df.iterrows():
        emp_id = row.get("emp_id")
        sup_id = row.get("supervisor_id")
        if not _is_empty(emp_id) and not _is_empty(sup_id):
            supervisor_map[emp_id] = sup_id

    for _, row in df.iterrows():
        emp_id = row.get("emp_id")
        sup_id = row.get("supervisor_id")
        row_idx = int(row.get("row_id", 0)) if "row_id" in df.columns else None

        if _is_empty(sup_id):
            continue

        if sup_id not in valid_ids:
            issues.append(ValidationIssue(
                error_code=ErrorCode.SUPERVISOR_NOT_FOUND,
                error_level=ERROR_LEVEL_CONFIG[ErrorCode.SUPERVISOR_NOT_FOUND],
                emp_id=emp_id if not _is_empty(emp_id) else None,
                field_name="supervisor_id",
                message=ERROR_MESSAGE_TEMPLATES[ErrorCode.SUPERVISOR_NOT_FOUND].format(sup_id),
                row_index=row_idx,
                suggestion=SUGGESTION_TEMPLATES[ErrorCode.SUPERVISOR_NOT_FOUND],
                actual_value=sup_id,
            ))

    cycles = _detect_cycles(supervisor_map)
    seen_cycles = set()
    for cycle in cycles:
        cycle_key = "->".join(sorted(cycle[:-1]))
        if cycle_key in seen_cycles:
            continue
        seen_cycles.add(cycle_key)
        cycle_desc = " -> ".join(cycle)
        for emp_id in cycle[:-1]:
            row_data = df[df["emp_id"] == emp_id]
            if not row_data.empty:
                row_idx = int(row_data.iloc[0].get("row_id", 0)) if "row_id" in df.columns else None
                issues.append(ValidationIssue(
                    error_code=ErrorCode.SUPERVISOR_CYCLE,
                    error_level=ERROR_LEVEL_CONFIG[ErrorCode.SUPERVISOR_CYCLE],
                    emp_id=emp_id,
                    field_name="supervisor_id",
                    message=ERROR_MESSAGE_TEMPLATES[ErrorCode.SUPERVISOR_CYCLE].format(cycle_desc),
                    row_index=row_idx,
                    suggestion=SUGGESTION_TEMPLATES[ErrorCode.SUPERVISOR_CYCLE],
                    actual_value=cycle_desc,
                ))
    return issues


def check_employment_status(df: pd.DataFrame) -> List[ValidationIssue]:
    """检查在职状态与入职/离职日期的一致性"""
    issues = []
    for _, row in df.iterrows():
        emp_id = row.get("emp_id")
        status = row.get("status")
        hire_date = _parse_date(row.get("hire_date"))
        resign_date = _parse_date(row.get("resign_date"))
        row_idx = int(row.get("row_id", 0)) if "row_id" in df.columns else None

        conflict_msg = None
        if _is_empty(status):
            if not _is_empty(resign_date):
                conflict_msg = f"有离职日期 ({resign_date.date()}) 但状态为空"
            else:
                continue
        elif status == "在职":
            if not _is_empty(resign_date):
                conflict_msg = f"状态为'在职'但存在离职日期 ({resign_date.date()})"
            if not _is_empty(hire_date) and hire_date > datetime.now():
                conflict_msg = f"状态为'在职'但入职日期 ({hire_date.date()}) 在未来"
        elif status == "离职":
            if _is_empty(resign_date):
                conflict_msg = "状态为'离职'但缺少离职日期"
            elif not _is_empty(hire_date) and resign_date < hire_date:
                conflict_msg = f"离职日期 ({resign_date.date()}) 早于入职日期 ({hire_date.date()})"
        elif status in ["停薪留职", "退休"]:
            pass

        if conflict_msg:
            issues.append(ValidationIssue(
                error_code=ErrorCode.EMPLOYMENT_STATUS_CONFLICT,
                error_level=ERROR_LEVEL_CONFIG[ErrorCode.EMPLOYMENT_STATUS_CONFLICT],
                emp_id=emp_id if not _is_empty(emp_id) else None,
                field_name="status",
                message=ERROR_MESSAGE_TEMPLATES[ErrorCode.EMPLOYMENT_STATUS_CONFLICT].format(conflict_msg),
                row_index=row_idx,
                suggestion=SUGGESTION_TEMPLATES[ErrorCode.EMPLOYMENT_STATUS_CONFLICT],
                actual_value=f"status={status}, hire={row.get('hire_date')}, resign={row.get('resign_date')}",
            ))
    return issues


def validate_roster(
    df: pd.DataFrame,
    valid_departments: Optional[List[str]] = None
) -> List[ValidationIssue]:
    """
    执行所有校验规则

    Args:
        df: 员工花名册 DataFrame
        valid_departments: 自定义有效部门列表，None 则使用默认

    Returns:
        校验问题列表
    """
    issues: List[ValidationIssue] = []

    issues.extend(check_duplicate_emp_ids(df))
    issues.extend(check_empty_required_fields(df))
    issues.extend(check_date_fields(df))
    issues.extend(check_departments(df, valid_departments))
    issues.extend(check_employment_types(df))
    issues.extend(check_supervisor_relations(df))
    issues.extend(check_employment_status(df))

    return issues


def sort_issues(issues: List[ValidationIssue]) -> List[ValidationIssue]:
    """按错误等级和行号排序问题"""
    level_order = {
        ErrorLevel.CRITICAL: 0,
        ErrorLevel.ERROR: 1,
        ErrorLevel.WARNING: 2,
        ErrorLevel.INFO: 3,
    }
    return sorted(issues, key=lambda x: (
        level_order.get(x.error_level, 99),
        x.row_index if x.row_index else 0,
        x.error_code.value,
    ))


def issues_to_dataframe(issues: List[ValidationIssue]) -> pd.DataFrame:
    """将校验问题转换为 DataFrame 便于导出"""
    records = []
    for issue in sort_issues(issues):
        records.append({
            "错误等级": issue.error_level.value,
            "错误代码": issue.error_code.value,
            "行号": issue.row_index,
            "工号": issue.emp_id,
            "字段": FIELD_CN_MAPPING.get(issue.field_name, issue.field_name) if issue.field_name else "",
            "问题描述": issue.message,
            "修正建议": issue.suggestion,
            "当前值": issue.actual_value,
        })
    return pd.DataFrame(records) if records else pd.DataFrame(columns=[
        "错误等级", "错误代码", "行号", "工号", "字段", "问题描述", "修正建议", "当前值"
    ])


def get_clean_roster(df: pd.DataFrame, issues: List[ValidationIssue]) -> pd.DataFrame:
    """获取没有问题的干净数据"""
    problem_rows = set()
    problem_emp_ids = set()

    for issue in issues:
        if issue.error_level in [ErrorLevel.CRITICAL, ErrorLevel.ERROR]:
            if issue.row_index:
                problem_rows.add(issue.row_index)
            if issue.emp_id:
                problem_emp_ids.add(issue.emp_id)

    clean_df = df.copy()
    if "row_id" in clean_df.columns:
        clean_df = clean_df[~clean_df["row_id"].isin(problem_rows)]
    if not clean_df.empty and "emp_id" in clean_df.columns:
        clean_df = clean_df[~clean_df["emp_id"].isin(problem_emp_ids)]

    return clean_df
