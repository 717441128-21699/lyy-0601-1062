from setuptools import setup, find_packages

setup(
    name="hr-roster-check",
    version="1.0.0",
    description="人力资源花名册校验命令行工具",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "pandas>=2.0.0",
        "click>=8.1.0",
        "openpyxl>=3.1.0",
        "tqdm>=4.65.0",
        "rich>=13.0.0",
    ],
    entry_points={
        "console_scripts": [
            "hrcheck=hrcheck.cli:cli",
        ],
    },
)
