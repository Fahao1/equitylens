"""Four shared deterministic evaluators; historical and live callers use these same rules."""
from . import trend,breakout,mean_reversion,value


def evaluate_strategies(snapshot,context,config):
    return [module.evaluate(snapshot,context,config) for module in (trend,breakout,mean_reversion,value)]
