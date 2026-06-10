"""命令行工具主入口"""

import os
import sys
from typing import Optional, List
from collections import Counter

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from .config import (
    ErrorLevel, ValidationIssue,
    ALL_FIELDS, REQUIRED_FIELDS, FIELD_CN_MAPPING,
    ErrorCode,
)
from .io_utils import import_roster, export_to_excel, export_to_csv, get_file_info
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
    apply_fixes,
)

console = Console()


def _print_banner():
    banner = Panel(
        Text(
            "人力资源花名册校验工具 (HR Roster Check)\n"
            "用于月报、审计和系统迁移前快速检查员工基础数据",
            style="bold cyan",
            justify="center"
        ),
        border_style="blue",
    )
    console.print(banner)


def _print_issues_summary(issues: List[ValidationIssue]):
    """打印问题统计"""
    level_counter = Counter()
    code_counter = Counter()
    for issue in issues:
        level_counter[issue.error_level.value] += 1
        code_counter[issue.error_code.value] += 1

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


def _print_issues_table(issues: List[ValidationIssue], max_rows: int = 50):
    """打印问题明细表格"""
    if not issues:
        console.print("[green]✓ 未发现任何校验问题！[/green]")
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
        field_cn = FIELD_CN_MAPPING.get(issue.field_name, issue.field_name) if issue.field_name else ""
        table.add_row(
            Text(level_short.get(issue.error_level, issue.error_level.value), style=style),
            str(issue.row_index) if issue.row_index else "",
            issue.emp_id if issue.emp_id else "",
            field_cn,
            issue.message,
        )
    console.print(table)


@click.group()
@click.version_option(version="1.0.0", prog_name="hrcheck")
def cli():
    """人力资源花名册校验工具

    提供 import、check、diff、fix、report 五个命令，
    用于月报、审计和系统迁移前快速检查员工基础数据。
    """
    _print_banner()


@cli.command("import")
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--sheet-name", "-s", default=None, help="Excel 工作表名")
@click.option("--output", "-o", default=None, help="标准化后输出文件路径")
@click.option("--format", "-f", "fmt", type=click.Choice(["xlsx", "csv"]), default="xlsx", help="输出格式")
@click.option("--verbose", "-v", is_flag=True, help="显示详细信息")
def import_cmd(file_path, sheet_name, output, fmt, verbose):
    """导入花名册文件并标准化格式

    FILE_PATH: 花名册文件路径（CSV 或 Excel）

    示例:
      hrcheck import 员工花名册.xlsx
      hrcheck import 员工花名册.xlsx -o 标准化花名册.xlsx
    """
    try:
        info = get_file_info(file_path)
        if verbose:
            info_table = Table(title="文件信息", show_header=False, header_style="bold")
            info_table.add_column("属性", style="bold")
            info_table.add_column("值")
            info_table.add_row("文件名", info["file_name"])
            info_table.add_row("完整路径", info["file_path"])
            info_table.add_row("文件大小", f"{info['file_size'] / 1024:.1f} KB")
            info_table.add_row("文件格式", info["file_format"])
            import datetime
            info_table.add_row("修改时间", datetime.datetime.fromtimestamp(info["modified_time"]).strftime("%Y-%m-%d %H:%M:%S"))
            console.print(info_table)

        df = import_roster(file_path, sheet_name)
        console.print(f"[green]✓ 成功导入 {len(df)} 条记录[/green]")

        if verbose:
            cols_table = Table(title="字段检测结果", show_header=True, header_style="bold magenta")
            cols_table.add_column("字段名", style="bold")
            cols_table.add_column("中文名", style="bold")
            cols_table.add_column("是否必填")
            cols_table.add_column("非空数", justify="right")
            cols_table.add_column("空值数", justify="right")

            for col in ALL_FIELDS:
                if col in df.columns:
                    non_empty = df[col].apply(lambda x: not (x is None or (isinstance(x, float) and __import__('pandas').isna(x)) or (isinstance(x, str) and x.strip() == ""))).sum()
                    empty = len(df) - non_empty
                    required = "是" if col in REQUIRED_FIELDS else "否"
                    required_style = "bold red" if col in REQUIRED_FIELDS else "white"
                    cols_table.add_row(
                        col,
                        FIELD_CN_MAPPING.get(col, ""),
                        Text(required, style=required_style),
                        str(non_empty),
                        Text(str(empty), style="red" if empty > 0 and col in REQUIRED_FIELDS else "white"),
                    )
            console.print(cols_table)

        if output:
            if fmt == "xlsx":
                export_to_excel(output, {"花名册": df})
            else:
                export_to_csv(output, df)
            console.print(f"[green]✓ 已输出到: {output}[/green]")
        else:
            base = os.path.splitext(file_path)[0]
            default_output = f"{base}_标准化.{fmt}"
            if fmt == "xlsx":
                export_to_excel(default_output, {"花名册": df})
            else:
                export_to_csv(default_output, df)
            console.print(f"[green]✓ 已输出到: {default_output}[/green]")

    except Exception as e:
        console.print(f"[bold red]✗ 导入失败: {e}[/bold red]")
        sys.exit(1)


@cli.command("check")
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--sheet-name", "-s", default=None, help="Excel 工作表名")
@click.option("--output", "-o", default=None, help="问题报告输出路径")
@click.option("--departments", "-d", "dept_file", default=None, type=click.Path(exists=True),
              help="自定义有效部门列表文件 (每行一个部门)")
@click.option("--clean-output", "-c", default=None, help="干净数据输出路径")
@click.option("--max-display", "-m", default=50, type=int, help="最多显示的问题条数")
def check_cmd(file_path, sheet_name, output, dept_file, clean_output, max_display):
    """校验花名册数据

    检查重复工号、空值、日期异常、部门不存在、上下级循环、离职状态冲突等。

    FILE_PATH: 花名册文件路径

    示例:
      hrcheck check 员工花名册.xlsx
      hrcheck check 员工花名册.xlsx -o 问题报告.xlsx -c 干净数据.xlsx
    """
    try:
        df = import_roster(file_path, sheet_name)
        console.print(f"[blue]→ 已导入 {len(df)} 条记录，开始校验...[/blue]")

        valid_depts = None
        if dept_file:
            with open(dept_file, "r", encoding="utf-8") as f:
                valid_depts = [line.strip() for line in f if line.strip()]
            console.print(f"[blue]→ 载入自定义部门列表，共 {len(valid_depts)} 个部门[/blue]")

        issues = validate_roster(df, valid_depts)
        console.print(f"[blue]→ 校验完成，共发现 {len(issues)} 个问题[/blue]")

        _print_issues_summary(issues)
        _print_issues_table(issues, max_rows=max_display)

        base = os.path.splitext(file_path)[0]

        if output:
            issues_df = issues_to_dataframe(issues)
            export_to_excel(output, {
                "问题统计": _create_summary_sheet(issues),
                "问题明细": issues_df,
            })
            console.print(f"[green]✓ 问题报告已输出到: {output}[/green]")
        elif issues:
            default_output = f"{base}_问题报告.xlsx"
            issues_df = issues_to_dataframe(issues)
            export_to_excel(default_output, {
                "问题统计": _create_summary_sheet(issues),
                "问题明细": issues_df,
            })
            console.print(f"[green]✓ 问题报告已输出到: {default_output}[/green]")

        if clean_output:
            clean_df = get_clean_roster(df, issues)
            export_to_excel(clean_output, {"花名册": clean_df})
            console.print(f"[green]✓ 干净数据已输出到: {clean_output} (共 {len(clean_df)} 条)[/green]")
        elif issues:
            default_clean = f"{base}_干净版.xlsx"
            clean_df = get_clean_roster(df, issues)
            export_to_excel(default_clean, {"花名册": clean_df})
            console.print(f"[green]✓ 干净数据已输出到: {default_clean} (共 {len(clean_df)} 条)[/green]")

        critical = sum(1 for i in issues if i.error_level == ErrorLevel.CRITICAL)
        errors = sum(1 for i in issues if i.error_level == ErrorLevel.ERROR)
        if critical > 0 or errors > 0:
            sys.exit(2)

    except Exception as e:
        console.print(f"[bold red]✗ 校验失败: {e}[/bold red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def _create_summary_sheet(issues):
    """创建汇总统计页"""
    import pandas as pd
    from collections import Counter

    level_counter = Counter()
    code_counter = Counter()
    field_counter = Counter()
    for issue in issues:
        level_counter[issue.error_level.value] += 1
        code_counter[issue.error_code.value] += 1
        if issue.field_name:
            field_counter[FIELD_CN_MAPPING.get(issue.field_name, issue.field_name)] += 1

    level_names = {"CRITICAL": "严重", "ERROR": "错误", "WARNING": "警告", "INFO": "提示"}
    summary_data = []
    summary_data.append(["===== 错误等级统计 =====", "", ""])
    for level, name in level_names.items():
        summary_data.append([name, level, level_counter.get(level, 0)])
    summary_data.append(["合计", "", len(issues)])
    summary_data.append(["", "", ""])
    summary_data.append(["===== 错误类型统计 =====", "", ""])
    for code, count in code_counter.most_common():
        summary_data.append([code, count, ""])
    summary_data.append(["", "", ""])
    summary_data.append(["===== 涉及字段统计 =====", "", ""])
    for field, count in field_counter.most_common():
        summary_data.append([field, count, ""])

    return pd.DataFrame(summary_data, columns=["项目", "详情", "数量"])


@cli.command("diff")
@click.argument("last_month_file", type=click.Path(exists=True, dir_okay=False))
@click.argument("current_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--last-sheet", default=None, help="上月数据工作表名")
@click.option("--current-sheet", default=None, help="本月数据工作表名")
@click.option("--output", "-o", default=None, help="差异报告输出路径")
@click.option("--summary-only", is_flag=True, help="仅显示汇总信息")
def diff_cmd(last_month_file, current_file, last_sheet, current_sheet, output, summary_only):
    """对比两个月的花名册差异

    检测新增、离职、调岗、改名、部门变更、上级变更等记录。

    LAST_MONTH_FILE: 上月花名册文件
    CURRENT_FILE: 本月花名册文件

    示例:
      hrcheck diff 上月花名册.xlsx 本月花名册.xlsx
      hrcheck diff 5月.xlsx 6月.xlsx -o 5-6月差异报告.xlsx
    """
    try:
        last_df = import_roster(last_month_file, last_sheet)
        curr_df = import_roster(current_file, current_sheet)
        console.print(f"[blue]→ 上月数据: {len(last_df)} 条 | 本月数据: {len(curr_df)} 条[/blue]")

        diffs = compare_rosters(last_df, curr_df)
        console.print(f"[blue]→ 差异分析完成，共 {len(diffs)} 条变更记录[/blue]")

        change_counter = Counter()
        for d in diffs:
            change_counter[d.change_type] += 1

        sum_table = Table(title="变更类型统计", show_header=True, header_style="bold magenta")
        sum_table.add_column("变更类型", style="bold")
        sum_table.add_column("数量", justify="right")
        sum_table.add_column("说明", style="italic")

        type_desc = {
            "新增": "本月新增员工",
            "离职": "员工已离职",
            "调岗": "岗位调整",
            "改名": "姓名变更",
            "部门变更": "部门调整",
            "上级变更": "直属上级变更",
            "用工类型变更": "用工类型变更",
            "其他修改": "其他字段变更",
        }
        type_style = {
            "新增": "green",
            "离职": "red",
            "调岗": "yellow",
            "改名": "cyan",
            "部门变更": "magenta",
            "上级变更": "blue",
            "用工类型变更": "white",
            "其他修改": "dim",
        }
        for ctype, count in change_counter.most_common():
            sum_table.add_row(
                Text(ctype, style=type_style.get(ctype, "white")),
                str(count),
                type_desc.get(ctype, ""),
            )
        console.print(sum_table)

        if not summary_only and diffs:
            display_diffs = diffs[:50]
            diff_table = Table(title=f"变更明细 (显示前 {len(display_diffs)}/{len(diffs)} 条)",
                              show_header=True, header_style="bold magenta")
            diff_table.add_column("工号", width=10)
            diff_table.add_column("变更类型", width=12)
            diff_table.add_column("字段", width=10)
            diff_table.add_column("变更说明", overflow="fold")
            for d in display_diffs:
                diff_table.add_row(
                    d.emp_id,
                    Text(d.change_type, style=type_style.get(d.change_type, "white")),
                    FIELD_CN_MAPPING.get(d.field_name, d.field_name) if d.field_name else "",
                    d.description,
                )
            console.print(diff_table)

        summaries = get_department_summary(last_df, curr_df, diffs)
        if summaries:
            dept_df = summary_to_dataframe(summaries)
            console.print()
            console.print(Panel("部门人数变化汇总", border_style="cyan"))
            dept_display = dept_df.head(20)
            dept_table = Table(show_header=True, header_style="bold cyan")
            for col in dept_display.columns:
                dept_table.add_column(col, justify="right" if col != "部门" else "left")
            for _, row in dept_display.iterrows():
                vals = [str(v) for v in row.tolist()]
                net_val = row.get("净变化", "")
                style = "green" if isinstance(net_val, str) and net_val.startswith("+") else ("red" if isinstance(net_val, str) and net_val.startswith("-") else "white")
                vals[-1] = Text(vals[-1], style=style)
                dept_table.add_row(*vals)
            console.print(dept_table)
            if len(dept_df) > 20:
                console.print(f"  [dim]... 另外 {len(dept_df) - 20} 个部门数据详见输出文件[/dim]")

        if output:
            diffs_df = diffs_to_dataframe(diffs)
            dept_df = summary_to_dataframe(summaries)
            export_to_excel(output, {
                "变更汇总": _create_diff_summary_sheet(change_counter),
                "变更明细": diffs_df,
                "部门汇总": dept_df,
            })
            console.print(f"[green]✓ 差异报告已输出到: {output}[/green]")
        else:
            base = os.path.splitext(current_file)[0]
            default_output = f"{base}_差异报告.xlsx"
            diffs_df = diffs_to_dataframe(diffs)
            dept_df = summary_to_dataframe(summaries)
            export_to_excel(default_output, {
                "变更汇总": _create_diff_summary_sheet(change_counter),
                "变更明细": diffs_df,
                "部门汇总": dept_df,
            })
            console.print(f"[green]✓ 差异报告已输出到: {default_output}[/green]")

    except Exception as e:
        console.print(f"[bold red]✗ 差异对比失败: {e}[/bold red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def _create_diff_summary_sheet(change_counter):
    import pandas as pd
    type_desc = {
        "新增": "本月新增员工",
        "离职": "员工已离职",
        "调岗": "岗位调整",
        "改名": "姓名变更",
        "部门变更": "部门调整",
        "上级变更": "直属上级变更",
        "用工类型变更": "用工类型变更",
        "其他修改": "其他字段变更",
    }
    data = []
    total = 0
    for ctype, count in change_counter.most_common():
        data.append([ctype, count, type_desc.get(ctype, "")])
        total += count
    data.append(["合计", total, ""])
    return pd.DataFrame(data, columns=["变更类型", "数量", "说明"])


@cli.command("fix")
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--sheet-name", "-s", default=None, help="Excel 工作表名")
@click.option("--output", "-o", default=None, help="修复建议表输出路径")
@click.option("--apply", "-a", "apply_file", default=None, type=click.Path(exists=True),
              help="已确认的修复建议表 (用于批量应用修复)")
@click.option("--fixed-output", "-f", default=None, help="应用修复后的花名册输出路径")
@click.option("--confidence", "-c", type=click.Choice(["high", "medium", "low"]),
              default=None, help="仅显示指定置信度的建议")
def fix_cmd(file_path, sheet_name, output, apply_file, fixed_output, confidence):
    """生成修复建议并支持批量应用

    为每个问题生成可人工确认的修正建议，确认后可批量应用。

    FILE_PATH: 花名册文件路径

    示例:
      hrcheck fix 员工花名册.xlsx                    # 生成修复建议表
      hrcheck fix 员工花名册.xlsx -a 已确认建议.xlsx   # 应用已确认的修复
    """
    try:
        df = import_roster(file_path, sheet_name)
        console.print(f"[blue]→ 已导入 {len(df)} 条记录[/blue]")

        if apply_file:
            console.print(f"[blue]→ 载入已确认的修复建议: {apply_file}[/blue]")
            confirm_df = pd.read_excel(apply_file, sheet_name="修复建议")

            issues = validate_roster(df)
            suggestions = generate_fix_suggestions(df, issues)

            fixed_df, stats = apply_fixes(df, suggestions, confirm_df)
            stats_table = Table(title="修复应用统计", show_header=True, header_style="bold green")
            stats_table.add_column("项目", style="bold")
            stats_table.add_column("数量", justify="right")
            stats_table.add_row("总建议数", str(stats["total_suggestions"]))
            stats_table.add_row("已应用", Text(str(stats["applied"]), style="green"))
            stats_table.add_row("需人工确认", Text(str(stats["needs_manual"]), style="yellow"))
            stats_table.add_row("跳过", Text(str(stats["skipped"]), style="dim"))
            console.print(stats_table)

            if fixed_output:
                export_to_excel(fixed_output, {"花名册": fixed_df})
            else:
                base = os.path.splitext(file_path)[0]
                fixed_output = f"{base}_已修复.xlsx"
                export_to_excel(fixed_output, {"花名册": fixed_df})
            console.print(f"[green]✓ 修复后的花名册已输出到: {fixed_output}[/green]")
            return

        issues = validate_roster(df)
        console.print(f"[blue]→ 发现 {len(issues)} 个问题，正在生成修复建议...[/blue]")

        suggestions = generate_fix_suggestions(df, issues)
        if confidence:
            suggestions = [s for s in suggestions if s.confidence == confidence]
        console.print(f"[blue]→ 已生成 {len(suggestions)} 条修复建议[/blue]")

        conf_counter = Counter()
        type_counter = Counter()
        need_confirm = 0
        for s in suggestions:
            conf_counter[s.confidence] += 1
            type_counter[s.fix_type] += 1
            if s.needs_confirmation:
                need_confirm += 1

        stats_table = Table(title="修复建议统计", show_header=True, header_style="bold magenta")
        stats_table.add_column("置信度", style="bold")
        stats_table.add_column("数量", justify="right")
        conf_names = {"high": "高", "medium": "中", "low": "低"}
        conf_styles = {"high": "green", "medium": "yellow", "low": "red"}
        for level in ["high", "medium", "low"]:
            stats_table.add_row(
                Text(conf_names[level], style=conf_styles[level]),
                str(conf_counter.get(level, 0)),
            )
        stats_table.add_row("需人工确认", Text(str(need_confirm), style="yellow"))
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
            sug_table.add_column("建议值")
            sug_table.add_column("详细说明", overflow="fold")
            for idx, s in enumerate(display_sugs, 1):
                field_cn = FIELD_CN_MAPPING.get(s.field_name, s.field_name) if s.field_name else ""
                sug_table.add_row(
                    str(idx),
                    s.emp_id if s.emp_id else "",
                    field_cn,
                    Text(conf_names.get(s.confidence, s.confidence), style=conf_styles.get(s.confidence, "white")),
                    str(s.suggested_value) if s.suggested_value is not None else "需人工",
                    s.description,
                )
            console.print(sug_table)

        suggestions_df = suggestions_to_dataframe(suggestions)
        if output:
            export_to_excel(output, {
                "修复建议": suggestions_df,
                "问题明细": issues_to_dataframe(issues),
            })
            console.print(f"[green]✓ 修复建议已输出到: {output}[/green]")
        else:
            base = os.path.splitext(file_path)[0]
            default_output = f"{base}_修复建议.xlsx"
            export_to_excel(default_output, {
                "修复建议": suggestions_df,
                "问题明细": issues_to_dataframe(issues),
            })
            console.print(f"[green]✓ 修复建议已输出到: {default_output}[/green]")

        console.print()
        console.print("[yellow]📋 使用说明:[/yellow]")
        console.print("  1. 打开输出的修复建议 Excel 文件")
        console.print("  2. 在'修复建议'表中，对于需要确认的建议，填写'是否采纳'列（是/否）")
        console.print("  3. 如果建议值不合适，可在'人工修正值'列填写正确的值")
        console.print("  4. 保存后运行: hrcheck fix <花名册> -a <已确认的建议.xlsx>")

    except Exception as e:
        console.print(f"[bold red]✗ 生成修复建议失败: {e}[/bold red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


@cli.command("report")
@click.argument("current_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--last-month", "-l", "last_file", default=None, type=click.Path(exists=True),
              help="上月花名册文件（用于生成对比报告）")
@click.option("--current-sheet", default=None, help="本月数据工作表名")
@click.option("--last-sheet", default=None, help="上月数据工作表名")
@click.option("--output", "-o", default=None, help="完整报告输出路径")
@click.option("--departments", "-d", "dept_file", default=None, type=click.Path(exists=True),
              help="自定义有效部门列表文件")
def report_cmd(current_file, last_file, current_sheet, last_sheet, output, dept_file):
    """生成完整的综合报告

    包含：数据概览、问题明细、差异分析、部门汇总、干净数据导出。

    CURRENT_FILE: 本月花名册文件路径

    示例:
      hrcheck report 6月花名册.xlsx -l 5月花名册.xlsx -o 6月人事报告.xlsx
    """
    try:
        curr_df = import_roster(current_file, current_sheet)
        console.print(f"[blue]→ 本月数据: {len(curr_df)} 条[/blue]")

        valid_depts = None
        if dept_file:
            with open(dept_file, "r", encoding="utf-8") as f:
                valid_depts = [line.strip() for line in f if line.strip()]
            console.print(f"[blue]→ 载入自定义部门列表: {len(valid_depts)} 个[/blue]")

        issues = validate_roster(curr_df, valid_depts)
        console.print(f"[blue]→ 校验完成: {len(issues)} 个问题[/blue]")

        suggestions = generate_fix_suggestions(curr_df, issues)

        sheets = {}
        sheets["数据概览"] = _create_overview_sheet(curr_df, issues)
        sheets["问题明细"] = issues_to_dataframe(issues)
        sheets["修复建议"] = suggestions_to_dataframe(suggestions)
        sheets["干净数据"] = get_clean_roster(curr_df, issues)

        if last_file:
            last_df = import_roster(last_file, last_sheet)
            console.print(f"[blue]→ 上月数据: {len(last_df)} 条[/blue]")
            diffs = compare_rosters(last_df, curr_df)
            console.print(f"[blue]→ 差异分析: {len(diffs)} 条变更[/blue]")
            summaries = get_department_summary(last_df, curr_df, diffs)
            sheets["差异汇总"] = _create_diff_summary_sheet(Counter(d.change_type for d in diffs))
            sheets["差异明细"] = diffs_to_dataframe(diffs)
            sheets["部门汇总"] = summary_to_dataframe(summaries)

        if output:
            export_to_excel(output, sheets)
            console.print(f"[green]✓ 完整报告已输出到: {output}[/green]")
        else:
            base = os.path.splitext(current_file)[0]
            default_output = f"{base}_综合报告.xlsx"
            export_to_excel(default_output, sheets)
            output = default_output
            console.print(f"[green]✓ 完整报告已输出到: {default_output}[/green]")

        console.print()
        overview_panel = Panel(
            "\n".join([
                f"[bold cyan]报告内容:[/bold cyan]",
                f"  📊 数据概览: {len(curr_df)} 条记录",
                f"  ❌ 问题明细: {len(issues)} 个问题",
                f"  🔧 修复建议: {len(suggestions)} 条建议",
                f"  ✅ 干净数据: {len(sheets['干净数据'])} 条无错记录",
            ] + ([
                f"  📈 差异明细: {len(sheets['差异明细'])} 条变更",
                f"  📋 部门汇总: {len(sheets['部门汇总'])} 个部门统计",
            ] if last_file else [])),
            title="报告生成完成",
            border_style="green",
        )
        console.print(overview_panel)

        critical = sum(1 for i in issues if i.error_level == ErrorLevel.CRITICAL)
        errors = sum(1 for i in issues if i.error_level == ErrorLevel.ERROR)
        if critical > 0 or errors > 0:
            console.print(f"[yellow]⚠ 警告: 存在 {critical} 个严重问题和 {errors} 个错误，建议优先处理[/yellow]")

    except Exception as e:
        console.print(f"[bold red]✗ 生成报告失败: {e}[/bold red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def _create_overview_sheet(df, issues):
    import pandas as pd
    from collections import Counter

    data = []
    data.append(["===== 数据概览 =====", "", ""])
    data.append(["总记录数", len(df), ""])
    for field in REQUIRED_FIELDS:
        if field in df.columns:
            non_empty = df[field].apply(lambda x: not (x is None or (isinstance(x, float) and __import__('pandas').isna(x)) or (isinstance(x, str) and x.strip() == ""))).sum()
            data.append([f"{FIELD_CN_MAPPING.get(field, field)} 非空数", int(non_empty), f"{non_empty/len(df)*100:.1f}%"])

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
    if "department" in df.columns:
        dept_counts = df["department"].value_counts()
        for dept, count in dept_counts.items():
            data.append([str(dept), int(count), f"{count/len(df)*100:.1f}%"])

    data.append(["", "", ""])
    data.append(["===== 用工类型分布 =====", "", ""])
    if "employment_type" in df.columns:
        type_counts = df["employment_type"].value_counts()
        for t, count in type_counts.items():
            data.append([str(t), int(count), f"{count/len(df)*100:.1f}%"])

    return pd.DataFrame(data, columns=["项目", "数值", "占比/说明"])


if __name__ == "__main__":
    cli()
