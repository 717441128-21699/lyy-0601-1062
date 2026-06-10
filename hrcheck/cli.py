"""命令行工具主入口 - 整合所有改进"""

import os
import sys
import io
import json

if sys.platform.startswith("win"):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass

from typing import Optional, List, Dict, Any
from collections import Counter
from datetime import datetime

import click
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from .config import (
    ErrorLevel, ValidationIssue, ErrorCode,
    ALL_FIELDS, REQUIRED_FIELDS, FIELD_CN_MAPPING,
)
from .rules_config import (
    RulesConfig, DEFAULT_CONFIG,
    load_rules_config, generate_template_config,
)
from .io_utils import (
    import_roster, export_to_excel, export_to_csv, get_file_info,
)
from .validator import (
    validate_roster, issues_to_dataframe,
    get_clean_roster, sort_issues,
)
from .diff import (
    compare_rosters, diffs_to_dataframe,
    get_department_summary, summary_to_dataframe,
)
from .fixer import (
    generate_fix_suggestions, suggestions_to_dataframe,
    apply_fixes, FixApplicationResult,
)

console = Console(force_terminal=False, highlight=False, emoji=False, markup=True)
SYM_OK = "[OK]"
SYM_WARN = "[WARN]"
SYM_ERR = "[ERR]"
SYM_CHECK = "[OK]"
SYM_CROSS = "[X]"


def _print_banner():
    banner = Panel(
        Text(
            "人力资源花名册校验工具 (HR Roster Check) v1.1\n"
            "月报 · 审计 · 系统迁移前快速检查员工基础数据",
            style="bold cyan",
            justify="center"
        ),
        border_style="blue",
    )
    console.print(banner)


def _print_issues_summary(issues: List[ValidationIssue]):
    """打印问题统计"""
    level_counter = Counter()
    for issue in issues:
        level_counter[issue.error_level.value] += 1

    table = Table(title="校验问题统计", show_header=True, header_style="bold magenta")
    table.add_column("错误等级", style="bold")
    table.add_column("数量", justify="right")
    table.add_column("占比", justify="right")

    total = len(issues) if issues else 1
    level_order = ["CRITICAL", "ERROR", "WARNING", "INFO"]
    level_styles = {
        "CRITICAL": "bold red",
        "ERROR": "red",
        "WARNING": "yellow",
        "INFO": "blue",
    }
    level_names = {
        "CRITICAL": "严重",
        "ERROR": "错误",
        "WARNING": "警告",
        "INFO": "提示",
    }
    for level in level_order:
        count = level_counter.get(level, 0)
        pct = f"{count / total * 100:.1f}%"
        table.add_row(
            Text(f"{level_names.get(level, level)} ({level})", style=level_styles.get(level, "white")),
            str(count),
            pct,
        )
    table.add_row("合计", str(len(issues)), "100%", style="bold")
    console.print(table)


def _print_issues_table(issues: List[ValidationIssue], max_rows: int = 50,
                        config: RulesConfig = DEFAULT_CONFIG):
    """打印问题明细表格"""
    if not issues:
        console.print("[green][OK] 未发现任何校验问题！[/green]")
        return

    sorted_issues = sort_issues(issues)
    display_issues = sorted_issues[:max_rows]

    table = Table(title=f"问题明细 (共 {len(issues)} 条，显示前 {len(display_issues)} 条)",
                  show_header=True, header_style="bold magenta")
    table.add_column("等级", style="bold", width=6)
    table.add_column("行号", justify="right", width=6)
    table.add_column("工号", width=10)
    table.add_column("字段", width=10)
    table.add_column("问题描述", overflow="fold")

    level_styles = {
        ErrorLevel.CRITICAL: "bold red",
        ErrorLevel.ERROR: "red",
        ErrorLevel.WARNING: "yellow",
        ErrorLevel.INFO: "blue",
    }
    level_short = {
        ErrorLevel.CRITICAL: "严重",
        ErrorLevel.ERROR: "错误",
        ErrorLevel.WARNING: "警告",
        ErrorLevel.INFO: "提示",
    }
    for issue in display_issues:
        style = level_styles.get(issue.error_level, "white")
        field_cn = config.get_field_cn(issue.field_name) if issue.field_name else ""
        table.add_row(
            Text(level_short.get(issue.error_level, issue.error_level.value), style=style),
            str(issue.row_index) if issue.row_index else "",
            issue.emp_id if issue.emp_id else "",
            field_cn,
            issue.message,
        )
    console.print(table)


def _create_summary_sheet(issues, config: RulesConfig, df: pd.DataFrame = None):
    """创建汇总统计页"""
    from collections import Counter
    level_counter = Counter()
    code_counter = Counter()
    field_counter = Counter()
    for issue in issues:
        level_counter[issue.error_level.value] += 1
        code_counter[issue.error_code.value] += 1
        if issue.field_name:
            field_counter[config.get_field_cn(issue.field_name)] += 1

    level_names = {"CRITICAL": "严重", "ERROR": "错误", "WARNING": "警告", "INFO": "提示"}
    data = []
    data.append(["===== 错误等级统计 =====", "", ""])
    for level, name in level_names.items():
        data.append([name, level, level_counter.get(level, 0)])
    data.append(["合计", "", len(issues)])
    data.append(["", "", ""])
    data.append(["===== 错误类型统计 =====", "", ""])
    for code, count in code_counter.most_common():
        data.append([code, count, ""])
    data.append(["", "", ""])
    data.append(["===== 涉及字段统计 =====", "", ""])
    for field, count in field_counter.most_common():
        data.append([field, count, ""])

    if df is not None:
        data.append(["", "", ""])
        data.append(["===== 数据概览 =====", "", ""])
        data.append(["总记录数", len(df), ""])
        for field in config.required_fields:
            if field in df.columns:
                def _chk_empty(v):
                    if v is None: return True
                    if isinstance(v, float) and pd.isna(v): return True
                    if isinstance(v, str) and v.strip() == "": return True
                    return False
                if len(df) == 0:
                    non_empty = 0
                else:
                    non_empty = int((~df[field].apply(_chk_empty)).sum())
                pct = f"{non_empty/len(df)*100:.1f}%" if len(df) else "0%"
                data.append([f"{config.get_field_cn(field)} 非空", non_empty, pct])
    return pd.DataFrame(data, columns=["项目", "详情", "数量"])


def _create_diff_summary_sheet(change_counter):
    type_desc = {
        "新增": "本月新增员工",
        "离职": "员工已离职（含花名册移除和状态变更）",
        "调岗": "岗位调整",
        "改名": "姓名变更",
        "部门变更": "部门调整",
        "上级变更": "直属上级变更",
        "用工类型变更": "用工类型变更",
        "状态变更": "在职状态变更（非离职类）",
        "其他修改": "其他字段变更",
    }
    data = []
    total = 0
    for ctype, count in change_counter.most_common():
        data.append([ctype, count, type_desc.get(ctype, "")])
        total += count
    data.append(["合计", total, ""])
    return pd.DataFrame(data, columns=["变更类型", "数量", "说明"])


def _create_overview_sheet(df, issues, config: RulesConfig, last_df=None):
    from collections import Counter
    data = []
    data.append(["===== 数据概览 =====", "", ""])
    data.append(["总记录数", len(df), ""])
    for field in config.required_fields:
        if field in df.columns and len(df) > 0:
            def _chk_empty(v):
                if v is None: return True
                if isinstance(v, float) and pd.isna(v): return True
                if isinstance(v, str) and v.strip() == "": return True
                return False
            non_empty = (~df[field].apply(_chk_empty)).sum()
            data.append([f"{config.get_field_cn(field)} 非空数", int(non_empty), f"{non_empty/len(df)*100:.1f}%"])
    if last_df is not None:
        data.append(["上月记录数", len(last_df), ""])

    data.append(["", "", ""])
    data.append(["===== 问题概览 =====", "", ""])
    level_counter = Counter(i.error_level.value for i in issues)
    level_names = {"CRITICAL": "严重", "ERROR": "错误", "WARNING": "警告", "INFO": "提示"}
    for level in ["CRITICAL", "ERROR", "WARNING", "INFO"]:
        count = level_counter.get(level, 0)
        data.append([level_names.get(level, level), count, f"{count/len(issues)*100:.1f}%" if issues else "0%"])
    data.append(["问题总数", len(issues), ""])

    data.append(["", "", ""])
    data.append(["===== 部门分布 =====", "", ""])
    if "department" in df.columns and len(df) > 0:
        dept_counts = df["department"].value_counts()
        for dept, count in dept_counts.items():
            data.append([str(dept), int(count), f"{count/len(df)*100:.1f}%" if len(df) else "0%"])

    data.append(["", "", ""])
    data.append(["===== 用工类型分布 =====", "", ""])
    if "employment_type" in df.columns and len(df) > 0:
        type_counts = df["employment_type"].value_counts()
        for t, count in type_counts.items():
            data.append([str(t), int(count), f"{count/len(df)*100:.1f}%" if len(df) else "0%"])

    data.append(["", "", ""])
    data.append(["===== 在职状态分布 =====", "", ""])
    if "status" in df.columns and len(df) > 0:
        status_counts = df["status"].value_counts()
        for t, count in status_counts.items():
            data.append([str(t), int(count), f"{count/len(df)*100:.1f}%" if len(df) else "0%"])

    return pd.DataFrame(data, columns=["项目", "数值", "占比/说明"])


def _safe_read_excel_sheet(path, sheet_name, default_cols=None):
    """安全读取 Excel 工作表，不存在返回空 DataFrame"""
    try:
        xl = pd.ExcelFile(path)
        if sheet_name in xl.sheet_names:
            return pd.read_excel(path, sheet_name=sheet_name, dtype=str, keep_default_na=False)
    except Exception:
        pass
    return pd.DataFrame(columns=default_cols or [])


@click.group()
@click.version_option(version="1.1.0", prog_name="hrcheck")
def cli():
    """人力资源花名册校验工具

    提供 import、check、diff、fix、report 五个命令，
    支持 -r 指定外置 JSON 规则配置。
    """
    _print_banner()


@cli.command("init-config")
@click.option("--output", "-o", default="hr_rules_config.json", show_default=True,
              help="输出配置文件名")
def init_config_cmd(output):
    """生成规则配置模板文件

    示例: hrcheck init-config -o my_company_rules.json
    """
    try:
        generate_template_config(output)
        console.print(f"[green][OK] 规则配置模板已生成: {output}[/green]")
        console.print("[blue]提示: 按公司实际情况修改 JSON 文件后，用各命令的 -r 参数指定[/blue]")
    except Exception as e:
        console.print(f"[bold red][X] 生成配置模板失败: {e}[/bold red]")
        sys.exit(1)


@cli.command("import")
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--sheet-name", "-s", default=None, help="Excel 工作表名")
@click.option("--output", "-o", default=None, help="标准化后输出文件路径")
@click.option("--format", "-f", "fmt", type=click.Choice(["xlsx", "csv"]), default="xlsx", help="输出格式")
@click.option("--rules-config", "-r", "rules_file", default=None, type=click.Path(exists=True, dir_okay=False),
              help="外置规则配置 JSON 文件")
@click.option("--verbose", "-v", is_flag=True, help="显示详细信息")
def import_cmd(file_path, sheet_name, output, fmt, rules_file, verbose):
    """导入花名册文件并标准化格式

    FILE_PATH: 花名册文件路径（CSV 或 Excel）
    """
    try:
        config = load_rules_config(rules_file)
        if rules_file:
            console.print(f"[blue]-> 使用规则配置: {rules_file}[/blue]")

        info = get_file_info(file_path)
        if verbose:
            info_table = Table(title="文件信息", show_header=False, header_style="bold")
            info_table.add_column("属性", style="bold")
            info_table.add_column("值")
            info_table.add_row("文件名", info["file_name"])
            info_table.add_row("完整路径", info["file_path"])
            info_table.add_row("文件大小", f"{info['file_size'] / 1024:.1f} KB")
            info_table.add_row("文件格式", info["file_format"])
            info_table.add_row("修改时间", datetime.fromtimestamp(info["modified_time"]).strftime("%Y-%m-%d %H:%M:%S"))
            console.print(info_table)

        df = import_roster(file_path, sheet_name, rules_config=config)
        console.print(f"[green][OK] 成功导入 {len(df)} 条记录[/green]")
        if len(df) == 0:
            console.print("[yellow][WARN] 花名册为空，继续处理但输出空表[/yellow]")

        if verbose:
            cols_table = Table(title="字段检测结果", show_header=True, header_style="bold magenta")
            cols_table.add_column("字段名", style="bold")
            cols_table.add_column("中文名", style="bold")
            cols_table.add_column("是否必填")
            cols_table.add_column("非空数", justify="right")
            cols_table.add_column("空值数", justify="right")

            def _chk_empty(v):
                if v is None: return True
                if isinstance(v, float) and pd.isna(v): return True
                if isinstance(v, str) and v.strip() == "": return True
                return False

            for col in config.all_fields:
                if col in df.columns:
                    non_empty = 0 if len(df) == 0 else int((~df[col].apply(_chk_empty)).sum())
                    empty = len(df) - non_empty
                    required = "是" if col in config.required_fields else "否"
                    required_style = "bold red" if col in config.required_fields else "white"
                    cols_table.add_row(
                        col,
                        config.get_field_cn(col),
                        Text(required, style=required_style),
                        str(non_empty),
                        Text(str(empty), style="red" if empty > 0 and col in config.required_fields else "white"),
                    )
            console.print(cols_table)

        if output:
            if fmt == "xlsx":
                export_to_excel(output, {"花名册": df}, rules_config=config)
            else:
                export_to_csv(output, df, rules_config=config)
            console.print(f"[green][OK] 已输出到: {output}[/green]")
        else:
            base = os.path.splitext(file_path)[0]
            default_output = f"{base}_标准化.{fmt}"
            if fmt == "xlsx":
                export_to_excel(default_output, {"花名册": df}, rules_config=config)
            else:
                export_to_csv(default_output, df, rules_config=config)
            console.print(f"[green][OK] 已输出到: {default_output}[/green]")

    except Exception as e:
        console.print(f"[bold red][X] 导入失败: {e}[/bold red]")
        import traceback; traceback.print_exc()
        sys.exit(1)


@cli.command("check")
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--sheet-name", "-s", default=None, help="Excel 工作表名")
@click.option("--output", "-o", default=None, help="问题报告输出路径")
@click.option("--rules-config", "-r", "rules_file", default=None, type=click.Path(exists=True, dir_okay=False),
              help="外置规则配置 JSON 文件")
@click.option("--departments", "-d", "dept_file", default=None, type=click.Path(exists=True),
              help="自定义有效部门列表文件（每行一个，优先于规则配置）")
@click.option("--clean-output", "-c", default=None, help="干净数据输出路径")
@click.option("--max-display", "-m", default=50, type=int, help="最多显示的问题条数")
def check_cmd(file_path, sheet_name, output, rules_file, dept_file, clean_output, max_display):
    """校验花名册数据

    检查重复工号、空值、日期异常、部门不存在、上下级循环、离职状态冲突等。
    """
    try:
        config = load_rules_config(rules_file)
        if rules_file:
            console.print(f"[blue]-> 使用规则配置: {rules_file}[/blue]")

        df = import_roster(file_path, sheet_name, rules_config=config)
        console.print(f"[blue]-> 已导入 {len(df)} 条记录，开始校验...[/blue]")
        if len(df) == 0:
            console.print("[yellow][WARN] 花名册为空，输出空报告[/yellow]")

        valid_depts_override = None
        if dept_file:
            with open(dept_file, "r", encoding="utf-8") as f:
                valid_depts_override = [line.strip() for line in f if line.strip()]
            console.print(f"[blue]-> 载入自定义部门列表文件，共 {len(valid_depts_override)} 个部门[/blue]")

        issues = validate_roster(df, rules_config=config, valid_departments=valid_depts_override)
        console.print(f"[blue]-> 校验完成，共发现 {len(issues)} 个问题[/blue]")

        _print_issues_summary(issues)
        _print_issues_table(issues, max_rows=max_display, config=config)

        base = os.path.splitext(file_path)[0]

        if output:
            issues_df = issues_to_dataframe(issues, config)
            export_to_excel(output, {
                "问题统计": _create_summary_sheet(issues, config, df),
                "问题明细": issues_df,
            }, rules_config=config)
            console.print(f"[green][OK] 问题报告已输出到: {output}[/green]")
        else:
            default_output = f"{base}_问题报告.xlsx"
            issues_df = issues_to_dataframe(issues, config)
            export_to_excel(default_output, {
                "问题统计": _create_summary_sheet(issues, config, df),
                "问题明细": issues_df,
            }, rules_config=config)
            console.print(f"[green][OK] 问题报告已输出到: {default_output}[/green]")

        if clean_output:
            clean_df = get_clean_roster(df, issues, config)
            export_to_excel(clean_output, {"花名册": clean_df}, rules_config=config)
            console.print(f"[green][OK] 干净数据已输出到: {clean_output} (共 {len(clean_df)} 条)[/green]")
        else:
            default_clean = f"{base}_干净版.xlsx"
            clean_df = get_clean_roster(df, issues, config)
            export_to_excel(default_clean, {"花名册": clean_df}, rules_config=config)
            console.print(f"[green][OK] 干净数据已输出到: {default_clean} (共 {len(clean_df)} 条)[/green]")

        critical = sum(1 for i in issues if i.error_level == ErrorLevel.CRITICAL)
        errors = sum(1 for i in issues if i.error_level == ErrorLevel.ERROR)
        if critical > 0 or errors > 0:
            console.print(f"[yellow][WARN] 共 {critical} 个严重 + {errors} 个错误，请优先修复[/yellow]")

    except Exception as e:
        console.print(f"[bold red][X] 校验失败: {e}[/bold red]")
        import traceback; traceback.print_exc()
        sys.exit(1)


@cli.command("diff")
@click.argument("last_month_file", type=click.Path(exists=True, dir_okay=False))
@click.argument("current_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--last-sheet", default=None, help="上月数据工作表名")
@click.option("--current-sheet", default=None, help="本月数据工作表名")
@click.option("--output", "-o", default=None, help="差异报告输出路径")
@click.option("--rules-config", "-r", "rules_file", default=None, type=click.Path(exists=True, dir_okay=False),
              help="外置规则配置 JSON 文件")
@click.option("--summary-only", is_flag=True, help="仅显示汇总信息")
def diff_cmd(last_month_file, current_file, last_sheet, current_sheet, output, rules_file, summary_only):
    """对比两个月的花名册差异

    检测：新增、离职（含花名册移除+状态变离职）、调岗、改名、部门/上级/用工类型变更。
    """
    try:
        config = load_rules_config(rules_file)
        if rules_file:
            console.print(f"[blue]-> 使用规则配置: {rules_file}[/blue]")

        last_df = import_roster(last_month_file, last_sheet, rules_config=config)
        curr_df = import_roster(current_file, current_sheet, rules_config=config)
        console.print(f"[blue]-> 上月: {len(last_df)} 条 | 本月: {len(curr_df)} 条[/blue]")
        if len(last_df) == 0 and len(curr_df) == 0:
            console.print("[yellow][WARN] 两个月花名册都为空，输出空报告[/yellow]")

        diffs = compare_rosters(last_df, curr_df, rules_config=config)
        console.print(f"[blue]-> 差异分析完成，共 {len(diffs)} 条变更[/blue]")

        change_counter = Counter()
        for d in diffs:
            change_counter[d.change_type] += 1

        sum_table = Table(title="变更类型统计", show_header=True, header_style="bold magenta")
        sum_table.add_column("变更类型", style="bold")
        sum_table.add_column("数量", justify="right")
        sum_table.add_column("说明", style="italic")

        type_style = {
            "新增": "green", "离职": "red", "调岗": "yellow", "改名": "cyan",
            "部门变更": "magenta", "上级变更": "blue", "用工类型变更": "white",
            "状态变更": "dim", "其他修改": "dim",
        }
        type_desc = {
            "新增": "本月新员工",
            "离职": "（含花名册移除 + 状态变离职）",
            "调岗": "岗位调整",
            "改名": "姓名变更",
            "部门变更": "部门调动",
            "上级变更": "直属上级变更",
            "用工类型变更": "合同类型变更",
            "状态变更": "在职状态（非离职类）",
            "其他修改": "日期/联系方式等",
        }
        for ctype in ["新增", "离职", "调岗", "改名", "部门变更", "上级变更", "用工类型变更", "状态变更", "其他修改"]:
            count = change_counter.get(ctype, 0)
            if count > 0 or ctype in ["新增", "离职"]:
                sum_table.add_row(
                    Text(ctype, style=type_style.get(ctype, "white")),
                    str(count),
                    type_desc.get(ctype, ""),
                )
        console.print(sum_table)

        if not summary_only and diffs:
            display_diffs = [d for d in diffs if d.change_type == "离职"][:10] + \
                           [d for d in diffs if d.change_type == "新增"][:10] + \
                           [d for d in diffs if d.change_type not in ["离职", "新增"]][:30]
            display_diffs = display_diffs[:50]
            diff_table = Table(title=f"变更明细 (显示前 {len(display_diffs)}/{len(diffs)} 条，重点展示离职/新增)",
                              show_header=True, header_style="bold magenta")
            diff_table.add_column("工号", width=10)
            diff_table.add_column("变更类型", width=12)
            diff_table.add_column("字段", width=10)
            diff_table.add_column("变更说明", overflow="fold")
            for d in display_diffs:
                diff_table.add_row(
                    d.emp_id,
                    Text(d.change_type, style=type_style.get(d.change_type, "white")),
                    config.get_field_cn(d.field_name) if d.field_name else "",
                    d.description,
                )
            console.print(diff_table)

        summaries = get_department_summary(last_df, curr_df, diffs, rules_config=config)
        if summaries or (len(last_df) == 0 and len(curr_df) == 0):
            dept_df = summary_to_dataframe(summaries)
            console.print()
            console.print(Panel("部门在职人数变化汇总（已自动扣除状态离职员工）", border_style="cyan"))
            if not dept_df.empty:
                dept_display = dept_df.head(30)
                dept_table = Table(show_header=True, header_style="bold cyan")
                for col in dept_display.columns:
                    dept_table.add_column(col, justify="right" if col != "部门" else "left")
                for _, row in dept_display.iterrows():
                    vals = []
                    for col in dept_display.columns:
                        v = row[col]
                        if col == "净变化":
                            sv = str(v)
                            style = "green" if sv.startswith("+") else ("red" if sv.startswith("-") else "white")
                            vals.append(Text(sv, style=style))
                        else:
                            vals.append(str(v))
                    dept_table.add_row(*vals)
                console.print(dept_table)
                if len(dept_df) > 30:
                    console.print(f"  [dim]... 另外 {len(dept_df) - 30} 个部门数据详见输出文件[/dim]")
            else:
                console.print("[dim]（暂无部门数据）[/dim]")

        if output:
            diffs_df = diffs_to_dataframe(diffs, config)
            dept_df = summary_to_dataframe(summaries)
            export_to_excel(output, {
                "变更汇总": _create_diff_summary_sheet(change_counter),
                "离职明细": diffs_to_dataframe([d for d in diffs if d.change_type == "离职"], config),
                "变更明细": diffs_df,
                "部门汇总": dept_df,
            }, rules_config=config)
            console.print(f"[green][OK] 差异报告已输出到: {output}[/green]")
        else:
            base = os.path.splitext(current_file)[0]
            default_output = f"{base}_差异报告.xlsx"
            diffs_df = diffs_to_dataframe(diffs, config)
            dept_df = summary_to_dataframe(summaries)
            export_to_excel(default_output, {
                "变更汇总": _create_diff_summary_sheet(change_counter),
                "离职明细": diffs_to_dataframe([d for d in diffs if d.change_type == "离职"], config),
                "变更明细": diffs_df,
                "部门汇总": dept_df,
            }, rules_config=config)
            console.print(f"[green][OK] 差异报告已输出到: {default_output}[/green]")

    except Exception as e:
        console.print(f"[bold red][X] 差异对比失败: {e}[/bold red]")
        import traceback; traceback.print_exc()
        sys.exit(1)


@cli.command("fix")
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--sheet-name", "-s", default=None, help="Excel 工作表名")
@click.option("--output", "-o", default=None, help="修复建议表输出路径")
@click.option("--rules-config", "-r", "rules_file", default=None, type=click.Path(exists=True, dir_okay=False),
              help="外置规则配置 JSON 文件")
@click.option("--apply", "-a", "apply_file", default=None, type=click.Path(exists=True, dir_okay=False),
              help="已确认的修复建议表（HR填完后用此参数批量应用）")
@click.option("--fixed-output", "-f", default=None, help="应用修复后的花名册输出路径")
@click.option("--report-output", default=None, help="修复+复检完整报告输出路径")
@click.option("--confidence", "-c", type=click.Choice(["high", "medium", "low"]),
              default=None, help="仅显示指定置信度的建议")
@click.option("--no-recheck", is_flag=True, help="应用修复后不做复检")
def fix_cmd(file_path, sheet_name, output, rules_file, apply_file, fixed_output,
            report_output, confidence, no_recheck):
    """生成修复建议并支持批量应用

    流程：
    1) 第一次运行生成含「是否删除此行」「人工修正值」的建议表
    2) HR 在 Excel 中填写确认信息
    3) 第二次用 -a 应用，自动输出修复后花名册 + 修复记录 + 复检结果
    """
    try:
        config = load_rules_config(rules_file)
        if rules_file:
            console.print(f"[blue]-> 使用规则配置: {rules_file}[/blue]")

        df = import_roster(file_path, sheet_name, rules_config=config)
        console.print(f"[blue]-> 已导入 {len(df)} 条记录[/blue]")
        if len(df) == 0:
            console.print("[yellow][WARN] 花名册为空，输出空建议表[/yellow]")

        if apply_file:
            console.print(f"[blue]-> 载入已确认的修复建议: {apply_file}[/blue]")
            confirm_df = _safe_read_excel_sheet(apply_file, "修复建议",
                ["序号", "是否采纳", "是否删除此行", "人工修正值"])
            if confirm_df.empty:
                raise ValueError("修复建议表中没有'修复建议'工作表，请检查文件")
            console.print(f"[blue]-> 共读取 {len(confirm_df)} 行确认记录[/blue]")

            issues = validate_roster(df, rules_config=config)
            suggestions = generate_fix_suggestions(df, issues, rules_config=config)

            result = apply_fixes(
                df, suggestions, confirm_df,
                rules_config=config, do_recheck=not no_recheck
            )

            stats_table = Table(title="修复应用统计", show_header=True, header_style="bold green")
            stats_table.add_column("项目", style="bold")
            stats_table.add_column("数量", justify="right")
            stats_table.add_row("修复建议总数", str(len(suggestions)))
            stats_table.add_row("已成功应用", Text(str(result.applied_count), style="green"))
            stats_table.add_row("  - 其中删除行", Text(str(len(result.deleted_rows)), style="red"))
            stats_table.add_row("  - 其中修改字段", Text(str(result.applied_count - len(result.deleted_rows)), style="cyan"))
            stats_table.add_row("需人工确认/未采纳", Text(str(result.needs_manual_count), style="yellow"))
            stats_table.add_row("跳过", Text(str(result.skipped_count), style="dim"))
            if not no_recheck:
                stats_table.add_row("──────", "──")
                stats_table.add_row("复检问题数", Text(str(len(result.recheck_issues)),
                    style="red" if len(result.recheck_issues) > 0 else "green"))
            console.print(stats_table)

            if result.modified_fields:
                mod_table = Table(title="字段修改明细（前10条）", show_header=True, header_style="bold cyan")
                mod_table.add_column("行号", justify="right")
                mod_table.add_column("工号")
                mod_table.add_column("字段")
                mod_table.add_column("原值")
                mod_table.add_column("新值")
                for mf in result.modified_fields[:10]:
                    mod_table.add_row(
                        str(mf["row_index"]) if mf["row_index"] else "",
                        mf["emp_id"] or "",
                        config.get_field_cn(mf["field"]),
                        str(mf["old"]) if not (mf["old"] is None or (isinstance(mf["old"], str) and mf["old"].strip()=="")) else "[空]",
                        str(mf["new"]),
                    )
                console.print(mod_table)
                if len(result.modified_fields) > 10:
                    console.print(f"  [dim]... 另外 {len(result.modified_fields) - 10} 条修改详见输出文件[/dim]")

            if not no_recheck and result.recheck_issues:
                console.print()
                console.print(Panel("🔍 复检结果（修复后仍存在的问题）", border_style="yellow"))
                _print_issues_summary(result.recheck_issues)
                _print_issues_table(result.recheck_issues, max_rows=20, config=config)

            base = os.path.splitext(file_path)[0]

            fixed_path = fixed_output if fixed_output else f"{base}_已修复.xlsx"
            export_to_excel(fixed_path, {"花名册": result.fixed_df}, rules_config=config)
            console.print(f"[green][OK] 修复后的花名册已输出: {fixed_path} ({len(result.fixed_df)} 条)[/green]")

            report_path = report_output if report_output else f"{base}_修复报告.xlsx"
            sheets = {
                "修复统计": pd.DataFrame([
                    ["修复建议总数", len(suggestions)],
                    ["成功应用", result.applied_count],
                    ["  删除行数", len(result.deleted_rows)],
                    ["  修改字段数", result.applied_count - len(result.deleted_rows)],
                    ["需人工确认", result.needs_manual_count],
                    ["跳过", result.skipped_count],
                    ["复检剩余问题", len(result.recheck_issues)],
                ], columns=["项目", "数值"]),
                "修复记录": result.fix_records_df,
                "已修复花名册": result.fixed_df,
            }
            if not no_recheck:
                sheets["复检问题明细"] = issues_to_dataframe(result.recheck_issues, config)
            export_to_excel(report_path, sheets, rules_config=config)
            console.print(f"[green][OK] 完整修复+复检报告已输出: {report_path}[/green]")

            if len(result.recheck_issues) > 0 and not no_recheck:
                console.print("[yellow][WARN] 修复后仍有问题，请检查「复检问题明细」工作表并决定是否继续处理[/yellow]")
            return

        issues = validate_roster(df, rules_config=config)
        console.print(f"[blue]-> 发现 {len(issues)} 个问题，正在生成修复建议...[/blue]")

        suggestions = generate_fix_suggestions(df, issues, rules_config=config)
        if confidence:
            suggestions = [s for s in suggestions if s.confidence == confidence]
        console.print(f"[blue]-> 已生成 {len(suggestions)} 条修复建议[/blue]")

        conf_counter = Counter()
        type_counter = Counter()
        need_confirm = 0
        deletable = 0
        for s in suggestions:
            conf_counter[s.confidence] += 1
            type_counter[s.fix_type] += 1
            if s.needs_confirmation:
                need_confirm += 1
            if s.allow_delete:
                deletable += 1

        stats_table = Table(title="修复建议统计", show_header=True, header_style="bold magenta")
        stats_table.add_column("维度", style="bold")
        stats_table.add_column("数量", justify="right")
        conf_names = {"high": "高", "medium": "中", "low": "低"}
        conf_styles = {"high": "green", "medium": "yellow", "low": "red"}
        for level in ["high", "medium", "low"]:
            stats_table.add_row(
                Text(f"置信度 {conf_names[level]}", style=conf_styles[level]),
                str(conf_counter.get(level, 0)),
            )
        stats_table.add_row("需人工确认", Text(str(need_confirm), style="yellow"))
        stats_table.add_row("可删除的重复行", Text(str(deletable), style="red"))
        stats_table.add_row("合计", str(len(suggestions)))
        console.print(stats_table)

        display_sugs = suggestions[:30]
        if display_sugs:
            sug_table = Table(title=f"修复建议 (显示前 {len(display_sugs)}/{len(suggestions)} 条)",
                            show_header=True, header_style="bold magenta")
            sug_table.add_column("序号", justify="right", width=5)
            sug_table.add_column("工号", width=10)
            sug_table.add_column("字段", width=8)
            sug_table.add_column("置信度", width=6)
            sug_table.add_column("可删", width=4)
            sug_table.add_column("建议值")
            sug_table.add_column("详细说明", overflow="fold")
            for idx, s in enumerate(display_sugs, 1):
                field_cn = config.get_field_cn(s.field_name) if s.field_name else ""
                sug_table.add_row(
                    str(idx),
                    s.emp_id if s.emp_id else "",
                    field_cn,
                    Text(conf_names.get(s.confidence, s.confidence), style=conf_styles.get(s.confidence, "white")),
                    Text("[OK]", style="red") if s.allow_delete else "",
                    str(s.suggested_value) if s.suggested_value is not None else "需人工",
                    s.description,
                )
            console.print(sug_table)

        suggestions_df = suggestions_to_dataframe(suggestions)
        if output:
            export_to_excel(output, {
                "修复建议": suggestions_df,
                "问题明细": issues_to_dataframe(issues, config),
            }, rules_config=config)
            console.print(f"[green][OK] 修复建议已输出到: {output}[/green]")
        else:
            base = os.path.splitext(file_path)[0]
            default_output = f"{base}_修复建议.xlsx"
            export_to_excel(default_output, {
                "修复建议": suggestions_df,
                "问题明细": issues_to_dataframe(issues, config),
            }, rules_config=config)
            console.print(f"[green][OK] 修复建议已输出到: {default_output}[/green]")

        console.print()
        console.print(Panel(
            "[bold yellow]HR 操作流程:[/bold yellow]\n"
            "  1.  打开修复建议 Excel -> [修复建议] 工作表\n"
            "  2.  [bold]重复工号[/bold]: 在「是否删除此行」填 [red]是[/red] 删除多余行\n"
            "     或在「人工修正值」填新工号（并「是否采纳」填是）\n"
            "  3.  [bold]其他问题[/bold]: 同意建议就在「是否采纳」填是\n"
            "     建议值不对就在「人工修正值」填正确值再勾选采纳\n"
            "  4.  保存文件后运行:\n"
            "     [bold cyan]hrcheck fix <花名册.xlsx> -a <已确认的建议.xlsx>[/bold cyan]\n"
            "  📌 系统将自动输出: [green]已修复花名册 + 修复记录 + 复检结果[/green]",
            title="📋 使用说明",
            border_style="blue",
        ))

    except Exception as e:
        console.print(f"[bold red][X] 修复流程失败: {e}[/bold red]")
        import traceback; traceback.print_exc()
        sys.exit(1)


@cli.command("report")
@click.argument("current_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--last-month", "-l", "last_file", default=None, type=click.Path(exists=True, dir_okay=False),
              help="上月花名册文件（用于生成差异和部门汇总对比）")
@click.option("--current-sheet", default=None, help="本月数据工作表名")
@click.option("--last-sheet", default=None, help="上月数据工作表名")
@click.option("--output", "-o", default=None, help="综合报告 Excel 输出路径")
@click.option("--rules-config", "-r", "rules_file", default=None, type=click.Path(exists=True, dir_okay=False),
              help="外置规则配置 JSON 文件")
@click.option("--departments", "-d", "dept_file", default=None, type=click.Path(exists=True),
              help="自定义部门列表文件")
@click.option("--audit-package", "-p", "audit_dir", default=None,
              help="审计包输出目录（一次性导出所有文件+JSON）")
def report_cmd(current_file, last_file, current_sheet, last_sheet, output,
               rules_file, dept_file, audit_dir):
    """生成完整人事报告 + 可选审计包导出

    综合报告工作表：数据概览 / 问题明细 / 修复建议 / 干净数据
                    [+差异汇总 / 离职明细 / 变更明细 / 部门汇总（有上月时）]

    审计包目录：
      01_标准化花名册.xlsx
      02_干净花名册.xlsx
      03_问题明细.xlsx
      04_修复建议.xlsx
      05_差异报告.xlsx   （有上月时）
      06_部门汇总.xlsx   （有上月时）
      07_修复记录.xlsx
      audit_summary.json （机器可读）
    """
    try:
        config = load_rules_config(rules_file)
        if rules_file:
            console.print(f"[blue]-> 使用规则配置: {rules_file}[/blue]")

        curr_df = import_roster(current_file, current_sheet, rules_config=config)
        console.print(f"[blue]-> 本月数据: {len(curr_df)} 条[/blue]")
        if len(curr_df) == 0:
            console.print("[yellow][WARN] 本月花名册为空，继续处理并输出空表[/yellow]")

        valid_depts_override = None
        if dept_file:
            with open(dept_file, "r", encoding="utf-8") as f:
                valid_depts_override = [line.strip() for line in f if line.strip()]
            console.print(f"[blue]-> 载入自定义部门列表: {len(valid_depts_override)} 个[/blue]")

        issues = validate_roster(curr_df, rules_config=config, valid_departments=valid_depts_override)
        console.print(f"[blue]-> 校验完成: {len(issues)} 个问题[/blue]")

        suggestions = generate_fix_suggestions(curr_df, issues, rules_config=config)
        clean_df = get_clean_roster(curr_df, issues, config)

        sheets = {
            "数据概览": _create_overview_sheet(curr_df, issues, config),
            "问题明细": issues_to_dataframe(issues, config),
            "修复建议": suggestions_to_dataframe(suggestions),
            "干净数据": clean_df,
        }

        last_df = None
        diffs = []
        summaries = []
        if last_file:
            last_df = import_roster(last_file, last_sheet, rules_config=config)
            console.print(f"[blue]-> 上月数据: {len(last_df)} 条[/blue]")
            diffs = compare_rosters(last_df, curr_df, rules_config=config)
            console.print(f"[blue]-> 差异分析: {len(diffs)} 条变更[/blue]")
            summaries = get_department_summary(last_df, curr_df, diffs, rules_config=config)

            change_counter = Counter(d.change_type for d in diffs)
            sheets["数据概览"] = _create_overview_sheet(curr_df, issues, config, last_df=last_df)
            sheets["差异汇总"] = _create_diff_summary_sheet(change_counter)
            sheets["离职明细"] = diffs_to_dataframe([d for d in diffs if d.change_type == "离职"], config)
            sheets["变更明细"] = diffs_to_dataframe(diffs, config)
            sheets["部门汇总"] = summary_to_dataframe(summaries)

        base = os.path.splitext(current_file)[0]
        output_path = output if output else f"{base}_综合报告.xlsx"
        export_to_excel(output_path, sheets, rules_config=config)

        overview_panel_lines = [
            f"[bold cyan]综合报告工作表:[/bold cyan]",
            f"  📊 数据概览: {len(curr_df)} 条",
            f"  [ERR] 问题明细: {len(issues)} 个问题",
            f"  🔧 修复建议: {len(suggestions)} 条",
            f"  [OK] 干净数据: {len(clean_df)} 条无错记录",
        ]
        if last_file:
            overview_panel_lines += [
                f"  📈 差异汇总 + 离职明细 + 变更明细: {len(diffs)} 条",
                f"  📋 部门汇总: {len(summaries)} 个部门统计",
            ]
        overview_panel = Panel("\n".join(overview_panel_lines), title="综合报告生成完成", border_style="green")
        console.print(overview_panel)
        console.print(f"[green][OK] 综合报告已输出: {output_path}[/green]")

        if audit_dir:
            console.print()
            console.print(f"[blue]📦 正在生成审计包: {audit_dir}[/blue]")
            os.makedirs(audit_dir, exist_ok=True)

            export_to_excel(os.path.join(audit_dir, "01_标准化花名册.xlsx"),
                           {"花名册": curr_df}, rules_config=config)
            export_to_excel(os.path.join(audit_dir, "02_干净花名册.xlsx"),
                           {"花名册": clean_df}, rules_config=config)
            export_to_excel(os.path.join(audit_dir, "03_问题明细.xlsx"),
                           {"问题统计": _create_summary_sheet(issues, config, curr_df),
                            "问题明细": issues_to_dataframe(issues, config)},
                           rules_config=config)
            export_to_excel(os.path.join(audit_dir, "04_修复建议.xlsx"),
                           {"修复建议": suggestions_to_dataframe(suggestions),
                            "问题明细": issues_to_dataframe(issues, config)},
                           rules_config=config)

            fix_records_empty = pd.DataFrame(columns=[
                "序号", "工号", "行号", "字段", "原值", "新值", "修复方式", "确认方式", "处理时间"
            ])
            export_to_excel(os.path.join(audit_dir, "07_修复记录.xlsx"),
                           {"修复记录": fix_records_empty},
                           rules_config=config)

            if last_file:
                change_counter = Counter(d.change_type for d in diffs)
                export_to_excel(os.path.join(audit_dir, "05_差异报告.xlsx"),
                               {"变更汇总": _create_diff_summary_sheet(change_counter),
                                "离职明细": diffs_to_dataframe([d for d in diffs if d.change_type == "离职"], config),
                                "变更明细": diffs_to_dataframe(diffs, config)},
                               rules_config=config)
                export_to_excel(os.path.join(audit_dir, "06_部门汇总.xlsx"),
                               {"部门汇总": summary_to_dataframe(summaries)},
                               rules_config=config)

            audit_json: Dict[str, Any] = {
                "audit_package_version": "1.1",
                "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "rules_config": {
                    "source": rules_file or "default",
                    "required_fields_count": len(config.required_fields),
                    "valid_departments_count": len(config.valid_departments),
                    "valid_employment_types_count": len(config.valid_employment_types),
                },
                "current_roster": {
                    "file": current_file,
                    "total_records": len(curr_df),
                    "active_records": 0,
                    "resigned_records": 0,
                },
                "issues": {
                    "total": len(issues),
                    "by_level": dict(Counter(i.error_level.value for i in issues)),
                    "by_code": dict(Counter(i.error_code.value for i in issues)),
                },
                "clean_roster_records": len(clean_df),
                "fix_suggestions": {
                    "total": len(suggestions),
                    "by_confidence": dict(Counter(s.confidence for s in suggestions)),
                    "requires_manual_confirmation": sum(1 for s in suggestions if s.needs_confirmation),
                },
            }

            if "status" in curr_df.columns and len(curr_df) > 0:
                sr = config.status_rules or {}
                resigned_list = sr.get("resigned_statuses", ["离职", "退休"])
                active_list = sr.get("active_statuses", ["在职"])

                def _is_r(s):
                    if s is None: return False
                    if isinstance(s, float) and pd.isna(s): return False
                    return str(s).strip() in resigned_list
                def _is_a(s):
                    if s is None: return False
                    if isinstance(s, float) and pd.isna(s): return False
                    return str(s).strip() in active_list
                audit_json["current_roster"]["active_records"] = int(curr_df["status"].apply(_is_a).sum())
                audit_json["current_roster"]["resigned_records"] = int(curr_df["status"].apply(_is_r).sum())

            if last_file:
                audit_json["last_month_roster"] = {
                    "file": last_file,
                    "total_records": len(last_df),
                }
                audit_json["diffs"] = {
                    "total": len(diffs),
                    "by_type": dict(Counter(d.change_type for d in diffs)),
                }
                audit_json["department_summary"] = [
                    {
                        "department": s.department,
                        "last_month_count": s.last_month_count,
                        "current_count": s.current_count,
                        "new_count": s.new_count,
                        "resign_count": s.resign_count,
                        "transfer_in": s.transfer_in,
                        "transfer_out": s.transfer_out,
                        "net_change": s.net_change,
                    }
                    for s in summaries
                ]

            json_path = os.path.join(audit_dir, "audit_summary.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(audit_json, f, ensure_ascii=False, indent=2)

            console.print(Panel(
                "\n".join([
                    f"[bold cyan]审计包文件清单:[/bold cyan]",
                    f"  01_标准化花名册.xlsx ({len(curr_df)} 条)",
                    f"  02_干净花名册.xlsx ({len(clean_df)} 条)",
                    f"  03_问题明细.xlsx ({len(issues)} 问题)",
                    f"  04_修复建议.xlsx ({len(suggestions)} 建议)",
                    f"  07_修复记录.xlsx (待填写)",
                ] + ([
                    f"  05_差异报告.xlsx ({len(diffs)} 变更)",
                    f"  06_部门汇总.xlsx ({len(summaries)} 部门)",
                ] if last_file else []) + [
                    f"  audit_summary.json (机器可读)",
                    "",
                    f"[green]共 {7 + (2 if last_file else 0)} 个文件[/green]",
                ]),
                title="📦 审计包导出完成",
                border_style="cyan",
            ))

        critical = sum(1 for i in issues if i.error_level == ErrorLevel.CRITICAL)
        errors = sum(1 for i in issues if i.error_level == ErrorLevel.ERROR)
        if critical > 0 or errors > 0:
            console.print(f"[yellow][WARN] 存在 {critical} 个严重 + {errors} 个错误，建议用 fix 命令处理[/yellow]")

    except Exception as e:
        console.print(f"[bold red][X] 生成报告失败: {e}[/bold red]")
        import traceback; traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    cli()
