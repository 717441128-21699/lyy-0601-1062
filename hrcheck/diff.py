"""差异对比模块：对比两个花名册的差异"""

import pandas as pd
from typing import List, Dict, Tuple
from collections import defaultdict
from .config import DiffRecord, DepartmentSummary, FIELD_CN_MAPPING


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


def _normalize_value(value):
    """标准化值用于比较"""
    if _is_empty(value):
        return None
    if isinstance(value, str):
        return value.strip()
    return value


def compare_rosters(
    last_month_df: pd.DataFrame,
    current_df: pd.DataFrame
) -> List[DiffRecord]:
    """
    对比两个月的花名册，生成差异记录

    Args:
        last_month_df: 上月花名册
        current_df: 本月花名册

    Returns:
        差异记录列表
    """
    diffs: List[DiffRecord] = []

    last_ids = set(last_month_df[~last_month_df["emp_id"].apply(_is_empty)]["emp_id"].tolist())
    current_ids = set(current_df[~current_df["emp_id"].apply(_is_empty)]["emp_id"].tolist())

    new_ids = current_ids - last_ids
    resigned_ids = last_ids - current_ids
    common_ids = last_ids & current_ids

    last_lookup = {}
    for _, row in last_month_df.iterrows():
        eid = row.get("emp_id")
        if not _is_empty(eid):
            last_lookup[eid] = row

    current_lookup = {}
    for _, row in current_df.iterrows():
        eid = row.get("emp_id")
        if not _is_empty(eid):
            current_lookup[eid] = row

    for emp_id in new_ids:
        row = current_lookup[emp_id]
        name = row.get("name", "")
        dept = row.get("department", "")
        pos = row.get("position", "")
        desc_parts = []
        if name:
            desc_parts.append(f"姓名:{name}")
        if dept:
            desc_parts.append(f"部门:{dept}")
        if pos:
            desc_parts.append(f"岗位:{pos}")
        diffs.append(DiffRecord(
            emp_id=emp_id,
            change_type="新增",
            description=f"新增员工 ({' | '.join(desc_parts) if desc_parts else ''})",
            new_value=f"{name}|{dept}|{pos}",
        ))

    for emp_id in resigned_ids:
        row = last_lookup[emp_id]
        name = row.get("name", "")
        dept = row.get("department", "")
        pos = row.get("position", "")
        desc_parts = []
        if name:
            desc_parts.append(f"姓名:{name}")
        if dept:
            desc_parts.append(f"部门:{dept}")
        if pos:
            desc_parts.append(f"岗位:{pos}")
        diffs.append(DiffRecord(
            emp_id=emp_id,
            change_type="离职",
            description=f"离职员工 ({' | '.join(desc_parts) if desc_parts else ''})",
            old_value=f"{name}|{dept}|{pos}",
        ))

    for emp_id in common_ids:
        last_row = last_lookup[emp_id]
        curr_row = current_lookup[emp_id]

        name_change_detected = False
        dept_change_detected = False
        pos_change_detected = False
        sup_change_detected = False
        emp_type_change_detected = False

        last_name = _normalize_value(last_row.get("name"))
        curr_name = _normalize_value(curr_row.get("name"))
        if last_name != curr_name:
            name_change_detected = True
            diffs.append(DiffRecord(
                emp_id=emp_id,
                change_type="改名",
                field_name="name",
                old_value=last_name,
                new_value=curr_name,
                description=f"姓名变更: {last_name} → {curr_name}",
            ))

        last_dept = _normalize_value(last_row.get("department"))
        curr_dept = _normalize_value(curr_row.get("department"))
        if last_dept != curr_dept:
            dept_change_detected = True
            diffs.append(DiffRecord(
                emp_id=emp_id,
                change_type="部门变更",
                field_name="department",
                old_value=last_dept,
                new_value=curr_dept,
                description=f"部门变更: {last_dept} → {curr_dept}",
            ))

        last_pos = _normalize_value(last_row.get("position"))
        curr_pos = _normalize_value(curr_row.get("position"))
        if last_pos != curr_pos:
            pos_change_detected = True
            diffs.append(DiffRecord(
                emp_id=emp_id,
                change_type="调岗",
                field_name="position",
                old_value=last_pos,
                new_value=curr_pos,
                description=f"岗位变更: {last_pos} → {curr_pos}",
            ))

        if dept_change_detected and pos_change_detected:
            pass
        elif dept_change_detected or pos_change_detected:
            pass

        last_sup = _normalize_value(last_row.get("supervisor_id"))
        curr_sup = _normalize_value(curr_row.get("supervisor_id"))
        if last_sup != curr_sup:
            sup_change_detected = True
            diffs.append(DiffRecord(
                emp_id=emp_id,
                change_type="上级变更",
                field_name="supervisor_id",
                old_value=last_sup,
                new_value=curr_sup,
                description=f"直属上级变更: {last_sup} → {curr_sup}",
            ))

        last_etype = _normalize_value(last_row.get("employment_type"))
        curr_etype = _normalize_value(curr_row.get("employment_type"))
        if last_etype != curr_etype:
            emp_type_change_detected = True
            diffs.append(DiffRecord(
                emp_id=emp_id,
                change_type="用工类型变更",
                field_name="employment_type",
                old_value=last_etype,
                new_value=curr_etype,
                description=f"用工类型变更: {last_etype} → {curr_etype}",
            ))

        other_changes = []
        for field in ["hire_date", "status", "phone", "email", "id_card", "gender", "birthday", "education"]:
            last_val = _normalize_value(last_row.get(field))
            curr_val = _normalize_value(curr_row.get(field))
            if last_val != curr_val:
                field_cn = FIELD_CN_MAPPING.get(field, field)
                other_changes.append(f"{field_cn}: {last_val} → {curr_val}")

        if other_changes:
            diffs.append(DiffRecord(
                emp_id=emp_id,
                change_type="其他修改",
                field_name="multiple",
                description="; ".join(other_changes),
            ))

    return diffs


def diffs_to_dataframe(diffs: List[DiffRecord]) -> pd.DataFrame:
    """将差异记录转换为 DataFrame"""
    records = []
    for d in diffs:
        field_cn = FIELD_CN_MAPPING.get(d.field_name, d.field_name) if d.field_name else ""
        records.append({
            "工号": d.emp_id,
            "变更类型": d.change_type,
            "变更字段": field_cn,
            "原值": d.old_value if d.old_value is not None else "",
            "新值": d.new_value if d.new_value is not None else "",
            "变更说明": d.description,
        })
    return pd.DataFrame(records) if records else pd.DataFrame(columns=[
        "工号", "变更类型", "变更字段", "原值", "新值", "变更说明"
    ])


def get_department_summary(
    last_month_df: pd.DataFrame,
    current_df: pd.DataFrame,
    diffs: List[DiffRecord]
) -> List[DepartmentSummary]:
    """
    按部门汇总人数变化

    Args:
        last_month_df: 上月花名册
        current_df: 本月花名册
        diffs: 差异记录列表

    Returns:
        部门汇总列表
    """
    summaries: Dict[str, Dict] = defaultdict(lambda: {
        "department": "",
        "last_month_count": 0,
        "current_count": 0,
        "new_count": 0,
        "resign_count": 0,
        "transfer_in": 0,
        "transfer_out": 0,
    })

    last_valid = last_month_df[~last_month_df["emp_id"].apply(_is_empty)]
    curr_valid = current_df[~current_df["emp_id"].apply(_is_empty)]

    last_dept_counts = last_valid["department"].value_counts()
    curr_dept_counts = curr_valid["department"].value_counts()

    all_depts = set(last_dept_counts.index) | set(curr_dept_counts.index)
    all_depts = {d for d in all_depts if not _is_empty(d)}

    for dept in all_depts:
        summaries[dept]["department"] = dept
        summaries[dept]["last_month_count"] = int(last_dept_counts.get(dept, 0))
        summaries[dept]["current_count"] = int(curr_dept_counts.get(dept, 0))

    for d in diffs:
        if d.change_type == "新增":
            if d.new_value:
                parts = str(d.new_value).split("|")
                if len(parts) >= 2 and not _is_empty(parts[1]):
                    dept = parts[1]
                    if dept in summaries:
                        summaries[dept]["new_count"] += 1
        elif d.change_type == "离职":
            if d.old_value:
                parts = str(d.old_value).split("|")
                if len(parts) >= 2 and not _is_empty(parts[1]):
                    dept = parts[1]
                    if dept in summaries:
                        summaries[dept]["resign_count"] += 1
        elif d.change_type == "部门变更":
            old_dept = d.old_value if not _is_empty(d.old_value) else None
            new_dept = d.new_value if not _is_empty(d.new_value) else None
            if old_dept and old_dept in summaries:
                summaries[old_dept]["transfer_out"] += 1
            if new_dept and new_dept in summaries:
                summaries[new_dept]["transfer_in"] += 1

    result = []
    for dept in sorted(all_depts):
        s = summaries[dept]
        s["net_change"] = s["current_count"] - s["last_month_count"]
        result.append(DepartmentSummary(**s))

    return result


def summary_to_dataframe(summaries: List[DepartmentSummary]) -> pd.DataFrame:
    """将部门汇总转换为 DataFrame"""
    records = []
    for s in summaries:
        net_change = s.net_change
        net_str = f"+{net_change}" if net_change > 0 else str(net_change)
        records.append({
            "部门": s.department,
            "上月人数": s.last_month_count,
            "本月人数": s.current_count,
            "新增": s.new_count,
            "离职": s.resign_count,
            "调入": s.transfer_in,
            "调出": s.transfer_out,
            "净变化": net_str,
        })
    return pd.DataFrame(records) if records else pd.DataFrame(columns=[
        "部门", "上月人数", "本月人数", "新增", "离职", "调入", "调出", "净变化"
    ])
