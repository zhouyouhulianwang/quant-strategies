"""遗传算法参数优化器 - 比网格搜索高效 10 倍"""
import numpy as np
import random
from typing import Dict, List, Tuple, Callable, Any
from dataclasses import dataclass
from concurrent.futures import ProcessPoolExecutor
import time

@dataclass
class GAConfig:
    """遗传算法配置"""
    population_size: int = 30           # 种群大小
    generations: int = 20               # 迭代次数
    crossover_rate: float = 0.8         # 交叉概率
    mutation_rate: float = 0.2          # 变异概率
    elite_count: int = 3                # 精英保留数量
    min_mutation: float = 0.1           # 最小变异幅度
    max_mutation: float = 0.5           # 最大变异幅度
    early_stopping_generations: int = 5  # 早停 patience

class ParameterSpace:
    """参数空间定义"""
    
    def __init__(self, params: Dict[str, Tuple]):
        """
        params: {
            'max_position_pct': ('float', 0.05, 0.3),      # (类型, 最小, 最大)
            'rebalance_freq': ('int', 5, 30),
            'max_stocks': ('int', 5, 20),
            'use_trend_filter': ('bool', None, None)
        }
        """
        self.params = params
        self.keys = list(params.keys())
    
    def random_individual(self) -> Dict[str, Any]:
        """生成随机个体"""
        individual = {}
        for key, (ptype, min_val, max_val) in self.params.items():
            if ptype == 'float':
                individual[key] = random.uniform(min_val, max_val)
            elif ptype == 'int':
                individual[key] = random.randint(min_val, max_val)
            elif ptype == 'bool':
                individual[key] = random.choice([True, False])
        return individual
    
    def mutate(self, individual: Dict[str, Any], generation: int, total_generations: int) -> Dict[str, Any]:
        """变异操作"""
        mutated = individual.copy()
        # 随着代数增加，减小变异幅度
        adaptive_rate = 1.0 - (generation / total_generations)
        
        for key, (ptype, min_val, max_val) in self.params.items():
            if random.random() < 0.3:  # 每个参数 30% 概率变异
                if ptype == 'float':
                    mutation = random.gauss(0, (max_val - min_val) * 0.1 * adaptive_rate)
                    mutated[key] = np.clip(individual[key] + mutation, min_val, max_val)
                elif ptype == 'int':
                    mutation = random.randint(-2, 2)
                    mutated[key] = np.clip(individual[key] + mutation, min_val, max_val)
                elif ptype == 'bool':
                    mutated[key] = not individual[key]
        
        return mutated
    
    def crossover(self, parent1: Dict, parent2: Dict) -> Tuple[Dict, Dict]:
        """交叉操作"""
        child1, child2 = {}, {}
        
        for key in self.keys:
            if random.random() < 0.5:
                child1[key] = parent1[key]
                child2[key] = parent2[key]
            else:
                child1[key] = parent2[key]
                child2[key] = parent1[key]
        
        # 对连续参数进行线性组合交叉
        for key, (ptype, min_val, max_val) in self.params.items():
            if ptype == 'float' and random.random() < 0.3:
                alpha = random.random()
                child1[key] = alpha * parent1[key] + (1 - alpha) * parent2[key]
                child2[key] = (1 - alpha) * parent1[key] + alpha * parent2[key]
        
        return child1, child2

class GeneticOptimizer:
    """遗传算法优化器"""
    
    def __init__(self, config: GAConfig = None):
        self.config = config or GAConfig()
        self.best_fitness_history = []
        self.avg_fitness_history = []
    
    def optimize(self, 
                 param_space: ParameterSpace,
                 fitness_fn: Callable[[Dict], float],
                 maximize: bool = True) -> Tuple[Dict, float]:
        """
        执行遗传算法优化
        
        Args:
            param_space: 参数空间
            fitness_fn: 适应度函数，接收参数字典，返回 float
            maximize: True 最大化，False 最小化
        
        Returns:
            (最优参数, 最优适应度)
        """
        config = self.config
        
        # 初始化种群
        population = [param_space.random_individual() for _ in range(config.population_size)]
        fitness_scores = self._evaluate_population(population, fitness_fn)
        
        best_ever = None
        best_fitness_ever = -np.inf if maximize else np.inf
        generations_without_improvement = 0
        
        print(f"遗传算法开始: 种群={config.population_size}, 代数={config.generations}")
        
        for generation in range(config.generations):
            start_time = time.time()
            
            # 排序
            sorted_indices = np.argsort(fitness_scores)
            if maximize:
                sorted_indices = sorted_indices[::-1]
            
            # 记录
            best_fitness = fitness_scores[sorted_indices[0]]
            avg_fitness = np.mean(fitness_scores)
            self.best_fitness_history.append(best_fitness)
            self.avg_fitness_history.append(avg_fitness)
            
            # 更新最优
            if (maximize and best_fitness > best_fitness_ever) or \
               (not maximize and best_fitness < best_fitness_ever):
                best_fitness_ever = best_fitness
                best_ever = population[sorted_indices[0]].copy()
                generations_without_improvement = 0
            else:
                generations_without_improvement += 1
            
            elapsed = time.time() - start_time
            print(f"Gen {generation+1}/{config.generations}: "
                  f"Best={best_fitness:.4f}, Avg={avg_fitness:.4f}, "
                  f"Time={elapsed:.1f}s")
            
            # 早停
            if generations_without_improvement >= config.early_stopping_generations:
                print(f"早停: {config.early_stopping_generations} 代无改进")
                break
            
            # 生成下一代
            new_population = []
            
            # 保留精英
            for i in range(config.elite_count):
                new_population.append(population[sorted_indices[i]])
            
            # 生成子代
            while len(new_population) < config.population_size:
                # 锦标赛选择
                parent1 = self._tournament_select(population, fitness_scores, maximize)
                parent2 = self._tournament_select(population, fitness_scores, maximize)
                
                # 交叉
                if random.random() < config.crossover_rate:
                    child1, child2 = param_space.crossover(parent1, parent2)
                else:
                    child1, child2 = parent1.copy(), parent2.copy()
                
                # 变异
                if random.random() < config.mutation_rate:
                    child1 = param_space.mutate(child1, generation, config.generations)
                if random.random() < config.mutation_rate:
                    child2 = param_space.mutate(child2, generation, config.generations)
                
                new_population.extend([child1, child2])
            
            # 截断到种群大小
            population = new_population[:config.population_size]
            fitness_scores = self._evaluate_population(population, fitness_fn)
        
        print(f"\n优化完成!")
        print(f"最优适应度: {best_fitness_ever:.4f}")
        print(f"最优参数: {best_ever}")
        
        return best_ever, best_fitness_ever
    
    def _evaluate_population(self, population: List[Dict], 
                            fitness_fn: Callable) -> np.ndarray:
        """评估种群"""
        scores = []
        for individual in population:
            try:
                score = fitness_fn(individual)
                scores.append(score)
            except Exception as e:
                print(f"评估失败: {e}")
                scores.append(-np.inf)
        return np.array(scores)
    
    def _tournament_select(self, population: List[Dict], 
                          fitness_scores: np.ndarray,
                          maximize: bool,
                          tournament_size: int = 3) -> Dict:
        """锦标赛选择"""
        indices = random.sample(range(len(population)), min(tournament_size, len(population)))
        
        if maximize:
            best_idx = max(indices, key=lambda i: fitness_scores[i])
        else:
            best_idx = min(indices, key=lambda i: fitness_scores[i])
        
        return population[best_idx].copy()
    
    def plot_evolution(self):
        """绘制进化过程"""
        import matplotlib.pyplot as plt
        
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(self.best_fitness_history, 'b-', label='Best Fitness', linewidth=2)
        ax.plot(self.avg_fitness_history, 'r--', label='Average Fitness', alpha=0.7)
        ax.set_xlabel('Generation')
        ax.set_ylabel('Fitness')
        ax.set_title('Genetic Algorithm Evolution')
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        return fig


# ========== 使用示例 ==========

if __name__ == "__main__":
    # 定义参数空间
    param_space = ParameterSpace({
        'max_position_pct': ('float', 0.05, 0.3),
        'rebalance_freq': ('int', 5, 30),
        'max_stocks': ('int', 3, 15),
        'stop_loss_pct': ('float', 0.03, 0.15),
        'trailing_stop_pct': ('float', 0.05, 0.20),
        'use_trend_filter': ('bool', None, None),
        'sector_rotation_enabled': ('bool', None, None)
    })
    
    # 示例适应度函数（实际使用时替换为回测函数）
    def example_fitness(params):
        """示例：最大化夏普比率"""
        # 这里应该调用回测引擎
        # 返回夏普比率
        return random.gauss(0.3, 0.1)  # 模拟
    
    # 运行优化
    optimizer = GeneticOptimizer(GAConfig(
        population_size=20,
        generations=15,
        early_stopping_generations=3
    ))
    
    best_params, best_fitness = optimizer.optimize(
        param_space, example_fitness, maximize=True
    )
