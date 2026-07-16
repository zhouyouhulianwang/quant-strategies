"""LocalQuant CLI 工具"""
import click
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'localquant'))

from localquant.data.manager import DataManager
from localquant.core.engine import BacktestEngine
from localquant.analytics import AnalyticsEngine
from localquant.strategy import BaseStrategy

@click.group()
@click.version_option(version='0.1.0')
def cli():
    """LocalQuant - 本地量化交易平台"""
    pass

@cli.command()
@click.option('--symbol', '-s', required=True, help='股票代码 (如 AAPL)')
@click.option('--start', default=(datetime.now() - timedelta(days=365*3)).strftime('%Y-%m-%d'), 
              help='开始日期 (YYYY-MM-DD)')
@click.option('--end', default=datetime.now().strftime('%Y-%m-%d'), 
              help='结束日期 (YYYY-MM-DD)')
@click.option('--interval', '-i', default='1d', help='时间间隔 (1d, 1m, 1h)')
@click.option('--source', default='yahoo', help='数据源')
def download(symbol, start, end, interval, source):
    """下载数据到本地缓存"""
    dm = DataManager()
    start_dt = datetime.strptime(start, '%Y-%m-%d')
    end_dt = datetime.strptime(end, '%Y-%m-%d')
    
    click.echo(f"Downloading {symbol} from {start} to {end}...")
    data = dm.get_data(symbol, start_dt, end_dt, interval, source)
    
    if len(data) > 0:
        click.echo(f"✓ Downloaded {len(data)} rows")
        click.echo(f"  Date range: {data.index[0].date()} to {data.index[-1].date()}")
        click.echo(f"  Cached to: ./data_cache/stocks/{interval}/{symbol.upper()}.parquet")
    else:
        click.echo("✗ Failed to download data")

@cli.command()
@click.option('--strategy', '-s', required=True, help='策略文件路径')
@click.option('--symbol', '-sym', required=True, help='回测标的')
@click.option('--start', default=(datetime.now() - timedelta(days=365*2)).strftime('%Y-%m-%d'),
              help='回测开始日期')
@click.option('--end', default=datetime.now().strftime('%Y-%m-%d'),
              help='回测结束日期')
@click.option('--cash', default=100000.0, help='初始资金')
@click.option('--commission', default=0.001, help='手续费率')
def backtest(strategy, symbol, start, end, cash, commission):
    """运行回测"""
    # 导入策略
    sys.path.insert(0, str(Path.cwd()))
    
    strategy_path = Path(strategy)
    if not strategy_path.exists():
        click.echo(f"✗ Strategy file not found: {strategy}")
        return
    
    # 动态加载策略
    import importlib.util
    spec = importlib.util.spec_from_file_location("strategy_module", strategy_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    # 获取策略类
    strategy_class = None
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and issubclass(attr, BaseStrategy) and attr != BaseStrategy:
            strategy_class = attr
            break
    
    if strategy_class is None:
        click.echo("✗ No valid strategy class found in file")
        return
    
    # 获取数据
    click.echo(f"Fetching data for {symbol}...")
    dm = DataManager()
    start_dt = datetime.strptime(start, '%Y-%m-%d')
    end_dt = datetime.strptime(end, '%Y-%m-%d')
    data = dm.get_data(symbol, start_dt, end_dt, '1d', 'yahoo')
    
    if len(data) == 0:
        click.echo("✗ No data available")
        return
    
    click.echo(f"✓ Loaded {len(data)} rows")
    
    # 创建引擎并运行
    engine = BacktestEngine(initial_cash=cash, commission_rate=commission)
    engine.set_data(data)
    engine.set_strategy(strategy_class())
    
    click.echo(f"\nRunning backtest with {strategy_class.__name__}...")
    results = engine.run()
    
    # 分析绩效
    metrics = AnalyticsEngine.calculate_metrics(
        results['returns'], 
        results['equity_curve'],
        results['trades'],
        cash
    )
    
    AnalyticsEngine.print_report(metrics)

@cli.command()
def list_cache():
    """列出已缓存的数据"""
    cache_dir = Path('./data_cache')
    if not cache_dir.exists():
        click.echo("No cached data found")
        return
    
    click.echo("Cached data:")
    for asset_type in cache_dir.iterdir():
        if asset_type.is_dir():
            click.echo(f"\n{asset_type.name}:")
            for interval in asset_type.iterdir():
                if interval.is_dir():
                    files = list(interval.glob('*.parquet'))
                    if files:
                        click.echo(f"  {interval.name}: {len(files)} symbols")
                        for f in files:
                            size = f.stat().st_size / 1024
                            click.echo(f"    {f.stem} ({size:.1f} KB)")

if __name__ == '__main__':
    cli()
