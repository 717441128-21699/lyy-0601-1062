"""修复建议模块：生成建议、人工确认应用、重复工号删除/改号、生成修复记录"""

import pandas as pd
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
from copy import deepcopy

from .config import (
    ValidationIssue, ErrorCode, ErrorLevel,
    VALID_DEPARTMENTS, VALID_EMPLOYMENT_TYPES, VALID_STATUS,
    ALL_FIELDS, FIELD_CN_MAPPING,
)
from .rules_config import RulesConfig, DEFAULT_CONFIG


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
    allow_delete: bool = False


@dataclass
class FixApplicationResult:
    """修复应用结果"""
    fixed_df: pd.DataFrame
    applied_count: int
    skipped_count: int
    needs_manual_count: int
    deleted_rows: List[int]
    modified_fields: List[Dict]
    fix_records_df: pd.DataFrame
    recheck_issues: List[ValidationIssue]


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
    """简单模糊匹配"""
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


def _normalize_date_value(value: str, date_formats: List[str]) -> Optional[str]:
    """尝试标准化日期格式为 YYYY-MM-DD"""
    if _is_empty(value):
        return None
    value_str = str(value).strip()
    from .validator import _parse_date
    parsed = _parse_date(value_str, date_formats)
    if parsed:
        return parsed.strftime("%Y-%m-%d")
    digits = "".join(c for c in value_str if c.isdigit())
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
    issues: List[ValidationIssue],
    rules_config: Optional[RulesConfig] = None
) -> List[FixSuggestion]:
    """
    为每个校验问题生成修复建议

    关键改进：
    - 重复工号建议增加 allow_delete 标记，允许 HR 选择删除某行
    - 所有建议支持 RulesConfig

    Args:
        df: 花名册 DataFrame
        issues: 校验问题列表
        rules_config: 规则配置

    Returns:
        修复建议列表
    """
    config = rules_config if rules_config else DEFAULT_CONFIG
    suggestions: List[FixSuggestion] = []

    if df.empty:
        return suggestions

    df_lookup = {}
    for _, row in df.iterrows():
        rid = row.get("row_id")
        if rid is not None:
            df_lookup[int(rid)] = row
        eid = row.get("emp_id")
        if eid and not _is_empty(eid):
            df_lookup[f"eid_{eid}"] = row

    valid_ids = set(df[~df["emp_id"].apply(_is_empty)]["emp_id"].tolist())
    valid_depts = config.valid_departments
    valid_etypes = config.valid_employment_types
    date_formats = config.date_formats

    dup_emp_groups = defaultdict(list)
    for issue in issues:
        if issue.error_code == ErrorCode.DUPLICATE_EMP_ID and issue.emp_id and issue.row_index:
            dup_emp_groups[issue.emp_id].append(issue.row_index)

    for issue in issues:
        if issue.error_code == ErrorCode.DUPLICATE_EMP_ID:
            emp_id = issue.emp_id
            row_idx = issue.row_index
            rows = dup_emp_groups.get(emp_id, [])
            first_row = min(rows) if rows else None
            is_first = (row_idx == first_row)
            if is_first:
                desc = f"工号 {emp_id} 重复，建议保留此行（请确认其他重复行是否删除）"
                suggestions.append(FixSuggestion(
                    issue=issue,
                    emp_id=emp_id,
                    field_name="emp_id",
                    row_index=row_idx,
                    suggested_value=emp_id,
                    fix_type="keep_original",
                    confidence="high",
                    needs_confirmation=False,
                    description=desc,
                    allow_delete=False,
                ))
            else:
                desc = f"工号 {emp_id} 重复，建议删除此行（或填写'人工修正值'改为新工号）"
                suggestions.append(FixSuggestion(
                    issue=issue,
                    emp_id=emp_id,
                    field_name="emp_id",
                    row_index=row_idx,
                    suggested_value=None,
                    fix_type="delete_duplicate",
                    confidence="medium",
                    needs_confirmation=True,
                    description=desc,
                    allow_delete=True,
                ))

        elif issue.error_code == ErrorCode.EMPTY_FIELD:
            field = issue.field_name
            suggested = None
            confidence = "low"
            desc = f"字段 {config.get_field_cn(field)} 需要补充信息"

            if field == "status":
                if issue.row_index and issue.row_index in df_lookup:
                    row = df_lookup[issue.row_index]
                    resign_date = row.get("resign_date")
                    suggested = "离职" if not _is_empty(resign_date) else "在职"
                    confidence = "medium" if suggested else "low"
                    desc = f"根据{'离职日期' if not _is_empty(resign_date) else '缺省'}建议状态为: {suggested}"

            elif field == "supervisor_id":
                if issue.emp_id:
                    key = f"eid_{issue.emp_id}"
                    if key in df_lookup:
                        row = df_lookup[key]
                        dept = row.get("department")
                        if not _is_empty(dept):
                            dept_emps = df[df["department"] == dept]
                            positions = ["经理", "主管", "总监", "负责人", "主任"]
                            found = False
                            for pos in positions:
                                managers = dept_emps[
                                    dept_emps["position"].fillna("").str.contains(pos, na=False)
                                ]
                                if not managers.empty:
                                    mid = managers.iloc[0]["emp_id"]
                                    mname = managers.iloc[0].get("name", mid)
                                    if mid != issue.emp_id:
                                        suggested = mid
                                        confidence = "medium"
                                        desc = f"建议补充上级为同部门{pos}: {mname}({mid})"
                                        found = True
                                        break

            elif field == "department":
                if issue.emp_id:
                    key = f"eid_{issue.emp_id}"
                    if key in df_lookup:
                        row = df_lookup[key]
                        pos = str(row.get("position", ""))
                        dept_hints = {
                            "工程师": "技术部", "开发": "技术部", "研发": "研发中心",
                            "产品": "产品部", "设计": "设计部", "测试": "测试部",
                            "销售": "销售部", "市场": "市场部", "运营": "运营部",
                            "人事": "人力资源部", "HR": "人力资源部", "财务": "财务部",
                            "行政": "行政部", "客服": "客户服务部", "采购": "采购部",
                            "生产": "生产部", "质检": "质量管理部", "法务": "法务部",
                        }
                        for kw, dept in dept_hints.items():
                            if kw in pos:
                                suggested = dept
                                confidence = "medium"
                                desc = f"根据岗位'{pos}'建议部门: {dept}"
                                break

            elif field == "employment_type":
                suggested = "正式"
                confidence = "low"
                desc = "缺省建议用工类型为: 正式"

            elif field == "position":
                confidence = "low"
                desc = "请人工补充岗位信息"

            elif field == "name":
                confidence = "low"
                desc = "请人工补充员工姓名"

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
            suggested = _normalize_date_value(str(issue.actual_value), date_formats) if issue.actual_value else None
            confidence = "high" if suggested else "low"
            desc = f"建议将日期格式化为 YYYY-MM-DD: {suggested if suggested else '需人工确认正确日期'}"
            suggestions.append(FixSuggestion(
                issue=issue,
                emp_id=issue.emp_id,
                field_name=field,
                row_index=issue.row_index,
                suggested_value=suggested,
                fix_type="fix_date_format",
                confidence=confidence,
                needs_confirmation=confidence != "high",
                description=desc,
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
                description=f"日期 {issue.actual_value} 在未来，请确认是否为预入职/预离职（是则人工修正值填'保留'）",
            ))

        elif issue.error_code == ErrorCode.DEPARTMENT_NOT_FOUND:
            actual = str(issue.actual_value) if issue.actual_value else ""
            suggested = _fuzzy_match(actual, valid_depts)
            confidence = "high" if suggested and suggested == actual.strip() else ("medium" if suggested else "low")
            desc_parts = []
            if suggested:
                desc_parts.append(f"模糊匹配建议: {suggested}")
            else:
                desc_parts.append("未匹配到有效部门")
            desc_parts.append(f"可选: {', '.join(valid_depts[:10])}{'...' if len(valid_depts) > 10 else ''}")
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
            suggested = _fuzzy_match(actual, valid_etypes)
            confidence = "high" if suggested and suggested == actual.strip() else ("medium" if suggested else "low")
            desc = f"有效类型: {', '.join(valid_etypes)}"
            if suggested:
                desc = f"模糊匹配建议: {suggested} | {desc}"
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
                description=f"上级工号 {issue.actual_value} 不存在，请人工确认正确的工号",
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
                description=f"存在循环引用: {issue.actual_value}，请在人工修正值中填写正确的上级工号",
            ))

        elif issue.error_code == ErrorCode.EMPLOYMENT_STATUS_CONFLICT:
            if issue.row_index and issue.row_index in df_lookup:
                row = df_lookup[issue.row_index]
                status = row.get("status")
                resign_date = row.get("resign_date")
                hire_date = row.get("hire_date")
                if _is_empty(status) and not _is_empty(resign_date):
                    suggestions.append(FixSuggestion(
                        issue=issue,
                        emp_id=issue.emp_id,
                        field_name="status",
                        row_index=issue.row_index,
                        suggested_value="离职",
                        fix_type="fix_status",
                        confidence="medium",
                        needs_confirmation=True,
                        description="存在离职日期但状态为空，建议状态改为: 离职",
                    ))
                    continue
                if status == "在职" and not _is_empty(resign_date):
                    suggestions.append(FixSuggestion(
                        issue=issue,
                        emp_id=issue.emp_id,
                        field_name="status",
                        row_index=issue.row_index,
                        suggested_value="离职",
                        fix_type="fix_status",
                        confidence="medium",
                        needs_confirmation=True,
                        description=f"状态为在职但有离职日期 ({resign_date})，建议改为: 离职",
                    ))
                    continue
                if status == "离职" and _is_empty(resign_date):
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
                        description=f"状态为离职但缺少离职日期，建议补充: {today}（请人工确认）",
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
                    description=f"状态冲突: {issue.message}，请人工修正（状态/入职日期/离职日期任选其一修改）",
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
                description=f"姓名 '{issue.actual_value}' 格式异常，请人工确认并在修正值中填写正确姓名",
            ))

    return suggestions


def suggestions_to_dataframe(suggestions: List[FixSuggestion]) -> pd.DataFrame:
    """将修复建议转换为 DataFrame（含是否删除列、人工修正值列等）"""
    records = []
    conf_icons = {"high": "高", "medium": "中", "low": "低"}
    fix_type_names = {
        "keep_original": "保留原工号",
        "delete_duplicate": "删除重复行",
        "fill_empty": "补空字段",
        "fix_date_format": "修正日期格式",
        "verify_future_date": "确认未来日期",
        "fix_department": "修正部门",
        "fix_employment_type": "修正用工类型",
        "fix_supervisor": "修正上级工号",
        "break_cycle": "打破上级循环",
        "fix_status": "修正在职状态",
        "add_resign_date": "补充离职日期",
        "fix_status_conflict": "解决状态冲突",
        "verify_name": "确认姓名格式",
    }
    for idx, s in enumerate(suggestions, 1):
        field_cn = FIELD_CN_MAPPING.get(s.field_name, s.field_name) if s.field_name else ""
        records.append({
            "序号": idx,
            "工号": s.emp_id if s.emp_id else "",
            "行号": s.row_index if s.row_index else "",
            "问题字段": field_cn,
            "错误等级": s.issue.error_level.value,
            "错误代码": s.issue.error_code.value,
            "问题描述": s.issue.message,
            "修复方式": fix_type_names.get(s.fix_type, s.fix_type),
            "建议修复值": s.suggested_value if s.suggested_value is not None else "",
            "置信度": conf_icons.get(s.confidence, s.confidence),
            "需人工确认": "是" if s.needs_confirmation else "否",
            "可删除此行": "是" if s.allow_delete else "否",
            "详细说明": s.description,
            "是否采纳": "",
            "是否删除此行": "",
            "人工修正值": "",
            "备注": "",
        })
    columns = ["序号", "工号", "行号", "问题字段", "错误等级", "错误代码", "问题描述",
               "修复方式", "建议修复值", "置信度", "需人工确认", "可删除此行",
               "详细说明", "是否采纳", "是否删除此行", "人工修正值", "备注"]
    return pd.DataFrame(records) if records else pd.DataFrame(columns=columns)


def _build_fix_records_df(fix_records: List[Dict]) -> pd.DataFrame:
    """构造修复记录 DataFrame"""
    columns = ["序号", "工号", "行号", "字段", "原值", "新值", "修复方式", "确认方式", "处理时间"]
    if not fix_records:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(fix_records)


def apply_fixes(
    df: pd.DataFrame,
    suggestions: List[FixSuggestion],
    confirmation_df: Optional[pd.DataFrame] = None,
    rules_config: Optional[RulesConfig] = None,
    do_recheck: bool = True
) -> FixApplicationResult:
    """
    应用修复建议，支持：
    - 按确认表的"是否删除此行"删除重复工号行
    - 按"人工修正值"修改工号、字段值
    - 自动应用高置信度无需确认的建议
    - 应用后执行复检并返回问题列表

    Args:
        df: 原始花名册 DataFrame
        suggestions: 修复建议列表
        confirmation_df: 人工确认表（HR 填写后返回的）
        rules_config: 规则配置
        do_recheck: 是否执行复检

    Returns:
        FixApplicationResult 结果对象
    """
    config = rules_config if rules_config else DEFAULT_CONFIG
    fixed_df = df.copy()

    stats = {"applied": 0, "skipped": 0, "needs_manual": 0}
    deleted_rows: List[int] = []
    modified_fields: List[Dict] = []
    fix_records: List[Dict] = []
    seq_no = 0

    confirm_map = {}
    if confirmation_df is not None and not confirmation_df.empty:
        required_cols = ["序号", "是否采纳", "是否删除此行", "人工修正值"]
        for col in required_cols:
            if col not in confirmation_df.columns:
                raise ValueError(f"确认表缺少必要列: {col}，请确保未修改表头")
        for _, row in confirmation_df.iterrows():
            seq = row.get("序号")
            if seq is not None and not _is_empty(seq):
                seq_int = int(seq)
                adopted = str(row.get("是否采纳", "")).strip() in ["是", "Y", "y", "1", "true", "TRUE", "yes", "YES"]
                do_delete = str(row.get("是否删除此行", "")).strip() in ["是", "Y", "y", "1", "true", "TRUE", "yes", "YES"]
                manual_raw = row.get("人工修正值")
                manual = None if _is_empty(manual_raw) else manual_raw
                confirm_map[seq_int] = {
                    "adopted": adopted,
                    "do_delete": do_delete,
                    "manual_value": str(manual).strip() if manual and not isinstance(manual, str) else manual,
                }

    rows_to_delete = set()
    fields_to_update: Dict[Tuple, Dict] = {}

    for idx, s in enumerate(suggestions, 1):
        seq_no += 1
        conf = confirm_map.get(idx, {})
        do_delete = conf.get("do_delete", False)
        adopted = conf.get("adopted", False)
        manual_val = conf.get("manual_value")

        if s.allow_delete and do_delete and s.row_index:
            rows_to_delete.add(int(s.row_index))
            old_val = s.issue.actual_value if s.issue else ""
            fix_records.append({
                "序号": seq_no, "工号": s.emp_id or "", "行号": s.row_index or "",
                "字段": "整行", "原值": old_val or "", "新值": "[已删除]",
                "修复方式": "删除重复行", "确认方式": "人工确认删除",
                "处理时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            stats["applied"] += 1
            deleted_rows.append(int(s.row_index))
            continue

        should_apply = False
        value_to_use = None

        if not s.needs_confirmation:
            should_apply = True
            value_to_use = s.suggested_value
            if adopted and manual_val is not None:
                value_to_use = manual_val
        else:
            if adopted:
                should_apply = True
                value_to_use = manual_val if manual_val is not None else s.suggested_value
            else:
                stats["needs_manual"] += 1
                stats["skipped"] += 1
                continue

        if not should_apply:
            stats["skipped"] += 1
            continue

        if value_to_use is None and s.fix_type not in ["delete_duplicate", "break_cycle", "verify_future_date"]:
            stats["skipped"] += 1
            continue

        if s.fix_type == "verify_future_date":
            if manual_val == "保留" or (adopted and s.suggested_value is None and manual_val is None):
                stats["applied"] += 1
                fix_records.append({
                    "序号": seq_no, "工号": s.emp_id or "", "行号": s.row_index or "",
                    "字段": config.get_field_cn(s.field_name) if s.field_name else "",
                    "原值": s.issue.actual_value or "", "新值": "[保留不变]",
                    "修复方式": "确认保留未来日期", "确认方式": "人工确认",
                    "处理时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                continue
            if manual_val is None:
                stats["skipped"] += 1
                continue

        if s.row_index and s.field_name and s.field_name in fixed_df.columns:
            target_mask = fixed_df["row_id"] == int(s.row_index) if "row_id" in fixed_df.columns else None
            if target_mask is None and s.emp_id and "emp_id" in fixed_df.columns:
                target_mask = fixed_df["emp_id"] == s.emp_id
            if target_mask is not None and target_mask.any():
                old_val = fixed_df.loc[target_mask, s.field_name].iloc[0]
                if value_to_use is not None and str(value_to_use) != str(old_val):
                    fixed_df.loc[target_mask, s.field_name] = value_to_use
                    modified_fields.append({
                        "row_index": s.row_index, "emp_id": s.emp_id,
                        "field": s.field_name, "old": old_val, "new": value_to_use
                    })
                    fix_records.append({
                        "序号": seq_no, "工号": s.emp_id or "", "行号": s.row_index or "",
                        "字段": config.get_field_cn(s.field_name),
                        "原值": old_val if not _is_empty(old_val) else "[空]",
                        "新值": value_to_use,
                        "修复方式": s.fix_type,
                        "确认方式": "无需确认" if not s.needs_confirmation else "人工采纳建议" + ("(人工修正值)" if manual_val is not None else ""),
                        "处理时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    stats["applied"] += 1
                else:
                    stats["skipped"] += 1
            else:
                stats["skipped"] += 1
        else:
            stats["skipped"] += 1

    if rows_to_delete and "row_id" in fixed_df.columns:
        before = len(fixed_df)
        fixed_df = fixed_df[~fixed_df["row_id"].isin(rows_to_delete)].reset_index(drop=True)
        after = len(fixed_df)
        stats["applied"] += (before - after)

    fix_records_df = _build_fix_records_df(fix_records)

    recheck_issues = []
    if do_recheck:
        from .validator import validate_roster
        recheck_issues = validate_roster(fixed_df, rules_config=config)

    return FixApplicationResult(
        fixed_df=fixed_df,
        applied_count=stats["applied"],
        skipped_count=stats["skipped"],
        needs_manual_count=stats["needs_manual"],
        deleted_rows=deleted_rows,
        modified_fields=modified_fields,
        fix_records_df=fix_records_df,
        recheck_issues=recheck_issues,
    )
