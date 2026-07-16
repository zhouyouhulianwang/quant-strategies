from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name='localquant',
    version='1.0.0',
    description='LocalQuant - Production-grade quantitative trading platform',
    long_description=long_description,
    long_description_content_type="text/markdown",
    author='Dave',
    python_requires='>=3.10',
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        'pandas>=2.0.0',
        'numpy>=1.24.0',
        'polars>=0.20.0',
        'pyarrow>=12.0.0',
        'yfinance>=0.2.0',
        'ccxt>=4.0.0',
        'akshare>=1.18.0',
        'fastapi>=0.100.0',
        'uvicorn>=0.23.0',
        'apscheduler>=3.10.0',
        'click>=8.1.0',
        'plotly>=5.15.0',
        'streamlit>=1.25.0',
        'kaleido>=1.3.0',
    ],
    extras_require={
        'dev': [
            'pytest>=7.0.0',
            'pytest-cov>=4.0.0',
            'mypy>=1.0.0',
            'black>=23.0.0',
            'isort>=5.12.0',
            'flake8>=6.0.0',
        ],
        'performance': [
            'numba>=0.58.0',
        ]
    },
    entry_points={
        'console_scripts': [
            'localquant=scripts.cli:cli',
        ],
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Financial and Insurance Industry',
        'Topic :: Office/Business :: Financial :: Investment',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
    ],
)
