"""生成示例测试数据"""

import pandas as pd
import os
import random
from datetime import datetime, timedelta

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "examples")
os.makedirs(OUTPUT_DIR, exist_ok=True)

DEPARTMENTS = ["技术部", "产品部", "设计部", "市场部", "销售部", "人力资源部", "财务部", "行政部", "运营部", "研发中心"]
POSITIONS = {
    "技术部": ["高级工程师", "中级工程师", "初级工程师", "技术经理", "架构师"],
    "产品部": ["产品经理", "产品助理", "产品总监"],
    "设计部": ["UI设计师", "UX设计师", "设计主管"],
    "市场部": ["市场专员", "市场经理", "品牌经理"],
    "销售部": ["销售代表", "销售经理", "销售总监"],
    "人力资源部": ["HR专员", "HRBP", "招聘经理", "人事主管"],
    "财务部": ["会计", "出纳", "财务经理"],
    "行政部": ["行政专员", "行政主管"],
    "运营部": ["运营专员", "运营经理", "内容运营"],
    "研发中心": ["研究员", "研发工程师", "研发经理"],
}
EMPLOYMENT_TYPES = ["正式", "试用期", "实习", "外包", "派遣"]
STATUSES = ["在职", "在职", "在职", "在职", "在职", "离职"]

SURNAMES = ["张", "王", "李", "赵", "陈", "刘", "杨", "黄", "周", "吴", "徐", "孙", "胡", "朱", "高", "林", "何", "郭", "马", "罗"]
GIVEN_NAMES = ["伟", "芳", "娜", "秀英", "敏", "静", "丽", "强", "磊", "军", "洋", "勇", "艳", "杰", "娟", "涛", "明", "超", "秀兰", "霞", "平", "刚", "桂英", "建华", "文", "辉", "玲", "斌", "波", "宇", "浩", "凯", "健", "俊", "帆", "鹏", "博", "婷", "雪", "倩", "琳", "欣", "颖", "佳", "悦", "璐", "瑶", "丹", "萍"]


def random_name():
    return random.choice(SURNAMES) + random.choice(GIVEN_NAMES)


def random_date(start_year=2010, end_year=2025):
    start = datetime(start_year, 1, 1)
    end = datetime(end_year, 12, 31)
    delta = end - start
    random_days = random.randint(0, delta.days)
    return (start + timedelta(days=random_days)).strftime("%Y-%m-%d")


def generate_employees(count, start_id=1, seed=42):
    random.seed(seed)
    employees = []

    supervisors = []
    for i in range(count):
        emp_id = f"E{start_id + i:05d}"
        dept = random.choice(DEPARTMENTS)
        pos = random.choice(POSITIONS[dept])
        name = random_name()
        hire_date = random_date(2015, 2025)
        emp_type = random.choice(EMPLOYMENT_TYPES)
        status = random.choice(STATUSES)
        resign_date = ""

        if status == "离职":
            hire_dt = datetime.strptime(hire_date, "%Y-%m-%d")
            resign_dt = hire_dt + timedelta(days=random.randint(30, 365 * 5))
            if resign_dt > datetime(2026, 6, 1):
                resign_dt = datetime(2026, 5, 31)
            resign_date = resign_dt.strftime("%Y-%m-%d")
            if "经理" in pos or "总监" in pos or "主管" in pos or "架构师" in pos:
                pass
            else:
                supervisors.append(emp_id)
        else:
            if "经理" in pos or "总监" in pos or "主管" in pos or "架构师" in pos:
                supervisors.append(emp_id)

        employees.append({
            "工号": emp_id,
            "姓名": name,
            "部门": dept,
            "岗位": pos,
            "入职日期": hire_date,
            "用工类型": emp_type,
            "直属上级工号": "",
            "在职状态": status,
            "离职日期": resign_date,
            "电话": f"138{random.randint(10000000, 99999999)}",
            "邮箱": f"{emp_id.lower()}@company.com",
        })

    for emp in employees:
        if emp["在职状态"] == "在职" and supervisors:
            candidates = [s for s in supervisors if s != emp["工号"]]
            if candidates:
                emp["直属上级工号"] = random.choice(candidates)

    return employees


def inject_errors(employees):
    """注入各种错误用于测试"""
    df = pd.DataFrame(employees)

    if len(df) > 5:
        df.loc[5, "姓名"] = ""

    if len(df) > 8:
        df.loc[8, "部门"] = ""

    if len(df) > 10:
        df.loc[10, "入职日期"] = "2025/13/45"

    if len(df) > 3:
        df.loc[3, "工号"] = df.loc[0, "工号"]

    if len(df) > 15:
        df.loc[15, "部门"] = "神秘部门"

    if len(df) > 20:
        df.loc[20, "用工类型"] = "随意类型"

    if len(df) > 25 and df.loc[25, "在职状态"] == "在职":
        df.loc[25, "离职日期"] = "2025-12-31"

    if len(df) > 30 and df.loc[30, "在职状态"] == "离职":
        df.loc[30, "离职日期"] = ""

    if len(df) > 35:
        df.loc[35, "入职日期"] = "2030-01-01"

    if len(df) > 40:
        df.loc[40, "岗位"] = ""

    return df


def generate_test_data():
    """生成测试数据集"""

    last_month = generate_employees(50, start_id=1, seed=42)
    current = generate_employees(55, start_id=1, seed=43)

    for i in range(40, 50):
        if i < len(last_month):
            last_month[i]["在职状态"] = "在职"
            last_month[i]["离职日期"] = ""

    current_df = inject_errors(current)

    last_df = pd.DataFrame(last_month)

    current_df.to_excel(os.path.join(OUTPUT_DIR, "本月花名册.xlsx"), index=False)
    last_df.to_excel(os.path.join(OUTPUT_DIR, "上月花名册.xlsx"), index=False)

    current_csv = current_df.copy()
    current_csv.to_csv(os.path.join(OUTPUT_DIR, "本月花名册.csv"), index=False, encoding="utf-8-sig")

    dept_file = os.path.join(OUTPUT_DIR, "部门列表.txt")
    with open(dept_file, "w", encoding="utf-8") as f:
        for d in DEPARTMENTS:
            f.write(d + "\n")

    print(f"✓ 示例数据已生成到: {OUTPUT_DIR}")
    print(f"  - 上月花名册.xlsx ({len(last_df)} 条)")
    print(f"  - 本月花名册.xlsx ({len(current_df)} 条, 含注入错误)")
    print(f"  - 本月花名册.csv (CSV 格式)")
    print(f"  - 部门列表.txt (自定义部门配置)")


if __name__ == "__main__":
    generate_test_data()
