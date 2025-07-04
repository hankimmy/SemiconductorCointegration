import pandas as pd
import numpy as np
from statsmodels.tsa.stattools import coint
import statsmodels.api as sm

def generate_positions(zscore, entry_threshold, exit_threshold, stop_z = 3.0):
    """
    stop_z: z-score level for stop-loss (e.g. 3.0 = exit if z-score moves 3 stddevs against the trade)
    """
    positions = []
    in_trade = 0
    entry_side = 0 

    for i in range(len(zscore)):
        z = zscore.iloc[i]
        if in_trade == 0:
            if z > entry_threshold:
                positions.append(-1)
                in_trade = -1
                entry_side = -1
            elif z < -entry_threshold:
                positions.append(1)
                in_trade = 1
                entry_side = 1
            else:
                positions.append(0)
        elif in_trade == 1:
            if abs(z) < exit_threshold:
                positions.append(0)
                in_trade = 0
                entry_side = 0
            elif z < -stop_z:
                positions.append(0)
                in_trade = 0
                entry_side = 0
            else:
                positions.append(1)
        elif in_trade == -1:
            if abs(z) < exit_threshold:
                positions.append(0)
                in_trade = 0
                entry_side = 0
            elif z > stop_z:
                positions.append(0)
                in_trade = 0
                entry_side = 0
            else:
                positions.append(-1)

    return pd.Series(positions, index=zscore.index)


def calculate_returns(px, py, positions, betas, tc, alphas=None):
    betas  = pd.Series(betas,  index=px.index)
    alphas = pd.Series(0.0 if alphas is None else alphas, index=px.index)

    # -------- residual & daily P&L (USD) ------------------------------------
    spread        = px - (alphas + betas * py)
    spread_change = spread.diff().fillna(0)

    pos_lag       = positions.shift(1).fillna(0)          # trade enters next bar
    strategy_pnl  = pos_lag * spread_change               # USD per 1-unit spread

    # -------- transaction costs (USD) --------------------------------------
    gross_notional = px.abs() + (betas.abs() * py.abs())  # $X + $Y per unit
    units_traded   = positions.diff().abs().fillna(0)     # 0 or 1 (or 2 if flip)

    daily_costs    = tc * gross_notional * units_traded   # cost on both legs
    strategy_pnl_net = strategy_pnl - daily_costs

    # -------- convert to percentage returns --------------------------------
    capital_shift = gross_notional.shift(1)               # capital at risk yesterday
    with np.errstate(divide="ignore", invalid="ignore"):
        daily_return     = (strategy_pnl     / capital_shift).replace([np.inf, -np.inf], 0).fillna(0)
        daily_return_net = (strategy_pnl_net / capital_shift).replace([np.inf, -np.inf], 0).fillna(0)

    # -------- cumulatives ---------------------------------------------------
    cum_pnl         = strategy_pnl.cumsum()
    cum_pnl_net     = strategy_pnl_net.cumsum()
    cum_returns     = (1 + daily_return).cumprod()     - 1
    cum_returns_net = (1 + daily_return_net).cumprod() - 1

    # -------- Sharpe (annualised) ------------------------------------------
    sharpe = sharpe_net = 0.0
    if daily_return.std() > 0:
        sharpe = daily_return.mean() / daily_return.std() * np.sqrt(252)
    if daily_return_net.std() > 0:
        sharpe_net = daily_return_net.mean() / daily_return_net.std() * np.sqrt(252)

    # -------- package -------------------------------------------------------
    return dict(
        # P&L in dollars
        strategy_pnl        = strategy_pnl,
        strategy_pnl_net    = strategy_pnl_net,
        cum_pnl             = cum_pnl,
        cum_pnl_net         = cum_pnl_net,
        # percentage returns
        daily_return        = daily_return,
        daily_return_net    = daily_return_net,
        cum_returns         = cum_returns,
        cum_returns_net     = cum_returns_net,
        # metrics
        sharpe              = sharpe,
        sharpe_net          = sharpe_net,
        # housekeeping
        positions           = positions,
    )

def fit_rolling_params(px, py, window):
    idx = px.index
    alphas, betas, means, stds, pvals = [], [], [], [], []
    for i in range(window, len(px)):
        X, Y = px.iloc[i - window:i], py.iloc[i - window:i]
        reg = sm.OLS(X, sm.add_constant(Y)).fit()
        alpha, beta = reg.params
        spread = X - (alpha + beta * Y)
        alphas.append(alpha)
        betas.append(beta)
        means.append(spread.mean())
        stds.append(spread.std())
        try:
            _, pval, _ = coint(X, Y)
        except Exception:
            pval = 1
        pvals.append(pval)
    idx = idx[window:]
    return pd.Series(alphas, idx), pd.Series(betas, idx), pd.Series(means, idx), pd.Series(stds, idx), pd.Series(pvals, idx)
