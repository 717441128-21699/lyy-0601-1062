"""修复建议模块：生成修正建议，支持人工确认和批量修复"""

import pandas as pd
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from .config import (
    ValidationIssue, ErrorCode, ErrorLevel,
    VALID_DEPARTMENTS, VALID_EMPLOYMENT_TYPES, VALID_STATUS,
    ALL_FIELDS, FIELD_CN_MAPPING,
)


@dataclass
class FixSuggestion:
    """修复建议"""
    issue: ValidationIssue
    emp_id: Optional[str]
    field_name: Optional[str]
    row_index: Optional[int]
    suggested_value: Any
    fix_type: str
    confidence: str
    needs_confirmation: bool
    description: str


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, str) and value.lower() in ["nan", "none", "null", "nat"]:
        return True
    return False


def _fuzzy_match(value: str, valid_list: List[str], threshold: float = 0.6) -> Optional[str]:
    """简单的模糊匹配，找到最相似的有效值"""
    if not value:
        return None
    value_clean = value.strip()
    if value_clean in valid_list:
        return value_clean

    best_match = None
    best_score = 0
    value_lower = value_clean.lower()

    for valid in valid_list:
        valid_lower = valid.lower()
        score = 0

        if value_lower == valid_lower:
            return valid

        if valid_lower.startswith(value_lower) or value_lower.startswith(valid_lower):
            score = 0.8

        common = len(set(value_lower) & set(valid_lower))
        total = len(set(value_lower) | set(valid_lower))
        if total > 0:
            score = max(score, common / total)

        if value_lower in valid_lower or valid_lower in value_lower:
            score = max(score, 0.7)

        if score > best_score and score >= threshold:
            best_score = score
            best_match = valid

    return best_match


def _normalize_date_value(value: str) -> Optional[str]:
    """尝试标准化日期格式为 YYYY-MM-DD"""
    if _is_empty(value):
        return None
    value = str(value).strip()
    from .validator import _parse_date
    parsed = _parse_date(value)
    if parsed:
        return parsed.strftime("%Y-%m-%d")

    digits = "".join(c for c in value if c.isdigit())
    if len(digits) == 8:
        try:
            return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
        except (ValueError, IndexError):
            pass
    if len(digits) == 6:
        try:
            return f"{digits[:4]}-{digits[4:6]}-01"
        except (ValueError, IndexError):
            pass
    return None


def generate_fix_suggestions(
    df: pd.DataFrame,
    issues: List[ValidationIssue]
) -> List[FixSuggestion]:
    """
    为每个校验问题生成修复建议

    Args:
        df: 花名册 DataFrame
        issues: 校验问题列表

    Returns:
        修复建议列表
    """
    suggestions: List[FixSuggestion] = []
    df_lookup = {}
    for _, row in df.iterrows():
        rid = row.get("row_id")
        if rid is not None:
            df_lookup[int(rid)] = row
        eid = row.get("emp_id")
        if eid and not _is_empty(eid):
            df_lookup[f"eid_{eid}"] = row

    valid_ids = set(df[~df["emp_id"].apply(_is_empty)]["emp_id"].tolist())

    for issue in issues:
        if issue.error_code == ErrorCode.DUPLICATE_EMP_ID:
            suggestions.append(FixSuggestion(
                issue=issue,
                emp_id=issue.emp_id,
                field_name="emp_id",
                row_index=issue.row_index,
                suggested_value=None,
                fix_type="delete_duplicate",
                confidence="medium",
                needs_confirmation=True,
                description=f"工号 {issue.emp_id} 重复，请确认删除重复记录或更正工号",
            ))

        elif issue.error_code == ErrorCode.EMPTY_FIELD:
            field = issue.field_name
            suggested = None
            confidence = "low"
            desc = f"字段 {FIELD_CN_MAPPING.get(field, field)} 需要补充信息"

            if field == "status":
                if issue.row_index and issue.row_index in df_lookup:
                    row = df_lookup[issue.row_index]
                    resign_date = row.get("resign_date")
                    suggested = "离职" if not _is_empty(resign_date) else "在职"
                    confidence = "medium" if suggested else "low"

            elif field == "supervisor_id":
                if issue.emp_id:
                    key = f"eid_{issue.emp_id}"
                    if key in df_lookup:
                        row = df_lookup[key]
                        dept = row.get("department")
                        if not _is_empty(dept):
                            dept_emps = df[df["department"] == dept]
                            positions = ["经理", "主管", "总监", "负责人", "主任"]
                            for pos in positions:
                                managers = dept_emps[
                                    dept_emps["position"].fillna("").str.contains(pos, na=False)
                                ]
                                if not managers.empty:
                                    suggested = managers.iloc[0]["emp_id"]
                                    confidence = "medium"
                                    desc = f"建议补充上级为同部门{pos}: {managers.iloc[0].get('name', suggested)}"
                                    break

            elif field == "department":
                if issue.emp_id:
                    key = f"eid_{issue.emp_id}"
                    if key in df_lookup:
                        row = df_lookup[key]
                        pos = row.get("position", "")
                        dept_hints = {
                            "工程师": "技术部", "开发": "技术部", "研发": "研发中心",
                            "产品": "产品部", "设计": "设计部", "测试": "测试部",
                            "销售": "销售部", "市场": "市场部", "运营": "运营部",
                            "人事": "人力资源部", "HR": "人力资源部", "财务": "财务部",
                            "行政": "行政部", "客服": "客户服务部", "采购": "采购部",
                            "生产": "生产部", "质检": "质量管理部", "法务": "法务部",
                        }
                        for kw, dept in dept_hints.items():
                            if kw in str(pos):
                                suggested = dept
                                confidence = "medium"
                                break

            elif field == "employment_type":
                suggested = "正式"
                confidence = "low"

            suggestions.append(FixSuggestion(
                issue=issue,
                emp_id=issue.emp_id,
                field_name=field,
                row_index=issue.row_index,
                suggested_value=suggested,
                fix_type="fill_empty",
                confidence=confidence,
                needs_confirmation=confidence != "high",
                description=desc,
            ))

        elif issue.error_code == ErrorCode.INVALID_DATE:
            field = issue.field_name
            suggested = _normalize_date_value(str(issue.actual_value)) if issue.actual_value else None
            confidence = "high" if suggested else "low"
            suggestions.append(FixSuggestion(
                issue=issue,
                emp_id=issue.emp_id,
                field_name=field,
                row_index=issue.row_index,
                suggested_value=suggested,
                fix_type="fix_date_format",
                confidence=confidence,
                needs_confirmation=confidence != "high",
                description=f"建议将日期格式化为 YYYY-MM-DD: {suggested if suggested else '需人工确认'}",
            ))

        elif issue.error_code == ErrorCode.FUTURE_DATE:
            field = issue.field_name
            suggestions.append(FixSuggestion(
                issue=issue,
                emp_id=issue.emp_id,
                field_name=field,
                row_index=issue.row_index,
                suggested_value=None,
                fix_type="verify_future_date",
                confidence="medium",
                needs_confirmation=True,
                description=f"日期 {issue.actual_value} 在未来，请确认是否为预期（如预入职）",
            ))

        elif issue.error_code == ErrorCode.DEPARTMENT_NOT_FOUND:
            actual = str(issue.actual_value) if issue.actual_value else ""
            suggested = _fuzzy_match(actual, VALID_DEPARTMENTS)
            confidence = "high" if suggested and suggested == actual.strip() else ("medium" if suggested else "low")
            desc_parts = []
            if suggested:
                desc_parts.append(f"建议修正为: {suggested}")
            desc_parts.append(f"有效部门: {', '.join(VALID_DEPARTMENTS[:10])}{'...' if len(VALID_DEPARTMENTS) > 10 else ''}")
            suggestions.append(FixSuggestion(
                issue=issue,
                emp_id=issue.emp_id,
                field_name="department",
                row_index=issue.row_index,
                suggested_value=suggested,
                fix_type="fix_department",
                confidence=confidence,
                needs_confirmation=True,
                description=" | ".join(desc_parts),
            ))

        elif issue.error_code == ErrorCode.INVALID_EMPLOYMENT_TYPE:
            actual = str(issue.actual_value) if issue.actual_value else ""
            suggested = _fuzzy_match(actual, VALID_EMPLOYMENT_TYPES)
            confidence = "high" if suggested and suggested == actual.strip() else ("medium" if suggested else "low")
            desc = f"有效类型: {', '.join(VALID_EMPLOYMENT_TYPES)}"
            if suggested:
                desc = f"建议修正为: {suggested} | {desc}"
            suggestions.append(FixSuggestion(
                issue=issue,
                emp_id=issue.emp_id,
                field_name="employment_type",
                row_index=issue.row_index,
                suggested_value=suggested,
                fix_type="fix_employment_type",
                confidence=confidence,
                needs_confirmation=True,
                description=desc,
            ))

        elif issue.error_code == ErrorCode.SUPERVISOR_NOT_FOUND:
            suggestions.append(FixSuggestion(
                issue=issue,
                emp_id=issue.emp_id,
                field_name="supervisor_id",
                row_index=issue.row_index,
                suggested_value=None,
                fix_type="fix_supervisor",
                confidence="low",
                needs_confirmation=True,
                description=f"上级工号 {issue.actual_value} 不存在，请确认工号或先录入上级信息",
            ))

        elif issue.error_code == ErrorCode.SUPERVISOR_CYCLE:
            suggestions.append(FixSuggestion(
                issue=issue,
                emp_id=issue.emp_id,
                field_name="supervisor_id",
                row_index=issue.row_index,
                suggested_value=None,
                fix_type="break_cycle",
                confidence="low",
                needs_confirmation=True,
                description=f"存在循环引用: {issue.actual_value}，请调整上级关系",
            ))

        elif issue.error_code == ErrorCode.EMPLOYMENT_STATUS_CONFLICT:
            if issue.row_index and issue.row_index in df_lookup:
                row = df_lookup[issue.row_index]
                status = row.get("status")
                resign_date = row.get("resign_date")
                hire_date = row.get("hire_date")
                suggested = None
                if _is_empty(status) and not _is_empty(resign_date):
                    suggested = "离职"
                elif status == "在职" and not _is_empty(resign_date):
                    suggested = "离职"
                elif status == "离职" and _is_empty(resign_date):
                    today = datetime.now().strftime("%Y-%m-%d")
                    suggestions.append(FixSuggestion(
                        issue=issue,
                        emp_id=issue.emp_id,
                        field_name="resign_date",
                        row_index=issue.row_index,
                        suggested_value=today,
                        fix_type="add_resign_date",
                        confidence="medium",
                        needs_confirmation=True,
                        description=f"状态为离职但缺少离职日期，建议补充: {today}（请确认）",
                    ))
                    continue
                if suggested:
                    suggestions.append(FixSuggestion(
                        issue=issue,
                        emp_id=issue.emp_id,
                        field_name="status",
                        row_index=issue.row_index,
                        suggested_value=suggested,
                        fix_type="fix_status",
                        confidence="medium",
                        needs_confirmation=True,
                        description=f"建议修正状态为: {suggested}",
                    ))
                    continue
            suggestions.append(FixSuggestion(
                issue=issue,
                emp_id=issue.emp_id,
                field_name="status",
                row_index=issue.row_index,
                suggested_value=None,
                fix_type="fix_status_conflict",
                confidence="low",
                needs_confirmation=True,
                description=f"状态冲突: {issue.message}，请人工确认",
            ))

        elif issue.error_code == ErrorCode.INVALID_NAME_FORMAT:
            suggestions.append(FixSuggestion(
                issue=issue,
                emp_id=issue.emp_id,
                field_name="name",
                row_index=issue.row_index,
                suggested_value=None,
                fix_type="verify_name",
                confidence="low",
                needs_confirmation=True,
                description=f"姓名 '{issue.actual_value}' 格式异常，请人工确认",
            ))

    return suggestions


def suggestions_to_dataframe(suggestions: List[FixSuggestion]) -> pd.DataFrame:
    """将修复建议转换为 DataFrame"""
    records = []
    conf_icons = {"high": "高", "medium": "中", "low": "低"}
    for idx, s in enumerate(suggestions, 1):
        records.append({
            "序号": idx,
            "工号": s.emp_id if s.emp_id else "",
            "行号": s.row_index if s.row_index else "",
            "问题字段": FIELD_CN_MAPPING.get(s.field_name, s.field_name) if s.field_name else "",
            "错误等级": s.issue.error_level.value,
            "错误代码": s.issue.error_code.value,
            "问题描述": s.issue.message,
            "建议修复值": s.suggested_value if s.suggested_value is not None else "",
            "修复方式": s.fix_type,
            "置信度": conf_icons.get(s.confidence, s.confidence),
            "需人工确认": "是" if s.needs_confirmation else "否",
            "详细说明": s.description,
            "是否采纳": "",
            "人工修正值": "",
        })
    return pd.DataFrame(records) if records else pd.DataFrame(columns=[
        "序号", "工号", "行号", "问题字段", "错误等级", "错误代码", "问题描述",
        "建议修复值", "修复方式", "置信度", "需人工确认", "详细说明", "是否采纳", "人工修正值"
    ])


def apply_fixes(
    df: pd.DataFrame,
    suggestions: List[FixSuggestion],
    confirmation_df: Optional[pd.DataFrame] = None
) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """
    应用修复建议到 DataFrame

    Args:
        df: 原始花名册
        suggestions: 修复建议列表
        confirmation_df: 人工确认表，可选，包含"序号"、"是否采纳"、"人工修正值"列

    Returns:
        (修复后的 DataFrame, 统计信息)
    """
    fixed_df = df.copy()
    stats = {
        "total_suggestions": len(suggestions),
        "applied": 0,
        "skipped": 0,
        "needs_manual": 0,
    }

    confirm_map = {}
    if confirmation_df is not None and not confirmation_df.empty:
        for _, row in confirmation_df.iterrows():
            seq = row.get("序号")
            if seq is not None:
                confirm_map[int(seq)] = {
                    "accepted": str(row.get("是否采纳", "")).strip() in ["是", "Y", "y", "1", "true", "TRUE"],
                    "manual_value": row.get("人工修正值") if not _is_empty(row.get("人工修正值")) else None,
                }

    for idx, s in enumerate(suggestions, 1):
        confirm_info = confirm_map.get(idx)
        should_apply = False
        value_to_use = None

        if s.needs_confirmation:
            if confirm_info and confirm_info["accepted"]:
                should_apply = True
                value_to_use = confirm_info["manual_value"] if confirm_info["manual_value"] else s.suggested_value
            else:
                stats["needs_manual"] += 1
                continue
        else:
            should_apply = True
            value_to_use = s.suggested_value
            if confirm_info and confirm_info["accepted"] and confirm_info["manual_value"]:
                value_to_use = confirm_info["manual_value"]

        if not should_apply:
            stats["skipped"] += 1
            continue

        if value_to_use is None and s.fix_type not in ["delete_duplicate", "break_cycle"]:
            stats["skipped"] += 1
            continue

        if s.fix_type == "delete_duplicate":
            stats["applied"] += 1
            continue

        target_mask = None
        if s.row_index and "row_id" in fixed_df.columns:
            target_mask = fixed_df["row_id"] == s.row_index
        elif s.emp_id and "emp_id" in fixed_df.columns:
            target_mask = fixed_df["emp_id"] == s.emp_id

        if target_mask is not None and s.field_name and s.field_name in fixed_df.columns:
            fixed_df.loc[target_mask, s.field_name] = value_to_use
            stats["applied"] += 1
        else:
            stats["skipped"] += 1

    return fixed_df, stats
