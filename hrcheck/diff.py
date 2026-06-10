"""差异对比模块：对比两个花名册的差异，支持 RulesConfig"""

import pandas as pd
from typing import List, Dict, Tuple
from collections import defaultdict
from .config import DiffRecord, DepartmentSummary, FIELD_CN_MAPPING
from .rules_config import RulesConfig, DEFAULT_CONFIG


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


def _is_resigned(status_value: str, config: RulesConfig) -> bool:
    """根据配置判断状态是否属于离职类"""
    if _is_empty(status_value):
        return False
    status_rules = config.status_rules or {}
    resigned = status_rules.get("resigned_statuses", ["离职", "退休"])
    return str(status_value).strip() in resigned


def _is_active(status_value: str, config: RulesConfig) -> bool:
    """根据配置判断状态是否属于在职类"""
    if _is_empty(status_value):
        return False
    status_rules = config.status_rules or {}
    active = status_rules.get("active_statuses", ["在职"])
    return str(status_value).strip() in active


def compare_rosters(
    last_month_df: pd.DataFrame,
    current_df: pd.DataFrame,
    rules_config: Optional[RulesConfig] = None
) -> List[DiffRecord]:
    """
    对比两个月的花名册，生成差异记录

    关键改进：识别员工仍在本月花名册中、但状态从在职变为离职的情况，
    按离职记录展示。

    Args:
        last_month_df: 上月花名册
        current_df: 本月花名册
        rules_config: 规则配置

    Returns:
        差异记录列表
    """
    config = rules_config if rules_config else DEFAULT_CONFIG
    diffs: List[DiffRecord] = []

    if len(last_month_df) == 0 or "emp_id" not in last_month_df.columns:
        last_ids = set()
    else:
        last_mask = ~last_month_df["emp_id"].apply(_is_empty)
        last_ids = set(last_month_df.loc[last_mask, "emp_id"].tolist())

    if len(current_df) == 0 or "emp_id" not in current_df.columns:
        current_ids = set()
    else:
        curr_mask = ~current_df["emp_id"].apply(_is_empty)
        current_ids = set(current_df.loc[curr_mask, "emp_id"].tolist())

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
        name = _normalize_value(row.get("name")) or ""
        dept = _normalize_value(row.get("department")) or ""
        pos = _normalize_value(row.get("position")) or ""
        status = _normalize_value(row.get("status")) or ""
        desc_parts = []
        if name:
            desc_parts.append(f"姓名:{name}")
        if dept:
            desc_parts.append(f"部门:{dept}")
        if pos:
            desc_parts.append(f"岗位:{pos}")
        if status:
            desc_parts.append(f"状态:{status}")
        diffs.append(DiffRecord(
            emp_id=emp_id,
            change_type="新增",
            description=f"新增员工 ({' | '.join(desc_parts) if desc_parts else ''})",
            new_value=f"{name}|{dept}|{pos}|{status}",
        ))

    for emp_id in resigned_ids:
        row = last_lookup[emp_id]
        name = _normalize_value(row.get("name")) or ""
        dept = _normalize_value(row.get("department")) or ""
        pos = _normalize_value(row.get("position")) or ""
        status = _normalize_value(row.get("status")) or ""
        desc_parts = []
        if name:
            desc_parts.append(f"姓名:{name}")
        if dept:
            desc_parts.append(f"部门:{dept}")
        if pos:
            desc_parts.append(f"岗位:{pos}")
        if status:
            desc_parts.append(f"原状态:{status}")
        diffs.append(DiffRecord(
            emp_id=emp_id,
            change_type="离职",
            description=f"离职员工（已从花名册移除） ({' | '.join(desc_parts) if desc_parts else ''})",
            old_value=f"{name}|{dept}|{pos}|{status}",
        ))

    for emp_id in common_ids:
        last_row = last_lookup[emp_id]
        curr_row = current_lookup[emp_id]

        last_status = _normalize_value(last_row.get("status"))
        curr_status = _normalize_value(curr_row.get("status"))

        last_was_active = _is_active(last_status, config) if last_status else True
        curr_is_resigned = _is_resigned(curr_status, config) if curr_status else False

        if last_was_active and curr_is_resigned:
            name = _normalize_value(curr_row.get("name")) or ""
            dept = _normalize_value(curr_row.get("department")) or ""
            pos = _normalize_value(curr_row.get("position")) or ""
            resign_date = _normalize_value(curr_row.get("resign_date")) or ""
            desc_parts = [f"姓名:{name}" if name else "",
                          f"部门:{dept}" if dept else "",
                          f"岗位:{pos}" if pos else ""]
            if resign_date:
                desc_parts.append(f"离职日期:{resign_date}")
            desc_parts = [p for p in desc_parts if p]
            diffs.append(DiffRecord(
                emp_id=emp_id,
                change_type="离职",
                field_name="status",
                old_value=last_status,
                new_value=curr_status,
                description=f"本月状态变更为离职 ({' | '.join(desc_parts)})",
            ))

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

        last_status_val = _normalize_value(last_row.get("status"))
        curr_status_val = _normalize_value(curr_row.get("status"))
        if (last_status_val != curr_status_val
                and not (last_was_active and curr_is_resigned)):
            diffs.append(DiffRecord(
                emp_id=emp_id,
                change_type="状态变更",
                field_name="status",
                old_value=last_status_val,
                new_value=curr_status_val,
                description=f"在职状态变更: {last_status_val} → {curr_status_val}",
            ))

        other_changes = []
        for field in ["hire_date", "resign_date", "phone", "email", "id_card", "gender", "birthday", "education"]:
            last_val = _normalize_value(last_row.get(field))
            curr_val = _normalize_value(curr_row.get(field))
            if last_val != curr_val:
                field_cn = config.get_field_cn(field)
                if field == "resign_date" and curr_is_resigned:
                    continue
                other_changes.append(f"{field_cn}: {last_val} → {curr_val}")

        if other_changes:
            diffs.append(DiffRecord(
                emp_id=emp_id,
                change_type="其他修改",
                field_name="multiple",
                description="; ".join(other_changes),
            ))

    return diffs


def diffs_to_dataframe(
    diffs: List[DiffRecord],
    config: RulesConfig = DEFAULT_CONFIG
) -> pd.DataFrame:
    """将差异记录转换为 DataFrame"""
    records = []
    for d in diffs:
        field_cn = config.get_field_cn(d.field_name) if d.field_name else ""
        records.append({
            "工号": d.emp_id,
            "变更类型": d.change_type,
            "变更字段": field_cn,
            "原值": d.old_value if d.old_value is not None else "",
            "新值": d.new_value if d.new_value is not None else "",
            "变更说明": d.description,
        })
    columns = ["工号", "变更类型", "变更字段", "原值", "新值", "变更说明"]
    return pd.DataFrame(records) if records else pd.DataFrame(columns=columns)


def get_department_summary(
    last_month_df: pd.DataFrame,
    current_df: pd.DataFrame,
    diffs: List[DiffRecord],
    rules_config: Optional[RulesConfig] = None
) -> List[DepartmentSummary]:
    """
    按部门汇总人数变化

    关键改进：本月状态变为离职的员工，不再计入部门在职人数。
    统计逻辑：
    - 上月人数 = 上月花名册中 status != 离职类 的人数
    - 本月人数 = 本月花名册中 status != 离职类 的人数
    - 新增 / 离职 / 调入 / 调出 基于 diffs 统计

    Args:
        last_month_df: 上月花名册
        current_df: 本月花名册
        diffs: 差异记录列表
        rules_config: 规则配置

    Returns:
        部门汇总列表
    """
    config = rules_config if rules_config else DEFAULT_CONFIG
    summaries: Dict[str, Dict] = defaultdict(lambda: {
        "department": "",
        "last_month_count": 0,
        "current_count": 0,
        "new_count": 0,
        "resign_count": 0,
        "transfer_in": 0,
        "transfer_out": 0,
    })

    def _count_by_dept(df: pd.DataFrame) -> pd.Series:
        """按部门统计（排除离职状态）"""
        if df.empty:
            return pd.Series(dtype=int)
        active_mask = df["status"].apply(lambda s: not _is_resigned(s, config))
        active_df = df[active_mask]
        dept_series = active_df["department"].apply(
            lambda d: None if _is_empty(d) else d
        )
        return dept_series.value_counts()

    last_dept_counts = _count_by_dept(last_month_df)
    curr_dept_counts = _count_by_dept(current_df)

    all_depts = set(last_dept_counts.index) | set(curr_dept_counts.index)
    all_depts = {d for d in all_depts if d is not None}

    for dept in all_depts:
        summaries[dept]["department"] = dept
        summaries[dept]["last_month_count"] = int(last_dept_counts.get(dept, 0))
        summaries[dept]["current_count"] = int(curr_dept_counts.get(dept, 0))

    seen_transfers = set()
    for d in diffs:
        if d.change_type == "新增":
            if d.new_value:
                parts = str(d.new_value).split("|")
                if len(parts) >= 2 and not _is_empty(parts[1]):
                    dept = parts[1]
                    if dept in summaries:
                        summaries[dept]["new_count"] += 1
        elif d.change_type == "离职":
            key = f"resign_{d.emp_id}"
            if key in seen_transfers:
                continue
            seen_transfers.add(key)
            dept_found = None
            if d.old_value:
                parts = str(d.old_value).split("|")
                if len(parts) >= 2 and not _is_empty(parts[1]):
                    dept_found = parts[1]
            if dept_found is None and d.field_name == "status":
                for _, row in current_df.iterrows():
                    if row.get("emp_id") == d.emp_id:
                        dept_found = _normalize_value(row.get("department"))
                        break
            if dept_found and dept_found in summaries:
                summaries[dept_found]["resign_count"] += 1
        elif d.change_type == "部门变更":
            key = f"dept_{d.emp_id}"
            if key in seen_transfers:
                continue
            seen_transfers.add(key)
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
            "上月在职人数": s.last_month_count,
            "本月在职人数": s.current_count,
            "新增": s.new_count,
            "离职": s.resign_count,
            "调入": s.transfer_in,
            "调出": s.transfer_out,
            "净变化": net_str,
        })
    columns = ["部门", "上月在职人数", "本月在职人数", "新增", "离职", "调入", "调出", "净变化"]
    return pd.DataFrame(records) if records else pd.DataFrame(columns=columns)
